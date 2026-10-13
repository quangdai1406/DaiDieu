"""The four-button window: Record, Stop, Save, Transcribe.

Only drawing lives here. Every rule is in controller.py, which is tested
without a display.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .controller import AppController, State, ThreadRunner, format_elapsed

REFRESH_MS = 100
BUTTONS = (("record", "Record"), ("stop", "Stop"), ("save", "Save"), ("transcribe", "Transcribe"))
RED, GREEN = "#b00020", "#1b6e2d"


def ask_save_target(default_name):
    """Ask for a folder name to copy the recording into, and whether to add an MP3."""
    chosen = filedialog.asksaveasfilename(
        title="Choose where to save, and a name for this recording",
        initialfile=default_name, confirmoverwrite=False)
    if not chosen:
        return None
    want_mp3 = messagebox.askyesno(
        "Also save an MP3?",
        "Also save a small mix.mp3? It is handy for uploading to Word's Transcribe.")
    return Path(chosen), want_mp3


class App:
    def __init__(self, root, controller, runner):
        self.root, self.controller, self.runner = root, controller, runner
        self._shown_transcript = None
        root.title("Meeting Recorder")
        root.minsize(460, 520)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._unexpected_error

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)

        self.indicator = ttk.Label(frame, text="Not recording", font=("Segoe UI", 11, "bold"))
        self.indicator.pack(anchor="w")
        self.timer = ttk.Label(frame, text=format_elapsed(0), font=("Segoe UI", 30))
        self.timer.pack(anchor="w", pady=(0, 8))

        self.mic_bar = self._level_row(frame, "Mic")
        self.speaker_bar = self._level_row(frame, "Speakers")

        self.buttons = {}
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=12)
        for name, label in BUTTONS:
            button = ttk.Button(row, text=label, command=lambda n=name: self.press(n))
            button.pack(side="left", expand=True, fill="x", padx=3)
            self.buttons[name] = button

        self._default_color = ttk.Style().lookup("TLabel", "foreground") or "black"
        self.status = ttk.Label(frame, text="", wraplength=420, justify="left")
        self.status.pack(anchor="w", fill="x")
        frame.bind("<Configure>", lambda e: self.status.configure(wraplength=max(200, e.width - 32)))

        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True, pady=(12, 0))
        self.text = tk.Text(box, height=10, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.refresh()

    def _level_row(self, parent, label):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=9).pack(side="left")
        bar = ttk.Progressbar(row, maximum=100)
        bar.pack(side="left", fill="x", expand=True)
        return bar

    def press(self, name):
        getattr(self.controller, name)()
        self.render()

    def refresh(self):
        """Timer tick: finish background work, redraw, schedule the next tick."""
        self.runner.poll()
        self.render()
        self._after_id = self.root.after(REFRESH_MS, self.refresh)

    def render(self):
        snap = self.controller.snapshot()
        recording = snap.state is State.RECORDING
        self.indicator.configure(text="● Recording" if recording else "Not recording",
                                 foreground=RED if recording else self._default_color)
        self.timer.configure(text=format_elapsed(snap.elapsed))
        self.mic_bar["value"] = min(snap.mic_level, 1.0) * 100
        self.speaker_bar["value"] = min(snap.speaker_level, 1.0) * 100
        for name, button in self.buttons.items():
            button.state(["!disabled"] if snap.enabled[name] else ["disabled"])
        color = {"error": RED, "ok": GREEN}.get(snap.message_kind, self._default_color)
        self.status.configure(text=snap.message, foreground=color)
        if snap.transcript != self._shown_transcript:
            self._shown_transcript = snap.transcript
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", snap.transcript)
            self.text.configure(state="disabled")

    def close(self):
        self.controller.shutdown()  # never lose a recording in progress
        self.root.destroy()

    def _unexpected_error(self, exc_type, exc, tb):
        messagebox.showerror("Something went wrong", f"{exc_type.__name__}: {exc}")


def run(backend):
    root = tk.Tk()
    runner = ThreadRunner()
    App(root, AppController(backend, runner, ask_save_target), runner)
    root.mainloop()
    return 0
