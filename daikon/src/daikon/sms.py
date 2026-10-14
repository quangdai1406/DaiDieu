"""SMS channel (Twilio). Inbound: only Dai's own number, sent to our number, fresh, once.
Outbound: only to Dai, through the policy gate. Message bodies are never stored.

An SMS "From" can be spoofed in rare cases, so a command still needs a valid one-time approval
code that was only ever sent to Dai; PAUSE is the only code-free command and it is safe-direction.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.commands import VerifiedCommand, parse_command
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.identity import DaiIdentity
from daikon.policy import Channel, OutboundAction

MAX_AGE = timedelta(hours=2)
MAX_SMS_CHARS = 320


@dataclass(frozen=True)
class InboundSms:
    id: str
    from_number: str
    to_number: str
    body: str
    sent: datetime


class SmsTransport(Protocol):
    def list_inbound(self) -> list[InboundSms]: ...

    def send(self, to: str, body: str) -> str: ...


class _Policy(Protocol):
    def evaluate(self, action: OutboundAction) -> Any: ...


class SmsInbox:
    def __init__(self, transport: SmsTransport, store: GraphStore, identity: DaiIdentity,
                 our_number: str, clock: Clock, audit: AuditLog) -> None:
        self._t, self._store, self._identity = transport, store, identity
        self._ours, self._clock, self._audit = our_number, clock, audit

    def fetch_commands(self) -> list[VerifiedCommand]:
        try:
            messages = self._t.list_inbound()
        except Exception as exc:  # noqa: BLE001 - a network blip must not stop the mail loop
            self._audit.append("sms", "sms.poll_failed", error=type(exc).__name__)
            return []
        commands = []
        for m in sorted(messages, key=lambda x: (x.sent, x.id)):
            node_id = "sms-" + re.sub(r"[^a-z0-9]", "", m.id.lower())
            if self._store.exists("sms", node_id):
                continue
            self._store.write(
                Node(id=node_id, type="sms", status="seen", created=self._clock.now()))
            cmd = self._authenticate(m)
            if cmd is None:
                self._audit.append("sms", "sms.ignored", sms_id=m.id)
            else:
                commands.append(cmd)
        return commands

    def _authenticate(self, m: InboundSms) -> VerifiedCommand | None:
        if m.from_number not in self._identity.phones or m.to_number != self._ours:
            return None
        if self._clock.now() - m.sent > MAX_AGE:
            return None
        first = next((ln.strip() for ln in m.body.splitlines() if ln.strip()), "")
        cmd = parse_command(first, m.from_number)
        return replace(cmd, channel="sms") if cmd is not None else None


class DaiSms:
    """The Alerter's ``SmsSender``: texts Dai's number through the policy gate."""

    def __init__(self, transport: SmsTransport, policy: _Policy, phone: str) -> None:
        self._t, self._policy, self._phone = transport, policy, phone

    def send(self, body: str) -> bool:
        decision = self._policy.evaluate(OutboundAction(Channel.SMS, (self._phone,), "alert"))
        if decision.verdict != "allow":
            return False
        try:
            self._t.send(self._phone, body[:MAX_SMS_CHARS])
        except Exception:  # noqa: BLE001
            return False
        return True


Http = Callable[[str, str, tuple[str, str], "dict[str, str] | None"], dict[str, Any]]


def _urllib_http(method: str, url: str, auth: tuple[str, str],
                 data: dict[str, str] | None) -> dict[str, Any]:
    if not url.startswith("https://api.twilio.com/"):
        raise ValueError("refusing to call a non-Twilio URL")
    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method,  # noqa: S310 - https checked above
                                 headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        parsed: dict[str, Any] = json.loads(resp.read())
    return parsed


class TwilioTransport:
    """Twilio REST with a scoped API key (not the master auth token)."""

    def __init__(self, account_sid: str, key_sid: str, key_secret: str, number: str,
                 http: Http = _urllib_http) -> None:
        self._account, self._auth, self._number, self._http = (
            account_sid, (key_sid, key_secret), number, http)

    def _url(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self._account}/Messages.json"

    def list_inbound(self) -> list[InboundSms]:
        query = urllib.parse.urlencode({"To": self._number, "PageSize": "50"})
        data = self._http("GET", f"{self._url()}?{query}", self._auth, None)
        out = []
        for raw in data.get("messages", []):
            if raw.get("direction") != "inbound" or raw.get("to") != self._number:
                continue
            out.append(InboundSms(str(raw["sid"]), str(raw.get("from") or ""), str(raw["to"]),
                                  str(raw.get("body") or ""),
                                  parsedate_to_datetime(str(raw["date_sent"]))))
        return out

    def send(self, to: str, body: str) -> str:
        data = self._http("POST", self._url(), self._auth,
                          {"To": to, "From": self._number, "Body": body})
        return str(data["sid"])
