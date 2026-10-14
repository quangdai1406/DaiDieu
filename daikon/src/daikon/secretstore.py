"""Secret storage: Windows Credential Manager via keyring in production, memory in tests.

Secrets carry optional expiry metadata so Daikon can warn before tokens lapse.
Values are never included in repr() and never written to config files.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Protocol

import keyring
import keyring.errors


class SecretNotFoundError(KeyError):
    """Raised when a named secret is not stored."""


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...
    def set(self, name: str, value: str, expires_at: datetime | None = None) -> None: ...
    def expiring_within(self, window: timedelta, now: datetime) -> list[str]: ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, datetime | None]] = {}

    def __repr__(self) -> str:
        return f"MemorySecretStore(names={sorted(self._data)})"

    def get(self, name: str) -> str:
        try:
            return self._data[name][0]
        except KeyError:
            raise SecretNotFoundError(name) from None

    def set(self, name: str, value: str, expires_at: datetime | None = None) -> None:
        self._data[name] = (value, expires_at)

    def expiring_within(self, window: timedelta, now: datetime) -> list[str]:
        return sorted(
            n for n, (_, exp) in self._data.items() if exp is not None and exp <= now + window
        )


class KeyringSecretStore:
    """Stores each secret as a JSON blob {value, expires_at} under one keyring service."""

    _INDEX = "__index__"

    def __init__(self, service: str = "daikon") -> None:
        self._service = service

    def __repr__(self) -> str:
        return f"KeyringSecretStore(service={self._service!r})"

    def _names(self) -> list[str]:
        raw = keyring.get_password(self._service, self._INDEX)
        return list(json.loads(raw)) if raw else []

    def get(self, name: str) -> str:
        raw = keyring.get_password(self._service, name)
        if raw is None:
            raise SecretNotFoundError(name)
        return str(json.loads(raw)["value"])

    def set(self, name: str, value: str, expires_at: datetime | None = None) -> None:
        blob = {"value": value, "expires_at": expires_at.isoformat() if expires_at else None}
        keyring.set_password(self._service, name, json.dumps(blob))
        names = set(self._names()) | {name}
        keyring.set_password(self._service, self._INDEX, json.dumps(sorted(names)))

    def expiring_within(self, window: timedelta, now: datetime) -> list[str]:
        out: list[str] = []
        for name in self._names():
            raw = keyring.get_password(self._service, name)
            if raw is None:
                continue
            exp = json.loads(raw)["expires_at"]
            if exp and datetime.fromisoformat(exp).astimezone(UTC) <= now + window:
                out.append(name)
        return sorted(out)
