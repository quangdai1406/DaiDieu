"""Voice guide for drafts. Dai-owned text from a local file (later synced from the
``dai-email-drafting`` skill); it is added to the system prompt as trusted instructions."""

from __future__ import annotations

import re
from pathlib import Path

from daikon.guard import contains_secret

MAX_STYLE_CHARS = 4000
DEFAULT_STYLE = (
    "Write in Dai Tran's professional voice: short and direct. Be informal with colleagues "
    "and formal with external contacts. Do not invent facts, commitments, prices or dates; "
    "if something is unknown, say Dai will follow up."
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def load_style(path: Path | None) -> str:
    if path is None or not path.is_file():
        return DEFAULT_STYLE
    text = _CONTROL.sub("", path.read_text(encoding="utf-8")).strip()
    if contains_secret(text):
        raise ValueError("style file looks like it contains a secret")
    return text[:MAX_STYLE_CHARS] if text else DEFAULT_STYLE
