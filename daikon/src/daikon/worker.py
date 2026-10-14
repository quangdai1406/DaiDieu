"""Worker: turns one untrusted email into a draft node. The model never picks recipients.

Malformed or truncated output is retried once; a refusal is not retried. Both end as
``DraftFailed`` so the pipeline can ask Dai to handle the email manually. Temporary API
failures and spend caps are raised unchanged for the pipeline to handle.
"""

from __future__ import annotations

import re
from typing import Any

from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.drafts import (
    DRAFT_SCHEMA,
    DraftSchemaError,
    content_hash,
    reply_subject,
    validate_draft,
)
from daikon.gateway.anthropic_api import (
    BadModelOutputError,
    ModelRefusalError,
    TruncatedOutputError,
)
from daikon.gateway.base import Gateway
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.prompt import DRAFT_SYSTEM, wrap_untrusted
from daikon.style import DEFAULT_STYLE
from daikon.untrusted import Untrusted

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ATTEMPTS = 2


class DraftFailed(Exception):  # noqa: N818 - reads better than DraftFailedError at call sites
    """No usable draft after the allowed attempts. ``reason``: ``refusal`` or ``bad_output``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Worker:
    def __init__(self, gateway: Gateway, store: GraphStore, clock: Clock, audit: AuditLog,
                 style: str = DEFAULT_STYLE) -> None:
        self._gateway, self._store, self._clock, self._audit = gateway, store, clock, audit
        self._system = f"{DRAFT_SYSTEM}\n\nVoice and style (from Dai, trusted):\n{style}"

    def _ask(self, u: Untrusted) -> dict[str, Any]:
        for _ in range(ATTEMPTS):
            try:
                raw = self._gateway.complete_json(
                    "draft", self._system, wrap_untrusted(u), DRAFT_SCHEMA
                )
                return validate_draft(raw)
            except ModelRefusalError:
                raise DraftFailed("refusal") from None
            except (DraftSchemaError, BadModelOutputError, TruncatedOutputError):
                continue
        raise DraftFailed("bad_output")

    def draft_reply(self, message_id: str, subject: str, u: Untrusted, recipient: str) -> Node:
        try:
            data = self._ask(u)
        except DraftFailed as exc:
            self._audit.append("worker", "worker.draft_failed", message_id=message_id,
                               reason=exc.reason)
            raise
        body = _CONTROL.sub("", data["draft_body"]).strip()
        recipients = [recipient]  # decided by code (the From address), never by the model
        reply = reply_subject(subject)
        node = Node(
            id=f"draft-{message_id}", type="draft", status="pending_approval",
            created=self._clock.now(), links={"replies_to": [f"message-{message_id}"]}, body=body,
            extra={
                "recipients": recipients, "subject": reply, "version": 1,
                "content_hash": content_hash(recipients, reply, body),
                "in_reply_to": message_id, "category": data["category"], "urgency": data["urgency"],
                "confidence": data["confidence"], "needs_dai": data["needs_dai"],
                "summary": data["summary"], "citations": data["citations"],
                "sensitivity_flags": data["sensitivity_flags"],
            },
        )
        self._store.write(node)
        self._audit.append("worker", "worker.draft", draft_id=node.id, message_id=message_id,
                           category=data["category"], confidence=data["confidence"])
        return node
