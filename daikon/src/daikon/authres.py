"""Parse the receiving server's ``Authentication-Results`` (RT-04, RT-19).

Only a header whose authserv-id is a trusted receiver (Gmail's ``mx.google.com``) counts, and
the topmost such header wins: Gmail adds its own above anything the sender supplied.
Parenthesized comments are removed first so text inside them cannot fake a result.
A message passes only when SPF, DKIM and DMARC all pass (DMARC proves alignment with From).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from daikon.mail import AuthResults

TRUSTED_AUTHSERV_IDS = frozenset({"mx.google.com"})
_COMMENT = re.compile(r"\([^()]*\)")
_METHOD = re.compile(r"^(dkim|spf|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)


def _strip_comments(value: str) -> str:
    previous = None
    while previous != value:
        previous, value = value, _COMMENT.sub("", value)
    return value


def _pick(values: list[str] | None) -> str:
    if not values:
        return "none"
    return "pass" if "pass" in values else values[0]


def parse_authentication_results(headers: Sequence[tuple[str, str]]) -> AuthResults:
    for name, value in headers:
        if name.lower() != "authentication-results":
            continue
        flat = value.replace("\r", " ").replace("\n", " ")
        parts = [p.strip() for p in _strip_comments(flat).split(";")]
        authserv = parts[0].split()[0].lower() if parts and parts[0] else ""
        if authserv not in TRUSTED_AUTHSERV_IDS:
            continue
        results: dict[str, list[str]] = {}
        for segment in parts[1:]:
            m = _METHOD.match(segment)
            if m:
                results.setdefault(m.group(1).lower(), []).append(m.group(2).lower())
        return AuthResults(
            spf=_pick(results.get("spf")),
            dkim=_pick(results.get("dkim")),
            dmarc=_pick(results.get("dmarc")),
        )
    return AuthResults()
