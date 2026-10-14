from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class Gateway(Protocol):
    """Every model call goes through this seam (audit, caps and backend rules live behind it).

    There is deliberately no ``tools`` parameter: the mail lane's models cannot call tools.
    """

    def complete_json(
        self,
        role: str,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
        data_label: str = "normal",
    ) -> dict[str, Any]: ...
