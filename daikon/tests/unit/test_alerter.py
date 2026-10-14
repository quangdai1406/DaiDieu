"""M1.9: Alerter with severity routing, de-duplication, caps and sanitized messages."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.alerter import Alerter, Severity
from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.limiter import Limiter, default_rules

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@dataclass
class FakeMessenger:
    sms_ok: bool = True
    email_ok: bool = True
    sent: list[tuple[str, str, str]] = field(default_factory=list)  # (channel, subject, body)

    def send_sms(self, body: str) -> bool:
        self.sent.append(("sms", "", body))
        return self.sms_ok

    def send_email(self, subject: str, body: str) -> bool:
        self.sent.append(("email", subject, body))
        return self.email_ok


def make(tmp_path: Path, m: FakeMessenger, limits: Limits | None = None) -> tuple[Alerter, FakeClock]:
    clock = FakeClock(T0)
    audit = AuditLog(tmp_path / "audit", clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(limits or Limits()))
    return Alerter(m, limiter, audit), clock


def audit_actions(tmp_path: Path) -> list[str]:
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    return [json.loads(line)["action"] for line in raw.splitlines()]


def test_info_is_logged_not_sent(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.INFO, "k", "all quiet") is True
    assert m.sent == [] and audit_actions(tmp_path) == ["alert.logged"]


def test_warning_goes_by_email_only(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.WARNING, "spend", "80% of cap")
    assert [c for c, *_ in m.sent] == ["email"]


def test_critical_uses_sms_first(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.CRITICAL, "audit", "chain broken")
    assert [c for c, *_ in m.sent] == ["sms"]


def test_critical_falls_back_to_email_when_sms_fails(tmp_path: Path) -> None:
    m = FakeMessenger(sms_ok=False)
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.CRITICAL, "audit", "chain broken")
    assert [c for c, *_ in m.sent] == ["sms", "email"]


def test_undeliverable_alert_is_reported_false_and_audited(tmp_path: Path) -> None:
    m = FakeMessenger(sms_ok=False, email_ok=False)
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.CRITICAL, "k", "x") is False
    assert "alert.undelivered" in audit_actions(tmp_path)


def test_same_key_is_suppressed_for_an_hour(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, clock = make(tmp_path, m)
    assert alerter.alert(Severity.WARNING, "offline", "down")
    assert alerter.alert(Severity.WARNING, "offline", "still down") is False
    assert len(m.sent) == 1 and "alert.suppressed" in audit_actions(tmp_path)
    clock.advance(timedelta(hours=1, seconds=1))
    assert alerter.alert(Severity.WARNING, "offline", "down again")
    assert len(m.sent) == 2


def test_different_keys_are_independent(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    assert alerter.alert(Severity.WARNING, "a", "x") and alerter.alert(Severity.WARNING, "b", "y")


def test_daily_cap_stops_alert_floods(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m, Limits(alerts_per_day=2))
    results = [alerter.alert(Severity.WARNING, f"k{i}", "x") for i in range(4)]
    assert results == [True, True, False, False]


def test_message_is_sanitized(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    alerter.alert(Severity.CRITICAL, "k", "bad\nlink https://evil.example.com " + "x" * 500 + "\x07")
    body = m.sent[0][2]
    assert "\n" not in body and "https://" not in body and "\x07" not in body
    assert len(body) <= 300


def test_secret_looking_messages_are_masked(tmp_path: Path) -> None:
    m = FakeMessenger()
    alerter, _ = make(tmp_path, m)
    alerter.alert(Severity.CRITICAL, "k", "key leaked sk-ant-" + "A" * 30)
    assert "sk-ant-" not in m.sent[0][2]
