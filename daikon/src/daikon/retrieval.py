"""Second Brain retrieval: safe excerpts for the drafting prompt (RT-09, M4.2/M4.4).

For each relevant note Daikon builds a short excerpt around the match, tags who wrote it
(``owner`` only when Dai both owns and last edited it), strips invisible text and flags
instruction-like wording. Sensitivity is decided by code, not by a model: notes in the
configured top-level folders, or containing credentials, SSNs, valid card numbers, health or
finance terms, are *withheld*: Dai is told they exist, but their text never goes to a model.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from daikon.drive.scoped import DriveAccessError, DriveFile, ScopedDrive
from daikon.guard import contains_secret
from daikon.untrusted import Source, Trust, normalize_text

SENSITIVE_PREFIXES = ("06 ", "07 ")  # 06 Trading and Investments, 07 Personal and Working Style
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_TERM_GROUPS = (
    ("credential_term", r"password|passcode|passphrase|api key|private key|secret key"),
    ("health_term", r"diagnosis|prescription|medical record|patient"),
    ("finance_term", r"bank account|routing number|tax return|net worth|brokerage"),
)
_TERM_RES = [(name, re.compile(rf"\b(?:{words})\b", re.IGNORECASE)) for name, words in _TERM_GROUPS]


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def sensitivity_reasons(
    path: str, text: str, prefixes: tuple[str, ...] = SENSITIVE_PREFIXES
) -> tuple[str, ...]:
    reasons: list[str] = []
    if path.split("/")[0].startswith(prefixes):
        reasons.append("folder")
    for name, pattern in _TERM_RES[:1]:
        if pattern.search(text):
            reasons.append(name)
    if _SSN.search(text):
        reasons.append("ssn")
    runs = (re.sub(r"\D", "", m.group()) for m in _CARD.finditer(text))
    if any(13 <= len(d) <= 19 and _luhn(d) for d in runs):
        reasons.append("card_number")
    for name, pattern in _TERM_RES[1:]:
        if pattern.search(text):
            reasons.append(name)
    if contains_secret(text):
        reasons.append("secret")
    return tuple(reasons)


@dataclass(frozen=True)
class Excerpt:
    file_id: str
    title: str
    path: str
    url: str
    text: str
    trust: Trust
    flags: frozenset[str]


@dataclass(frozen=True)
class Withheld:
    """A relevant but sensitive note. Only metadata, never text."""

    file_id: str
    title: str
    path: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    excerpts: list[Excerpt]
    withheld: list[Withheld]


def _window(text: str, terms: Iterable[str], size: int) -> str:
    lowered = text.lower()
    hits = [i for t in terms if t.strip() and (i := lowered.find(t.strip().lower())) >= 0]
    start = max(0, (min(hits) if hits else 0) - size // 4)
    return text[start : start + size]


class Retriever:
    def __init__(
        self,
        drive: ScopedDrive,
        dai_emails: Collection[str],
        *,
        excerpt_chars: int = 1200,
        max_excerpts: int = 5,
        max_withheld: int = 10,
        sensitive_prefixes: tuple[str, ...] = SENSITIVE_PREFIXES,
    ) -> None:
        self._drive, self._dai = drive, {e.lower() for e in dai_emails}
        self._chars, self._max, self._max_withheld = excerpt_chars, max_excerpts, max_withheld
        self._prefixes = sensitive_prefixes

    def search(self, terms: Iterable[str]) -> RetrievalResult:
        terms = [t for t in terms if t.strip()]
        if not terms:
            return RetrievalResult([], [])
        excerpts: list[Excerpt] = []
        withheld: list[Withheld] = []
        for found in self._drive.search(terms, limit=self._max * 3):
            try:
                doc = self._drive.read(found.id)
            except DriveAccessError:
                continue
            reasons = sensitivity_reasons(doc.file.path, doc.text, self._prefixes)
            if reasons:
                if len(withheld) < self._max_withheld:
                    withheld.append(Withheld(found.id, found.name, doc.file.path, reasons))
            elif len(excerpts) < self._max:
                excerpts.append(self._excerpt(doc.file, doc.text, terms))
        return RetrievalResult(excerpts, withheld)

    def _excerpt(self, file: DriveFile, text: str, terms: list[str]) -> Excerpt:
        owner, editor = (file.owner or "").lower(), (file.last_modifier or "").lower()
        by_dai = owner in self._dai and editor in self._dai
        u = normalize_text(
            _window(text, terms, self._chars), source=Source.DRIVE, origin=file.id,
            owner=file.owner, trust=Trust.OWNER if by_dai else Trust.UNTRUSTED,
            max_chars=self._chars,
        )
        flags = u.flags if by_dai else u.flags | {"not_authored_by_dai"}
        return Excerpt(file.id, file.name, file.path,
                       f"https://drive.google.com/file/d/{file.id}/view", u.text, u.trust, flags)
