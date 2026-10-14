from __future__ import annotations

from typing import Any, Protocol


class Gateway(Protocol):
    """Every model call goes through this seam (audit, caps and backend rules live behind it)."""

    def complete_json(self, role: str, system: str, user: str) -> dict[str, Any]: ...
