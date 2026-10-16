"""Authenticated commands from Dai. Only top-level text of a verified message counts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr

from daikon.identity import DaiIdentity
from daikon.mail import InboundEmail
from daikon.untrusted import Untrusted

_PAUSE = re.compile(r"^PAUSE$", re.IGNORECASE)
_COMMAND = re.compile(
    r"^(OK|NO|EDIT|UNDO|RESUME|CONFIRM)\s+([23456789A-HJKMNP-Z]{4})(?:\s+(.*))?$", re.IGNORECASE
)


@dataclass(frozen=True)
class VerifiedCommand:
    verb: str
    code: str
    actor: str
    arg: str
    channel: str = "email"


def sender_address(msg: InboundEmail) -> str:
    return parseaddr(msg.from_addr)[1].strip().lower()


def authenticate_email(
    msg: InboundEmail, u: Untrusted, identity: DaiIdentity
) -> VerifiedCommand | None:
    """Return a command only if the sender is Dai's address, SPF and DKIM passed, and the
    command is the first line of the top-level text (not quoted or forwarded)."""
    actor = sender_address(msg)
    if actor not in identity.emails or not msg.auth.passed:
        return None
    first = next((ln.strip() for ln in u.text.splitlines() if ln.strip()), "")
    cmd = parse_command(first, actor)
    if cmd is not None and cmd.verb == "CONFIRM":
        return None  # a second-channel confirmation must come by SMS, never by email
    return cmd


def parse_command(first_line: str, actor: str) -> VerifiedCommand | None:
    """Parse one already-authenticated line. Authentication is the caller's job."""
    if _PAUSE.match(first_line):
        return VerifiedCommand("PAUSE", "", actor, "")
    m = _COMMAND.match(first_line)
    if not m:
        return None
    arg = (m.group(3) or "").strip()
    return VerifiedCommand(m.group(1).upper(), m.group(2).upper(), actor, arg)
