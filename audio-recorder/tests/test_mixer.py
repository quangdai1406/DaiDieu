import numpy as np
import pytest
import soundfile as sf

from recorder.mixer import mix_wavs

SR = 8000


def write(path, values, sr=SR):
    sf.write(path, np.asarray(values, dtype=np.float32), sr, subtype="PCM_16")


def read(path):
    data, sr = sf.read(path, dtype="float32")
    return data, sr


def test_mix_applies_gains(tmp_path):
    write(tmp_path / "a.wav", np.full(SR, 0.2))
    write(tmp_path / "b.wav", np.full(SR, 0.4))
    mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "b.wav", 0.5)], tmp_path / "m.wav")
    data, sr = read(tmp_path / "m.wav")
    assert sr == SR
    assert np.allclose(data, 0.4, atol=1e-3)


def test_mix_pads_shorter_input(tmp_path):
    write(tmp_path / "a.wav", np.full(SR, 0.3))
    write(tmp_path / "b.wav", np.full(SR // 2, 0.3))
    mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "b.wav", 1.0)], tmp_path / "m.wav")
    data, _ = read(tmp_path / "m.wav")
    assert len(data) == SR
    assert np.allclose(data[: SR // 2], 0.6, atol=1e-3)
    assert np.allclose(data[SR // 2:], 0.3, atol=1e-3)


def test_mix_clips_instead_of_wrapping(tmp_path):
    write(tmp_path / "a.wav", np.full(SR, 0.9))
    write(tmp_path / "b.wav", np.full(SR, 0.9))
    mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "b.wav", 1.0)], tmp_path / "m.wav")
    data, _ = read(tmp_path / "m.wav")
    assert data.max() <= 1.0
    assert data.min() > 0.9


def test_mix_works_across_block_boundaries(tmp_path):
    ramp = np.linspace(-0.4, 0.4, 5000)
    write(tmp_path / "a.wav", ramp)
    write(tmp_path / "b.wav", ramp)
    mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "b.wav", 1.0)], tmp_path / "m.wav", blocksize=777)
    data, _ = read(tmp_path / "m.wav")
    assert len(data) == 5000
    assert np.allclose(data, ramp * 2, atol=1e-3)


def test_mix_rejects_mismatched_sample_rates(tmp_path):
    write(tmp_path / "a.wav", np.zeros(100), sr=8000)
    write(tmp_path / "b.wav", np.zeros(100), sr=16000)
    with pytest.raises(ValueError):
        mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "b.wav", 1.0)], tmp_path / "m.wav")


def test_mix_skips_missing_inputs(tmp_path):
    write(tmp_path / "a.wav", np.full(SR, 0.2))
    mix_wavs([(tmp_path / "a.wav", 1.0), (tmp_path / "missing.wav", 1.0)], tmp_path / "m.wav")
    data, _ = read(tmp_path / "m.wav")
    assert np.allclose(data, 0.2, atol=1e-3)


def test_export_mp3_keeps_duration_and_is_much_smaller(tmp_path):
    from recorder.mixer import export_mp3

    t = np.arange(SR * 4) / SR
    write(tmp_path / "a.wav", 0.4 * np.sin(2 * np.pi * 440 * t), sr=SR)
    out = export_mp3(tmp_path / "a.wav", tmp_path / "a.mp3", blocksize=3000)
    info = sf.info(out)
    assert info.format == "MP3"
    assert info.samplerate == SR
    assert abs(info.duration - 4.0) < 0.1
    assert out.stat().st_size < (tmp_path / "a.wav").stat().st_size / 2
