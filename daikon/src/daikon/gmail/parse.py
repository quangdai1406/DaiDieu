"""Gmail ``users.messages`` resource -> InboundEmail.

Attachments are counted and never fetched or decoded (RT-13). Authentication results come
only from the receiving server's header (see daikon.authres). Bodies are size-capped before
decoding and decoding never raises on bad charsets or bytes.
"""

from __future__ import annotations

import base64
import codecs
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses
from typing import Any

from daikon.authres import parse_authentication_results
from daikon.mail import InboundEmail

MAX_B64_CHARS = 2_666_664  # about 2 MB decoded
MAX_HEADERS = 200
MAX_HEADER_VALUE = 2000
_CHARSET = re.compile(r"charset\s*=\s*\"?([A-Za-z0-9_\-:.]+)", re.IGNORECASE)


@dataclass
class _Acc:
    text: str | None = None
    html: str | None = None
    attachments: int = 0
    seen: list[str] = field(default_factory=list)


def _decode_header_text(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - malformed encoded words must not break ingestion
        return value


def _header(headers: list[dict[str, str]], name: str) -> str:
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")


def _decode_body(part: dict[str, Any]) -> str:
    data = str(part.get("body", {}).get("data", ""))[:MAX_B64_CHARS]
    data += "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data)
    match = _CHARSET.search(_header(part.get("headers", []), "Content-Type"))
    charset = match.group(1) if match else "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:
        charset = "utf-8"
    return raw.decode(charset, errors="replace")


def _walk(part: dict[str, Any], acc: _Acc) -> None:
    if part.get("filename") or part.get("body", {}).get("attachmentId"):
        acc.attachments += 1  # counted only; the attachment is never requested
        return
    children = part.get("parts")
    if children:
        for child in children:
            _walk(child, acc)
        return
    mime = part.get("mimeType", "")
    if mime == "text/plain" and acc.text is None:
        acc.text = _decode_body(part)
    elif mime == "text/html" and acc.html is None:
        acc.html = _decode_body(part)


def parse_message(resource: dict[str, Any]) -> InboundEmail:
    payload = resource.get("payload", {})
    headers: list[dict[str, str]] = payload.get("headers", [])
    pairs = tuple(
        (h["name"], h["value"][:MAX_HEADER_VALUE]) for h in headers[:MAX_HEADERS]
    )
    acc = _Acc()
    _walk(payload, acc)
    reply_to = _header(headers, "Reply-To") or None
    to = tuple(
        a.lower() for _, a in getaddresses([_header(headers, "To")]) if a
    )
    received = datetime.fromtimestamp(int(resource.get("internalDate", "0")) / 1000, tz=UTC)
    return InboundEmail(
        id=resource["id"],
        thread_id=resource.get("threadId", resource["id"]),
        from_addr=_decode_header_text(_header(headers, "From")),
        to=to,
        subject=_decode_header_text(_header(headers, "Subject")),
        text=acc.text,
        html=acc.html,
        auth=parse_authentication_results(pairs),
        received=received,
        reply_to=reply_to,
        headers=pairs,
        attachment_count=acc.attachments,
    )
