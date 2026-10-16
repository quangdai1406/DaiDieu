"""M2.2b: flags that help Dai spot impersonation (RT-19). Flags warn; they never grant trust."""

import pytest

from daikon.senders import analyze_sender

pytestmark = [pytest.mark.unit, pytest.mark.security]
KNOWN = {"bob@example.com", "dai@example.com"}


def flags(frm: str, reply_to: str | None = None, known: set[str] | None = None) -> set[str]:
    return set(analyze_sender(frm, reply_to, KNOWN if known is None else known).flags)


def test_known_sender_has_no_flags() -> None:
    assert flags("Bob Smith <bob@example.com>") == set()


def test_unknown_sender_is_new() -> None:
    assert flags("alice@other.org") == {"new_sender"}


def test_address_and_name_are_extracted_and_lowercased() -> None:
    info = analyze_sender('"Bob S." <BOB@Example.COM>', None, KNOWN)
    assert info.address == "bob@example.com" and info.display_name == "Bob S."


def test_display_name_with_a_different_address_is_flagged() -> None:
    assert "display_name_mismatch" in flags('"ceo@bank.com" <evil@x.test>')


def test_display_name_with_the_same_address_is_fine() -> None:
    assert "display_name_mismatch" not in flags('"bob@example.com" <bob@example.com>')


def test_reply_to_on_another_domain_is_flagged() -> None:
    assert "reply_to_mismatch" in flags("bob@example.com", "bob@gmail.com")
    assert "reply_to_mismatch" not in flags("bob@example.com", "billing@example.com")


def test_any_mismatching_reply_to_address_counts() -> None:
    assert "reply_to_mismatch" in flags("bob@example.com", "a@example.com, evil@x.test")


@pytest.mark.parametrize(
    "sender", ["x@examp1e.com", "x@exarnple.com", "x@exampel.com", "x@exämple.com"]
)
def test_lookalike_domains_are_flagged(sender: str) -> None:
    assert "lookalike_domain" in flags(sender)


@pytest.mark.parametrize("sender", ["x@example.org", "x@totally-different.io", "bob@example.com"])
def test_unrelated_or_identical_domains_are_not_lookalikes(sender: str) -> None:
    assert "lookalike_domain" not in flags(sender)


def test_idn_domains_are_flagged() -> None:
    assert "idn_domain" in flags("x@xn--exmple-cua.com")
    assert "idn_domain" in flags("x@exämple.com")
    assert "idn_domain" not in flags("x@example.com")


def test_unparseable_from_is_flagged_bad_from() -> None:
    info = analyze_sender("not an address", None, KNOWN)
    assert info.address == "" and "bad_from" in info.flags


def test_empty_known_set_marks_everyone_new_without_crashing() -> None:
    assert flags("a@b.org", known=set()) == {"new_sender"}
