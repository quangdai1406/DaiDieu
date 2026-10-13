from types import SimpleNamespace

import os
import sys
import types

import pytest

import recorder.transcribe as transcribe_module

from recorder.transcribe import (Segment, add_nvidia_dll_dirs, coalesce, explain_error, load_model, resolve_compute_type, format_srt_time, format_clock,
                                 merge_segments, to_srt, to_txt, transcribe_file, transcribe_track,
                                 write_transcripts)


class FakeModel:
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return iter(self._segments), SimpleNamespace(language="en")


def seg(start, end, speaker, text):
    return Segment(start, end, speaker, text)


def test_format_clock():
    assert format_clock(0) == "00:00:00"
    assert format_clock(3725.9) == "01:02:05"


def test_format_srt_time():
    assert format_srt_time(3725.5) == "01:02:05,500"
    assert format_srt_time(0.0004) == "00:00:00,000"


def test_merge_orders_by_start_across_speakers():
    me = [seg(5.0, 6.0, "Me", "hello"), seg(20.0, 21.0, "Me", "bye")]
    others = [seg(1.0, 4.0, "Others", "hi there"), seg(10.0, 12.0, "Others", "ok")]
    merged = merge_segments(me, others)
    assert [s.text for s in merged] == ["hi there", "hello", "ok", "bye"]


def test_coalesce_joins_same_speaker_close_together():
    segs = [seg(0, 2, "Me", "first part"), seg(2.5, 4, "Me", "second part"),
            seg(4.2, 6, "Others", "reply"), seg(30, 31, "Me", "later")]
    out = coalesce(segs, max_gap=1.5)
    assert [(s.speaker, s.text) for s in out] == [
        ("Me", "first part second part"), ("Others", "reply"), ("Me", "later")]
    assert out[0].start == 0 and out[0].end == 4


def test_to_txt_lines():
    text = to_txt([seg(5, 6, "Me", "hello"), seg(65, 66, "Others", "hi")])
    assert text == "[00:00:05] Me: hello\n[00:01:05] Others: hi\n"


def test_to_srt_blocks():
    srt = to_srt([seg(1.0, 2.5, "Me", "hello"), seg(3.0, 4.0, "Others", "hi")])
    assert srt == (
        "1\n00:00:01,000 --> 00:00:02,500\nMe: hello\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nOthers: hi\n\n"
    )


def test_transcribe_track_labels_and_strips(tmp_path):
    model = FakeModel([SimpleNamespace(start=0.0, end=1.0, text="  hello  "),
                       SimpleNamespace(start=1.0, end=2.0, text="   ")])
    out = transcribe_track(model, tmp_path / "me.wav", "Me", language="en")
    assert out == [Segment(0.0, 1.0, "Me", "hello")]
    path, kwargs = model.calls[0]
    assert path == str(tmp_path / "me.wav")
    assert kwargs["vad_filter"] is True
    assert kwargs["language"] == "en"


def test_write_transcripts_creates_txt_and_srt(tmp_path):
    (tmp_path / "me.wav").write_bytes(b"")
    (tmp_path / "others.wav").write_bytes(b"")

    class PerFileModel:
        def transcribe(self, path, **kwargs):
            if path.endswith("me.wav"):
                data = [SimpleNamespace(start=5.0, end=6.0, text="from me")]
            else:
                data = [SimpleNamespace(start=1.0, end=2.0, text="from them")]
            return iter(data), SimpleNamespace(language="en")

    txt, srt = write_transcripts(PerFileModel(), tmp_path, {"me": "Me", "others": "Others"})
    assert txt.read_text() == "[00:00:01] Others: from them\n[00:00:05] Me: from me\n"
    assert "Others: from them" in srt.read_text()
    assert txt.name == "transcript.txt" and srt.name == "transcript.srt"


def test_write_transcripts_skips_missing_tracks(tmp_path):
    (tmp_path / "me.wav").write_bytes(b"")
    model = FakeModel([SimpleNamespace(start=0.0, end=1.0, text="only me")])
    txt, _ = write_transcripts(model, tmp_path, {"me": "Me", "others": "Others"})
    assert txt.read_text() == "[00:00:00] Me: only me\n"


def test_txt_and_srt_omit_an_empty_speaker_label():
    segs = [seg(5, 6, "", "hello")]
    assert to_txt(segs) == "[00:00:05] hello\n"
    assert to_srt(segs) == "1\n00:00:05,000 --> 00:00:06,000\nhello\n\n"


def test_transcribe_file_writes_next_to_the_source(tmp_path):
    audio = tmp_path / "Voice 261013_093023.m4a"
    audio.write_bytes(b"")
    model = FakeModel([SimpleNamespace(start=0.0, end=2.0, text=" hello there "),
                       SimpleNamespace(start=2.5, end=4.0, text="second part")])
    txt, srt = transcribe_file(model, audio, language="en")
    assert txt == tmp_path / "Voice 261013_093023.transcript.txt"
    assert srt == tmp_path / "Voice 261013_093023.transcript.srt"
    assert txt.read_text(encoding="utf-8") == "[00:00:00] hello there second part\n"
    path, kwargs = model.calls[0]
    assert path == str(audio)
    assert kwargs["language"] == "en"


def test_transcribe_file_never_overwrites_an_earlier_transcript(tmp_path):
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"")
    model = FakeModel([SimpleNamespace(start=0.0, end=1.0, text="hi")])
    first_txt, _ = transcribe_file(model, audio)
    first_txt.write_text("my edits", encoding="utf-8")
    model._segments = [SimpleNamespace(start=0.0, end=1.0, text="hi")]
    second_txt, second_srt = transcribe_file(model, audio)
    assert second_txt == tmp_path / "a.transcript_2.txt"
    assert second_srt == tmp_path / "a.transcript_2.srt"
    assert first_txt.read_text(encoding="utf-8") == "my edits"


def test_transcribe_file_reports_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        transcribe_file(FakeModel([]), tmp_path / "nope.m4a")


def test_resolve_compute_type_defaults_per_device():
    assert resolve_compute_type("cpu", None) == "int8"
    assert resolve_compute_type("cuda", None) == "auto"
    assert resolve_compute_type("auto", None) == "auto"
    assert resolve_compute_type("cuda", "float16") == "float16"


def test_add_nvidia_dll_dirs_finds_the_bin_folders(tmp_path, monkeypatch):
    site = tmp_path / "site"
    cublas_bin = site / "nvidia" / "cublas" / "bin"
    cudnn_bin = site / "nvidia" / "cudnn" / "bin"
    for folder in (cublas_bin, cudnn_bin, site / "nvidia" / "other"):
        folder.mkdir(parents=True)
    added = []
    monkeypatch.setattr(os, "add_dll_directory", lambda p: added.append(p), raising=False)
    monkeypatch.setenv("PATH", "old_path")

    dirs = add_nvidia_dll_dirs([str(site)])
    assert sorted(dirs) == sorted([str(cublas_bin), str(cudnn_bin)])
    assert sorted(added) == sorted(dirs)
    parts = os.environ["PATH"].split(os.pathsep)
    assert set(dirs) <= set(parts) and "old_path" in parts

    add_nvidia_dll_dirs([str(site)])  # calling again must not pile up PATH entries
    assert os.environ["PATH"].split(os.pathsep).count(str(cublas_bin)) == 1


def test_add_nvidia_dll_dirs_with_nothing_installed(tmp_path):
    assert add_nvidia_dll_dirs([str(tmp_path)]) == []


def test_load_model_passes_device_and_the_resolved_compute_type(monkeypatch):
    calls, dll_calls = [], []
    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = lambda name, device, compute_type: calls.append((name, device, compute_type)) or "model"
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(transcribe_module, "add_nvidia_dll_dirs", lambda *a: dll_calls.append(1) or [])

    assert load_model("base.en", "cpu", None) == "model"
    assert calls[-1] == ("base.en", "cpu", "int8") and dll_calls == []
    load_model("small.en", "cuda", None)
    assert calls[-1] == ("small.en", "cuda", "auto") and dll_calls == [1]
    load_model("small.en", "cuda", "float16")
    assert calls[-1] == ("small.en", "cuda", "float16")


def test_explain_error_adds_a_gpu_hint_for_missing_cuda_libraries():
    msg = explain_error(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))
    assert "cublas64_12.dll" in msg
    assert "requirements-gpu.txt" in msg and "--device cpu" in msg


def test_explain_error_leaves_other_errors_alone():
    assert explain_error(RuntimeError("boom")) == "Transcription failed: boom"
    assert explain_error(SystemExit("needs a package")) == "needs a package"
