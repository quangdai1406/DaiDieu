"""M1.5: persistent caps for model runs, dollars, sends, SMS, approvals, per-sender rates."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.limiter import Limiter, Rule, default_rules

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def make(tmp_path: Path, **rules: Rule) -> tuple[Limiter, FakeClock]:
    clock = FakeClock(T0)
    return Limiter(tmp_path / "limits.json", clock, rules), clock


def test_allows_until_limit_then_denies(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, sends=Rule(2, "day"))
    assert lim.check_and_consume("sends").allowed
    assert lim.check_and_consume("sends").allowed
    r = lim.check_and_consume("sends")
    assert not r.allowed and r.used == 2 and r.limit == 2


def test_denied_request_consumes_nothing(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, dollars=Rule(10, "month"))
    assert lim.check_and_consume("dollars", amount=8).allowed
    assert not lim.check_and_consume("dollars", amount=5).allowed
    assert lim.peek("dollars").used == 8
    assert lim.check_and_consume("dollars", amount=2).allowed


def test_peek_does_not_consume(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, sends=Rule(1, "day"))
    assert lim.peek("sends").used == 0
    assert lim.peek("sends").used == 0
    assert lim.check_and_consume("sends").allowed


def test_keys_are_independent(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, sender_hourly=Rule(1, "hour"))
    assert lim.check_and_consume("sender_hourly", key="a@x.com").allowed
    assert not lim.check_and_consume("sender_hourly", key="a@x.com").allowed
    assert lim.check_and_consume("sender_hourly", key="b@x.com").allowed


@pytest.mark.parametrize(
    ("window", "advance"),
    [("hour", timedelta(hours=1)), ("day", timedelta(days=1)), ("month", timedelta(days=31))],
)
def test_window_resets(tmp_path: Path, window: str, advance: timedelta) -> None:
    lim, clock = make(tmp_path, x=Rule(1, window))  # type: ignore[arg-type]
    assert lim.check_and_consume("x").allowed
    assert not lim.check_and_consume("x").allowed
    clock.advance(advance)
    assert lim.check_and_consume("x").allowed


def test_resets_at_is_reported(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, x=Rule(1, "day"))
    lim.check_and_consume("x")
    assert lim.check_and_consume("x").resets_at == datetime(2026, 10, 15, tzinfo=UTC)


def test_state_survives_restart(tmp_path: Path) -> None:
    lim, clock = make(tmp_path, sends=Rule(1, "day"))
    assert lim.check_and_consume("sends").allowed
    again = Limiter(tmp_path / "limits.json", clock, {"sends": Rule(1, "day")})
    assert not again.check_and_consume("sends").allowed


def test_unknown_scope_fails_closed(tmp_path: Path) -> None:
    lim, _ = make(tmp_path)
    with pytest.raises(KeyError):
        lim.check_and_consume("nope")


def test_corrupt_state_file_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "limits.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="limiter state"):
        Limiter(tmp_path / "limits.json", FakeClock(T0), {"x": Rule(1, "day")})


def test_default_rules_follow_config() -> None:
    rules = default_rules(Limits(model_runs_per_day=5, dollars_per_month=7.5, sends_per_day=3))
    assert rules["model_runs"] == Rule(5, "day")
    assert rules["dollars"] == Rule(7.5, "month")
    assert rules["sends"] == Rule(3, "day")
    assert {"sms", "approvals", "sender_hourly"} <= set(rules)


def test_record_adds_spend_even_beyond_the_cap_and_blocks_afterwards(tmp_path: Path) -> None:
    lim, _ = make(tmp_path, dollars=Rule(1.0, "month"))
    lim.record("dollars", 0.8)
    lim.record("dollars", 0.5)  # the money is already spent; the ledger must show it
    assert lim.peek("dollars").used == 1.3 and not lim.peek("dollars").allowed
    assert not lim.check_and_consume("dollars", amount=0.01).allowed


def test_record_unknown_scope_fails_closed(tmp_path: Path) -> None:
    lim, _ = make(tmp_path)
    with pytest.raises(KeyError):
        lim.record("nope", 1)
