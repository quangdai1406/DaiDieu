from datetime import datetime
from types import SimpleNamespace

import numpy as np

from recorder.cli import main
from tests.fakes import FakeBackend


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


def test_two_recordings_in_the_same_minute_do_not_overwrite(tmp_path):
    for _ in range(2):
        main(["record", "--out", str(tmp_path), "--sample-rate", "8000"],
             backend=FakeBackend(), waiter=lambda s: None, now=NOW)
    assert (tmp_path / "26_1013_0905_meeting" / "mix.wav").exists()
    assert (tmp_path / "26_1013_0905_meeting_2" / "mix.wav").exists()


def test_gui_command_opens_the_window_with_the_backend(monkeypatch):
    import sys

    opened = []
    monkeypatch.setitem(sys.modules, "recorder.gui",
                        SimpleNamespace(run=lambda backend, **options: opened.append((backend, options)) or 0))
    backend = FakeBackend()
    assert main(["gui"], backend=backend) == 0
    assert opened == [(backend, {"model_name": "base.en", "device": "cpu",
                                 "compute_type": None, "language": "en"})]


def test_gui_command_explains_a_missing_tkinter(monkeypatch, capsys):
    import sys

    monkeypatch.setitem(sys.modules, "recorder.gui", None)  # makes the import fail
    assert main(["gui"], backend=FakeBackend()) == 1
    assert "tkinter" in capsys.readouterr().out


def test_transcribe_subcommand_accepts_an_audio_file(tmp_path, capsys):
    audio = tmp_path / "Voice 261013_093023.m4a"
    audio.write_bytes(b"")
    code = main(["transcribe", str(audio)], backend=FakeBackend(), model_loader=lambda *a: FakeModel())
    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "Voice 261013_093023.transcript.txt").read_text() == "[00:00:00] from them\n"
    assert "Voice 261013_093023.transcript.txt" in out


def test_transcribe_subcommand_reports_a_missing_path(tmp_path, capsys):
    code = main(["transcribe", str(tmp_path / "nope.m4a")], backend=FakeBackend(),
                model_loader=lambda *a: FakeModel())
    assert code == 1
    assert "not found" in capsys.readouterr().out.lower()


def test_transcribe_prints_progress_so_it_never_looks_frozen(tmp_path, capsys):
    audio = tmp_path / "Voice 1.m4a"
    audio.write_bytes(b"")
    main(["transcribe", str(audio)], backend=FakeBackend(), model_loader=lambda *a: FakeModel())
    out = capsys.readouterr().out
    assert "Loading the speech model 'base.en'" in out
    assert "Transcribing Voice 1.m4a" in out
    assert out.index("Loading the speech model") < out.index("Transcribing") < out.index("Transcript:")


def test_transcribe_failure_is_reported_not_silent(tmp_path, capsys):
    audio = tmp_path / "Voice 1.m4a"
    audio.write_bytes(b"")

    def loader(*args):
        raise RuntimeError("boom")

    assert main(["transcribe", str(audio)], backend=FakeBackend(), model_loader=loader) == 1
    assert "Transcription failed: boom" in capsys.readouterr().out


def test_transcribe_missing_package_message_is_printed(tmp_path, capsys):
    audio = tmp_path / "Voice 1.m4a"
    audio.write_bytes(b"")

    def loader(*args):
        raise SystemExit("Transcription needs faster-whisper: pip install faster-whisper")

    assert main(["transcribe", str(audio)], backend=FakeBackend(), model_loader=loader) == 1
    assert "pip install faster-whisper" in capsys.readouterr().out


def test_gui_command_passes_the_speech_settings(monkeypatch):
    import sys

    opened = []
    monkeypatch.setitem(sys.modules, "recorder.gui",
                        SimpleNamespace(run=lambda backend, **options: opened.append(options) or 0))
    main(["gui", "--device", "cuda", "--model", "small.en", "--compute-type", "float16"],
         backend=FakeBackend())
    assert opened == [{"model_name": "small.en", "device": "cuda",
                       "compute_type": "float16", "language": "en"}]


def test_check_reports_cpu_and_gpu_separately(capsys):
    def probe(model, device):
        if device == "cpu":
            return True, 0, "PROBE OK"
        return False, -1073741819, "Windows fatal exception: access violation"

    assert main(["check"], backend=FakeBackend(), probe_runner=probe) == 0
    out = capsys.readouterr().out
    assert "cpu" in out and "OK" in out
    assert "cuda" in out and "FAILED" in out and "-1073741819" in out and "access violation" in out
    assert "python -m recorder gui" in out
    assert "requirements-gpu.txt" in out


def test_check_recommends_the_gpu_when_it_works(capsys):
    assert main(["check", "--model", "tiny.en"], backend=FakeBackend(),
                probe_runner=lambda model, device: (True, 0, "PROBE OK")) == 0
    assert "gui --device cuda" in capsys.readouterr().out


def test_check_fails_when_nothing_works(capsys):
    assert main(["check"], backend=FakeBackend(),
                probe_runner=lambda model, device: (False, 1, "nope")) == 1
    assert "Neither" in capsys.readouterr().out
