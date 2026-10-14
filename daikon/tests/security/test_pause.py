"""M5.3: PAUSE / RESUME. Stopping is easy and always allowed; resuming needs the one-time code."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.limiter import Limiter, default_rules
from daikon.pause import PauseSwitch

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def make(tmp_path: Path) -> tuple[PauseSwitch, FakeClock]:
    clock = FakeClock(T0)
    audit = AuditLog(tmp_path / "audit", clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(Limits()))
    return PauseSwitch(tmp_path, clock, audit, limiter), clock


def test_pause_creates_the_file_and_returns_a_resume_code(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    assert not sw.is_paused()
    code = sw.pause("dai")
    assert code and len(code) == 4 and sw.is_paused() and (tmp_path / "PAUSE").exists()


def test_the_code_is_stored_only_as_a_hash(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    code = sw.pause("dai") or ""
    assert code not in (tmp_path / "PAUSE").read_text(encoding="utf-8")


def test_pausing_twice_does_not_issue_a_new_code(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    sw.pause("dai")
    assert sw.pause("dai") is None


def test_wrong_code_does_not_resume_and_right_code_does(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    code = sw.pause("dai") or ""
    assert sw.resume("ZZZZ", "dai") is False and sw.is_paused()
    assert sw.resume(code, "dai") is True and not sw.is_paused()


def test_the_code_works_once_only(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    code = sw.pause("dai") or ""
    sw.resume(code, "dai")
    sw.pause("dai")  # a new pause issues a new code
    assert sw.resume(code, "dai") is False and sw.is_paused()


def test_three_attempts_an_hour_even_for_the_right_code(tmp_path: Path) -> None:
    sw, clock = make(tmp_path)
    code = sw.pause("dai") or ""
    for guess in ("AAAA", "BBBB", "CCCC"):
        assert sw.resume(guess, "attacker") is False
    assert sw.resume(code, "dai") is False and sw.is_paused()
    clock.advance(timedelta(hours=1, seconds=1))
    assert sw.resume(code, "dai") is True


def test_a_manually_created_pause_file_can_only_be_removed_by_hand(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    (tmp_path / "PAUSE").write_text("", encoding="utf-8")
    assert sw.is_paused() and sw.resume("ABCD", "dai") is False and sw.pause("dai") is None


def test_every_change_is_audited_without_the_code(tmp_path: Path) -> None:
    sw, _ = make(tmp_path)
    code = sw.pause("dai") or ""
    sw.resume("ZZZZ", "x")
    sw.resume(code, "dai")
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    actions = [json.loads(x)["action"] for x in raw.splitlines()]
    assert actions == ["pause.on", "pause.resume_failed", "pause.off"] and code not in raw
