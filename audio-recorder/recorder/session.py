"""RecordingSession: capture two sources, align them, and build the final files."""

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import LinearResampler, to_mono
from .mixer import mix_wavs
from .track import TrackWriter

# mode -> (mic track name, loopback track name, keep the raw tracks by default)
MODES = {
    "meeting": ("me", "others", True),
    "karaoke": ("voice", "music", False),
}


def unique_dir(base, name):
    """Return ``base/name``, or ``base/name_2``, ``_3``... if that folder is taken.

    Recordings are named by minute, so two started in the same minute must not
    overwrite each other.
    """
    base = Path(base)
    candidate, n = base / name, 2
    while candidate.exists():
        candidate = base / f"{name}_{n}"
        n += 1
    return candidate


@dataclass(frozen=True)
class SessionResult:
    mix: Path
    tracks: dict = field(default_factory=dict)
    duration: float = 0.0


class RecordingSession:
    """Record a microphone source and a loopback (speakers) source together.

    Sources only need ``name``, ``sample_rate``, ``start(callback)`` and
    ``stop()``; ``callback(timestamp, samples)`` is called from the device
    thread. Chunks go through a queue to one writer thread, so device callbacks
    never block on disk I/O. All timestamps come from ``clock`` (monotonic).
    """

    def __init__(self, out_dir, mic, loopback, mode="meeting", sample_rate=48000,
                 mic_gain=1.0, music_gain=1.0, keep_tracks=None, clock=time.monotonic):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; choose from {sorted(MODES)}")
        mic_track, loop_track, keep_default = MODES[mode]
        self.out_dir = Path(out_dir)
        self.mic, self.loopback = mic, loopback
        self.sample_rate = int(sample_rate)
        self.mic_gain, self.music_gain = mic_gain, music_gain
        self.keep_tracks = keep_default if keep_tracks is None else keep_tracks
        self._clock = clock
        self._names = {mic.name: mic_track, loopback.name: loop_track}
        self._gains = {mic_track: mic_gain, loop_track: music_gain}
        self._writers = {}
        self._resamplers = {}
        self._queue = queue.Queue()
        self._thread = None
        self._started = []
        self._result = None
        self._t0 = None
        self.peaks = {}
        self.error = None

    def start(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._t0 = self._clock()
        for source in (self.mic, self.loopback):
            track = self._names[source.name]
            self._writers[source.name] = TrackWriter(
                self.out_dir / f"{track}.wav", self.sample_rate, self._t0)
            self._resamplers[source.name] = LinearResampler(source.sample_rate, self.sample_rate)
            self.peaks[source.name] = 0.0
        self._thread = threading.Thread(target=self._drain, name="track-writer", daemon=True)
        self._thread.start()
        try:
            for source in (self.mic, self.loopback):
                source.start(lambda ts, samples, name=source.name: self._queue.put((name, ts, samples)))
                self._started.append(source)
        except Exception:
            self._shutdown_sources()
            self._queue.put(None)
            self._thread.join()
            for writer in self._writers.values():
                writer.close()
            raise

    def stop(self):
        if self._result is not None:
            return self._result
        self._shutdown_sources()
        end_time = self._clock()
        self._queue.put(None)
        self._thread.join()
        for writer in self._writers.values():
            writer.close(end_time=end_time)
        if self.error:
            raise RuntimeError("writer thread failed") from self.error

        tracks = {self._names[n]: self.out_dir / f"{self._names[n]}.wav" for n in self._writers}
        mix_path = mix_wavs([(tracks[t], self._gains[t]) for t in tracks], self.out_dir / "mix.wav")
        if not self.keep_tracks:
            for path in tracks.values():
                path.unlink(missing_ok=True)
            tracks = {}
        self._result = SessionResult(mix=mix_path, tracks=tracks, duration=end_time - self._t0)
        return self._result

    def _shutdown_sources(self):
        for source in self._started:
            try:
                source.stop()
            except Exception:  # keep stopping the rest; the recording must still be saved
                pass
        self._started = []

    def _drain(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            name, timestamp, samples = item
            try:
                mono = to_mono(samples)
                if len(mono):
                    self.peaks[name] = float(np.max(np.abs(mono)))
                self._writers[name].write(timestamp, self._resamplers[name].process(mono))
            except Exception as exc:  # surfaced from stop()
                self.error = exc
