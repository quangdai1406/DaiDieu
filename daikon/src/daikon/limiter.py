"""Persistent caps shared by the gateway, filter, policy gate and notifier.

One ledger answers "may I spend this?" for every scope (model runs, dollars, sends, SMS,
approvals, per-sender rates). Windows are fixed UTC calendar windows. Unknown scopes and
corrupt state fail closed. A denied request consumes nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from daikon.clock import Clock
from daikon.config import Limits

Window = Literal["hour", "day", "month"]


@dataclass(frozen=True)
class Rule:
    limit: float
    window: Window


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    used: float
    limit: float
    resets_at: datetime


def default_rules(limits: Limits) -> dict[str, Rule]:
    return {
        "model_runs": Rule(limits.model_runs_per_day, "day"),
        "dollars": Rule(limits.dollars_per_month, "month"),
        "sends": Rule(limits.sends_per_day, "day"),
        "sms": Rule(limits.sms_per_day, "day"),
        "approvals": Rule(limits.approvals_per_day, "day"),
        "sender_hourly": Rule(limits.per_sender_per_hour, "hour"),
        "alerts": Rule(limits.alerts_per_day, "day"),
        "alert_key": Rule(1, "hour"),
        "inbound_hourly": Rule(limits.per_sender_per_hour, "hour"),
    }


def _window_bounds(now: datetime, window: Window) -> tuple[str, datetime]:
    now = now.astimezone(UTC)
    if window == "hour":
        start = now.replace(minute=0, second=0, microsecond=0)
        return f"{start:%Y-%m-%dT%H}", start + timedelta(hours=1)
    if window == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return f"{start:%Y-%m-%d}", start + timedelta(days=1)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return f"{start:%Y-%m}", nxt


class Limiter:
    def __init__(self, path: Path, clock: Clock, rules: dict[str, Rule]) -> None:
        self._path, self._clock, self._rules = path, clock, rules
        self._lock = threading.Lock()
        self._used: dict[str, float] = self._load()

    def _load(self) -> dict[str, float]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in raw.items()}
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"corrupt limiter state: {self._path}") from exc

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(self._used, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def _slot(self, scope: str, key: str) -> tuple[str, Rule, datetime]:
        rule = self._rules[scope]  # KeyError for unknown scopes: fail closed
        window_id, resets_at = _window_bounds(self._clock.now(), rule.window)
        return f"{scope}|{key}|{rule.window}|{window_id}", rule, resets_at

    def peek(self, scope: str, key: str = "*") -> LimitResult:
        slot, rule, resets_at = self._slot(scope, key)
        used = self._used.get(slot, 0.0)
        return LimitResult(used < rule.limit, used, rule.limit, resets_at)

    def check_and_consume(self, scope: str, key: str = "*", amount: float = 1) -> LimitResult:
        with self._lock:
            slot, rule, resets_at = self._slot(scope, key)
            used = self._used.get(slot, 0.0)
            if used + amount > rule.limit:
                return LimitResult(False, used, rule.limit, resets_at)
            self._used[slot] = used + amount
            self._prune(slot)
            self._save()
            return LimitResult(True, used + amount, rule.limit, resets_at)

    def record(self, scope: str, amount: float, key: str = "*") -> None:
        """Add spend that already happened (it may push usage past the cap)."""
        with self._lock:
            slot, _, _ = self._slot(scope, key)
            self._used[slot] = self._used.get(slot, 0.0) + amount
            self._prune(slot)
            self._save()

    def _prune(self, current_slot: str) -> None:
        """Drop counters from past windows of the same scope/key/window type."""
        prefix = current_slot.rsplit("|", 1)[0] + "|"
        for slot in [s for s in self._used if s.startswith(prefix) and s != current_slot]:
            del self._used[slot]
