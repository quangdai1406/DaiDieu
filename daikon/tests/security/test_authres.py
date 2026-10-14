"""M2.2: parse the receiving server's Authentication-Results, never the sender's claims."""

import pytest

from daikon.authres import parse_authentication_results
from daikon.mail import AuthResults

pytestmark = [pytest.mark.unit, pytest.mark.security]

GMAIL_PASS = (
    "mx.google.com;\r\n"
    "       dkim=pass header.i=@example.com header.s=sel header.b=abc123;\r\n"
    "       spf=pass (google.com: domain of bob@example.com designates 1.2.3.4 as permitted "
    "sender) smtp.mailfrom=bob@example.com;\r\n"
    "       dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=example.com"
)
GMAIL_FAIL = (
    "mx.google.com; dkim=fail header.i=@example.com; spf=softfail (google.com: domain of "
    "transitioning bob@example.com does not designate 9.9.9.9) smtp.mailfrom=bob@example.com; "
    "dmarc=fail (p=REJECT) header.from=example.com"
)
FORGED = "evil.example; spf=pass dkim=pass dmarc=pass"


def hdr(*values: str) -> list[tuple[str, str]]:
    return [("Authentication-Results", v) for v in values]


def test_typical_gmail_pass() -> None:
    r = parse_authentication_results(hdr(GMAIL_PASS))
    assert r == AuthResults(spf="pass", dkim="pass", dmarc="pass") and r.passed


def test_failures_are_reported() -> None:
    r = parse_authentication_results(hdr(GMAIL_FAIL))
    assert (r.spf, r.dkim, r.dmarc) == ("softfail", "fail", "fail") and not r.passed


def test_missing_header_means_none() -> None:
    r = parse_authentication_results([("Subject", "hi")])
    assert (r.spf, r.dkim, r.dmarc) == ("none", "none", "none") and not r.passed


def test_forged_header_from_another_server_is_ignored() -> None:
    r = parse_authentication_results(hdr(FORGED, GMAIL_FAIL))
    assert r.dmarc == "fail" and not r.passed


def test_topmost_google_header_wins_over_a_later_forged_google_header() -> None:
    forged_google = "mx.google.com; spf=pass dkim=pass dmarc=pass"
    r = parse_authentication_results(hdr(GMAIL_FAIL, forged_google))
    assert r.dmarc == "fail" and not r.passed


def test_only_a_forged_foreign_header_gives_none() -> None:
    assert not parse_authentication_results(hdr(FORGED)).passed


def test_one_passing_dkim_signature_among_several_counts() -> None:
    value = (
        "mx.google.com; dkim=fail header.i=@relay.test; dkim=pass header.i=@example.com; "
        "spf=pass smtp.mailfrom=bob@example.com; dmarc=pass header.from=example.com"
    )
    assert parse_authentication_results(hdr(value)).dkim == "pass"


def test_text_inside_comments_cannot_fake_a_result() -> None:
    value = (
        "mx.google.com; spf=fail (google.com: nope dkim=pass dmarc=pass) smtp.mailfrom=a@b.test; "
        "dkim=none; dmarc=fail"
    )
    r = parse_authentication_results(hdr(value))
    assert (r.spf, r.dkim, r.dmarc) == ("fail", "none", "fail")


def test_header_name_is_case_insensitive() -> None:
    r = parse_authentication_results([("authentication-RESULTS", GMAIL_PASS)])
    assert r.passed


def test_passed_requires_all_three() -> None:
    assert not AuthResults(spf="pass", dkim="pass", dmarc="none").passed
    assert not AuthResults(spf="pass", dkim="fail", dmarc="pass").passed
    assert AuthResults(spf="pass", dkim="pass", dmarc="pass").passed
