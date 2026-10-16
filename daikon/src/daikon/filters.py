"""Rule filter: plain code decides which mail may cost a model run (and which is dropped).

Order: blocked sender -> automated mail -> daily model-run cap -> per-sender hourly rate.
Automated and blocked mail never consumes the sender's budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from daikon.audit import AuditLog
from daikon.limiter import Limiter
from daikon.mail import InboundEmail
from daikon.people import PersonBook

_AUTOMATED_LOCAL = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|notifications?|bounces?)"
    r"([+._-].*)?$"
)
_BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})


class Action(StrEnum):
    PROCESS = "process"
    SKIP_AUTOMATED = "skip_automated"
    SKIP_BLOCKED = "skip_blocked"
    SKIP_CAP = "skip_cap"


@dataclass(frozen=True)
class FilterDecision:
    action: Action
    reason: str = "ok"


def _is_automated(msg: InboundEmail, address: str) -> str | None:
    if _AUTOMATED_LOCAL.match(address.split("@", 1)[0].lower()):
        return "automated_sender_name"
    for name, value in msg.headers:
        key, val = name.lower(), value.strip().lower()
        if key == "list-unsubscribe":
            return "list_unsubscribe"
        if key == "precedence" and val in _BULK_PRECEDENCE:
            return "bulk_precedence"
        if key == "auto-submitted" and val != "no":
            return "auto_submitted"
        if key == "x-auto-response-suppress":
            return "auto_response_suppress"
    return None


class RuleFilter:
    def __init__(self, limiter: Limiter, people: PersonBook, audit: AuditLog) -> None:
        self._limiter, self._people, self._audit = limiter, people, audit

    def evaluate(self, msg: InboundEmail, address: str) -> FilterDecision:
        decision = self._decide(msg, address)
        self._audit.append("filter", "filter.decision", message_id=msg.id, sender=address,
                           action=decision.action.value, reason=decision.reason)
        return decision

    def _decide(self, msg: InboundEmail, address: str) -> FilterDecision:
        if self._people.is_blocked(address):
            return FilterDecision(Action.SKIP_BLOCKED, "blocked_sender")
        automated = _is_automated(msg, address)
        if automated:
            return FilterDecision(Action.SKIP_AUTOMATED, automated)
        if not self._limiter.peek("model_runs").allowed:
            return FilterDecision(Action.SKIP_CAP, "daily_model_cap")
        if not self._limiter.check_and_consume("inbound_hourly", address).allowed:
            return FilterDecision(Action.SKIP_CAP, "sender_rate")
        return FilterDecision(Action.PROCESS)
