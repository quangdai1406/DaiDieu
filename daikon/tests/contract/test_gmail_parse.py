"""M2.1a: Gmail message resource -> InboundEmail. Attachments are counted, never fetched."""

from datetime import UTC, datetime

import pytest

from daikon.gmail.parse import parse_message
from tests.contract.gmail_fixtures import b64, header, multipart_message, simple_message

pytestmark = pytest.mark.unit


def test_multipart_message_fields() -> None:
    m = parse_message(multipart_message())
    assert m.id == "18f0a1b2c3d4e5f6" and m.thread_id == "18f0a1b2c3d4e5f6"
    assert m.from_addr == "Bob Smith <bob@example.org>" and m.subject == "Lunch?"
    assert m.to == ("daikon@example.com",)
    assert m.text == "Can we move lunch to 12:30?" and m.html == "<p>Can we move lunch to 12:30?</p>"
    assert m.received == datetime.fromtimestamp(1760432400, tz=UTC)
    assert m.auth.passed and m.attachment_count == 0


def test_single_part_message() -> None:
    m = parse_message(simple_message(text="Just text"))
    assert m.text == "Just text" and m.html is None


def test_attachments_are_counted_and_content_is_never_requested() -> None:
    m = parse_message(multipart_message(attachments=2))
    assert m.attachment_count == 2
    assert "ATT0" not in repr(m)


def test_auth_comes_from_the_gmail_header_only() -> None:
    forged = header("Authentication-Results", "evil.example; spf=pass dkim=pass dmarc=pass")
    msg = multipart_message()
    hdrs = msg["payload"]["headers"]
    hdrs[0] = header("Authentication-Results", "mx.google.com; spf=fail; dkim=fail; dmarc=fail")
    hdrs.append(forged)
    assert not parse_message(msg).auth.passed


def test_reply_to_and_automation_headers_are_kept() -> None:
    msg = multipart_message(extra_headers=[
        header("Reply-To", "steal@elsewhere.test"), header("List-Unsubscribe", "<mailto:u@x.org>"),
        header("Precedence", "bulk"),
    ])
    m = parse_message(msg)
    assert m.reply_to == "steal@elsewhere.test"
    names = {n.lower() for n, _ in m.headers}
    assert {"list-unsubscribe", "precedence"} <= names


def test_encoded_subject_is_decoded() -> None:
    msg = multipart_message(subject="=?UTF-8?B?VGnhur9uZyBWaeG7h3Q=?=")
    assert parse_message(msg).subject == "Tiếng Việt"


def test_non_utf8_charset_is_decoded() -> None:
    msg = multipart_message(text=None, html=None)
    msg["payload"]["parts"] = [{
        "mimeType": "text/plain", "filename": "",
        "headers": [header("Content-Type", "text/plain; charset=iso-8859-1")],
        "body": {"data": b64("caf\xe9", "iso-8859-1")},
    }]
    assert parse_message(msg).text == "café"


def test_unknown_charset_and_bad_bytes_do_not_crash() -> None:
    msg = multipart_message(text=None, html=None)
    msg["payload"]["parts"] = [{
        "mimeType": "text/plain", "filename": "",
        "headers": [header("Content-Type", "text/plain; charset=made-up")],
        "body": {"data": "_-8"},
    }]
    assert isinstance(parse_message(msg).text, str)


def test_nested_multipart_prefers_first_text_and_html_parts() -> None:
    msg = multipart_message(text=None, html=None)
    inner = multipart_message("x", text="inner text", html="<b>inner</b>")["payload"]
    msg["payload"]["parts"] = [inner]
    m = parse_message(msg)
    assert m.text == "inner text" and m.html == "<b>inner</b>"


def test_oversize_body_is_truncated_before_decoding() -> None:
    msg = multipart_message(text="x" * 3_000_000, html=None)
    m = parse_message(msg)
    assert m.text is not None and len(m.text) <= 2_000_000


def test_missing_headers_fall_back_safely() -> None:
    msg = multipart_message()
    msg["payload"]["headers"] = []
    m = parse_message(msg)
    assert m.from_addr == "" and m.subject == "" and m.to == () and not m.auth.passed
