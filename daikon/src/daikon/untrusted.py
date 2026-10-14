"""The Untrusted type and the one normalization pipeline every inbound source goes through.

Everything that comes from outside (email, SMS, Drive notes, skill text) is wrapped in an
``Untrusted`` value: cleaned of invisible and hidden content, size-capped, split into
top-level and quoted/forwarded text, and tagged with flags that Dai sees in the digest.
Flags are warnings, never permissions. Nothing here fetches links or opens attachments.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser

DEFAULT_MAX_CHARS = 20_000
_TRUNC_MARKER = "\n[truncated]"


class Source(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    DRIVE = "drive"
    SKILL = "skill"


class Trust(StrEnum):
    UNTRUSTED = "untrusted"
    KNOWN = "known"
    OWNER = "owner"


@dataclass(frozen=True)
class Untrusted:
    text: str
    source: Source
    origin: str
    owner: str | None = None
    trust: Trust = Trust.UNTRUSTED
    flags: frozenset[str] = field(default_factory=frozenset)
    original_length: int = 0
    quoted_text: str = ""


# ---------- cleaning ----------
def _clean(text: str) -> tuple[str, set[str]]:
    flags: set[str] = set()
    out: list[str] = []
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        cat = unicodedata.category(ch)
        if 0xE0000 <= ord(ch) <= 0xE007F:
            flags.update({"hidden_text", "unicode_tags"})
        elif cat == "Cf":
            flags.add("hidden_text")
        elif cat == "Cc" and ch not in "\n\t":
            continue
        else:
            out.append(ch)
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), flags


_INSTRUCTION_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+(all\s+|any\s+)?(previous|prior|above|your)\s+(instructions?|rules?)",
        r"you\s+are\s+now\s+in\s+\w+\s+mode",
        r"^\s*(system|assistant|developer)\s*:",
        r"<\|[a-z_]+\|>",
        r"\[/?(system|inst)\]",
        r"(reveal|show|print|output)\s+(your\s+)?(system\s+prompt|instructions)",
        r"new\s+instructions?\s*:",
        r"do\s+not\s+(tell|inform|notify)\s+(dai|the\s+user)",
    )
]


def _instruction_like(text: str) -> bool:
    return any(p.search(text) for p in _INSTRUCTION_PATTERNS)


def _cap(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[: max_chars - len(_TRUNC_MARKER)] + _TRUNC_MARKER, True


# ---------- quoted / forwarded text ----------
_FORWARD = re.compile(
    r"^(-{2,}\s*(forwarded message|original message)\s*-{2,}|begin forwarded message:)\s*$",
    re.IGNORECASE,
)
_REPLY_HEADER = re.compile(r"^On .{5,300}wrote:\s*$", re.IGNORECASE)


def _split_quoted(text: str) -> tuple[str, str, set[str]]:
    flags: set[str] = set()
    top: list[str] = []
    quoted: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _FORWARD.match(line.strip()):
            flags.add("forwarded")
            quoted.extend(lines[i:])
            break
        if _REPLY_HEADER.match(line.strip()) or _REPLY_HEADER.match(f"{line} {nxt}".strip()):
            flags.add("quoted")
            quoted.extend(lines[i:])
            break
        if line.lstrip().startswith(">"):
            flags.add("quoted")
            quoted.append(line)
        else:
            top.append(line)
        i += 1
    return "\n".join(top).strip(), "\n".join(quoted).strip(), flags


# ---------- HTML ----------
_HIDING_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(px|pt|em|%)?\s*(;|$)"
    r"|opacity\s*:\s*0(\.0+)?\s*(;|$)|max-height\s*:\s*0|text-indent\s*:\s*-\d{3,}"
    r"|(left|top)\s*:\s*-\d{3,}",
)
_LOW_CONTRAST = re.compile(
    r"(?<![-\w])color\s*:\s*(#fff(fff)?\b|white\b|transparent\b|rgba?\(\s*255\s*,\s*255\s*,\s*255)"
)
_ALWAYS_HIDDEN = frozenset({"script", "style", "head", "title", "noscript", "template", "iframe"})
_VOID = frozenset({"br", "hr", "img", "meta", "link", "input", "area", "base", "col", "embed",
                   "source", "track", "wbr"})
_BLOCK = frozenset({"p", "div", "li", "tr", "table", "ul", "ol", "blockquote", "section",
                    "article", "h1", "h2", "h3", "h4", "h5", "h6"})


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.flags: set[str] = set()
        self._stack: list[tuple[str, bool]] = []

    def _hidden_now(self) -> bool:
        return any(hidden for _, hidden in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        style = a.get("style", "").lower()
        if tag in ("img", "link", "iframe", "embed", "source") and re.match(
            r"(https?:)?//", a.get("src", a.get("href", "")), re.IGNORECASE
        ):
            self.flags.add("remote_content")
        hidden = tag in _ALWAYS_HIDDEN
        aria_hidden = a.get("aria-hidden", "").lower() == "true"
        if "hidden" in a or aria_hidden or _HIDING_STYLE.search(style):
            hidden = True
            self.flags.add("hidden_text")
        elif _LOW_CONTRAST.search(style):
            hidden = True
            self.flags.add("low_contrast_text")
        if tag in _VOID:
            if tag == "br" and not self._hidden_now():
                self.parts.append("\n")
            return
        self._stack.append((tag, hidden))
        if tag in _BLOCK and not self._hidden_now():
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        matches = [i for i, (t, _) in enumerate(self._stack) if t == tag]
        if not matches:
            return
        del self._stack[matches[-1] :]
        if tag in _BLOCK and not self._hidden_now():
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_now():
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.flags.add("html_comment")


def _html_to_text(html: str) -> tuple[str, set[str]]:
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts), parser.flags


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _disagree(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    union = wa | wb
    return bool(union) and len(wa & wb) / len(union) < 0.5


# ---------- public API ----------
def normalize_text(
    text: str,
    *,
    source: Source,
    origin: str,
    owner: str | None = None,
    trust: Trust = Trust.UNTRUSTED,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Untrusted:
    cleaned, flags = _clean(text)
    if _instruction_like(cleaned):
        flags.add("instruction_like")
    original = len(cleaned)
    cleaned, truncated = _cap(cleaned, max_chars)
    if truncated:
        flags.add("truncated")
    return Untrusted(cleaned, source, origin, owner, trust, frozenset(flags), original)


def normalize_email(
    *,
    text: str | None,
    html: str | None,
    origin: str,
    owner: str | None = None,
    trust: Trust = Trust.UNTRUSTED,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Untrusted:
    flags: set[str] = set()
    html_text = ""
    if html is not None:
        html_text, html_flags = _html_to_text(html)
        flags |= html_flags
    body = text if text is not None else html_text
    cleaned, clean_flags = _clean(body)
    flags |= clean_flags
    if text is not None and html is not None and _disagree(cleaned, _clean(html_text)[0]):
        flags.add("text_html_mismatch")
    top, quoted, split_flags = _split_quoted(cleaned)
    flags |= split_flags
    if _instruction_like(top) or _instruction_like(quoted):
        flags.add("instruction_like")
    original = len(top)
    top, truncated = _cap(top, max_chars)
    quoted, quoted_truncated = _cap(quoted, max_chars)
    if truncated or quoted_truncated:
        flags.add("truncated")
    return Untrusted(top, Source.EMAIL, origin, owner, trust, frozenset(flags), original, quoted)
