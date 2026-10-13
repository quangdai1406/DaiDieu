import numpy as np
import soundfile as sf

from recorder.track import TrackWriter

SR = 8000


def chunk(seconds, value=0.25):
    return np.full(int(SR * seconds), value, dtype=np.float32)


def read(path):
    data, sr = sf.read(path, dtype="float32")
    return data, sr


def test_contiguous_chunks_have_exact_length(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=100.0)
    w.write(100.0, chunk(0.5))
    w.write(100.5, chunk(0.5))
    w.close()
    data, sr = read(tmp_path / "a.wav")
    assert sr == SR
    assert len(data) == SR


def test_leading_silence_when_first_chunk_is_late(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=100.0)
    w.write(101.0, chunk(0.5))
    w.close()
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == int(1.5 * SR)
    assert np.allclose(data[:SR], 0.0, atol=1e-3)
    assert np.allclose(data[SR:], 0.25, atol=1e-3)


def test_gap_is_filled_with_silence(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=0.0)
    w.write(0.0, chunk(0.5))
    w.write(2.0, chunk(0.5))  # loopback sent nothing for 1.5 s
    w.close()
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == int(2.5 * SR)
    assert np.allclose(data[int(0.5 * SR):int(2.0 * SR)], 0.0, atol=1e-3)


def test_small_jitter_does_not_insert_silence(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=0.0, tolerance=0.05)
    w.write(0.0, chunk(0.5))
    w.write(0.52, chunk(0.5))  # 20 ms late, inside tolerance
    w.close()
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == SR


def test_overlap_beyond_tolerance_is_trimmed(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=0.0, tolerance=0.05)
    w.write(0.0, chunk(1.0))
    w.write(0.5, chunk(1.0))  # claims to start 0.5 s before the previous chunk ended
    w.close()
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == int(1.5 * SR)


def test_close_pads_to_end_time_so_tracks_match(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=10.0)
    w.write(10.0, chunk(1.0))
    w.close(end_time=13.0)
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == 3 * SR


def test_flush_makes_file_readable_while_open(tmp_path):
    path = tmp_path / "a.wav"
    w = TrackWriter(path, SR, t0=0.0)
    w.write(0.0, chunk(1.0))
    w.flush()
    data, sr = read(path)  # simulates a crash: the writer is never closed
    assert sr == SR
    assert len(data) == SR
    w.close()


def test_write_after_close_is_ignored(tmp_path):
    w = TrackWriter(tmp_path / "a.wav", SR, t0=0.0)
    w.write(0.0, chunk(0.5))
    w.close()
    w.write(0.5, chunk(0.5))
    data, _ = read(tmp_path / "a.wav")
    assert len(data) == int(0.5 * SR)
