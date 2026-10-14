"""Digest text for Dai. Header fields are written by code; model text sits below a divider.

Plain text only, every URL defanged (RT-02, RT-03).
"""

from __future__ import annotations

from daikon.defang import defang
from daikon.graph.node import Node
from daikon.mail import InboundEmail
from daikon.untrusted import Untrusted


def build_digest(
    msg: InboundEmail, u: Untrusted, draft: Node, code: str, flags: frozenset[str]
) -> tuple[str, str]:
    x = draft.extra
    flag_text = ", ".join(sorted(flags)) or "none"
    excerpt = "\n".join(f"| {line}" for line in defang(u.text[:400]).splitlines())
    lines = [
        "New email needs your decision",
        f"From: {msg.from_addr} (SPF {msg.auth.spf} / DKIM {msg.auth.dkim}"
        f" / DMARC {msg.auth.dmarc})",
        f"Subject: {defang(msg.subject)[:120]}",
        f"Flags: {flag_text}",
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


_REASONS = {
    "refusal": "The model declined to draft a reply for this email.",
    "bad_output": "The model's answer could not be used after two tries.",
}


def build_attention(msg: InboundEmail, flags: frozenset[str], reason: str) -> tuple[str, str]:
    """Note for an email Daikon could not draft. No codes: there is nothing to approve."""
    lines = [
        "Daikon could not draft a reply. Please read this email yourself.",
        f"From: {msg.from_addr} (SPF {msg.auth.spf} / DKIM {msg.auth.dkim}"
        f" / DMARC {msg.auth.dmarc})",
        f"Subject: {defang(msg.subject)[:120]}",
        f"Flags: {', '.join(sorted(flags)) or 'none'}",
        f"Why: {_REASONS.get(reason, reason)}",
    ]
    return f"Daikon: couldn't draft a reply for {defang(msg.subject)[:60]}", "\n".join(lines)
