"""OutboundPolicy: the single decision point for anything that leaves Daikon.

Every email, SMS or call goes through ``evaluate``. It returns allow, hold (needs a second
channel confirmation) or deny, and writes an audit entry for every decision. Rules, in order:

  1. recipients must be well formed (no header injection, no lists);
  2. calls are not enabled in v1;
  3. only Dai's own identities may receive SMS;
  4. anything addressed to someone other than Dai requires: live mode (not ``dai_only``),
     no PAUSE file, a bounded recipient list, an approval in the ``sending`` state of kind
     ``send`` whose subject hash (body + recipients) matches, then risk tiering
     (first-time recipient, attachment, sensitive content -> second channel), then caps;
  5. messages to Dai are allowed, with the SMS cap applied.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parseaddr
from enum import StrEnum
from pathlib import Path
from typing import Literal

from daikon.approvals import ApprovalManager, Kind
from daikon.audit import AuditLog
from daikon.graph.node import InvalidNameError
from daikon.identity import DaiIdentity
from daikon.limiter import Limiter

MODES = ("dai_only", "live")
_EMAIL_RE = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
_PHONE_RE = re.compile(r"^\+\d{8,15}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    CALL = "call"


@dataclass(frozen=True)
class OutboundAction:
    channel: Channel
    recipients: tuple[str, ...]
    kind: str
    approval_request_id: str | None = None
    subject_hash: str | None = None
    has_attachment: bool = False
    sensitive: bool = False
    second_channel_confirmed: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Literal["allow", "hold", "deny"]
    reason: str = "ok"
    tier: str | None = None
    needs_second_channel: bool = False


def _normalize(channel: Channel, raw: str) -> str | None:
    if _CONTROL.search(raw):
        return None
    if channel is Channel.EMAIL:
        addr = parseaddr(raw)[1].strip().lower()
        return addr if _EMAIL_RE.match(addr) else None
    cleaned = re.sub(r"[\s\-().]", "", raw)
    return cleaned if _PHONE_RE.match(cleaned) else None


class OutboundPolicy:
    def __init__(
        self,
        *,
        data_dir: Path,
        identity: DaiIdentity,
        mode: str,
        limiter: Limiter,
        approvals: ApprovalManager,
        audit: AuditLog,
        known_recipient: Callable[[str], bool],
        max_recipients: int = 3,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self._data_dir, self._identity, self._mode = data_dir, identity, mode
        self._limiter, self._approvals, self._audit = limiter, approvals, audit
        self._known, self._max = known_recipient, max_recipients

    def evaluate(self, action: OutboundAction) -> PolicyDecision:
        decision, recipients = self._decide(action)
        self._audit.append(
            "policy", "policy.decision", channel=action.channel.value, kind=action.kind,
            recipients=recipients, verdict=decision.verdict, reason=decision.reason,
            tier=decision.tier,
        )
        return decision

    # ---------- rules ----------
    def _decide(self, a: OutboundAction) -> tuple[PolicyDecision, list[str]]:
        if a.channel is Channel.CALL:
            return PolicyDecision("deny", "call_not_enabled"), list(a.recipients)
        normalized = [_normalize(a.channel, r) for r in a.recipients]
        if not normalized or any(n is None for n in normalized):
            return PolicyDecision("deny", "bad_recipient"), []
        recipients = [n for n in normalized if n is not None]
        dai = self._identity.emails if a.channel is Channel.EMAIL else self._identity.phones
        others = [r for r in recipients if r not in dai]
        if not others:
            return self._to_dai(a), recipients
        if a.channel is Channel.SMS:
            return PolicyDecision("deny", "sms_to_others_unsupported"), recipients
        return self._to_others(a, recipients), recipients

    def _to_dai(self, a: OutboundAction) -> PolicyDecision:
        if a.channel is Channel.SMS and not self._limiter.check_and_consume("sms").allowed:
            return PolicyDecision("deny", "cap_exceeded")
        return PolicyDecision("allow")

    def _to_others(self, a: OutboundAction, recipients: list[str]) -> PolicyDecision:
        if self._mode == "dai_only":
            return PolicyDecision("deny", "dai_only_mode")
        if (self._data_dir / "PAUSE").exists():
            return PolicyDecision("deny", "paused")
        if len(recipients) > self._max:
            return PolicyDecision("deny", "too_many_recipients")
        approval_problem = self._check_approval(a)
        if approval_problem:
            return PolicyDecision("deny", approval_problem)
        high_risk = (
            a.has_attachment or a.sensitive or any(not self._known(r) for r in recipients)
        )
        if high_risk and not a.second_channel_confirmed:
            return PolicyDecision("hold", "second_channel_required", "high", True)
        return self._consume_caps(recipients)

    def _check_approval(self, a: OutboundAction) -> str | None:
        if not a.approval_request_id:
            return "no_approval"
        try:
            req = self._approvals.get(a.approval_request_id)
        except (FileNotFoundError, InvalidNameError):
            return "no_approval"
        if req.state != "sending" or req.kind is not Kind.SEND:
            return "no_approval"
        if not a.subject_hash or not hmac.compare_digest(a.subject_hash, req.subject_hash):
            return "subject_changed"
        return None

    def _consume_caps(self, recipients: list[str]) -> PolicyDecision:
        checks = [("sends", "*")] + [("sender_hourly", r) for r in recipients]
        if not all(self._limiter.peek(scope, key).allowed for scope, key in checks):
            return PolicyDecision("deny", "cap_exceeded")
        for scope, key in checks:
            self._limiter.check_and_consume(scope, key)
        return PolicyDecision("allow")
