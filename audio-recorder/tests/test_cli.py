from datetime import datetime
from types import SimpleNamespace

import numpy as np

from recorder.cli import main
from tests.fakes import FakeSource


class FakeBackend:
    def __init__(self):
        self.mic = FakeSource("mic", 8000)
        self.loopback = FakeSource("loopback", 8000)

    def list_devices(self):
        return [{"index": 1, "name": "Headset Mic", "kind": "mic", "channels": 1,
                 "rate": 44100, "default": True},
                {"index": 2, "name": "Speakers [Loopback]", "kind": "loopback", "channels": 2,
                 "rate": 48000, "default": False}]

    def open_sources(self, mic_index, loopback_index):
        self.requested = (mic_index, loopback_index)
        return self.mic, self.loopback


class FakeModel:
    def transcribe(self, path, **kwargs):
        text = "from me" if path.endswith("me.wav") else "from them"
        return iter([SimpleNamespace(start=0.0, end=1.0, text=text)]), None


NOW = lambda: datetime(2026, 10, 13, 9, 5)


def test_devices_lists_with_default_marker(capsys):
    assert main(["devices"], backend=FakeBackend()) == 0
    out = capsys.readouterr().out
    assert "* [  1] mic" in out
    assert "  [  2] loopback" in out


def test_meeting_record_end_to_end(tmp_path, capsys):
    backend = FakeBackend()

    def waiter(session):
        backend.mic.emit(session._t0, np.full(8000, 0.2, dtype=np.float32))
        backend.loopback.emit(session._t0, np.full(8000, 0.1, dtype=np.float32))

    code = main(["record", "--out", str(tmp_path), "--mic", "1", "--loopback", "2",
                 "--sample-rate", "8000", "--transcribe"],
                backend=backend, waiter=waiter, model_loader=lambda *a: FakeModel(), now=NOW)
    out = capsys.readouterr().out
    session_dir = tmp_path / "26_1013_0905_meeting"
    assert code == 0
    assert backend.requested == (1, 2)
    assert "tell the other participants" in out
    assert "RECORDING (meeting)" in out
    for name in ("me.wav", "others.wav", "mix.wav", "transcript.txt", "transcript.srt"):
        assert (session_dir / name).exists(), name
    text = (session_dir / "transcript.txt").read_text()
    assert "Me: from me" in text and "Others: from them" in text


def test_karaoke_record_has_no_consent_banner_and_only_mix(tmp_path, capsys):
    backend = FakeBackend()
    code = main(["record", "--mode", "karaoke", "--out", str(tmp_path), "--sample-rate", "8000"],
                backend=backend, waiter=lambda s: None, now=NOW)
    out = capsys.readouterr().out
    session_dir = tmp_path / "26_1013_0905_karaoke"
    assert code == 0
    assert "tell the other participants" not in out
    assert (session_dir / "mix.wav").exists()
    assert not (session_dir / "voice.wav").exists()


def test_recording_is_saved_even_if_waiter_raises(tmp_path):
    backend = FakeBackend()

    def waiter(session):
        raise KeyboardInterrupt

    try:
        main(["record", "--out", str(tmp_path), "--sample-rate", "8000"],
             backend=backend, waiter=waiter, now=NOW)
    except KeyboardInterrupt:
        pass
    assert (tmp_path / "26_1013_0905_meeting" / "mix.wav").exists()


def test_transcribe_subcommand(tmp_path, capsys):
    (tmp_path / "me.wav").write_bytes(b"")
    code = main(["transcribe", str(tmp_path)], backend=FakeBackend(),
                model_loader=lambda *a: FakeModel())
    assert code == 0
    assert (tmp_path / "transcript.txt").read_text() == "[00:00:00] Me: from me\n"


def test_mp3_flag_writes_mix_mp3(tmp_path):
    backend = FakeBackend()

    def waiter(session):
        backend.mic.emit(session._t0, np.full(8000, 0.2, dtype=np.float32))

    main(["record", "--out", str(tmp_path), "--sample-rate", "8000", "--mp3"],
         backend=backend, waiter=waiter, now=NOW)
    assert (tmp_path / "26_1013_0905_meeting" / "mix.mp3").exists()
