import os
import sys
from pathlib import Path


def default_log_dir():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Meeting Recorder"


def prepare_streams(log_dir=None):
    if sys.stdout is not None and sys.stderr is not None:
        return None
    folder = Path(log_dir) if log_dir else default_log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "last-run.log"
        log = open(path, "w", encoding="utf-8", buffering=1)
    except OSError:
        path, log = None, open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    return path
