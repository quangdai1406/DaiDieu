"""GmailMailbox: the real Mailbox over the Gmail API.

Polling uses the history API with a persisted marker, so the account needs only read and
send scopes (no labelling). The marker advances only after every new message was fetched,
so a failure re-delivers (the pipeline de-duplicates by message id). Attachments are never
requested. Outgoing mail is built with Python's email package; recipients are validated and
the subject is stripped of line breaks (no header injection).
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from googleapiclient.errors import HttpError

from daikon.clock import Clock
from daikon.gmail.parse import parse_message
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.mail import InboundEmail

STATE_TYPE, STATE_ID = "state", "gmail-history"
_RECIPIENT = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
_SKIP_LABELS = frozenset({"SENT", "DRAFT"})


def _status(exc: HttpError) -> int:
    return int(exc.resp.status)


class GmailMailbox:
    def __init__(self, service: Any, store: GraphStore, clock: Clock, address: str) -> None:
        self._svc, self._store, self._clock, self._address = service, store, clock, address.lower()

    # ---------- state ----------
    def _history_id(self) -> str | None:
        if not self._store.exists(STATE_TYPE, STATE_ID):
            return None
        return str(self._store.read(STATE_TYPE, STATE_ID).extra["history_id"])

    def _save_history_id(self, value: str) -> None:
        self._store.write(Node(id=STATE_ID, type=STATE_TYPE, status="ok",
                               created=self._clock.now(), extra={"history_id": value}))

    # ---------- receiving ----------
    def fetch_new(self) -> list[InboundEmail]:
        start = self._history_id()
        if start is None:
            self._save_history_id(self._profile_history_id())
            return []
        try:
            ids, latest = self._ids_from_history(start)
        except HttpError as exc:
            if _status(exc) != 404:
                raise
            latest = self._profile_history_id()
            ids = self._recent_ids()
        messages = [m for i in ids if (m := self._get(i)) is not None]
        self._save_history_id(latest)
        return messages

    def _profile_history_id(self) -> str:
        return str(self._svc.users().getProfile(userId="me").execute()["historyId"])

    def _ids_from_history(self, start: str) -> tuple[list[str], str]:
        ids: list[str] = []
        latest, token = start, None
        while True:
            resp = self._svc.users().history().list(
                userId="me", startHistoryId=start, historyTypes=["messageAdded"],
                labelId="INBOX", pageToken=token,
            ).execute()
            for record in resp.get("history", []):
                for added in record.get("messagesAdded", []):
                    msg = added["message"]
                    if not _SKIP_LABELS & set(msg.get("labelIds", [])) and msg["id"] not in ids:
                        ids.append(msg["id"])
            latest = str(resp.get("historyId", latest))
            token = resp.get("nextPageToken")
            if not token:
                return ids, latest

    def _recent_ids(self) -> list[str]:
        resp = self._svc.users().messages().list(userId="me", q="in:inbox newer_than:2d").execute()
        return [m["id"] for m in resp.get("messages", [])]

    def _get(self, message_id: str) -> InboundEmail | None:
        try:
            resource = self._svc.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        except HttpError as exc:
            if _status(exc) == 404:
                return None
            raise
        msg = parse_message(resource)
        if parseaddr(msg.from_addr)[1].lower() == self._address:
            return None
        return msg

    # ---------- sending ----------
    def send(
        self, to: list[str], subject: str, body: str, in_reply_to: str | None = None
    ) -> str:
        for recipient in to:
            if not _RECIPIENT.match(recipient):
                raise ValueError(f"invalid recipient: {recipient!r}")
        msg = EmailMessage()
        msg["To"] = ", ".join(to)
        msg["From"] = self._address
        msg["Subject"] = re.sub(r"[\r\n]+", " ", subject)[:300]
        msg.set_content(body)
        payload: dict[str, Any] = {}
        if in_reply_to:
            orig = self._svc.users().messages().get(
                userId="me", id=in_reply_to, format="metadata",
                metadataHeaders=["Message-ID", "References"],
            ).execute()
            headers = {h["name"].lower(): h["value"] for h in orig["payload"]["headers"]}
            message_id = headers.get("message-id", "")
            if message_id:
                msg["In-Reply-To"] = message_id
                msg["References"] = f"{headers.get('references', '')} {message_id}".strip()
            payload["threadId"] = orig.get("threadId", in_reply_to)
        payload["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        result = self._svc.users().messages().send(userId="me", body=payload).execute()
        return str(result["id"])
