"""Timestamp-aligned, crash-tolerant WAV track writer."""

import threading

import numpy as np
import soundfile as sf


class TrackWriter:
    """Write mono chunks into a 16-bit WAV, placing each chunk by its timestamp.

    All tracks of a session share ``t0``, so they stay aligned with each other.
    WASAPI loopback delivers no data while nothing is playing, so a chunk that
    arrives later than the audio written so far gets silence inserted first.
    Jitter smaller than ``tolerance`` seconds is ignored; a chunk that overlaps
    already-written audio by more than ``tolerance`` is trimmed.
    """

    def __init__(self, path, sample_rate, t0, tolerance=0.05, flush_seconds=2.0):
        self.path = path
        self.sample_rate = int(sample_rate)
        self.t0 = t0
        self.tolerance = tolerance
        self.frames_written = 0
        self._flush_every = int(flush_seconds * self.sample_rate)
        self._since_flush = 0
        self._lock = threading.Lock()
        self._file = sf.SoundFile(
            str(path), mode="w", samplerate=self.sample_rate, channels=1,
            format="WAV", subtype="PCM_16",
        )

    def write(self, timestamp, samples):
        with self._lock:
            if self._file is None or len(samples) == 0:
                return
            samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
            expected = self.t0 + self.frames_written / self.sample_rate
            offset = timestamp - expected
            if offset > self.tolerance:
                self._write_silence(int(round(offset * self.sample_rate)))
            elif offset < -self.tolerance:
                samples = samples[int(round(-offset * self.sample_rate)):]
            if len(samples):
                self._file.write(samples)
                self.frames_written += len(samples)
                self._since_flush += len(samples)
            if self._since_flush >= self._flush_every:
                self._flush_locked()

    def flush(self):
        with self._lock:
            self._flush_locked()

    def close(self, end_time=None):
        """Finish the file, optionally padding with silence up to ``end_time``."""
        with self._lock:
            if self._file is None:
                return
            if end_time is not None:
                target = int(round((end_time - self.t0) * self.sample_rate))
                if target > self.frames_written:
                    self._write_silence(target - self.frames_written)
            self._file.close()
            self._file = None

    def _write_silence(self, frames):
        block = 65536
        while frames > 0:
            n = min(block, frames)
            self._file.write(np.zeros(n, dtype=np.float32))
            self.frames_written += n
            frames -= n

    def _flush_locked(self):
        if self._file is not None:
            self._file.flush()
            self._since_flush = 0
