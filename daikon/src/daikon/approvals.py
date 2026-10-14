"""Approval core: the only way anything outward-facing gets Dai's yes.

Guarantees (each covered by tests in tests/security/test_approvals.py):
  * single-use random codes, stored only as salted hashes, compared in constant time;
  * approvals bind to one request version and one subject hash, so an edited body needs
    a new request and a new code;
  * three wrong attempts lock all approvals for an hour (persisted across restarts);
  * requests expire; a hold-and-undo window separates "approved" from "sending";
  * ``begin_send`` succeeds exactly once per request;
  * every transition is written to the audit log, never with codes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.graph.node import Node
from daikon.graph.store import GraphStore

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/1/I/L/O
CODE_LENGTH = 4
_CODE_RE = re.compile(rf"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$")
_OPEN_STATES = ("pending", "held")
_SALT_FOR = {"code_hash": "salt", "undo_hash": "undo_salt", "confirm_hash": "confirm_salt"}
CONFIRM_TTL = timedelta(minutes=30)


class Kind(StrEnum):
    SEND = "send"
    SKILL_ACTIVATION = "skill_activation"
    JOB_RUN = "job_run"
    CALL_BRIEF = "call_brief"


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str = "ok"
    request_id: str | None = None
    undo_code: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    kind: Kind
    subject_id: str
    subject_hash: str
    version: int
    state: str
    expires_at: datetime
    hold_until: datetime | None
    sending_since: datetime | None = None


def _hash(salt: str, code: str) -> str:
    return hashlib.sha256((salt + code).encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ApprovalManager:
    def __init__(
        self,
        store: GraphStore,
        audit: AuditLog,
        clock: Clock,
        *,
        ttl: timedelta = timedelta(hours=72),
        hold: timedelta = timedelta(seconds=60),
        max_failures: int = 3,
        lockout: timedelta = timedelta(hours=1),
        held_grace: timedelta = timedelta(hours=24),
    ) -> None:
        self._store, self._audit, self._clock = store, audit, clock
        self._ttl, self._hold = ttl, hold
        self._max_failures, self._lockout = max_failures, lockout
        self._held_grace = held_grace

    @property
    def hold(self) -> timedelta:
        return self._hold

    # ---------- reads ----------
    def get(self, request_id: str) -> ApprovalRequest:
        return self._view(self._store.read("approval", request_id))

    def held_requests(self) -> list[ApprovalRequest]:
        return [self._view(n) for n in self._store.find(type="approval", status={"held"})]

    def sending_requests(self) -> list[ApprovalRequest]:
        return [self._view(n) for n in self._store.find(type="approval", status={"sending"})]

    @staticmethod
    def _view(n: Node) -> ApprovalRequest:
        x = n.extra
        return ApprovalRequest(
            n.id, Kind(x["kind"]), x["subject_id"], x["subject_hash"], int(x["version"]),
            n.status, datetime.fromisoformat(x["expires_at"]), _dt(x.get("hold_until")),
            _dt(x.get("sending_since")),
        )

    # ---------- creation ----------
    def create(
        self, kind: Kind, subject_id: str, subject_hash: str, version: int = 1
    ) -> tuple[ApprovalRequest, str]:
        now = self._clock.now()
        code = self._unused_code()
        salt = secrets.token_hex(8)
        node = Node(
            id=f"approval-{subject_id}-v{version}", type="approval", status="pending",
            created=now, links={"approves": [subject_id]},
            extra={
                "kind": kind.value, "subject_id": subject_id, "subject_hash": subject_hash,
                "version": version, "salt": salt, "code_hash": _hash(salt, code),
                "expires_at": (now + self._ttl).isoformat(),
            },
        )
        self._store.write(node)
        self._audit.append("approvals", "approval.create", request_id=node.id, kind=kind.value,
                           version=version)
        return self._view(node), code

    def _unused_code(self) -> str:
        while True:
            code = _new_code()
            if (self._match(code, "code_hash", ("pending",)) is None
                    and self._match(code, "undo_hash", ("held",)) is None):
                return code

    # ---------- matching and lockout ----------
    def _match(self, code: str, field: str, states: tuple[str, ...]) -> Node | None:
        if not _CODE_RE.match(code):
            return None
        found: Node | None = None
        for node in self._store.find(type="approval", status=set(states)):
            salt = node.extra.get(_SALT_FOR[field])
            stored = node.extra.get(field)
            if salt and stored and hmac.compare_digest(_hash(salt, code), stored):
                found = node  # keep scanning: no early exit
        return found

    def _lock_node(self) -> Node:
        if self._store.exists("lockout", "approvals"):
            return self._store.read("lockout", "approvals")
        return Node(id="approvals", type="lockout", status="ok", created=self._clock.now(),
                    extra={"failures": 0, "locked_until": None})

    def _is_locked(self) -> bool:
        until = _dt(self._lock_node().extra.get("locked_until"))
        return until is not None and self._clock.now() < until

    def _record_failure(self, actor: str) -> None:
        node = self._lock_node()
        until = _dt(node.extra.get("locked_until"))
        failures = int(node.extra.get("failures", 0))
        if until is not None and self._clock.now() >= until:
            failures, node.extra["locked_until"] = 0, None
        failures += 1
        if failures >= self._max_failures:
            node.extra["locked_until"] = (self._clock.now() + self._lockout).isoformat()
            node.status, failures = "locked", 0
            self._audit.append("approvals", "approval.locked", by=actor)
        node.extra["failures"] = failures
        self._store.write(node)

    def _record_success(self) -> None:
        node = self._lock_node()
        node.extra.update(failures=0, locked_until=None)
        node.status = "ok"
        self._store.write(node)

    def _deny(self, reason: str, actor: str, request_id: str | None = None) -> Decision:
        self._audit.append("approvals", "approval.denied", reason=reason, by=actor,
                           request_id=request_id)
        return Decision(False, reason, request_id)

    def _set(self, node: Node, state: str, action: str, **extra: Any) -> None:
        node.status = state
        node.extra.update(extra)
        self._store.write(node)
        self._audit.append("approvals", action, request_id=node.id)

    # ---------- decisions by Dai ----------
    def _pending_for(self, code: str, actor: str) -> tuple[Node | None, Decision | None]:
        if self._is_locked():
            return None, self._deny("locked", actor)
        node = self._match(code, "code_hash", ("pending",))
        if node is None:
            self._record_failure(actor)
            return None, self._deny("wrong_code", actor)
        if self._clock.now() >= datetime.fromisoformat(node.extra["expires_at"]):
            self._set(node, "expired", "approval.expired")
            return None, Decision(False, "expired", node.id)
        return node, None

    def approve(
        self, code: str, current_subject_hash: str | Callable[[str], str], actor: str
    ) -> Decision:
        """Approve by code. The current subject hash may be a callable taking the subject id,
        evaluated only after the code matched (so wrong codes never trigger lookups)."""
        node, denied = self._pending_for(code, actor)
        if node is None:
            return denied or Decision(False, "wrong_code")
        current = (
            current_subject_hash(node.extra["subject_id"])
            if callable(current_subject_hash) else current_subject_hash
        )
        if not hmac.compare_digest(current, node.extra["subject_hash"]):
            return self._deny("subject_changed", actor, node.id)
        undo_code, salt = self._unused_code(), secrets.token_hex(8)
        self._record_success()
        self._set(
            node, "held", "approval.approve",
            hold_until=(self._clock.now() + self._hold).isoformat(),
            undo_salt=salt, undo_hash=_hash(salt, undo_code),
        )
        return Decision(True, "ok", node.id, undo_code)

    def reject(self, code: str, actor: str) -> Decision:
        node, denied = self._pending_for(code, actor)
        if node is None:
            return denied or Decision(False, "wrong_code")
        self._record_success()
        self._set(node, "rejected", "approval.reject")
        return Decision(True, "ok", node.id)

    def request_edit(self, code: str, actor: str) -> Decision:
        node, denied = self._pending_for(code, actor)
        if node is None:
            return denied or Decision(False, "wrong_code")
        self._record_success()
        self._set(node, "edit_requested", "approval.edit_requested")
        return Decision(True, "ok", node.id)

    def undo(self, undo_code: str, actor: str) -> Decision:
        if self._is_locked():
            return self._deny("locked", actor)
        node = self._match(undo_code, "undo_hash", ("held",))
        if node is None:
            self._record_failure(actor)
            return self._deny("wrong_code", actor)
        self._record_success()
        self._set(node, "undone", "approval.undo")
        return Decision(True, "ok", node.id)

    # ---------- sending lifecycle (called by the sender only) ----------
    def begin_send(self, request_id: str) -> Decision:
        node = self._store.read("approval", request_id)
        if node.status != "held":
            return self._deny("not_held", "sender", request_id)
        hold_until = _dt(node.extra.get("hold_until"))
        if hold_until is None or self._clock.now() < hold_until:
            return self._deny("hold_not_elapsed", "sender", request_id)
        self._set(node, "sending", "approval.begin_send",
                  sending_since=self._clock.now().isoformat())
        return Decision(True, "ok", request_id)

    # ---------- second-channel confirmation (first-time or high-risk recipients) ----------
    def require_confirmation(self, request_id: str) -> str | None:
        """sending -> needs_confirmation. Returns a one-time code to deliver to Dai by SMS."""
        node = self._store.read("approval", request_id)
        if node.status != "sending":
            return None
        while True:
            code = _new_code()
            if self._match(code, "confirm_hash", ("needs_confirmation",)) is None:
                break
        salt = secrets.token_hex(8)
        self._set(node, "needs_confirmation", "approval.needs_confirmation",
                  confirm_salt=salt, confirm_hash=_hash(salt, code),
                  confirm_expires=(self._clock.now() + CONFIRM_TTL).isoformat())
        return code

    def fail_confirmation(self, request_id: str, reason: str) -> Decision:
        node = self._store.read("approval", request_id)
        if node.status != "needs_confirmation":
            return self._deny("not_waiting", "sender", request_id)
        self._set(node, "failed", "approval.failed", failure=reason)
        return Decision(True, "ok", request_id)

    def confirm(self, code: str, actor: str) -> Decision:
        """Dai's one-time confirmation (SMS only). needs_confirmation -> sending."""
        if self._is_locked():
            return self._deny("locked", actor)
        node = self._match(code, "confirm_hash", ("needs_confirmation",))
        if node is None:
            self._record_failure(actor)
            return self._deny("wrong_code", actor)
        expires = _dt(node.extra.get("confirm_expires"))
        if expires is None or self._clock.now() >= expires:
            self._set(node, "expired", "approval.expired")
            return Decision(False, "expired", node.id)
        self._record_success()
        self._set(node, "sending", "approval.confirmed",
                  sending_since=self._clock.now().isoformat(), confirmed=True)
        return Decision(True, "ok", node.id)

    def is_confirmed(self, request_id: str) -> bool:
        return bool(self._store.read("approval", request_id).extra.get("confirmed"))

    def _finish(self, request_id: str, state: str, action: str, **extra: Any) -> Decision:
        node = self._store.read("approval", request_id)
        if node.status != "sending":
            return self._deny("not_sending", "sender", request_id)
        self._set(node, state, action, **extra)
        return Decision(True, "ok", request_id)

    def mark_sent(self, request_id: str) -> Decision:
        return self._finish(request_id, "sent", "approval.sent")

    def mark_failed(self, request_id: str, reason: str) -> Decision:
        return self._finish(request_id, "failed", "approval.failed", failure=reason)

    def due_for_reminder(self, after: timedelta) -> list[ApprovalRequest]:
        now = self._clock.now()
        return [self._view(n) for n in self._store.find(type="approval", status={"pending"})
                if not n.extra.get("reminded") and n.created + after <= now
                < datetime.fromisoformat(n.extra["expires_at"])]

    def mark_reminded(self, request_id: str) -> None:
        node = self._store.read("approval", request_id)
        node.extra["reminded"] = True
        self._store.write(node)
        self._audit.append("approvals", "approval.reminded", request_id=request_id)

    def expire_due(self) -> list[str]:
        now, expired = self._clock.now(), []
        for node in self._store.find(type="approval", status={"pending"}):
            if now >= datetime.fromisoformat(node.extra["expires_at"]):
                self._set(node, "expired", "approval.expired")
                expired.append(node.id)
        for node in self._store.find(type="approval", status={"needs_confirmation"}):
            expires = _dt(node.extra.get("confirm_expires"))
            if expires is not None and now >= expires:
                self._set(node, "expired", "approval.expired")
                expired.append(node.id)
        for node in self._store.find(type="approval", status={"held"}):
            hold_until = _dt(node.extra.get("hold_until"))
            if hold_until is not None and now > hold_until + self._held_grace:
                self._set(node, "expired", "approval.expired")  # approved long ago, never sent
                expired.append(node.id)
        return sorted(expired)
