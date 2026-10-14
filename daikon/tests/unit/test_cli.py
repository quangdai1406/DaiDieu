"""M2.5: smoke test logic and CLI wiring (the real run is manual, see docs/runbook)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from daikon.cli import build_parser, smoke_test
from daikon.clock import FakeClock
from daikon.gmail.mailbox import GmailMailbox
from daikon.graph.store import GraphStore
from tests.contract.fake_gmail import FakeGmail
from tests.contract.gmail_fixtures import multipart_message

pytestmark = pytest.mark.unit


def test_smoke_test_reads_one_message_and_sends_one_to_dai(tmp_path: Path) -> None:
    g = FakeGmail()
    g.resources["m1"] = multipart_message("m1")
    g.listed_ids = ["m1"]
    box = GmailMailbox(g, GraphStore(tmp_path), FakeClock(datetime(2026, 10, 14, tzinfo=UTC)), g.address)
    report = smoke_test(g, box, "dai@example.com")
    assert report.address == "daikon@example.com" and report.can_read and report.sent_id == "sent1"
    assert len(g.sent) == 1 and "threadId" not in g.sent[0]


def test_smoke_test_reports_an_empty_inbox_as_readable(tmp_path: Path) -> None:
    g = FakeGmail()
    box = GmailMailbox(g, GraphStore(tmp_path), FakeClock(datetime(2026, 10, 14, tzinfo=UTC)), g.address)
    assert smoke_test(g, box, "dai@example.com").can_read


def test_parser_has_auth_and_smoke_commands() -> None:
    p = build_parser()
    a = p.parse_args(["auth-gmail", "--client-secrets", "client.json"])
    assert a.command == "auth-gmail" and a.client_secrets == "client.json"
    s = p.parse_args(["smoke", "--dai-email", "dai@example.com"])
    assert s.command == "smoke" and s.dai_email == "dai@example.com"


def test_unknown_command_exits_with_error() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["wipe-everything"])
