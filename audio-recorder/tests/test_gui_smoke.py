"""Drives the real tkinter widgets. Skipped where there is no tkinter or display."""
import time
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")

from recorder.controller import AppController, ThreadRunner  # noqa: E402
from recorder.gui import App  # noqa: E402
from tests.fakes import FakeBackend, FakeClock  # noqa: E402

RATE = 48000


class FakeModel:
    def transcribe(self, path, **kwargs):
        return iter([SimpleNamespace(start=0.0, end=1.0, text="hello from the test")]), None


@pytest.fixture
def window(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    clock = FakeClock(1000.0)
    backend = FakeBackend(rate=RATE)
    runner = ThreadRunner()
    controller = AppController(
        backend, runner, ask_save_target=lambda name: (tmp_path / "saved", True),
        model_loader=lambda *a: FakeModel(), out_base=tmp_path / "rec",
        now=lambda: datetime(2026, 10, 13, 9, 5), clock=clock)
    app = App(root, controller, runner)
    yield SimpleNamespace(root=root, app=app, backend=backend, clock=clock, tmp=tmp_path)
    try:
        root.destroy()
    except tk.TclError:
        pass


def pump(window, condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        window.root.update()
        if condition():
            return True
        time.sleep(0.02)
    return False


def disabled(window, name):
    return "disabled" in window.app.buttons[name].state()


def test_buttons_follow_the_workflow(window):
    app = window.app
    window.root.update()
    assert [disabled(window, n) for n in ("record", "stop", "save", "transcribe")] == [False, True, True, True]

    app.buttons["record"].invoke()
    assert "Recording" in app.indicator.cget("text")
    assert [disabled(window, n) for n in ("record", "stop", "save", "transcribe")] == [True, False, True, True]

    window.backend.mic.emit(1000.0, np.full(RATE, 0.2, dtype=np.float32))
    window.backend.loopback.emit(1000.0, np.full(RATE, 0.1, dtype=np.float32))
    window.clock.now = 1065.0
    assert pump(window, lambda: app.timer.cget("text") == "0:01:05")  # redrawn on the next tick

    app.buttons["stop"].invoke()
    assert pump(window, lambda: not disabled(window, "save"))
    assert app.indicator.cget("text") == "Not recording"

    app.buttons["transcribe"].invoke()
    assert pump(window, lambda: "hello from the test" in app.text.get("1.0", "end"))
    assert not disabled(window, "transcribe")

    app.buttons["save"].invoke()
    assert pump(window, lambda: (window.tmp / "saved" / "mix.mp3").exists() and not disabled(window, "save"))
    assert (window.tmp / "saved" / "transcript.txt").exists()
    assert "Saved to" in app.status.cget("text")


def test_closing_while_recording_keeps_the_recording(window):
    window.app.buttons["record"].invoke()
    window.backend.mic.emit(1000.0, np.full(RATE, 0.2, dtype=np.float32))
    window.clock.now = 1001.0
    session_dir = window.app.controller.snapshot().session_dir
    window.app.close()
    assert (session_dir / "mix.wav").exists()


def test_transcribe_a_file_button(window):
    audio = window.tmp / "memo.m4a"
    audio.write_bytes(b"")
    window.app.controller.ask_open_file = lambda: audio
    window.root.update()
    assert not disabled(window, "transcribe_file")
    window.app.buttons["transcribe_file"].invoke()
    assert pump(window, lambda: "hello from the test" in window.app.text.get("1.0", "end"))
    assert (window.tmp / "memo.transcript.txt").exists()
    assert "memo.transcript.txt" in window.app.status.cget("text")
