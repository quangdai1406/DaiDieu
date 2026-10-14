"""Sender analysis: warning flags about who an email claims to be from (RT-19).

Flags are shown to Dai in the digest. They never raise trust, and none of them is needed for
the approval gate, which depends on authenticated identity and codes instead.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from email.utils import getaddresses, parseaddr

_ADDRESS = re.compile(r"[^@\s<>\",;]+@[^@\s<>\",;]+")
_CONFUSABLE = (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("|", "l"))


@dataclass(frozen=True)
class SenderInfo:
    address: str
    display_name: str
    flags: frozenset[str]


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def _skeleton(domain: str) -> str:
    text = unicodedata.normalize("NFKD", domain.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    for src, dst in _CONFUSABLE:
        text = text.replace(src, dst)
    return text


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _is_lookalike(domain: str, known_domains: Collection[str]) -> bool:
    if domain in known_domains:
        return False
    tld = domain.split(".")[-1]
    for known in known_domains:
        if _skeleton(domain) == _skeleton(known):
            return True
        close = len(known) >= 5 and _edit_distance(domain, known) <= 2
        if close and tld == known.split(".")[-1]:
            return True
    return False


def analyze_sender(
    from_header: str, reply_to_header: str | None, known_addresses: Collection[str]
) -> SenderInfo:
    name, raw = parseaddr(from_header)
    address = raw.strip().lower() if _ADDRESS.fullmatch(raw.strip()) else ""
    if not address:
        return SenderInfo("", name, frozenset({"bad_from"}))
    flags: set[str] = set()
    known = {a.lower() for a in known_addresses}
    if address not in known:
        flags.add("new_sender")
    for embedded in _ADDRESS.findall(name):
        if embedded.lower() != address:
            flags.add("display_name_mismatch")
    domain = _domain(address)
    if reply_to_header:
        for _, rt in getaddresses([reply_to_header]):
            if rt and _domain(rt) != domain:
                flags.add("reply_to_mismatch")
    if not domain.isascii() or any(label.startswith("xn--") for label in domain.split(".")):
        flags.add("idn_domain")
    if _is_lookalike(domain, {_domain(a) for a in known}):
        flags.add("lookalike_domain")
    return SenderInfo(address, name, frozenset(flags))
