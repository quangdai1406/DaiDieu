import numpy as np
import pytest
import soundfile as sf

from recorder.session import RecordingSession
from tests.fakes import FakeClock, FakeSource

SR = 8000


def tone(seconds, value, sr=SR):
    return np.full(int(sr * seconds), value, dtype=np.float32)


def read(path):
    data, sr = sf.read(path, dtype="float32")
    return data, sr


def make(tmp_path, mode="meeting", mic_sr=SR, loop_sr=SR, **kwargs):
    clock = FakeClock(1000.0)
    mic = FakeSource("mic", mic_sr)
    loop = FakeSource("loopback", loop_sr)
    session = RecordingSession(tmp_path, mic, loop, mode=mode, sample_rate=SR, clock=clock, **kwargs)
    return session, mic, loop, clock


def test_meeting_mode_writes_tracks_and_mix(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    mic.emit(1000.0, tone(1.0, 0.2))
    loop.emit(1000.0, tone(1.0, 0.1))
    clock.now = 1001.0
    result = session.stop()

    me, _ = read(tmp_path / "me.wav")
    others, _ = read(tmp_path / "others.wav")
    mix, sr = read(tmp_path / "mix.wav")
    assert sr == SR
    assert len(me) == len(others) == len(mix) == SR
    assert np.allclose(me, 0.2, atol=1e-3)
    assert np.allclose(others, 0.1, atol=1e-3)
    assert np.allclose(mix, 0.3, atol=1e-3)
    assert result.mix == tmp_path / "mix.wav"
    assert set(result.tracks) == {"me", "others"}
    assert result.duration == pytest.approx(1.0)


def test_silent_loopback_is_padded_and_stays_aligned(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    mic.emit(1000.0, tone(2.0, 0.2))
    loop.emit(1001.0, tone(1.0, 0.1))  # speakers were silent for the first second
    clock.now = 1002.0
    session.stop()

    me, _ = read(tmp_path / "me.wav")
    others, _ = read(tmp_path / "others.wav")
    assert len(me) == len(others) == 2 * SR
    assert np.allclose(others[:SR], 0.0, atol=1e-3)
    assert np.allclose(others[SR:], 0.1, atol=1e-3)


def test_trailing_silence_is_padded_to_session_end(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    mic.emit(1000.0, tone(1.0, 0.2))
    clock.now = 1003.0
    session.stop()
    others, _ = read(tmp_path / "others.wav")
    assert len(others) == 3 * SR


def test_sources_are_resampled_to_the_session_rate(tmp_path):
    session, mic, loop, clock = make(tmp_path, mic_sr=6000, loop_sr=8000)
    session.start()
    mic.emit(1000.0, tone(1.0, 0.2, sr=6000))
    loop.emit(1000.0, tone(1.0, 0.1))
    clock.now = 1001.0
    session.stop()
    me, sr = read(tmp_path / "me.wav")
    assert sr == SR
    assert abs(len(me) - SR) <= 2


def test_stereo_input_is_downmixed(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    stereo = np.stack([tone(1.0, 0.4), tone(1.0, 0.0)], axis=1)
    loop.emit(1000.0, stereo)
    clock.now = 1001.0
    session.stop()
    others, _ = read(tmp_path / "others.wav")
    assert np.allclose(others, 0.2, atol=1e-3)


def test_karaoke_mode_applies_gains_and_drops_raw_tracks(tmp_path):
    session, mic, loop, clock = make(tmp_path, mode="karaoke", mic_gain=0.5, music_gain=2.0)
    session.start()
    mic.emit(1000.0, tone(1.0, 0.2))
    loop.emit(1000.0, tone(1.0, 0.1))
    clock.now = 1001.0
    result = session.stop()
    mix, _ = read(tmp_path / "mix.wav")
    assert np.allclose(mix, 0.2 * 0.5 + 0.1 * 2.0, atol=1e-3)
    assert not (tmp_path / "voice.wav").exists()
    assert not (tmp_path / "music.wav").exists()
    assert result.tracks == {}


def test_karaoke_keep_tracks(tmp_path):
    session, mic, loop, clock = make(tmp_path, mode="karaoke", keep_tracks=True)
    session.start()
    mic.emit(1000.0, tone(1.0, 0.2))
    clock.now = 1001.0
    result = session.stop()
    assert (tmp_path / "voice.wav").exists()
    assert (tmp_path / "music.wav").exists()
    assert set(result.tracks) == {"voice", "music"}


def test_failed_source_start_stops_the_other_and_raises(tmp_path):
    clock = FakeClock()
    mic = FakeSource("mic", SR)
    loop = FakeSource("loopback", SR, fail_on_start=True)
    session = RecordingSession(tmp_path, mic, loop, sample_rate=SR, clock=clock)
    with pytest.raises(RuntimeError, match="cannot open device"):
        session.start()
    assert mic.stopped


def test_peaks_report_latest_level_per_source(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    mic.emit(1000.0, tone(0.5, 0.25))
    loop.emit(1000.0, tone(0.5, 0.5))
    clock.now = 1000.5
    session.stop()
    assert session.peaks["mic"] == pytest.approx(0.25)
    assert session.peaks["loopback"] == pytest.approx(0.5)


def test_stop_twice_returns_same_result(tmp_path):
    session, mic, loop, clock = make(tmp_path)
    session.start()
    mic.emit(1000.0, tone(0.5, 0.2))
    clock.now = 1000.5
    first = session.stop()
    assert session.stop() == first


def test_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        make(tmp_path, mode="podcast")
