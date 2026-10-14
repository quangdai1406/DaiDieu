from datetime import UTC, datetime, timedelta

import pytest

from daikon.clock import FakeClock, SystemClock

pytestmark = pytest.mark.unit


def test_fake_clock_starts_and_advances() -> None:
    c = FakeClock(datetime(2026, 10, 14, tzinfo=UTC))
    assert c.now() == datetime(2026, 10, 14, tzinfo=UTC)
    c.advance(timedelta(hours=25))
    assert c.now() == datetime(2026, 10, 15, 1, tzinfo=UTC)


def test_fake_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 10, 14))


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().tzinfo is not None
