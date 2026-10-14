"""Pipeline: poll -> normalize -> draft -> digest -> command -> hold -> send."""

from __future__ import annotations

from daikon.approvals import ApprovalManager, Kind
from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.commands import VerifiedCommand, authenticate_email, sender_address
from daikon.digest import build_digest
from daikon.drafts import content_hash
from daikon.gateway.base import Gateway
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.mail import InboundEmail, Mailbox
from daikon.notifier import Notifier
from daikon.people import PersonBook
from daikon.policy import DaiIdentity, OutboundPolicy
from daikon.sender import Sender
from daikon.senders import analyze_sender
from daikon.untrusted import Untrusted, normalize_email
from daikon.worker import Worker


class Pipeline:
    def __init__(self, *, mailbox: Mailbox, store: GraphStore, audit: AuditLog, clock: Clock,
                 gateway: Gateway, approvals: ApprovalManager, policy: OutboundPolicy,
                 identity: DaiIdentity, dai_email: str, people: PersonBook) -> None:
        self._mailbox, self._store, self._audit, self._clock = mailbox, store, audit, clock
        self._approvals, self._identity, self._people = approvals, identity, people
        self._worker = Worker(gateway, store, clock, audit)
        self._notifier = Notifier(mailbox, policy, dai_email)
        self._sender = Sender(mailbox, store, approvals, policy, people)

    def poll(self) -> None:
        for msg in self._mailbox.fetch_new():
            u = normalize_email(text=msg.text, html=msg.html, origin=msg.from_addr)
            if sender_address(msg) in self._identity.emails:
                self._handle_dai_message(msg, u)
            else:
                self._ingest(msg, u)

    def release_due(self) -> None:
        now = self._clock.now()
        for req in self._approvals.held_requests():
            if req.hold_until is not None and now >= req.hold_until:
                self._sender.send(req.id)

    # ---------- inbound mail from other people ----------
    def _ingest(self, msg: InboundEmail, u: Untrusted) -> None:
        if self._store.exists("message", f"message-{msg.id}"):
            self._audit.append("pipeline", "pipeline.duplicate", message_id=msg.id)
            return
        known = self._people.known_addresses() | set(self._identity.emails)
        info = analyze_sender(msg.from_addr, msg.reply_to, known)
        flags = u.flags | info.flags
        if not info.address:
            self._audit.append("pipeline", "pipeline.bad_from", message_id=msg.id)
            return
        self._people.ensure(info.address, info.display_name)
        self._store.write(Node(
            id=f"message-{msg.id}", type="message", status="received", created=self._clock.now(),
            body=u.text[:5000],
            extra={"gmail_id": msg.id, "thread_id": msg.thread_id, "from": msg.from_addr,
                   "subject": msg.subject[:200], "spf": msg.auth.spf,
                   "dkim": msg.auth.dkim, "dmarc": msg.auth.dmarc,
                   "flags": sorted(flags)},
        ))
        self._audit.append("pipeline", "pipeline.ingest", message_id=msg.id, flags=sorted(flags))
        draft = self._worker.draft_reply(msg, u, info.address)
        req, code = self._approvals.create(
            Kind.SEND, draft.id, str(draft.extra["content_hash"]), int(draft.extra["version"])
        )
        subject, body = build_digest(msg, u, draft, code, flags)
        self._notifier.send_to_dai(subject, body)
        self._audit.append("pipeline", "pipeline.digest_sent", request_id=req.id)

    # ---------- messages claiming to be from Dai ----------
    def _handle_dai_message(self, msg: InboundEmail, u: Untrusted) -> None:
        cmd = authenticate_email(msg, u, self._identity)
        if cmd is None:
            self._audit.append("pipeline", "pipeline.dai_message_ignored", message_id=msg.id,
                               authenticated=msg.auth.passed)
            return
        self._apply(cmd)

    def _apply(self, cmd: VerifiedCommand) -> None:
        if cmd.verb == "OK":
            result = self._approvals.approve(cmd.code, self._current_hash, actor=cmd.actor)
            if result.ok:
                hold = int(self._hold_seconds())
                self._notifier.send_to_dai(
                    f"Reply approved: sending in {hold}s",
                    f"Approved. It will send in {hold} seconds.\n"
                    f"UNDO {result.undo_code}  -> cancel",
                    kind="alert",
                )
        elif cmd.verb == "NO":
            self._approvals.reject(cmd.code, cmd.actor)
        elif cmd.verb == "EDIT":
            self._approvals.request_edit(cmd.code, cmd.actor)
        elif cmd.verb == "UNDO":
            self._approvals.undo(cmd.code, cmd.actor)

    def _current_hash(self, draft_id: str) -> str:
        draft = self._store.read("draft", draft_id)
        recipients = list(draft.extra["recipients"])
        return content_hash(recipients, str(draft.extra["subject"]), draft.body)

    @staticmethod
    def _hold_seconds() -> float:
        return 60
