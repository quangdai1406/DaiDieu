import threading
import time
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from recorder.controller import AppController, State, ThreadRunner
from tests.fakes import FakeBackend, FakeClock, ManualRunner, SyncRunner

RATE = 48000


class FakeModel:
    def transcribe(self, path, **kwargs):
        text = "from me" if path.endswith("me.wav") else "from them"
        return iter([SimpleNamespace(start=0.0, end=1.0, text=text)]), None


def tone(seconds, value):
    return np.full(int(RATE * seconds), value, dtype=np.float32)


def wait_for(condition, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Rig:
    def __init__(self, tmp_path, runner=None, loader=None):
        self.clock = FakeClock(1000.0)
        self.backend = FakeBackend(rate=RATE)
        self.loader_calls = 0

        def default_loader(*args):
            self.loader_calls += 1
            return FakeModel()

        self.ctrl = AppController(
            self.backend, runner or SyncRunner(),
            ask_save_target=lambda name: None,
            model_loader=loader or default_loader,
            out_base=tmp_path / "rec", now=lambda: datetime(2026, 10, 13, 9, 5),
            clock=self.clock)

    def record_one_second(self):
        assert self.ctrl.record()
        self.backend.mic.emit(1000.0, tone(1.0, 0.2))
        self.backend.loopback.emit(1000.0, tone(1.0, 0.1))
        self.clock.now = 1001.0

    def record_and_stop(self):
        self.record_one_second()
        assert self.ctrl.stop()


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_initial_state_only_record_is_enabled(rig):
    snap = rig.ctrl.snapshot()
    assert snap.state is State.IDLE
    assert snap.enabled == {"record": True, "stop": False, "save": False, "transcribe": False}
    assert snap.transcript == ""


def test_record_starts_a_session_and_enables_only_stop(rig, tmp_path):
    assert rig.ctrl.record()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.RECORDING
    assert snap.enabled == {"record": False, "stop": True, "save": False, "transcribe": False}
    assert snap.session_dir == tmp_path / "rec" / "26_1013_0905_meeting"
    assert "consent" in snap.message
    assert rig.backend.mic.started and rig.backend.loopback.started


def test_elapsed_follows_the_clock_then_freezes_after_stop(rig):
    rig.ctrl.record()
    rig.clock.now = 1012.5
    assert rig.ctrl.snapshot().elapsed == pytest.approx(12.5)
    rig.ctrl.stop()
    rig.clock.now = 1099.0
    assert rig.ctrl.snapshot().elapsed == pytest.approx(12.5)


def test_levels_reflect_the_latest_peaks(rig):
    rig.ctrl.record()
    rig.backend.mic.emit(1000.0, tone(0.5, 0.25))
    rig.backend.loopback.emit(1000.0, tone(0.5, 0.5))
    assert wait_for(lambda: rig.ctrl.snapshot().mic_level > 0 and rig.ctrl.snapshot().speaker_level > 0)
    snap = rig.ctrl.snapshot()
    assert snap.mic_level == pytest.approx(0.25)
    assert snap.speaker_level == pytest.approx(0.5)


def test_stop_finishes_files_and_enables_save_and_transcribe(rig):
    rig.record_and_stop()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPED
    assert snap.enabled == {"record": True, "stop": False, "save": True, "transcribe": True}
    assert snap.elapsed == pytest.approx(1.0)
    for name in ("me.wav", "others.wav", "mix.wav"):
        assert (snap.session_dir / name).exists()


def test_record_failure_stays_idle_with_a_plain_message(rig):
    rig.backend.fail_open = RuntimeError("no microphone found")
    assert not rig.ctrl.record()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.IDLE
    assert snap.message_kind == "error"
    assert "no microphone found" in snap.message
    assert snap.enabled["record"]


def test_actions_in_the_wrong_state_are_ignored(rig):
    assert not rig.ctrl.stop()
    assert not rig.ctrl.save()
    assert not rig.ctrl.transcribe()
    rig.ctrl.record()
    assert not rig.ctrl.record()
    assert not rig.ctrl.save()
    assert not rig.ctrl.transcribe()


def test_save_copies_the_files_and_the_optional_mp3(rig, tmp_path):
    rig.record_and_stop()
    dest = tmp_path / "saved" / "weekly"
    rig.ctrl.ask_save_target = lambda name: (dest, True)
    assert rig.ctrl.save()
    for name in ("me.wav", "others.wav", "mix.wav", "mix.mp3"):
        assert (dest / name).exists(), name
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPED
    assert snap.message_kind == "ok"
    assert str(dest) in snap.message


def test_save_without_mp3_writes_no_mp3(rig, tmp_path):
    rig.record_and_stop()
    dest = tmp_path / "saved"
    rig.ctrl.ask_save_target = lambda name: (dest, False)
    rig.ctrl.save()
    assert (dest / "mix.wav").exists()
    assert not (dest / "mix.mp3").exists()


def test_save_offers_the_session_name_as_default(rig):
    rig.record_and_stop()
    seen = []
    rig.ctrl.ask_save_target = lambda name: seen.append(name)
    rig.ctrl.save()
    assert seen == ["26_1013_0905_meeting"]


def test_cancelling_save_changes_nothing(rig, tmp_path):
    rig.record_and_stop()
    assert not rig.ctrl.save()  # ask_save_target returns None
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPED
    assert snap.message_kind == "info"
    assert not (tmp_path / "saved").exists()


def test_save_refuses_a_folder_that_already_has_files(rig, tmp_path):
    rig.record_and_stop()
    dest = tmp_path / "saved"
    dest.mkdir()
    (dest / "keep.txt").write_text("precious")
    rig.ctrl.ask_save_target = lambda name: (dest, False)
    rig.ctrl.save()
    assert rig.ctrl.snapshot().message_kind == "error"
    assert (dest / "keep.txt").read_text() == "precious"
    assert not (dest / "mix.wav").exists()


def test_transcribe_writes_files_and_shows_the_text(rig):
    rig.record_and_stop()
    assert rig.ctrl.transcribe()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPED
    assert "Me: from me" in snap.transcript and "Others: from them" in snap.transcript
    assert (snap.session_dir / "transcript.txt").exists()
    assert (snap.session_dir / "transcript.srt").exists()
    assert snap.message_kind == "ok"


def test_the_speech_model_is_loaded_once(rig):
    rig.record_and_stop()
    rig.ctrl.transcribe()
    rig.ctrl.transcribe()
    assert rig.loader_calls == 1


def test_missing_whisper_shows_a_message_instead_of_crashing(tmp_path):
    def loader(*args):
        raise SystemExit("Transcription needs faster-whisper: pip install faster-whisper")

    rig = Rig(tmp_path, loader=loader)
    rig.record_and_stop()
    rig.ctrl.transcribe()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPED
    assert snap.message_kind == "error"
    assert "faster-whisper" in snap.message
    assert snap.transcript == ""


def test_buttons_are_disabled_while_work_is_running(tmp_path):
    rig = Rig(tmp_path, runner=ManualRunner())
    rig.record_one_second()
    rig.ctrl.stop()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.STOPPING
    assert not any(snap.enabled.values())
    rig.ctrl._runner.run_all()
    assert rig.ctrl.snapshot().state is State.STOPPED

    rig.ctrl.transcribe()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.TRANSCRIBING
    assert not any(snap.enabled.values())
    rig.ctrl._runner.run_all()
    assert rig.ctrl.snapshot().state is State.STOPPED


def test_a_second_recording_in_the_same_minute_gets_its_own_folder(rig, tmp_path):
    rig.record_and_stop()
    first = rig.ctrl.snapshot().session_dir
    rig.clock.now = 2000.0
    rig.ctrl.record()
    second = rig.ctrl.snapshot().session_dir
    assert second == tmp_path / "rec" / "26_1013_0905_meeting_2"
    assert first.exists() and (first / "mix.wav").exists()


def test_a_new_recording_clears_the_old_transcript(rig):
    rig.record_and_stop()
    rig.ctrl.transcribe()
    assert rig.ctrl.snapshot().transcript
    rig.clock.now = 2000.0
    rig.ctrl.record()
    assert rig.ctrl.snapshot().transcript == ""


def test_closing_the_window_while_recording_still_saves_the_files(rig):
    rig.record_one_second()
    session_dir = rig.ctrl.snapshot().session_dir
    rig.ctrl.shutdown()
    assert (session_dir / "mix.wav").exists()
    assert rig.backend.mic.stopped and rig.backend.loopback.stopped


def test_shutdown_when_idle_does_nothing(rig):
    rig.ctrl.shutdown()
    assert rig.ctrl.snapshot().state is State.IDLE


def test_thread_runner_works_off_thread_and_calls_back_on_poll():
    runner = ThreadRunner()
    main_thread = threading.get_ident()
    seen = {}

    def work():
        seen["work_thread"] = threading.get_ident()
        return 42

    def done(result, error):
        seen["done_thread"] = threading.get_ident()
        seen["result"], seen["error"] = result, error

    runner.submit(work, done)
    assert wait_for(lambda: runner.poll() or "result" in seen)
    assert seen["result"] == 42 and seen["error"] is None
    assert seen["work_thread"] != main_thread
    assert seen["done_thread"] == main_thread


def test_thread_runner_reports_errors_including_system_exit():
    runner = ThreadRunner()
    seen = []
    runner.submit(lambda: (_ for _ in ()).throw(SystemExit("needs a package")),
                  lambda result, error: seen.append((result, error)))
    assert wait_for(lambda: runner.poll() or seen)
    result, error = seen[0]
    assert result is None
    assert isinstance(error, SystemExit) and "needs a package" in str(error)


def test_missing_capture_package_shows_a_message_not_an_exit(rig):
    rig.backend.fail_open = SystemExit("Capture needs PyAudioWPatch on Windows: pip install PyAudioWPatch")
    assert not rig.ctrl.record()
    snap = rig.ctrl.snapshot()
    assert snap.state is State.IDLE
    assert snap.message_kind == "error"
    assert "PyAudioWPatch" in snap.message


def test_format_elapsed():
    from recorder.controller import format_elapsed

    assert format_elapsed(0) == "0:00:00"
    assert format_elapsed(65.9) == "0:01:05"
    assert format_elapsed(3725) == "1:02:05"
