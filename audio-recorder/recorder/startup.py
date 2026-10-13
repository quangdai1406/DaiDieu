"""Make a windowless launch safe (the desktop shortcut starts the app with pythonw.exe)."""

import os
import sys
from pathlib import Path


def default_log_dir():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Meeting Recorder"


def prepare_streams(log_dir=None):
    """Give a windowless process somewhere to print.

    ``pythonw.exe`` starts with ``sys.stdout`` and ``sys.stderr`` set to None, which breaks
    ``print()`` and the model-download progress bars. Missing streams are sent to
    ``<log_dir>/last-run.log`` instead, so errors can still be read afterwards.
    Returns the log path, or None when both streams already exist.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    folder = Path(log_dir) if log_dir else default_log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "last-run.log"
        log = open(path, "w", encoding="utf-8", buffering=1)
    except OSError:  # cannot write a log: at least stop print() from crashing
        path, log = None, open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    return path
