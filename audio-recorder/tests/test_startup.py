import struct
import sys
from pathlib import Path

import recorder
from recorder.startup import prepare_streams


def test_nothing_changes_when_the_streams_exist(tmp_path):
    before = (sys.stdout, sys.stderr)
    assert prepare_streams(tmp_path) is None
    assert (sys.stdout, sys.stderr) == before
    assert list(tmp_path.iterdir()) == []


def test_a_windowless_launch_writes_to_a_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)  # what pythonw.exe starts with
    monkeypatch.setattr(sys, "stderr", None)
    log = prepare_streams(tmp_path / "logs")
    try:
        print("progress that a download bar would print")
        sys.stderr.write("an error message\n")
        sys.stdout.flush()
        text = log.read_text(encoding="utf-8")
        assert "progress that a download bar would print" in text
        assert "an error message" in text
        assert log == tmp_path / "logs" / "last-run.log"
    finally:
        sys.stdout.close()


def test_only_the_missing_stream_is_redirected(tmp_path, monkeypatch):
    original_stdout = sys.stdout
    monkeypatch.setattr(sys, "stderr", None)
    log = prepare_streams(tmp_path)
    try:
        assert sys.stdout is original_stdout
        assert sys.stderr is not None
        sys.stderr.write("only errors here\n")
        sys.stderr.flush()
        assert "only errors here" in log.read_text(encoding="utf-8")
    finally:
        sys.stderr.close()


def test_the_app_icon_is_a_valid_multi_size_ico():
    data = (Path(recorder.__file__).parent / "app.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 4
    for i in range(count):
        width, height, _c, _r, planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        assert bpp == 32
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + size <= len(data)
