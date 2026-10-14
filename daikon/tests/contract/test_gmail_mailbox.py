"""M2.1b: GmailMailbox over the (stubbed) Gmail client."""

import base64
import email
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

import pytest

from daikon.clock import FakeClock
from daikon.gmail.mailbox import GmailMailbox
from daikon.graph.store import GraphStore
from tests.contract.fake_gmail import FakeGmail
from tests.contract.gmail_fixtures import multipart_message

pytestmark = pytest.mark.unit


def setup(tmp_path: Path) -> tuple[GmailMailbox, FakeGmail, GraphStore]:
    g = FakeGmail()
    store = GraphStore(tmp_path)
    return GmailMailbox(g, store, FakeClock(datetime(2026, 10, 14, tzinfo=UTC)), g.address), g, store


def add(g: FakeGmail, id_: str, **kw: object) -> str:
    g.resources[id_] = multipart_message(id_, **kw)  # type: ignore[arg-type]
    return id_


def test_first_run_only_sets_a_baseline(tmp_path: Path) -> None:
    box, g, store = setup(tmp_path)
    add(g, "old1")
    g.listed_ids = ["old1"]
    assert box.fetch_new() == []
    assert store.read("state", "gmail-history").extra["history_id"] == "100"
    assert "history.list" not in g.calls and "messages.list" not in g.calls


def test_new_mail_arrives_through_history_across_pages(tmp_path: Path) -> None:
    box, g, store = setup(tmp_path)
    box.fetch_new()
    add(g, "a1"), add(g, "a2"), add(g, "a3")
    g.history_pages = [{"added": ["a1", "a2"], "historyId": "150"},
                       {"added": ["a2", "a3"], "historyId": "160"}]
    got = box.fetch_new()
    assert [m.id for m in got] == ["a1", "a2", "a3"]
    assert store.read("state", "gmail-history").extra["history_id"] == "160"


def test_sent_drafts_and_own_mail_are_skipped(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    box.fetch_new()
    add(g, "s1", label_ids=["SENT"])
    add(g, "d1", label_ids=["DRAFT"])
    add(g, "me", frm="Daikon <daikon@example.com>")
    add(g, "ok")
    g.history_pages = [{"added": ["s1", "d1", "me", "ok"]}]
    assert [m.id for m in box.fetch_new()] == ["ok"]


def test_a_failure_midway_does_not_advance_the_history_marker(tmp_path: Path) -> None:
    box, g, store = setup(tmp_path)
    box.fetch_new()
    add(g, "a1"), add(g, "a2")
    g.history_pages = [{"added": ["a1", "a2"], "historyId": "150"}]
    g.get_errors["a2"] = 500
    with pytest.raises(Exception, match="500|HttpError"):
        box.fetch_new()
    assert store.read("state", "gmail-history").extra["history_id"] == "100"
    del g.get_errors["a2"]
    assert [m.id for m in box.fetch_new()] == ["a1", "a2"]


def test_deleted_messages_are_skipped(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    box.fetch_new()
    add(g, "gone"), add(g, "here")
    g.history_pages = [{"added": ["gone", "here"]}]
    g.get_errors["gone"] = 404
    assert [m.id for m in box.fetch_new()] == ["here"]


def test_expired_history_falls_back_to_a_recent_listing(tmp_path: Path) -> None:
    box, g, store = setup(tmp_path)
    box.fetch_new()
    add(g, "r1")
    g.history_error, g.listed_ids, g.history_id = 404, ["r1"], 500
    assert [m.id for m in box.fetch_new()] == ["r1"]
    assert store.read("state", "gmail-history").extra["history_id"] == "500"


def test_attachments_are_never_requested(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    box.fetch_new()
    add(g, "att", attachments=2)
    g.history_pages = [{"added": ["att"]}]
    (m,) = box.fetch_new()
    assert m.attachment_count == 2
    assert not any("attachment" in c for c in g.calls)


def test_marker_survives_a_new_mailbox_instance(tmp_path: Path) -> None:
    box, g, store = setup(tmp_path)
    box.fetch_new()
    again = GmailMailbox(g, store, FakeClock(datetime(2026, 10, 14, tzinfo=UTC)), g.address)
    add(g, "n1")
    g.history_pages = [{"added": ["n1"]}]
    assert [m.id for m in again.fetch_new()] == ["n1"]


def _sent_message(g: FakeGmail) -> tuple[Message, dict[str, object]]:
    body = g.sent[-1]
    raw = base64.urlsafe_b64decode(str(body["raw"]) + "==")
    return email.message_from_bytes(raw), body


def test_send_builds_a_threaded_reply(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    add(g, "orig", subject="Lunch?")
    sent_id = box.send(["bob@example.org"], "Re: Lunch?", "12:30 works. Cảm ơn!", in_reply_to="orig")
    msg, body = _sent_message(g)
    assert sent_id == "sent1" and body["threadId"] == "orig"
    assert msg["To"] == "bob@example.org" and msg["From"] == "daikon@example.com"
    assert msg["In-Reply-To"] == "<orig@mail.example.org>"
    assert "<orig@mail.example.org>" in msg["References"]
    assert msg.get_payload(decode=True).decode("utf-8").strip() == "12:30 works. Cảm ơn!"


def test_send_without_reply_context_has_no_thread(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    box.send(["dai@example.com"], "Digest", "body")
    msg, body = _sent_message(g)
    assert "threadId" not in body and msg["In-Reply-To"] is None


def test_subject_newlines_are_neutralized(tmp_path: Path) -> None:
    box, g, _ = setup(tmp_path)
    box.send(["dai@example.com"], "Hi\r\nBcc: evil@x.test", "body")
    msg, _ = _sent_message(g)
    assert msg["Bcc"] is None and "\n" not in str(msg["Subject"])


@pytest.mark.parametrize("bad", ["a@x.org\nbcc: e@x.org", "a@x.org, b@x.org", "no-at-sign", ""])
def test_bad_recipients_are_refused(tmp_path: Path, bad: str) -> None:
    box, g, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="recipient"):
        box.send([bad], "s", "b")
    assert g.sent == []
