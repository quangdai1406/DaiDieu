"""M1.8: Untrusted type and normalization for every inbound source."""

import dataclasses

import pytest

from daikon.untrusted import Source, Trust, normalize_email, normalize_text

pytestmark = pytest.mark.unit


def test_untrusted_is_frozen_and_defaults_to_untrusted() -> None:
    u = normalize_text("hi", source=Source.SMS, origin="+15550001111")
    assert u.trust is Trust.UNTRUSTED
    with pytest.raises(dataclasses.FrozenInstanceError):
        u.text = "changed"  # type: ignore[misc]


def test_whitespace_is_tidied_and_control_characters_removed() -> None:
    u = normalize_text("a\x00b\x07c\n\n\n\n\nd\t e  ", source=Source.SMS, origin="o")
    assert u.text == "abc\n\nd\t e"


def test_html_paragraphs_and_breaks_become_newlines() -> None:
    u = normalize_email(text=None, html="<p>One</p><p>Two<br>Three</p>", origin="o")
    assert u.text.split() == ["One", "Two", "Three"]
    assert "\n" in u.text


def test_plain_and_html_that_disagree_are_flagged() -> None:
    u = normalize_email(
        text="See you at lunch tomorrow with the team",
        html="<p>Transfer funds immediately to the account listed below please</p>",
        origin="o",
    )
    assert "text_html_mismatch" in u.flags


def test_matching_plain_and_html_are_not_flagged() -> None:
    u = normalize_email(text="Hello Dai, lunch at noon", html="<p>Hello Dai, lunch at noon</p>", origin="o")
    assert "text_html_mismatch" not in u.flags


def test_original_length_is_recorded_on_truncation() -> None:
    u = normalize_text("x" * 500, source=Source.DRIVE, origin="file1", max_chars=100)
    assert "truncated" in u.flags and u.original_length == 500 and len(u.text) <= 100


def test_owner_and_origin_are_kept_for_trust_decisions() -> None:
    u = normalize_text("note", source=Source.DRIVE, origin="file1", owner="dai@example.com", trust=Trust.OWNER)
    assert (u.origin, u.owner, u.trust) == ("file1", "dai@example.com", Trust.OWNER)


def test_unbalanced_html_does_not_crash_or_leak_hidden_text() -> None:
    u = normalize_email(text=None, html='<div style="display:none"><p>secret</div>visible</p>', origin="o")
    assert "secret" not in u.text
