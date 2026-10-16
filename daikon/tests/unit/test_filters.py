"""M2.3: rule filter. Decides, in plain code, which mail may cost a model run."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.filters import Action, RuleFilter
from daikon.graph.store import GraphStore
from daikon.limiter import Limiter, default_rules
from daikon.mail import AuthResults, InboundEmail
from daikon.people import PersonBook

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@dataclass
class Env:
    flt: RuleFilter
    limiter: Limiter
    people: PersonBook
    clock: FakeClock
    root: Path


def env(tmp_path: Path, limits: Limits | None = None) -> Env:
    clock = FakeClock(T0)
    store = GraphStore(tmp_path / "graph")
    audit = AuditLog(tmp_path / "audit", clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(limits or Limits()))
    people = PersonBook(store, clock)
    return Env(RuleFilter(limiter, people, audit), limiter, people, clock, tmp_path)


def mail(frm: str = "bob@example.org", headers: tuple[tuple[str, str], ...] = (), id_: str = "m1"
         ) -> InboundEmail:
    return InboundEmail(id=id_, thread_id="t", from_addr=frm, to=("daikon@example.com",),
                        subject="Hi", text="hello", html=None, auth=AuthResults(), received=T0,
                        headers=headers)


def test_ordinary_human_mail_is_processed(tmp_path: Path) -> None:
    d = env(tmp_path).flt.evaluate(mail(), "bob@example.org")
    assert d.action is Action.PROCESS


@pytest.mark.parametrize(
    "sender",
    ["noreply@x.com", "no-reply@x.com", "donotreply@x.com", "MAILER-DAEMON@x.com",
     "notifications@x.com", "postmaster@x.com", "bounce+abc@x.com"],
)
def test_automated_sender_names_are_skipped(tmp_path: Path, sender: str) -> None:
    d = env(tmp_path).flt.evaluate(mail(sender), sender.lower())
    assert d.action is Action.SKIP_AUTOMATED


@pytest.mark.parametrize(
    "header",
    [("List-Unsubscribe", "<mailto:u@x.com>"), ("Precedence", "bulk"), ("precedence", "LIST"),
     ("Auto-Submitted", "auto-generated"), ("X-Auto-Response-Suppress", "All")],
)
def test_automated_headers_are_skipped(tmp_path: Path, header: tuple[str, str]) -> None:
    d = env(tmp_path).flt.evaluate(mail(headers=(header,)), "bob@example.org")
    assert d.action is Action.SKIP_AUTOMATED


def test_auto_submitted_no_is_not_automated(tmp_path: Path) -> None:
    d = env(tmp_path).flt.evaluate(mail(headers=(("Auto-Submitted", "no"),)), "bob@example.org")
    assert d.action is Action.PROCESS


def test_blocked_sender_is_skipped_first(tmp_path: Path) -> None:
    e = env(tmp_path)
    e.people.block("bob@example.org")
    d = e.flt.evaluate(mail(headers=(("Precedence", "bulk"),)), "bob@example.org")
    assert d.action is Action.SKIP_BLOCKED


def test_per_sender_hourly_rate(tmp_path: Path) -> None:
    e = env(tmp_path, Limits(per_sender_per_hour=3))
    results = [e.flt.evaluate(mail(id_=f"m{i}"), "bob@example.org").action for i in range(5)]
    assert results == [Action.PROCESS] * 3 + [Action.SKIP_CAP] * 2
    assert e.flt.evaluate(mail("carol@example.org"), "carol@example.org").action is Action.PROCESS
    e.clock.advance(timedelta(hours=1, seconds=1))
    assert e.flt.evaluate(mail(), "bob@example.org").action is Action.PROCESS


def test_daily_model_cap_blocks_processing(tmp_path: Path) -> None:
    e = env(tmp_path, Limits(model_runs_per_day=2))
    e.limiter.check_and_consume("model_runs", amount=2)
    d = e.flt.evaluate(mail(), "bob@example.org")
    assert d.action is Action.SKIP_CAP and d.reason == "daily_model_cap"


def test_skipped_automated_mail_does_not_use_the_sender_budget(tmp_path: Path) -> None:
    e = env(tmp_path, Limits(per_sender_per_hour=1))
    auto = mail(headers=(("Precedence", "bulk"),))
    for _ in range(3):
        assert e.flt.evaluate(auto, "bob@example.org").action is Action.SKIP_AUTOMATED
    assert e.flt.evaluate(mail(), "bob@example.org").action is Action.PROCESS


def test_decisions_are_audited_without_message_content(tmp_path: Path) -> None:
    e = env(tmp_path)
    e.flt.evaluate(mail("noreply@x.com"), "noreply@x.com")
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    rec = json.loads(raw.splitlines()[-1])
    assert rec["action"] == "filter.decision" and rec["data"]["action"] == "skip_automated"
    assert "hello" not in raw
