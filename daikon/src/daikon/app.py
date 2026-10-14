"""Composition root: builds every part from the config and wires them together.

Everything external (mailbox, model gateway, Drive API) can be injected, which is how tests
and the first dry runs use fakes; by default the real Gmail, Anthropic and Drive clients are
built from secrets in the OS credential store. ``doctor`` checks a setup without changing it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from daikon.alerter import Alerter
from daikon.approvals import ApprovalManager
from daikon.audit import AuditLog, verify
from daikon.clock import Clock
from daikon.config import Config
from daikon.drive.scoped import DriveApi, GoogleDriveApi, ScopedDrive
from daikon.filters import RuleFilter
from daikon.gateway.base import Gateway
from daikon.graph.store import GraphStore, InstanceLock
from daikon.limiter import Limiter, default_rules
from daikon.mail import Mailbox
from daikon.messenger import DaiMessenger
from daikon.notifier import Notifier
from daikon.pause import PauseSwitch
from daikon.people import PersonBook
from daikon.pipeline import Pipeline
from daikon.policy import OutboundPolicy
from daikon.retrieval import Retriever
from daikon.runner import Runner
from daikon.secretstore import SecretNotFoundError, SecretStore
from daikon.style import load_style

REQUIRED_SECRETS = ("anthropic_api_key", "gmail_token")


@dataclass
class App:
    runner: Runner
    pipeline: Pipeline
    people: PersonBook
    lock: InstanceLock
    config: Config

    def run(self, stop: Callable[[], bool]) -> None:
        self.runner.run_forever(stop, lock=self.lock)


def build_app(
    config: Config,
    secrets: SecretStore,
    clock: Clock,
    *,
    mailbox: Mailbox | None = None,
    gateway: Gateway | None = None,
    drive_api: DriveApi | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> App:
    data = config.data_dir
    data.mkdir(parents=True, exist_ok=True)
    store = GraphStore(data / "graph")
    audit = AuditLog(data / "audit", clock)
    limiter = Limiter(data / "limits.json", clock, default_rules(config.limits))
    approvals = ApprovalManager(store, audit, clock)
    people = PersonBook(store, clock)
    policy = OutboundPolicy(
        data_dir=data, identity=config.identity, mode=config.outbound_mode, limiter=limiter,
        approvals=approvals, audit=audit, known_recipient=people.is_known,
    )
    creds: Any = None
    if mailbox is None or (drive_api is None and config.second_brain_root_id):
        from daikon.gmail.auth import credentials_from_store

        creds = credentials_from_store(secrets)
    if mailbox is None:
        from daikon.gmail.auth import build_service
        from daikon.gmail.mailbox import GmailMailbox

        service = build_service(creds)
        address = str(service.users().getProfile(userId="me").execute()["emailAddress"])
        mailbox = GmailMailbox(service, store, clock, address)
    if gateway is None:
        from daikon.gateway.anthropic_api import AnthropicGateway, make_client

        gateway = AnthropicGateway(
            make_client(secrets.get("anthropic_api_key")), config.roles, limiter, audit
        )
    retriever: Retriever | None = None
    if config.second_brain_root_id:
        if drive_api is None:
            from daikon.gmail.auth import build_drive_service

            drive_api = GoogleDriveApi(build_drive_service(creds))
        drive = ScopedDrive(drive_api, config.second_brain_root_id, clock, audit)
        retriever = Retriever(drive, config.identity.emails)
    alerter = Alerter(DaiMessenger(Notifier(mailbox, policy, config.dai_email)), limiter, audit)
    pipeline = Pipeline(
        mailbox=mailbox, store=store, audit=audit, clock=clock, gateway=gateway,
        approvals=approvals, policy=policy, identity=config.identity, dai_email=config.dai_email,
        people=people, rule_filter=RuleFilter(limiter, people, audit), alerter=alerter,
        style=load_style(config.style_file), retriever=retriever,
        pause=PauseSwitch(data, clock, audit, limiter),
    )
    runner = Runner(pipeline, store, clock, alerter, audit, sleep=sleep)
    return App(runner, pipeline, people, InstanceLock(data), config)


# ---------- doctor ----------
@dataclass
class DoctorReport:
    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def fail(self, line: str) -> None:
        self.ok = False
        self.lines.append(f"FAIL  {line}")

    def note(self, line: str) -> None:
        self.lines.append(f"      {line}")

    def warn(self, line: str) -> None:
        self.lines.append(f"WARN  {line}")


def doctor(config: Config, secrets: SecretStore, clock: Clock) -> DoctorReport:
    """Read-only health check of a setup. Never prints secret values."""
    r = DoctorReport()
    created = "" if config.data_dir.exists() else " (will be created)"
    r.note(f"data dir: {config.data_dir}{created}")
    r.note(f"outbound_mode: {config.outbound_mode}")
    if config.outbound_mode == "live":
        r.warn("outbound_mode is LIVE: approved replies are sent to other people")
    ident = config.identity
    r.note(f"Dai identities: {len(ident.emails)} email(s), {len(ident.phones)} phone(s)")
    for name in REQUIRED_SECRETS:
        try:
            secrets.get(name)
            r.note(f"secret present: {name}")
        except SecretNotFoundError:
            r.fail(f"missing secret: {name}")
    for name in secrets.expiring_within(timedelta(days=14), clock.now()):
        r.warn(f"secret expiring within 14 days: {name}")
    if (config.data_dir / "PAUSE").exists():
        r.warn("PAUSED: nothing is sent to other people until RESUME")
    result = verify(config.data_dir / "audit")
    if result.ok:
        r.note("audit chain: ok")
    else:
        r.fail(f"audit chain: BROKEN at seq {result.bad_seq} ({result.reason})")
    try:
        Limiter(config.data_dir / "limits.json", clock, default_rules(config.limits))
        r.note("limit counters: ok")
    except ValueError as exc:
        r.fail(str(exc))
    r.note("roles: " + ", ".join(sorted(config.roles)))
    return r
