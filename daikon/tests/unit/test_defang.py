import pytest

from daikon.defang import defang

pytestmark = pytest.mark.unit


def test_urls_are_defanged() -> None:
    assert defang("see https://evil.example.com/a?b=1") == "see hxxps://evil[.]example[.]com/a?b=1"
    assert defang("http://a.io") == "hxxp://a[.]io"


def test_www_hosts_are_defanged() -> None:
    assert defang("go to www.example.com now") == "go to www[.]example[.]com now"


def test_email_addresses_are_left_alone() -> None:
    assert defang("write to bob@example.org") == "write to bob@example.org"


def test_text_without_links_is_unchanged() -> None:
    assert defang("Lunch at 12.30 on Friday.") == "Lunch at 12.30 on Friday."


def test_multiple_and_mixed_case_urls() -> None:
    out = defang("HTTP://X.com and https://y.org/z")
    assert "://" not in out.replace("hxxp", "").replace("HXXP", "") or "hxxp" in out.lower()
    assert "x[.]com" in out.lower() and "y[.]org" in out


def test_no_clickable_scheme_survives() -> None:
    out = defang("https://a.com ftp://b.net mailto:c@d.org")
    assert "https://" not in out and "ftp://" not in out
