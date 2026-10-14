"""Digest text for Dai. Header fields are written by code; model text sits below a divider.

Plain text only, every URL defanged (RT-02, RT-03).
"""

from __future__ import annotations

from daikon.defang import defang
from daikon.graph.node import Node
from daikon.mail import InboundEmail
from daikon.untrusted import Untrusted


def build_digest(msg: InboundEmail, u: Untrusted, draft: Node, code: str) -> tuple[str, str]:
    x = draft.extra
    flags = ", ".join(sorted(u.flags)) or "none"
    excerpt = "\n".join(f"| {line}" for line in defang(u.text[:400]).splitlines())
    lines = [
        "New email needs your decision",
        f"From: {msg.from_addr} (SPF {msg.auth.spf} / DKIM {msg.auth.dkim})",
        f"Subject: {defang(msg.subject)[:120]}",
        f"Flags: {flags}",
        f"Reply goes to: {', '.join(x['recipients'])}",
        "---- model summary (unverified, may be wrong) ----",
        f"Category: {defang(x['category'])}  Urgency: {x['urgency']}"
        f"  Confidence: {x['confidence']}",
        f"Summary: {defang(x['summary'])}",
        "Draft reply:",
        *[f"| {line}" for line in defang(draft.body).splitlines()],
        "---- original email excerpt (untrusted) ----",
        excerpt,
        "----",
        f"OK {code}   -> send this reply",
        f"NO {code}   -> discard",
        f"EDIT {code} <what to change>",
    ]
    return f"Daikon: reply needed for {defang(msg.subject)[:60]}", "\n".join(lines)
