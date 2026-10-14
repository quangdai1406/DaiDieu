"""M1.7: OutboundPolicy, the single decision point for anything leaving Daikon."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.approvals import ApprovalManager, Kind
from daikon.audit import AuditLog, verify
from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.graph.store import GraphStore
from daikon.limiter import Limiter, default_rules
from daikon.policy import Channel, DaiIdentity, OutboundAction, OutboundPolicy

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
H = "c" * 64
DAI = DaiIdentity(emails=frozenset({"dai@example.com"}), phones=frozenset({"+15550001111"}))


@dataclass
class Env:
    policy: OutboundPolicy
    approvals: ApprovalManager
    clock: FakeClock
    root: Path


def build(tmp_path: Path, mode: str = "dai_only", known: set[str] | None = None,
          limits: Limits | None = None) -> Env:
    clock = FakeClock(T0)
    store = GraphStore(tmp_path / "graph")
    audit = AuditLog(tmp_path / "audit", clock)
    approvals = ApprovalManager(store, audit, clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(limits or Limits()))
    policy = OutboundPolicy(
        data_dir=tmp_path, identity=DAI, mode=mode, limiter=limiter, approvals=approvals,
        audit=audit, known_recipient=lambda r: r in (known or set()),
    )
    return Env(policy, approvals, clock, tmp_path)


def email(to: list[str], kind: str = "reply", **kw: object) -> OutboundAction:
    return OutboundAction(Channel.EMAIL, tuple(to), kind, **kw)  # type: ignore[arg-type]


def sending_approval(env: Env, subject: str = "draft-1") -> str:
    req, code = env.approvals.create(Kind.SEND, subject, H)
    env.approvals.approve(code, H, "dai")
    env.clock.advance(timedelta(seconds=61))
    env.approvals.begin_send(req.id)
    return req.id


def test_unknown_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        build(tmp_path, mode="yolo")


def test_digest_to_dai_is_allowed_and_audited(tmp_path: Path) -> None:
    env = build(tmp_path)
    d = env.policy.evaluate(email(["dai@example.com"], kind="digest"))
    assert d.verdict == "allow"
    entries = [json.loads(x) for x in (tmp_path / "audit" / "2026-10.jsonl").read_text().splitlines()]
    assert entries[-1]["action"] == "policy.decision"
    assert entries[-1]["data"]["verdict"] == "allow"
    assert verify(tmp_path / "audit").ok


def test_display_name_and_case_are_normalized(tmp_path: Path) -> None:
    env = build(tmp_path)
    assert env.policy.evaluate(email(["Dai Tran <DAI@Example.com>"], kind="digest")).verdict == "allow"


@pytest.mark.parametrize(
    "bad", ["a@x.com\nbcc: evil@x.com", "a@x.com, b@y.com", "not-an-address", "", "a@x.com\r\n"]
)
def test_malformed_or_injected_recipients_are_denied(tmp_path: Path, bad: str) -> None:
    d = build(tmp_path).policy.evaluate(email([bad], kind="digest"))
    assert d.verdict == "deny" and d.reason == "bad_recipient"


def test_dai_only_mode_denies_everyone_else_even_with_approval(tmp_path: Path) -> None:
    env = build(tmp_path, mode="dai_only")
    rid = sending_approval(env)
    d = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid, subject_hash=H))
    assert d.verdict == "deny" and d.reason == "dai_only_mode"


def test_mixed_recipients_are_denied_in_dai_only_mode(tmp_path: Path) -> None:
    d = build(tmp_path).policy.evaluate(email(["dai@example.com", "bob@example.org"]))
    assert d.verdict == "deny" and d.reason == "dai_only_mode"


def test_live_mode_requires_a_sending_approval(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    none = env.policy.evaluate(email(["bob@example.org"], subject_hash=H))
    assert none.verdict == "deny" and none.reason == "no_approval"
    req, code = env.approvals.create(Kind.SEND, "draft-1", H)
    env.approvals.approve(code, H, "dai")  # held, not yet sending
    held = env.policy.evaluate(email(["bob@example.org"], approval_request_id=req.id, subject_hash=H))
    assert held.verdict == "deny" and held.reason == "no_approval"


def test_live_mode_allows_known_recipient_with_sending_approval(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    rid = sending_approval(env)
    d = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid, subject_hash=H))
    assert d.verdict == "allow"


def test_changed_content_or_recipients_hash_is_denied(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    rid = sending_approval(env)
    d = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid, subject_hash="d" * 64))
    assert d.verdict == "deny" and d.reason == "subject_changed"


def test_wrong_kind_of_approval_is_denied(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    req, code = env.approvals.create(Kind.SKILL_ACTIVATION, "skill-1", H)
    env.approvals.approve(code, H, "dai")
    env.clock.advance(timedelta(seconds=61))
    env.approvals.begin_send(req.id)
    d = env.policy.evaluate(email(["bob@example.org"], approval_request_id=req.id, subject_hash=H))
    assert d.verdict == "deny" and d.reason == "no_approval"


def test_first_time_recipient_needs_second_channel(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known=set())
    rid = sending_approval(env)
    act = email(["new@example.org"], approval_request_id=rid, subject_hash=H)
    d = env.policy.evaluate(act)
    assert d.verdict == "hold" and d.tier == "high" and d.needs_second_channel
    ok = env.policy.evaluate(email(["new@example.org"], approval_request_id=rid, subject_hash=H,
                                   second_channel_confirmed=True))
    assert ok.verdict == "allow"


@pytest.mark.parametrize("kw", [{"has_attachment": True}, {"sensitive": True}])
def test_attachment_or_sensitive_content_is_high_risk(tmp_path: Path, kw: dict[str, bool]) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    rid = sending_approval(env)
    d = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid, subject_hash=H, **kw))
    assert d.verdict == "hold" and d.needs_second_channel


def test_pause_blocks_others_but_not_messages_to_dai(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"})
    rid = sending_approval(env)
    (tmp_path / "PAUSE").write_text("", encoding="utf-8")
    blocked = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid, subject_hash=H))
    assert blocked.verdict == "deny" and blocked.reason == "paused"
    assert env.policy.evaluate(email(["dai@example.com"], kind="alert")).verdict == "allow"


def test_sms_to_anyone_but_dai_is_denied(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live")
    to_dai = OutboundAction(Channel.SMS, ("+1 (555) 000-1111",), "digest")
    assert env.policy.evaluate(to_dai).verdict == "allow"
    other = OutboundAction(Channel.SMS, ("+15559998888",), "reply")
    d = env.policy.evaluate(other)
    assert d.verdict == "deny" and d.reason == "sms_to_others_unsupported"


def test_calls_are_not_enabled(tmp_path: Path) -> None:
    d = build(tmp_path, mode="live").policy.evaluate(
        OutboundAction(Channel.CALL, ("+15559998888",), "call")
    )
    assert d.verdict == "deny" and d.reason == "call_not_enabled"


def test_too_many_recipients_denied(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={f"u{i}@x.org" for i in range(5)})
    rid = sending_approval(env)
    d = env.policy.evaluate(email([f"u{i}@x.org" for i in range(5)], approval_request_id=rid, subject_hash=H))
    assert d.verdict == "deny" and d.reason == "too_many_recipients"


def test_send_cap_denies_and_denial_consumes_nothing(tmp_path: Path) -> None:
    env = build(tmp_path, mode="live", known={"bob@example.org"}, limits=Limits(sends_per_day=1))
    rid1 = sending_approval(env, "draft-1")
    rid2 = sending_approval(env, "draft-2")
    a = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid1, subject_hash=H))
    b = env.policy.evaluate(email(["bob@example.org"], approval_request_id=rid2, subject_hash=H))
    assert a.verdict == "allow" and b.verdict == "deny" and b.reason == "cap_exceeded"


def test_sms_to_dai_is_capped(tmp_path: Path) -> None:
    env = build(tmp_path, limits=Limits(sms_per_day=2))
    sms = OutboundAction(Channel.SMS, ("+15550001111",), "alert")
    verdicts = [env.policy.evaluate(sms).verdict for _ in range(3)]
    assert verdicts == ["allow", "allow", "deny"]


def test_every_decision_is_audited_including_denials(tmp_path: Path) -> None:
    env = build(tmp_path)
    env.policy.evaluate(email(["dai@example.com"], kind="digest"))
    env.policy.evaluate(email(["bob@example.org"]))
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    verdicts = [json.loads(x)["data"]["verdict"] for x in raw.splitlines()]
    assert verdicts == ["allow", "deny"]
