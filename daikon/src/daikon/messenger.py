"""Messenger for the Alerter: Dai-bound email through the policy-gated notifier; SMS if wired."""

from __future__ import annotations

from typing import Protocol

from daikon.notifier import Notifier


class SmsSender(Protocol):
    def send(self, body: str) -> bool: ...


class DaiMessenger:
    def __init__(self, notifier: Notifier, sms: SmsSender | None = None) -> None:
        self._notifier, self._sms = notifier, sms

    def send_sms(self, body: str) -> bool:
        return self._sms.send(body) if self._sms is not None else False

    def send_email(self, subject: str, body: str) -> bool:
        return self._notifier.send_to_dai(subject, body, kind="alert")
