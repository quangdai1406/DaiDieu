import numpy as np
import pytest

from recorder.audio import LinearResampler, to_mono


def sine(freq, sr, seconds):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_to_mono_averages_channels():
    stereo = np.array([[1.0, 0.0], [0.5, 0.5], [-1.0, 1.0]], dtype=np.float32)
    assert np.allclose(to_mono(stereo), [0.5, 0.5, 0.0])


def test_to_mono_passes_mono_through():
    mono = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    assert np.array_equal(to_mono(mono), mono)
    column = mono.reshape(-1, 1)
    assert np.array_equal(to_mono(column), mono)


def test_resampler_same_rate_is_identity():
    data = sine(440, 48000, 0.1)
    out = LinearResampler(48000, 48000).process(data)
    assert np.array_equal(out, data)


def test_resampler_rejects_bad_rates():
    with pytest.raises(ValueError):
        LinearResampler(0, 48000)


def test_resampler_output_length_matches_ratio():
    data = sine(440, 44100, 1.0)
    out = LinearResampler(44100, 48000).process(data)
    assert abs(len(out) - 48000) <= 2


def test_resampler_preserves_frequency():
    data = sine(440, 44100, 1.0)
    out = LinearResampler(44100, 48000).process(data)
    spectrum = np.abs(np.fft.rfft(out))
    peak_hz = np.argmax(spectrum) * 48000 / len(out)
    assert abs(peak_hz - 440) < 2


def test_resampler_chunked_equals_one_shot():
    data = sine(440, 44100, 0.5)
    one_shot = LinearResampler(44100, 48000).process(data)
    chunked_rs = LinearResampler(44100, 48000)
    pieces = [chunked_rs.process(data[i:i + 700]) for i in range(0, len(data), 700)]
    chunked = np.concatenate(pieces)
    n = min(len(one_shot), len(chunked))
    assert abs(len(one_shot) - len(chunked)) <= 2
    assert np.allclose(one_shot[:n], chunked[:n], atol=1e-4)


def test_resampler_handles_empty_chunk():
    out = LinearResampler(44100, 48000).process(np.zeros(0, dtype=np.float32))
    assert len(out) == 0
