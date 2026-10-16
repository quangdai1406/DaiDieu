import numpy as np

import recorder.transcribe as transcribe_module
from recorder import probe


def test_probe_loads_the_model_and_runs_a_second_of_audio(monkeypatch, capsys):
    seen = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            seen["audio"], seen["kwargs"] = audio, kwargs
            return iter([]), None

    monkeypatch.setattr(transcribe_module, "load_model",
                        lambda name, device, compute_type: seen.update(args=(name, device, compute_type)) or FakeModel())
    assert probe.main(["probe", "tiny.en", "cuda"]) == 0
    assert seen["args"] == ("tiny.en", "cuda", None)
    assert isinstance(seen["audio"], np.ndarray) and len(seen["audio"]) == 16000
    assert "PROBE OK" in capsys.readouterr().out


def test_probe_reports_a_plain_reason_when_loading_fails(monkeypatch, capsys):
    def boom(name, device, compute_type):
        raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    monkeypatch.setattr(transcribe_module, "load_model", boom)
    assert probe.main(["probe", "tiny.en", "cuda"]) == 1
    out = capsys.readouterr().out
    assert "Transcription failed: Library cublas64_12.dll" in out
    assert "requirements-gpu.txt" in out
    assert "PROBE OK" not in out
