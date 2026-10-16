"""Daily backup of the parts of ``daikon-data`` that cannot be rebuilt.

Copies ``graph``, ``audit`` and ``limits.json`` into ``backups/<date>/`` (once a day, last
seven kept). The PAUSE file, logs and earlier backups are not copied. A backup is built in a
temporary folder and renamed, so a crash never leaves a half-written backup that looks complete.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

PARTS = ("graph", "audit", "limits.json")


def daily_backup(data_dir: Path, now: datetime, keep: int = 7) -> Path | None:
    """Make today's backup. Returns its folder, or ``None`` if today's already exists."""
    root = data_dir / "backups"
    final = root / f"{now:%Y-%m-%d}"
    if final.exists():
        return None
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.glob(".tmp-*"):
        shutil.rmtree(stale, ignore_errors=True)
    tmp = root / f".tmp-{now:%Y-%m-%d}"
    tmp.mkdir()
    for name in PARTS:
        src = data_dir / name
        if src.is_dir():
            shutil.copytree(src, tmp / name, symlinks=True)
        elif src.is_file():
            shutil.copy2(src, tmp / name)
    tmp.rename(final)
    finished = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    for old in finished[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return final
