"""Worker: turns one untrusted email into a draft node. The model never picks recipients."""

from __future__ import annotations

import re

from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.drafts import content_hash, reply_subject, validate_draft
from daikon.gateway.base import Gateway
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.mail import InboundEmail
from daikon.prompt import DRAFT_SYSTEM, wrap_untrusted
from daikon.untrusted import Untrusted

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class Worker:
    def __init__(self, gateway: Gateway, store: GraphStore, clock: Clock, audit: AuditLog) -> None:
        self._gateway, self._store, self._clock, self._audit = gateway, store, clock, audit

    def draft_reply(self, msg: InboundEmail, u: Untrusted) -> Node:
        raw = self._gateway.complete_json("draft", DRAFT_SYSTEM, wrap_untrusted(u))
        data = validate_draft(raw)
        body = _CONTROL.sub("", data["draft_body"]).strip()
        recipients = [msg.from_addr.strip().lower()]  # decided by code, never by the model
        subject = reply_subject(msg.subject)
        node = Node(
            id=f"draft-{msg.id}", type="draft", status="pending_approval",
            created=self._clock.now(), links={"replies_to": [f"message-{msg.id}"]}, body=body,
            extra={
                "recipients": recipients, "subject": subject, "version": 1,
                "content_hash": content_hash(recipients, subject, body),
                "in_reply_to": msg.id, "category": data["category"], "urgency": data["urgency"],
                "confidence": data["confidence"], "needs_dai": data["needs_dai"],
                "summary": data["summary"], "citations": data["citations"],
                "sensitivity_flags": data["sensitivity_flags"],
            },
        )
        self._store.write(node)
        self._audit.append("worker", "worker.draft", draft_id=node.id, message_id=msg.id,
                           category=data["category"], confidence=data["confidence"])
        return node
