"""Pipeline: receive -> store -> draft -> digest -> command -> hold -> send.

Reliability rule: every fetched message is written to the graph (status ``received``) before
any model call, and is only marked done after a draft (or an explicit decision) exists. A
temporary model failure therefore loses nothing: the stored message is retried on the next
poll, oldest first, in small batches. Duplicate deliveries are ignored by message id.
"""

from __future__ import annotations

from datetime import timedelta

from daikon.alerter import Alerter, Severity
from daikon.approvals import ApprovalManager, Kind
from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.commands import VerifiedCommand, authenticate_email, sender_address
from daikon.digest import build_attention, build_digest
from daikon.drafts import content_hash
from daikon.filters import Action, RuleFilter
from daikon.gateway.anthropic_api import GatewayCapError, GatewayError
from daikon.gateway.base import Gateway
from daikon.graph.node import Node
from daikon.graph.store import GraphStore
from daikon.identity import DaiIdentity
from daikon.limiter import Limiter
from daikon.mail import AuthResults, InboundEmail, Mailbox
from daikon.notifier import Notifier
from daikon.pause import PauseSwitch
from daikon.people import PersonBook
from daikon.policy import OutboundPolicy
from daikon.retrieval import Retriever
from daikon.sender import CHECK_AFTER, Sender
from daikon.senders import analyze_sender
from daikon.style import DEFAULT_STYLE
from daikon.untrusted import Source, Untrusted, normalize_email, normalize_text
from daikon.worker import DraftFailed, Worker

MAX_EDITS = 5
REMINDER_AFTER = timedelta(hours=24)


class Pipeline:
    def __init__(self, *, mailbox: Mailbox, store: GraphStore, audit: AuditLog, clock: Clock,
                 gateway: Gateway, approvals: ApprovalManager, policy: OutboundPolicy,
                 identity: DaiIdentity, dai_email: str, people: PersonBook,
                 rule_filter: RuleFilter, alerter: Alerter | None = None,
                 batch_size: int = 5, style: str = DEFAULT_STYLE,
                 retriever: Retriever | None = None,
                 pause: PauseSwitch | None = None, limiter: Limiter | None = None) -> None:
        self._mailbox, self._store, self._audit, self._clock = mailbox, store, audit, clock
        self._approvals, self._identity, self._people = approvals, identity, people
        self._filter, self._alerter, self._batch = rule_filter, alerter, batch_size
        self._pause, self._limiter = pause, limiter
        self._worker = Worker(gateway, store, clock, audit, style, retriever)
        self._notifier = Notifier(mailbox, policy, dai_email)
        self._sender = Sender(mailbox, store, approvals, policy, people)

    # ---------- one poll ----------
    def poll(self) -> None:
        for msg in self._mailbox.fetch_new():
            u = normalize_email(text=msg.text, html=msg.html, origin=msg.from_addr)
            if sender_address(msg) in self._identity.emails:
                self._handle_dai_message(msg, u)
            else:
                self._receive(msg, u)
        self._process_pending()

    def housekeeping(self) -> None:
        self._remind()
        for request_id in self._approvals.expire_due():
            self._audit.append("pipeline", "pipeline.expired", request_id=request_id)
            self._tell(request_id, "Daikon: expired without an answer: {subject}",
                       "This reply to {to} expired and nothing was sent. If it still matters, "
                       "tell me and I will draft it again.")
        self._recover_sending()

    def _remind(self) -> None:
        for req in self._approvals.due_for_reminder(REMINDER_AFTER):
            if self._tell(req.id, "Daikon: reminder, still waiting for you: {subject}",
                          "A reply to {to} is waiting for your answer. Reply OK, EDIT or NO "
                          "using the code in my earlier message."):
                self._approvals.mark_reminded(req.id)

    def _tell(self, request_id: str, subject: str, body: str) -> bool:
        req = self._approvals.get(request_id)
        if req.kind is not Kind.SEND:
            return False
        draft = self._store.read("draft", req.subject_id)
        fields = {"subject": str(draft.extra["subject"])[:80],
                  "to": ", ".join(draft.extra["recipients"])}
        return self._notifier.send_to_dai(subject.format(**fields), body.format(**fields),
                                          kind="reminder")

    def _recover_sending(self) -> None:
        now = self._clock.now()
        for req in self._approvals.sending_requests():
            if req.sending_since is None or now - req.sending_since < CHECK_AFTER:
                continue
            outcome = self._sender.recover(req.id, now)
            self._audit.append("pipeline", "pipeline.send_recovery", request_id=req.id,
                               outcome=outcome)
            if outcome == "failed":
                draft = self._store.read("draft", req.subject_id)
                self._notifier.send_to_dai(
                    "Daikon: couldn't confirm a reply was sent",
                    f"I could not confirm that the reply to {', '.join(draft.extra['recipients'])} "
                    f"({draft.extra['subject']}) was sent, and it is not in the Sent folder. "
                    "Nothing was resent. Please check Gmail and reply yourself if needed.",
                    kind="alert",
                )

    def release_due(self) -> None:
        if self._pause is not None and self._pause.is_paused():
            return  # approved drafts wait; stale ones expire in housekeeping
        now = self._clock.now()
        for req in self._approvals.held_requests():
            if req.hold_until is not None and now >= req.hold_until:
                self._sender.send(req.id)

    # ---------- store phase (no model calls) ----------
    def _receive(self, msg: InboundEmail, u: Untrusted) -> None:
        if self._store.exists("message", f"message-{msg.id}"):
            self._audit.append("pipeline", "pipeline.duplicate", message_id=msg.id)
            return
        known = self._people.known_addresses() | set(self._identity.emails)
        info = analyze_sender(msg.from_addr, msg.reply_to, known)
        flags = u.flags | info.flags
        if msg.attachment_count:
            flags = flags | {"has_attachments"}
        if not info.address:
            self._audit.append("pipeline", "pipeline.bad_from", message_id=msg.id)
            return
        self._people.ensure(info.address, info.display_name)
        verdict = self._filter.evaluate(msg, info.address)
        if verdict.action is not Action.PROCESS:
            self._skip(msg, verdict.action.value, verdict.reason, flags)
            return
        self._store.write(Node(
            id=f"message-{msg.id}", type="message", status="received", created=self._clock.now(),
            body=u.text,
            extra={"gmail_id": msg.id, "thread_id": msg.thread_id, "from": msg.from_addr,
                   "recipient": info.address, "subject": msg.subject[:200], "spf": msg.auth.spf,
                   "dkim": msg.auth.dkim, "dmarc": msg.auth.dmarc, "flags": sorted(flags)},
        ))
        self._audit.append("pipeline", "pipeline.ingest", message_id=msg.id, flags=sorted(flags))

    def _skip(self, msg: InboundEmail, action: str, reason: str, flags: frozenset[str]) -> None:
        self._store.write(Node(
            id=f"message-{msg.id}", type="message", status="skipped", created=self._clock.now(),
            extra={"gmail_id": msg.id, "from": msg.from_addr, "subject": msg.subject[:200],
                   "skip_action": action, "skip_reason": reason, "flags": sorted(flags)},
        ))
        if reason == "daily_model_cap" and self._alerter is not None:
            self._alerter.alert(Severity.WARNING, "model_cap",
                                "Daily model-run cap reached: new mail is not being drafted.")

    # ---------- model phase (oldest first, bounded, restartable) ----------
    def _process_pending(self) -> None:
        problem: GatewayError | None = None
        for run in (self._process_edits, self._process_messages):
            try:
                run()
            except GatewayError as exc:  # temporary: leave work pending, retry next poll
                problem = problem or exc
        if problem is not None:
            raise problem

    def _process_messages(self) -> None:
        pending = sorted(self._store.find(type="message", status={"received"}),
                         key=lambda n: (n.created, n.id))
        problem: GatewayError | None = None
        for node in pending[: self._batch]:
            try:
                self._draft_and_notify(node)
            except GatewayCapError as exc:
                self._mark(node, "skipped", skip_reason=exc.args[0])
                if self._alerter is not None:
                    self._alerter.alert(Severity.WARNING, "spend_cap",
                                        f"Model spending cap reached ({exc.args[0]}).")
            except GatewayError as exc:  # temporary: leave "received", retry next poll
                problem = problem or exc
                break
        if problem is not None:
            raise problem

    def _mark(self, node: Node, status: str, **extra: object) -> None:
        node.status = status
        node.extra.update(extra)
        self._store.write(node)

    @staticmethod
    def _load_message(node: Node) -> tuple[InboundEmail, Untrusted, frozenset[str]]:
        x = node.extra
        flags = frozenset(x["flags"])
        msg = InboundEmail(
            id=x["gmail_id"], thread_id=x["thread_id"], from_addr=x["from"], to=(),
            subject=x["subject"], text=node.body, html=None,
            auth=AuthResults(x["spf"], x["dkim"], x["dmarc"]), received=node.created,
        )
        u = Untrusted(text=node.body, source=Source.EMAIL, origin=x["from"], flags=flags,
                      original_length=len(node.body))
        return msg, u, flags

    # ---------- revisions asked for by Dai ----------
    def _process_edits(self) -> None:
        tasks = [t for t in self._store.find(type="task", status={"pending"})
                 if t.extra.get("kind") == "edit"]
        for task in sorted(tasks, key=lambda n: (n.created, n.id))[: self._batch]:
            try:
                self._revise(task)
            except GatewayCapError as exc:
                self._mark(task, "skipped", skip_reason=exc.args[0])
                if self._alerter is not None:
                    self._alerter.alert(Severity.WARNING, "spend_cap",
                                        f"Model spending cap reached ({exc.args[0]}).")

    def _revise(self, task: Node) -> None:
        draft = self._store.read("draft", str(task.extra["draft_id"]))
        original = self._store.read("message", draft.links["replies_to"][0])
        msg, u, flags = self._load_message(original)
        instruction = str(task.extra["instruction"])
        try:
            new = self._worker.redraft(draft, original, instruction)
        except DraftFailed as exc:
            subject, body = build_attention(msg, flags, exc.reason, "revise the draft")
            self._notifier.send_to_dai(subject, body, kind="alert")
            self._mark(task, "failed", reason=exc.reason)
            return
        version = int(new.extra["version"])
        _, code = self._approvals.create(Kind.SEND, new.id, str(new.extra["content_hash"]), version)
        subject, body = build_digest(msg, u, new, code, flags, revision=(version, instruction))
        self._notifier.send_to_dai(subject, body)
        self._mark(task, "done")

    def _queue_edit(self, request_id: str, instruction: str) -> None:
        draft = self._store.read("draft", self._approvals.get(request_id).subject_id)
        if int(draft.extra.get("edits", 0)) >= MAX_EDITS:
            self._notifier.send_to_dai(
                "Daikon: edit limit reached",
                f"Edit limit reached ({MAX_EDITS} revisions). This draft cannot be edited "
                "further: reply to the sender yourself, or ignore it.",
                kind="alert",
            )
            return
        version = int(draft.extra["version"]) + 1
        clean = normalize_text(instruction, source=Source.SMS, origin="dai", max_chars=500).text
        self._store.write(Node(
            id=f"task-edit-{draft.id}-v{version}", type="task", status="pending",
            created=self._clock.now(),
            extra={"kind": "edit", "draft_id": draft.id, "instruction": clean,
                   "from_request": request_id},
        ))
        self._audit.append("pipeline", "pipeline.edit_queued", draft_id=draft.id, version=version)

    def _draft_and_notify(self, node: Node) -> None:
        x = node.extra
        msg, u, flags = self._load_message(node)
        try:
            draft = self._worker.draft_reply(msg.id, msg.subject, u, x["recipient"])
        except DraftFailed as exc:
            subject, body = build_attention(msg, flags, exc.reason)
            self._notifier.send_to_dai(subject, body, kind="alert")
            self._mark(node, "attention", reason=exc.reason)
            return
        req, code = self._approvals.create(
            Kind.SEND, draft.id, str(draft.extra["content_hash"]), int(draft.extra["version"])
        )
        subject, body = build_digest(msg, u, draft, code, flags)
        self._notifier.send_to_dai(subject, body)
        self._mark(node, "drafted")
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
            if self._limiter is not None and not self._limiter.peek("approvals").allowed:
                self._notifier.send_to_dai(
                    "Daikon: daily approval limit reached",
                    "You reached today's approval limit, so nothing more was approved. "
                    "Your drafts are kept; try again after midnight UTC.",
                    kind="alert",
                )
                return
            result = self._approvals.approve(cmd.code, self._current_hash, actor=cmd.actor)
            if result.ok:
                if self._limiter is not None:
                    self._limiter.check_and_consume("approvals")
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
            if not cmd.arg:
                self._notifier.send_to_dai(
                    "Daikon: EDIT needs instructions",
                    "Reply like this:  EDIT <code> <what to change>",
                    kind="alert",
                )
                return
            result = self._approvals.request_edit(cmd.code, cmd.actor)
            if result.ok and result.request_id:
                self._queue_edit(result.request_id, cmd.arg)
        elif cmd.verb == "UNDO":
            self._approvals.undo(cmd.code, cmd.actor)
        elif cmd.verb == "PAUSE":
            self._pause_now(cmd)
        elif cmd.verb == "RESUME":
            if self._pause is not None and self._pause.resume(cmd.code, cmd.actor):
                self._notifier.send_to_dai(
                    "Daikon resumed", "Resumed. Approved replies will be sent.", kind="alert"
                )

    def _pause_now(self, cmd: VerifiedCommand) -> None:
        if self._pause is None:
            return
        code = self._pause.pause(cmd.actor)
        body = (
            "Paused: nothing will be sent to anyone but you until you resume.\n"
            f"RESUME {code}  -> resume" if code
            else "Already paused. Reply RESUME <code> with the code from the first pause notice."
        )
        self._notifier.send_to_dai("Daikon paused", body, kind="alert")

    def _current_hash(self, draft_id: str) -> str:
        draft = self._store.read("draft", draft_id)
        recipients = list(draft.extra["recipients"])
        return content_hash(recipients, str(draft.extra["subject"]), draft.body)

    @staticmethod
    def _hold_seconds() -> float:
        return 60
