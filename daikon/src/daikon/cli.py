"""Command line: one-time setup and the live smoke test. The long-running service is added
when all parts exist (M6)."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daikon.clock import SystemClock
from daikon.gmail.mailbox import GmailMailbox


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daikon")
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth-gmail", help="one-time Google sign-in for Daikon's Gmail account")
    auth.add_argument("--client-secrets", required=True, help="OAuth client JSON from Google Cloud")
    smoke = sub.add_parser("smoke", help="read one message and send one test mail to Dai")
    smoke.add_argument("--dai-email", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from daikon.gmail.auth import authorize, build_service, credentials_from_store
    from daikon.graph.store import GraphStore
    from daikon.secretstore import KeyringSecretStore

    store = KeyringSecretStore()
    if args.command == "auth-gmail":
        authorize(Path(args.client_secrets), store)
        print("Saved Gmail credentials in the OS credential store.")  # noqa: T201
        return 0
    service = build_service(credentials_from_store(store))
    address = str(service.users().getProfile(userId="me").execute()["emailAddress"])
    mailbox = GmailMailbox(service, GraphStore(Path.home() / "daikon-data" / "graph"),
                           SystemClock(), address)
    report = smoke_test(service, mailbox, args.dai_email)
    print(f"OK: signed in as {report.address}; read access works; test mail id {report.sent_id}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
