"""Command line: one-time setup and the live smoke test. The long-running service is added
when all parts exist (M6)."""

from __future__ import annotations

import argparse
import getpass
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from daikon.clock import SystemClock
from daikon.gmail.mailbox import GmailMailbox
from daikon.secretstore import SecretStore

KNOWN_SECRETS = ("anthropic_api_key",)  # the Gmail token is saved by `auth-gmail`
DEFAULT_CONFIG = Path.home() / "daikon-data" / "models.yaml"


@dataclass(frozen=True)
class SmokeReport:
    address: str
    can_read: bool
    sent_id: str


def smoke_test(service: Any, mailbox: GmailMailbox, dai_email: str) -> SmokeReport:
    """Prove the credentials work: read the profile, list one message, send one mail to Dai."""
    profile = service.users().getProfile(userId="me").execute()
    service.users().messages().list(userId="me", q="in:inbox", maxResults=1).execute()
    sent_id = mailbox.send(
        [dai_email],
        "Daikon smoke test",
        "If you can read this, Daikon can send mail. No action needed.",
    )
    return SmokeReport(str(profile["emailAddress"]), True, sent_id)


def set_secret(
    store: SecretStore, name: str, value: str, now: datetime, expires_in_days: int | None = None
) -> None:
    if name not in KNOWN_SECRETS:
        raise ValueError(f"unknown secret {name!r}; known: {', '.join(KNOWN_SECRETS)}")
    if not value.strip():
        raise ValueError("secret value is empty")
    expires = now + timedelta(days=expires_in_days) if expires_in_days else None
    store.set(name, value.strip(), expires_at=expires)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daikon")
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth-gmail", help="one-time Google sign-in for Daikon's account")
    auth.add_argument("--client-secrets", required=True, help="OAuth client JSON from Google Cloud")
    smoke = sub.add_parser("smoke", help="read one message and send one test mail to Dai")
    smoke.add_argument("--dai-email", required=True)
    run = sub.add_parser("run", help="run Daikon (Ctrl+C to stop)")
    run.add_argument("--config", default=str(DEFAULT_CONFIG))
    run.add_argument("--once", action="store_true", help="do a single cycle and exit")
    doc = sub.add_parser("doctor", help="check the setup without changing anything")
    doc.add_argument("--config", default=str(DEFAULT_CONFIG))
    sec = sub.add_parser("set-secret", help="store a secret in the OS credential store (prompted)")
    sec.add_argument("name")
    sec.add_argument("--expires-in-days", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from daikon.secretstore import KeyringSecretStore

    store = KeyringSecretStore()
    if args.command == "set-secret":
        set_secret(store, args.name, getpass.getpass(f"{args.name}: "), SystemClock().now(),
                   args.expires_in_days)
        print(f"Saved {args.name} in the OS credential store.")  # noqa: T201
        return 0
    if args.command in ("run", "doctor"):
        from daikon.app import build_app, doctor
        from daikon.config import load_config

        config = load_config(Path(args.config))
        if args.command == "doctor":
            report = doctor(config, store, SystemClock())
            print("\n".join(report.lines))  # noqa: T201
            return 0 if report.ok else 1
        app = build_app(config, store, SystemClock())
        if args.once:
            return 0 if app.runner.tick() else 1
        try:
            app.run(lambda: False)
        except KeyboardInterrupt:
            print("Stopped.")  # noqa: T201
        return 0
    from daikon.gmail.auth import authorize, build_service, credentials_from_store
    from daikon.graph.store import GraphStore

    if args.command == "auth-gmail":
        authorize(Path(args.client_secrets), store)
        print("Saved Google credentials in the OS credential store.")  # noqa: T201
        return 0
    service = build_service(credentials_from_store(store))
    address = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    mailbox = GmailMailbox(service, GraphStore(Path.home() / "daikon-data" / "graph"),
                           SystemClock(), address)
    report_ = smoke_test(service, mailbox, args.dai_email)
    print(f"OK: signed in as {report_.address}; read access works; test mail id {report_.sent_id}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
