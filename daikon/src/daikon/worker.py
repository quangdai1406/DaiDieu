"""Worker: turns one untrusted email into a draft node. The model never picks recipients.

Flow with a Second Brain: (1) a cheap call proposes search terms; (2) the retriever returns
safe excerpts (sensitive notes are withheld, never shown to a model); (3) the drafting call
sees the email plus numbered notes; (4) if the draft asks for more context with *new* terms,
exactly one more search and one more draft happen. Citations the model returns must be ids
of notes it was actually given; anything else is dropped.

Malformed or truncated output is retried once; a refusal is not retried. Both end as
``DraftFailed`` so the pipeline can ask Dai to handle the email manually. Temporary API
failures and spend caps are raised unchanged for the pipeline to handle.
"""

from __future__ import annotations

import re
from typing import Any

import jsonschema

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
from daikon.prompt import DRAFT_SYSTEM, TERMS_SCHEMA, TERMS_SYSTEM, notes_block, wrap_untrusted
from daikon.retrieval import Excerpt, RetrievalResult, Retriever, Withheld
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
                 style: str = DEFAULT_STYLE, retriever: Retriever | None = None) -> None:
        self._gateway, self._store, self._clock, self._audit = gateway, store, clock, audit
        self._system = f"{DRAFT_SYSTEM}\n\nVoice and style (from Dai, trusted):\n{style}"
        self._retriever = retriever

    # ---------- model calls ----------
    def _propose_terms(self, u: Untrusted) -> list[str]:
        try:
            raw = self._gateway.complete_json(
                "triage", TERMS_SYSTEM, wrap_untrusted(u), TERMS_SCHEMA
            )
            jsonschema.validate(raw, TERMS_SCHEMA)
        except (BadModelOutputError, TruncatedOutputError, ModelRefusalError,
                jsonschema.ValidationError):
            return []  # no notes is better than no draft
        return [t for t in raw["terms"] if isinstance(t, str) and t.strip()][:5]

    def _ask(self, u: Untrusted, catalog: dict[str, Excerpt]) -> dict[str, Any]:
        user = wrap_untrusted(u)
        if catalog:
            user = f"{user}\n\n{notes_block(catalog)}"
        for _ in range(ATTEMPTS):
            try:
                raw = self._gateway.complete_json("draft", self._system, user, DRAFT_SCHEMA)
                return validate_draft(raw)
            except ModelRefusalError:
                raise DraftFailed("refusal") from None
            except (DraftSchemaError, BadModelOutputError, TruncatedOutputError):
                continue
        raise DraftFailed("bad_output")

    # ---------- retrieval bookkeeping ----------
    @staticmethod
    def _add(catalog: dict[str, Excerpt], withheld: dict[str, Withheld],
             result: RetrievalResult) -> None:
        have = {e.file_id for e in catalog.values()}
        for e in result.excerpts:
            if e.file_id not in have:
                catalog[f"N{len(catalog) + 1}"] = e
        for w in result.withheld:
            withheld.setdefault(w.file_id, w)

    # ---------- the draft ----------
    def draft_reply(self, message_id: str, subject: str, u: Untrusted, recipient: str) -> Node:
        catalog: dict[str, Excerpt] = {}
        withheld: dict[str, Withheld] = {}
        try:
            used: set[str] = set()
            if self._retriever is not None:
                terms = self._propose_terms(u)
                used = {t.lower() for t in terms}
                self._add(catalog, withheld, self._retriever.search(terms))
            data = self._ask(u, catalog)
            more = [t for t in data["more_context_terms"] if t.lower() not in used]
            if self._retriever is not None and more:
                self._add(catalog, withheld, self._retriever.search(more))
                data = self._ask(u, catalog)
        except DraftFailed as exc:
            self._audit.append("worker", "worker.draft_failed", message_id=message_id,
                               reason=exc.reason)
            raise
        body = _CONTROL.sub("", data["draft_body"]).strip()
        recipients = [recipient]  # decided by code (the From address), never by the model
        reply = reply_subject(subject)
        cited = [i for i in dict.fromkeys(data["citations"]) if i in catalog]
        node = Node(
            id=f"draft-{message_id}", type="draft", status="pending_approval",
            created=self._clock.now(), links={"replies_to": [f"message-{message_id}"]}, body=body,
            extra={
                "recipients": recipients, "subject": reply, "version": 1,
                "content_hash": content_hash(recipients, reply, body),
                "in_reply_to": message_id, "category": data["category"], "urgency": data["urgency"],
                "confidence": data["confidence"], "needs_dai": data["needs_dai"],
                "summary": data["summary"],
                "citations": [{"id": i, "title": catalog[i].title, "url": catalog[i].url,
                               "trust": catalog[i].trust.value} for i in cited],
                "notes_used": [{"id": i, "title": e.title, "path": e.path, "url": e.url,
                                "trust": e.trust.value, "flags": sorted(e.flags)}
                               for i, e in catalog.items()],
                "withheld": [{"path": w.path, "reasons": list(w.reasons)}
                             for w in withheld.values()],
                "sensitivity_flags": data["sensitivity_flags"],
            },
        )
        self._store.write(node)
        self._audit.append("worker", "worker.draft", draft_id=node.id, message_id=message_id,
                           category=data["category"], confidence=data["confidence"],
                           notes=len(catalog), withheld=len(withheld))
        return node
