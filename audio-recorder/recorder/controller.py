"""All the logic of the four-button window, with no GUI toolkit in it.

The window only draws what ``AppController.snapshot()`` says and forwards
button clicks, so every rule here can be tested without a display.
"""

import queue
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from .mixer import export_mp3
from .session import RecordingSession, unique_dir
from .transcribe import SPEAKERS, load_model, write_transcripts

CONSENT_NOTE = ("Recording your microphone and speakers. Tell the other participants "
                "you are recording: many places require everyone's consent.")


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SAVING = "saving"
    TRANSCRIBING = "transcribing"


BUTTONS = ("record", "stop", "save", "transcribe")


def format_elapsed(seconds):
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


@dataclass(frozen=True)
class Snapshot:
    state: State
    elapsed: float
    mic_level: float
    speaker_level: float
    enabled: dict
    message: str
    message_kind: str  # "info" | "ok" | "error"
    transcript: str
    session_dir: Path | None


class ThreadRunner:
    """Run slow work on a thread; finished callbacks run on whoever calls ``poll()``.

    The GUI calls ``poll()`` from its own timer, so widgets are only ever touched
    from the GUI thread.
    """

    def __init__(self):
        self._finished = queue.Queue()

    def submit(self, work, done):
        def run():
            try:
                result = work()
            except BaseException as exc:  # noqa: BLE001 - includes SystemExit from load_model
                self._finished.put((done, None, exc))
            else:
                self._finished.put((done, result, None))

        threading.Thread(target=run, name="background-work", daemon=True).start()

    def poll(self):
        """Run callbacks for finished work; return how many ran."""
        ran = 0
        while True:
            try:
                done, result, error = self._finished.get_nowait()
            except queue.Empty:
                return ran
            done(result, error)
            ran += 1


class AppController:
    def __init__(self, backend, runner, ask_save_target, model_loader=load_model,
                 out_base="recordings", now=datetime.now, clock=time.monotonic,
                 language="en", model_name="base.en", device="cpu", compute_type="int8"):
        self._backend = backend
        self._runner = runner
        self.ask_save_target = ask_save_target  # (default_name) -> (folder, want_mp3) | None
        self._model_loader = model_loader
        self._out_base = Path(out_base)
        self._now = now
        self._clock = clock
        self._model_args = (model_name, device, compute_type)
        self._language = language
        self._model = None
        self._state = State.IDLE
        self._session = None
        self._session_dir = None
        self._started_at = 0.0
        self._elapsed = 0.0
        self._transcript = ""
        self._message, self._kind = "Ready. Press Record to start.", "info"

    # ---- what the window shows -------------------------------------------------

    def snapshot(self):
        recording = self._state is State.RECORDING
        peaks = self._session.peaks if (recording and self._session) else {}
        return Snapshot(
            state=self._state,
            elapsed=max(0.0, self._clock() - self._started_at) if recording else self._elapsed,
            mic_level=peaks.get("mic", 0.0),
            speaker_level=peaks.get("loopback", 0.0),
            enabled={name: self._is_enabled(name) for name in BUTTONS},
            message=self._message, message_kind=self._kind,
            transcript=self._transcript, session_dir=self._session_dir)

    def _is_enabled(self, button):
        if self._state is State.IDLE:
            return button == "record"
        if self._state is State.RECORDING:
            return button == "stop"
        if self._state is State.STOPPED:
            if button == "transcribe":
                return self._has_tracks()
            return button in ("record", "save")
        return False

    def _has_tracks(self):
        return bool(self._session_dir) and any(
            (self._session_dir / f"{track}.wav").exists() for track in SPEAKERS)

    def _say(self, text, kind="info"):
        self._message, self._kind = text, kind

    # ---- the four buttons ------------------------------------------------------

    def record(self):
        if self._state not in (State.IDLE, State.STOPPED):
            return False
        sources = None
        try:
            sources = self._backend.open_sources(None, None)
            session_dir = unique_dir(self._out_base, f"{self._now():%y_%m%d_%H%M}_meeting")
            session = RecordingSession(session_dir, *sources, mode="meeting", clock=self._clock)
            session.start()
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - shown in plain words
            for source in sources or ():
                try:
                    source.stop()
                except Exception:  # noqa: BLE001
                    pass
            self._say(str(exc) if isinstance(exc, SystemExit) else f"Could not start recording: {exc}",
                      "error")
            return False
        self._session, self._session_dir = session, session_dir
        self._started_at, self._elapsed = self._clock(), 0.0
        self._transcript = ""
        self._state = State.RECORDING
        self._say(CONSENT_NOTE)
        return True

    def stop(self):
        if self._state is not State.RECORDING:
            return False
        self._state = State.STOPPING
        self._say("Finishing the recording...")
        self._runner.submit(self._session.stop, self._on_stopped)
        return True

    def _on_stopped(self, result, error):
        if error is not None:
            self._state = State.STOPPED if self._has_tracks() else State.IDLE
            self._say(f"The recording stopped, but finishing it failed: {error}", "error")
            return
        self._elapsed = result.duration
        self._state = State.STOPPED
        self._say(f"Recording finished. Saved in {self._session_dir}. "
                  "You can Save a copy or Transcribe.", "ok")

    def save(self):
        if self._state is not State.STOPPED:
            return False
        target = self.ask_save_target(self._session_dir.name)
        if target is None:
            self._say("Save cancelled.")
            return False
        dest, want_mp3 = Path(target[0]), bool(target[1])
        if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
            self._say(f"{dest} already has files in it. Pick a new name so nothing is overwritten.",
                      "error")
            return False
        source = self._session_dir
        self._state = State.SAVING
        self._say(f"Saving to {dest}...")

        def work():
            dest.mkdir(parents=True, exist_ok=True)
            for item in sorted(source.iterdir()):
                if item.is_file():
                    shutil.copy2(item, dest / item.name)
            if want_mp3 and (source / "mix.wav").exists():
                export_mp3(source / "mix.wav", dest / "mix.mp3")
            return dest

        self._runner.submit(work, self._on_saved)
        return True

    def _on_saved(self, result, error):
        self._state = State.STOPPED
        if error is not None:
            self._say(f"Could not save: {error}", "error")
        else:
            self._say(f"Saved to {result}", "ok")

    def transcribe(self):
        if self._state is not State.STOPPED or not self._has_tracks():
            return False
        self._state = State.TRANSCRIBING
        self._say("Transcribing... The first time, the speech model is downloaded, "
                  "which can take a few minutes. Keep this window open.")
        session_dir = self._session_dir

        def work():
            if self._model is None:
                self._model = self._model_loader(*self._model_args)
            txt, _srt = write_transcripts(self._model, session_dir, SPEAKERS, self._language)
            return txt.read_text(encoding="utf-8")

        self._runner.submit(work, self._on_transcribed)
        return True

    def _on_transcribed(self, text, error):
        self._state = State.STOPPED
        if error is not None:
            plain = str(error) if isinstance(error, SystemExit) else f"Transcription failed: {error}"
            self._say(plain, "error")
        elif not text.strip():
            self._say("No speech was found in the recording.")
        else:
            self._transcript = text
            self._say("Transcript saved as transcript.txt and transcript.srt "
                      "in the recording folder.", "ok")

    def shutdown(self):
        """Call when the window closes: never lose a recording in progress."""
        if self._state is State.RECORDING and self._session is not None:
            try:
                self._session.stop()
            except Exception:  # noqa: BLE001 - the window is closing anyway
                pass
            self._state = State.STOPPED
