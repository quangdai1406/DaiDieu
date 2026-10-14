"""M1.6: approval core. Single-use codes, lockout, expiry, hash binding, hold/undo, exactly-once."""

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.approvals import CODE_ALPHABET, ApprovalManager, Kind
from daikon.audit import AuditLog, verify
from daikon.clock import FakeClock
from daikon.graph.store import GraphStore

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
H1, H2 = "a" * 64, "b" * 64


@dataclass
class Env:
    mgr: ApprovalManager
    store: GraphStore
    clock: FakeClock
    audit: AuditLog
    root: Path

    def reopen(self) -> ApprovalManager:
        return ApprovalManager(self.store, self.audit, self.clock)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    clock = FakeClock(T0)
    store = GraphStore(tmp_path / "graph")
    audit = AuditLog(tmp_path / "audit", clock)
    return Env(ApprovalManager(store, audit, clock), store, clock, audit, tmp_path)


def new(env: Env, subject: str = "draft-1", h: str = H1, version: int = 1) -> tuple[str, str]:
    req, code = env.mgr.create(Kind.SEND, subject, h, version)
    return req.id, code


def test_code_shape_and_storage(env: Env) -> None:
    rid, code = new(env)
    assert len(code) == 4 and set(code) <= set(CODE_ALPHABET)
    assert not set("01ILO") & set(CODE_ALPHABET)
    stored = (env.root / "graph" / "approval" / f"{rid}.md").read_text(encoding="utf-8")
    audit_text = "".join((env.root / "audit").glob("*.jsonl").__next__().read_text())
    assert code not in stored and code not in audit_text


def test_codes_are_unique_among_pending(env: Env) -> None:
    codes = {new(env, f"draft-{i}")[1] for i in range(200)}
    assert len(codes) == 200


def test_correct_code_moves_to_held_and_issues_undo_code(env: Env) -> None:
    rid, code = new(env)
    d = env.mgr.approve(code, H1, actor="dai")
    assert d.ok and d.undo_code
    req = env.mgr.get(rid)
    assert req.state == "held" and req.hold_until == T0 + timedelta(seconds=60)


def test_code_is_single_use(env: Env) -> None:
    _, code = new(env)
    assert env.mgr.approve(code, H1, "dai").ok
    again = env.mgr.approve(code, H1, "dai")
    assert not again.ok and again.reason == "wrong_code"


def test_wrong_codes_lock_approvals_for_an_hour(env: Env) -> None:
    _, code = new(env)
    for _ in range(3):
        assert env.mgr.approve("ZZZZ", H1, "attacker").reason == "wrong_code"
    locked = env.mgr.approve(code, H1, "dai")
    assert not locked.ok and locked.reason == "locked"
    env.clock.advance(timedelta(hours=1, seconds=1))
    assert env.mgr.approve(code, H1, "dai").ok


def test_lockout_survives_restart(env: Env) -> None:
    _, code = new(env)
    for _ in range(3):
        env.mgr.approve("ZZZZ", H1, "attacker")
    assert env.reopen().approve(code, H1, "dai").reason == "locked"


def test_success_resets_failure_count(env: Env) -> None:
    _, c1 = new(env, "draft-1")
    _, c2 = new(env, "draft-2")
    env.mgr.approve("ZZZZ", H1, "x")
    env.mgr.approve("YYYY", H1, "x")
    assert env.mgr.approve(c1, H1, "dai").ok
    env.mgr.approve("ZZZZ", H1, "x")
    env.mgr.approve("YYYY", H1, "x")
    assert env.mgr.approve(c2, H1, "dai").ok  # would be locked without the reset


def test_expired_request_cannot_be_approved(env: Env) -> None:
    rid, code = new(env)
    env.clock.advance(timedelta(hours=73))
    d = env.mgr.approve(code, H1, "dai")
    assert not d.ok and d.reason == "expired"
    assert env.mgr.get(rid).state == "expired"


def test_expire_due_sweeps_pending(env: Env) -> None:
    rid, _ = new(env)
    env.clock.advance(timedelta(hours=73))
    assert env.mgr.expire_due() == [rid]
    assert env.mgr.expire_due() == []


def test_changed_subject_hash_is_refused(env: Env) -> None:
    rid, code = new(env)
    d = env.mgr.approve(code, H2, "dai")
    assert not d.ok and d.reason == "subject_changed"
    assert env.mgr.get(rid).state == "pending"


def test_edit_supersedes_and_old_code_cannot_approve_new_version(env: Env) -> None:
    rid, code = new(env)
    assert env.mgr.request_edit(code, "dai").ok
    assert env.mgr.get(rid).state == "edit_requested"
    _, code2 = new(env, h=H2, version=2)
    assert code2 != code
    assert env.mgr.approve(code, H2, "dai").reason == "wrong_code"
    assert env.mgr.approve(code2, H2, "dai").ok


def test_reject(env: Env) -> None:
    rid, code = new(env)
    assert env.mgr.reject(code, "dai").ok
    assert env.mgr.get(rid).state == "rejected"


def test_begin_send_waits_for_hold_then_happens_exactly_once(env: Env) -> None:
    rid, code = new(env)
    env.mgr.approve(code, H1, "dai")
    early = env.mgr.begin_send(rid)
    assert not early.ok and early.reason == "hold_not_elapsed"
    env.clock.advance(timedelta(seconds=61))
    assert env.mgr.begin_send(rid).ok
    second = env.mgr.begin_send(rid)
    assert not second.ok and second.reason == "not_held"
    assert env.mgr.get(rid).state == "sending"


def test_undo_during_hold_blocks_sending(env: Env) -> None:
    rid, code = new(env)
    undo = env.mgr.approve(code, H1, "dai").undo_code
    assert undo
    assert env.mgr.undo(undo, "dai").ok
    env.clock.advance(timedelta(minutes=5))
    assert env.mgr.begin_send(rid).reason == "not_held"
    assert env.mgr.get(rid).state == "undone"


def test_undo_not_possible_once_sending(env: Env) -> None:
    rid, code = new(env)
    undo = env.mgr.approve(code, H1, "dai").undo_code or ""
    env.clock.advance(timedelta(seconds=61))
    env.mgr.begin_send(rid)
    assert env.mgr.undo(undo, "dai").reason == "wrong_code"


def test_mark_sent_and_failed_only_from_sending(env: Env) -> None:
    rid, code = new(env)
    env.mgr.approve(code, H1, "dai")
    assert not env.mgr.mark_sent(rid).ok
    env.clock.advance(timedelta(seconds=61))
    env.mgr.begin_send(rid)
    assert [r.id for r in env.mgr.sending_requests()] == [rid]
    assert env.mgr.mark_sent(rid).ok
    assert not env.mgr.mark_sent(rid).ok
    assert env.mgr.sending_requests() == []


def test_illegal_transitions_are_refused(env: Env) -> None:
    rid, code = new(env)
    env.mgr.reject(code, "dai")
    assert env.mgr.approve(code, H1, "dai").reason == "wrong_code"
    assert env.mgr.begin_send(rid).reason == "not_held"
    assert not env.mgr.mark_failed(rid, "x").ok


def test_pending_request_survives_restart(env: Env) -> None:
    _, code = new(env)
    assert env.reopen().approve(code, H1, "dai").ok


def test_comparison_uses_constant_time_compare(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    _, code = new(env)
    env.mgr.approve(code, H1, "dai")
    assert calls


def test_every_transition_is_audited_without_codes(env: Env) -> None:
    rid, code = new(env)
    undo = env.mgr.approve(code, H1, "dai").undo_code or ""
    env.clock.advance(timedelta(seconds=61))
    env.mgr.begin_send(rid)
    env.mgr.mark_sent(rid)
    raw = (env.root / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    actions = [json.loads(line)["action"] for line in raw.splitlines()]
    assert actions == [
        "approval.create", "approval.approve", "approval.begin_send", "approval.sent",
    ]
    assert code not in raw and undo not in raw
    assert verify(env.root / "audit").ok
