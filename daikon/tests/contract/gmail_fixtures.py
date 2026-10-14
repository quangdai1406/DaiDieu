"""Builders for Gmail API message resources (same JSON shape the real API returns)."""

import base64
from typing import Any


def b64(text: str, encoding: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(text.encode(encoding)).decode("ascii").rstrip("=")


def header(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value}


GMAIL_AR_PASS = (
    "mx.google.com; dkim=pass header.i=@example.org; spf=pass (google.com: ok) "
    "smtp.mailfrom=bob@example.org; dmarc=pass (p=NONE) header.from=example.org"
)


def multipart_message(
    id_: str = "18f0a1b2c3d4e5f6",
    *,
    frm: str = "Bob Smith <bob@example.org>",
    subject: str = "Lunch?",
    text: str | None = "Can we move lunch to 12:30?",
    html: str | None = "<p>Can we move lunch to 12:30?</p>",
    extra_headers: list[dict[str, str]] | None = None,
    attachments: int = 0,
    internal_date_ms: int = 1760432400000,
    label_ids: list[str] | None = None,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if text is not None:
        parts.append({"mimeType": "text/plain", "filename": "",
                      "headers": [header("Content-Type", 'text/plain; charset="UTF-8"')],
                      "body": {"size": len(text), "data": b64(text)}})
    if html is not None:
        parts.append({"mimeType": "text/html", "filename": "",
                      "headers": [header("Content-Type", "text/html; charset=UTF-8")],
                      "body": {"size": len(html), "data": b64(html)}})
    for i in range(attachments):
        parts.append({"mimeType": "application/pdf", "filename": f"invoice{i}.pdf",
                      "body": {"attachmentId": f"ATT{i}", "size": 12345}})
    headers = [
        header("Authentication-Results", GMAIL_AR_PASS),
        header("From", frm), header("To", "Daikon <daikon@example.com>"),
        header("Subject", subject), header("Message-ID", f"<{id_}@mail.example.org>"),
        *(extra_headers or []),
    ]
    return {
        "id": id_, "threadId": id_, "labelIds": label_ids or ["INBOX", "UNREAD"],
        "internalDate": str(internal_date_ms),
        "payload": {"mimeType": "multipart/alternative", "headers": headers, "parts": parts},
    }


def simple_message(id_: str = "18f0a1b2c3d4e5f7", text: str = "Plain body", **kw: Any) -> dict[str, Any]:
    msg = multipart_message(id_, text=None, html=None, **kw)
    msg["payload"] = {"mimeType": "text/plain",
                      "headers": msg["payload"]["headers"]
                      + [header("Content-Type", "text/plain; charset=UTF-8")],
                      "body": {"size": len(text), "data": b64(text)}}
    return msg
