"""Alerter: one place that decides how, and whether, Dai hears about a problem.

Critical alerts try SMS then email, warnings use email, info is only logged. Alerts are
de-duplicated per key (one per hour) and capped per day so a failure loop cannot flood Dai.
Messages are sanitized: control characters removed, URLs defanged, secret-looking text
withheld, length capped. Delivery goes through a ``Messenger`` (the policy-gated notifier).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from daikon.audit import AuditLog
from daikon.defang import defang
from daikon.guard import contains_secret
from daikon.limiter import Limiter

MAX_LEN = 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Messenger(Protocol):
    def send_sms(self, body: str) -> bool: ...
    def send_email(self, subject: str, body: str) -> bool: ...


def sanitize(message: str) -> str:
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", message)).strip()
    text = defang(text)
    if contains_secret(text):
        return "[message withheld: contained a secret-like value]"
    return text[:MAX_LEN]


class Alerter:
    def __init__(self, messenger: Messenger, limiter: Limiter, audit: AuditLog) -> None:
        self._messenger, self._limiter, self._audit = messenger, limiter, audit

    def alert(self, severity: Severity, key: str, message: str) -> bool:
        text = sanitize(message)
        if severity is Severity.INFO:
            self._audit.append("alerter", "alert.logged", key=key, message=text)
            return True
        fresh = self._limiter.peek("alert_key", key).allowed
        if not (fresh and self._limiter.peek("alerts").allowed):
            self._audit.append("alerter", "alert.suppressed", key=key, severity=severity.value)
            return False
        self._limiter.check_and_consume("alert_key", key)
        self._limiter.check_and_consume("alerts")
        delivered_by = self._deliver(severity, key, text)
        if delivered_by is None:
            self._audit.append("alerter", "alert.undelivered", key=key, severity=severity.value)
            return False
        self._audit.append("alerter", "alert.sent", key=key, severity=severity.value,
                           channel=delivered_by, message=text)
        return True

    def _deliver(self, severity: Severity, key: str, text: str) -> str | None:
        if severity is Severity.CRITICAL and self._try(lambda: self._messenger.send_sms(text)):
            return "sms"
        subject = sanitize(f"[Daikon {severity.value}] {key}")
        if self._try(lambda: self._messenger.send_email(subject, text)):
            return "email"
        return None

    @staticmethod
    def _try(send: Callable[[], bool]) -> bool:
        try:
            return bool(send())
        except Exception:  # noqa: BLE001 - a failing channel must never break the caller
            return False
