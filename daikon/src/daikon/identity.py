"""Dai's own identities: the only addresses and numbers that may command Daikon."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DaiIdentity:
    emails: frozenset[str]
    phones: frozenset[str]
