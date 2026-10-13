"""Small, dependency-light audio helpers: mono downmix and streaming resampling."""

import numpy as np


def to_mono(samples):
    """Return float32 mono from a 1-D array or an (n, channels) array."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1).astype(np.float32)


class LinearResampler:
    """Stateful linear-interpolation resampler for chunked mono audio.

    Chunks may be any size; the fractional read position and the last input
    sample carry over, so chunked output matches one-shot output. Linear
    interpolation has no low-pass filter, so use it between close rates
    (44.1 kHz <-> 48 kHz). Large downsampling ratios will alias.
    """

    def __init__(self, in_rate, out_rate):
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError("sample rates must be positive")
        self.in_rate = in_rate
        self.out_rate = out_rate
        self._step = in_rate / out_rate
        self._next = 0.0  # position of next output sample, in global input coordinates
        self._seen = 0  # input samples consumed before the current chunk
        self._last = None  # final input sample of the previous chunk

    def process(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        if self.in_rate == self.out_rate or len(chunk) == 0:
            return chunk
        if self._last is None:
            x, base = chunk, self._seen
        else:
            x, base = np.concatenate(([self._last], chunk)), self._seen - 1
        last_index = base + len(x) - 1
        count = int(np.floor((last_index - self._next) / self._step)) + 1
        if count > 0:
            positions = self._next + self._step * np.arange(count)
            out = np.interp(positions - base, np.arange(len(x)), x).astype(np.float32)
            self._next += self._step * count
        else:
            out = np.zeros(0, dtype=np.float32)
        self._last = chunk[-1]
        self._seen += len(chunk)
        return out
