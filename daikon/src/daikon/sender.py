"""Sender: sends exactly the approved draft, once, through the policy gate."""

from __future__ import annotations

from datetime import datetime, timedelta

from daikon.approvals import ApprovalManager
from daikon.drafts import content_hash
from daikon.graph.store import GraphStore
from daikon.mail import Mailbox, PermanentSendError
from daikon.people import PersonBook
from daikon.policy import Channel, OutboundAction, OutboundPolicy

CHECK_AFTER = timedelta(minutes=1)  # give the Sent folder time to show the message
GIVE_UP_AFTER = timedelta(minutes=10)


class Sender:
    def __init__(self, mailbox: Mailbox, store: GraphStore, approvals: ApprovalManager,
                 policy: OutboundPolicy, people: PersonBook) -> None:
        self._mailbox, self._store = mailbox, store
        self._approvals, self._policy, self._people = approvals, policy, people

    def send(self, request_id: str) -> bool:
        req = self._approvals.get(request_id)
        draft = self._store.read("draft", req.subject_id)
        recipients = list(draft.extra["recipients"])
        subject = str(draft.extra["subject"])
        current = content_hash(recipients, subject, draft.body)
        if not self._approvals.begin_send(request_id).ok:
            return False
        decision = self._policy.evaluate(OutboundAction(
            Channel.EMAIL, tuple(recipients), "reply", approval_request_id=request_id,
            subject_hash=current, sensitive=bool(draft.extra.get("sensitivity_flags")),
        ))
        if decision.verdict != "allow":
            self._approvals.mark_failed(request_id, decision.reason)
            return False
        try:
            self._mailbox.send(
                recipients, subject, draft.body, in_reply_to=draft.extra["in_reply_to"]
            )
        except PermanentSendError:
            self._approvals.mark_failed(request_id, "send_rejected")
            return False
        except Exception:  # noqa: BLE001 - ambiguous: it may have gone out; recover() decides
            return False
        self._approvals.mark_sent(request_id)
        for recipient in recipients:
            self._people.mark_contacted(recipient)
        draft.status = "sent"
        self._store.write(draft)
        return True

    def recover(self, request_id: str, now: datetime) -> str:
        """Resolve a request stuck in ``sending`` by looking in the Sent folder. Never resends.

        Returns ``sent``, ``pending`` (too early to tell) or ``failed`` (nothing found after
        ``GIVE_UP_AFTER``, so Dai is asked to handle it)."""
        req = self._approvals.get(request_id)
        if req.state != "sending" or req.sending_since is None:
            return req.state
        draft = self._store.read("draft", req.subject_id)
        recipients, subject = list(draft.extra["recipients"]), str(draft.extra["subject"])
        since = req.sending_since - timedelta(minutes=1)
        found = self._mailbox.find_sent(recipients, subject, since)
        if found:
            self._approvals.mark_sent(request_id)
            for recipient in recipients:
                self._people.mark_contacted(recipient)
            draft.status = "sent"
            self._store.write(draft)
            return "sent"
        if now - req.sending_since < GIVE_UP_AFTER:
            return "pending"
        self._approvals.mark_failed(request_id, "unconfirmed_send")
        return "failed"
