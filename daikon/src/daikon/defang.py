"""Make URLs unclickable in anything Daikon shows or sends (RT-02): hxxps://host[.]tld/path."""

from __future__ import annotations

import re

_SCHEME_URL = re.compile(r"\b(https?|ftp)://([^\s<>\"'/?#]+)([^\s<>\"']*)", re.IGNORECASE)
_WWW = re.compile(r"\bwww\.[A-Za-z0-9.\-]+", re.IGNORECASE)
_SCHEMES = {"http": "hxxp", "https": "hxxps", "ftp": "fxp"}


def _url(m: re.Match[str]) -> str:
    scheme = _SCHEMES[m.group(1).lower()]
    return f"{scheme}://{m.group(2).replace('.', '[.]')}{m.group(3)}"


def defang(text: str) -> str:
    return _WWW.sub(lambda m: m.group(0).replace(".", "[.]"), _SCHEME_URL.sub(_url, text))
