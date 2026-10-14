"""M1.4: append-only, hash-chained audit log with redaction."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.audit import GENESIS, AuditLog, verify
from daikon.clock import FakeClock

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def log_in(tmp_path: Path) -> tuple[AuditLog, FakeClock]:
    clock = FakeClock(T0)
    return AuditLog(tmp_path / "audit", clock), clock


def lines(tmp_path: Path, name: str = "2026-10.jsonl") -> list[str]:
    return (tmp_path / "audit" / name).read_text(encoding="utf-8").splitlines()


def test_entries_are_chained_from_genesis(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    a = log.append("runner", "fetch", count=3)
    b = log.append("runner", "draft", draft_id="d1")
    assert a.prev == GENESIS and a.seq == 1
    assert b.prev == a.hash and b.seq == 2
    assert verify(tmp_path / "audit").ok


def test_reopen_continues_the_chain(tmp_path: Path) -> None:
    log, clock = log_in(tmp_path)
    a = log.append("runner", "one")
    reopened = AuditLog(tmp_path / "audit", clock)
    b = reopened.append("runner", "two")
    assert b.prev == a.hash and b.seq == 2
    assert verify(tmp_path / "audit").ok


def test_month_rollover_keeps_chain(tmp_path: Path) -> None:
    log, clock = log_in(tmp_path)
    log.append("runner", "oct")
    clock.advance(timedelta(days=30))
    log.append("runner", "nov")
    assert (tmp_path / "audit" / "2026-10.jsonl").exists()
    assert (tmp_path / "audit" / "2026-11.jsonl").exists()
    assert verify(tmp_path / "audit").ok


def test_editing_an_entry_is_detected(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    log.append("runner", "send", to="dai@example.com")
    log.append("runner", "other")
    path = tmp_path / "audit" / "2026-10.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("dai@example.com", "evil@x.com"))
    result = verify(tmp_path / "audit")
    assert not result.ok and result.bad_seq == 1


def test_deleting_a_middle_entry_is_detected(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    for i in range(3):
        log.append("runner", f"a{i}")
    path = tmp_path / "audit" / "2026-10.jsonl"
    ls = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([ls[0], ls[2]]) + "\n", encoding="utf-8")
    result = verify(tmp_path / "audit")
    assert not result.ok and result.bad_seq == 3


def test_tail_truncation_needs_the_external_head(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    log.append("runner", "a")
    head = log.append("runner", "b").hash
    path = tmp_path / "audit" / "2026-10.jsonl"
    path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    assert verify(tmp_path / "audit").ok
    assert not verify(tmp_path / "audit", expected_head=head).ok


def test_append_never_changes_earlier_bytes(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    log.append("runner", "a")
    before = (tmp_path / "audit" / "2026-10.jsonl").read_bytes()
    log.append("runner", "b")
    assert (tmp_path / "audit" / "2026-10.jsonl").read_bytes().startswith(before)


def test_secret_keys_and_values_are_redacted(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    log.append(
        "gateway",
        "model_call",
        api_key="abc",
        nested={"Authorization": "Bearer zzz", "note": "key sk-ant-" + "A" * 30},
        ok="fine",
    )
    raw = "\n".join(lines(tmp_path))
    assert "abc" not in raw and "zzz" not in raw and "sk-ant-" not in raw
    entry = json.loads(lines(tmp_path)[0])
    assert entry["data"]["ok"] == "fine"
    assert entry["data"]["api_key"] == "[REDACTED]"
    assert verify(tmp_path / "audit").ok


def test_head_returns_last_hash(tmp_path: Path) -> None:
    log, _ = log_in(tmp_path)
    assert log.head() == GENESIS
    e = log.append("runner", "a")
    assert log.head() == e.hash
