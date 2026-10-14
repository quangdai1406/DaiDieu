"""Mail seam: what the pipeline needs from Gmail, independent of the real API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuthResults:
    spf: str = "none"
    dkim: str = "none"
    dmarc: str = "none"

    @property
    def passed(self) -> bool:
        """All three must pass; DMARC is what proves alignment with the visible From domain."""
        return self.spf == "pass" and self.dkim == "pass" and self.dmarc == "pass"


@dataclass(frozen=True)
class InboundEmail:
    id: str
    thread_id: str
    from_addr: str
    to: tuple[str, ...]
    subject: str
    text: str | None
    html: str | None
    auth: AuthResults
    received: datetime
    reply_to: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    attachment_count: int = 0


class Mailbox(Protocol):
    def fetch_new(self) -> list[InboundEmail]: ...

    def send(
        self, to: list[str], subject: str, body: str, in_reply_to: str | None = None
    ) -> str: ...
