"""Runner: the poll loop. One tick = poll mail, release approved sends, housekeeping.

Errors never escape a tick: they are audited (secrets redacted), back off exponentially up
to a cap, and raise one warning after three in a row. A heartbeat records the last good tick
so a long gap (laptop asleep, power cut) is reported once when Daikon wakes. Only one
runner per data directory may run (InstanceLock).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from daikon.alerter import Alerter, Severity
from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.graph.node import Node
from daikon.graph.store import GraphStore, InstanceLock
from daikon.guard import redact_secrets

HEARTBEAT = ("state", "heartbeat")


class PipelineLike(Protocol):
    def poll(self) -> None: ...
    def release_due(self) -> None: ...
    def housekeeping(self) -> None: ...


def _human(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


class Runner:
    def __init__(
        self,
        pipeline: PipelineLike,
        store: GraphStore,
        clock: Clock,
        alerter: Alerter,
        audit: AuditLog,
        *,
        interval: timedelta = timedelta(seconds=120),
        gap_alert_after: timedelta = timedelta(minutes=30),
        max_backoff: timedelta = timedelta(minutes=30),
        alert_after_failures: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        daily: Callable[[], object] | None = None,
    ) -> None:
        self._pipe, self._store, self._clock = pipeline, store, clock
        self._alerter, self._audit = alerter, audit
        self._interval, self._gap, self._max_backoff = interval, gap_alert_after, max_backoff
        self._alert_after, self._sleep = alert_after_failures, sleep
        self._daily = daily  # idempotent once-a-day work such as the backup
        self._failures, self._alerted = 0, False

    def next_delay(self) -> timedelta:
        if self._failures == 0:
            return self._interval
        return min(self._max_backoff, self._interval * (1 << self._failures))

    # ---------- heartbeat ----------
    def _last_ok(self) -> datetime | None:
        if not self._store.exists(*HEARTBEAT):
            return None
        return datetime.fromisoformat(str(self._store.read(*HEARTBEAT).extra["last_ok"]))

    def _beat(self) -> None:
        now = self._clock.now()
        self._store.write(Node(id=HEARTBEAT[1], type=HEARTBEAT[0], status="ok", created=now,
                               extra={"last_ok": now.isoformat()}))

    def _check_gap(self) -> None:
        last = self._last_ok()
        if last is not None and self._clock.now() - last > self._gap:
            gap = _human(self._clock.now() - last)
            self._alerter.alert(Severity.WARNING, "heartbeat_gap",
                                f"Daikon was offline for {gap}. Catching up now.")

    # ---------- one cycle ----------
    def tick(self) -> bool:
        self._check_gap()
        try:
            self._pipe.poll()
            self._pipe.release_due()
            self._pipe.housekeeping()
        except Exception as exc:  # noqa: BLE001 - a failing cycle must never kill the loop
            self._failures += 1
            self._audit.append("runner", "runner.error", error=type(exc).__name__,
                               message=redact_secrets(str(exc))[:200], failures=self._failures)
            if self._failures >= self._alert_after:
                self._alerter.alert(
                    Severity.WARNING, "poll_failing",
                    f"Polling failed {self._failures} times in a row ({type(exc).__name__}).",
                )
                self._alerted = True
            return False
        if self._alerted:
            self._alerter.alert(Severity.INFO, "poll_recovered", "Polling recovered.")
            self._alerted = False
        self._failures = 0
        self._beat()
        self._run_daily()
        return True

    def _run_daily(self) -> None:
        if self._daily is None:
            return
        try:
            self._daily()
        except Exception as exc:  # noqa: BLE001 - housekeeping must never stop mail handling
            self._audit.append("runner", "runner.daily_error", error=type(exc).__name__,
                               message=redact_secrets(str(exc))[:200])
            self._alerter.alert(Severity.WARNING, "daily_task_failed",
                                f"A daily task failed ({type(exc).__name__}).")

    def run_forever(self, stop: Callable[[], bool], lock: InstanceLock | None = None) -> None:
        if lock is not None:
            lock.acquire()
        try:
            while not stop():
                self.tick()
                self._sleep(self.next_delay().total_seconds())
        finally:
            if lock is not None:
                lock.release()
