"""M2.4: poll loop with backoff, heartbeat gap alerts and a single-instance lock."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.alerter import Alerter
from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.config import Limits
from daikon.graph.store import AlreadyRunningError, GraphStore, InstanceLock
from daikon.limiter import Limiter, default_rules
from daikon.runner import Runner
from daikon.testing import FakeMessenger

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@dataclass
class FakePipeline:
    fail_times: int = 0
    calls: list[str] = field(default_factory=list)

    def poll(self) -> None:
        self.calls.append("poll")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("boom token=abc")

    def release_due(self) -> None:
        self.calls.append("release_due")

    def housekeeping(self) -> None:
        self.calls.append("housekeeping")


@dataclass
class Rig:
    runner: Runner
    pipe: FakePipeline
    clock: FakeClock
    messenger: FakeMessenger
    root: Path
    sleeps: list[float] = field(default_factory=list)


def rig(tmp_path: Path, fail_times: int = 0) -> Rig:
    clock = FakeClock(T0)
    audit = AuditLog(tmp_path / "audit", clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(Limits()))
    messenger = FakeMessenger()
    pipe = FakePipeline(fail_times)
    r = Rig(None, pipe, clock, messenger, tmp_path)  # type: ignore[arg-type]

    def fake_sleep(seconds: float) -> None:
        r.sleeps.append(seconds)
        clock.advance(timedelta(seconds=seconds))

    r.runner = Runner(pipe, GraphStore(tmp_path / "graph"), clock, Alerter(messenger, limiter, audit),
                      audit, sleep=fake_sleep)
    return r


def audit_actions(root: Path) -> list[str]:
    raw = (root / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    return [json.loads(x)["action"] for x in raw.splitlines()]


def test_tick_runs_the_steps_in_order(tmp_path: Path) -> None:
    r = rig(tmp_path)
    assert r.runner.tick() is True
    assert r.pipe.calls == ["poll", "release_due", "housekeeping"]


def test_a_failure_is_audited_without_secrets_and_does_not_raise(tmp_path: Path) -> None:
    r = rig(tmp_path, fail_times=1)
    assert r.runner.tick() is False
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    assert "runner.error" in raw and "RuntimeError" in raw and "token=abc" not in raw


def test_backoff_doubles_and_is_capped_then_resets(tmp_path: Path) -> None:
    r = rig(tmp_path, fail_times=10)
    for _ in range(8):
        r.runner.tick()
    delays = [r.runner.next_delay().total_seconds()]
    assert delays[0] == 1800  # capped at 30 minutes
    r.pipe.fail_times = 0
    r.runner.tick()
    assert r.runner.next_delay() == timedelta(seconds=120)


def test_first_failures_back_off_gradually(tmp_path: Path) -> None:
    r = rig(tmp_path, fail_times=3)
    seen = []
    for _ in range(3):
        r.runner.tick()
        seen.append(r.runner.next_delay().total_seconds())
    assert seen == [240, 480, 960]


def test_three_failures_alert_once_and_recovery_is_logged(tmp_path: Path) -> None:
    r = rig(tmp_path, fail_times=5)
    for _ in range(5):
        r.runner.tick()
    assert [c for c, *_ in r.messenger.sent] == ["email"]  # warning, de-duplicated
    r.runner.tick()
    assert "alert.logged" in audit_actions(tmp_path)  # recovery notice


def test_a_long_gap_since_the_last_good_tick_raises_one_alert(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.runner.tick()
    r.clock.advance(timedelta(hours=2, minutes=10))  # laptop slept
    r.runner.tick()
    sent = [b for _, _, b in r.messenger.sent]
    assert len(sent) == 1 and "2h" in sent[0]
    r.runner.tick()
    assert len(r.messenger.sent) == 1


def test_short_gaps_do_not_alert(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.runner.tick()
    r.clock.advance(timedelta(minutes=5))
    r.runner.tick()
    assert r.messenger.sent == []


def test_heartbeat_survives_restart(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.runner.tick()
    again = rig(tmp_path)  # new runner over the same data dir
    again.clock.advance(timedelta(hours=3))
    again.runner.tick()
    assert len(again.messenger.sent) == 1


def test_run_forever_sleeps_between_ticks_and_stops(tmp_path: Path) -> None:
    r = rig(tmp_path)
    count = {"n": 0}

    def stop() -> bool:
        count["n"] += 1
        return count["n"] > 3

    r.runner.run_forever(stop)
    assert r.sleeps == [120, 120, 120] and r.pipe.calls.count("poll") == 3


def test_keyboard_interrupt_is_not_swallowed(tmp_path: Path) -> None:
    r = rig(tmp_path)

    def interrupt() -> None:
        raise KeyboardInterrupt

    r.pipe.poll = interrupt  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        r.runner.tick()


def test_second_instance_cannot_start(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            rig(tmp_path).runner.run_forever(lambda: True, lock=InstanceLock(tmp_path))
    finally:
        first.release()
