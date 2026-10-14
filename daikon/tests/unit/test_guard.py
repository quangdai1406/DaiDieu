"""M1.1: guard that blocks secrets and private runtime data from being committed."""

import pytest

from daikon.guard import find_violations

pytestmark = pytest.mark.unit


def test_clean_file_has_no_violations() -> None:
    assert find_violations({"src/daikon/a.py": "x = 1\n"}) == []


def test_anthropic_style_key_is_blocked() -> None:
    text = "key = 'sk-ant-api03-" + "A" * 40 + "'\n"
    v = find_violations({"src/daikon/a.py": text})
    assert [x.rule for x in v] == ["secret-anthropic-key"]


def test_private_key_block_is_blocked() -> None:
    v = find_violations({"notes.txt": "-----BEGIN PRIVATE KEY-----\nabc\n"})
    assert [x.rule for x in v] == ["secret-private-key"]


def test_twilio_sid_and_token_assignment_blocked() -> None:
    sid = "AC" + "0" * 32
    v = find_violations({"cfg.py": f"sid = '{sid}'\n"})
    assert [x.rule for x in v] == ["secret-twilio-sid"]


def test_daikon_data_path_is_blocked() -> None:
    v = find_violations({"daikon-data/graph/message/m1.md": "hello"})
    assert [x.rule for x in v] == ["private-data-path"]


def test_windows_style_daikon_data_path_is_blocked() -> None:
    v = find_violations({"x\\daikon-data\\audit\\2026-10.jsonl": "{}"})
    assert [x.rule for x in v] == ["private-data-path"]


def test_example_files_are_allowed_to_mention_daikon_data_in_text() -> None:
    assert find_violations({"docs/runbook.md": "data lives in %USERPROFILE%\\daikon-data\\"}) == []


def test_violation_reports_path_and_line() -> None:
    text = "ok\nsk-ant-" + "B" * 40 + "\n"
    (v,) = find_violations({"a.py": text})
    assert (v.path, v.line) == ("a.py", 2)
