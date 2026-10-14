"""Fakes shared by tests and the walking skeleton (no network, fully deterministic)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from daikon.mail import InboundEmail


@dataclass
class SentMail:
    to: list[str]
    subject: str
    body: str
    in_reply_to: str | None


@dataclass
class FakeMailbox:
    inbox: list[InboundEmail] = field(default_factory=list)
    sent: list[SentMail] = field(default_factory=list)

    def fetch_new(self) -> list[InboundEmail]:
        out, self.inbox = list(self.inbox), []
        return out

    def send(
        self, to: list[str], subject: str, body: str, in_reply_to: str | None = None
    ) -> str:
        self.sent.append(SentMail(list(to), subject, body, in_reply_to))
        return f"sent-{len(self.sent)}"


class FakeGateway:
    DEFAULT: ClassVar[dict[str, Any]] = {
        "category": "scheduling",
        "urgency": "normal",
        "confidence": 0.9,
        "needs_dai": True,
        "summary": "Sender asks a scheduling question.",
        "draft_body": "Hi, 12:30 works for me. Best, Dai",
        "citations": [],
        "sensitivity_flags": [],
    }

    def __init__(
        self, reply: dict[str, Any] | None = None, script: list[Any] | None = None
    ) -> None:
        """``script`` items are consumed one per call: an Exception is raised, a dict is
        returned, ``None`` returns the default reply. When it runs out, the default is used."""
        self.reply = dict(reply if reply is not None else self.DEFAULT)
        self.script = list(script or [])
        self.calls: list[tuple[str, str]] = []
        self.schemas: list[Mapping[str, Any] | None] = []

    def complete_json(
        self,
        role: str,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
        data_label: str = "normal",
    ) -> dict[str, Any]:
        self.calls.append((system, user))
        self.schemas.append(schema)
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        return dict(step) if isinstance(step, dict) else dict(self.reply)


@dataclass
class FakeMessenger:
    """Alerter messenger that records what it was asked to send."""

    sms_ok: bool = True
    email_ok: bool = True
    sent: list[tuple[str, str, str]] = field(default_factory=list)  # (channel, subject, body)

    def send_sms(self, body: str) -> bool:
        self.sent.append(("sms", "", body))
        return self.sms_ok

    def send_email(self, subject: str, body: str) -> bool:
        self.sent.append(("email", subject, body))
        return self.email_ok
