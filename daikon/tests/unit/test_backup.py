"""M6.3: daily copy of the graph, audit log and counters."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daikon.backup import daily_backup

pytestmark = pytest.mark.unit
D1 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def data(tmp_path: Path) -> Path:
    d = tmp_path / "daikon-data"
    (d / "graph" / "message").mkdir(parents=True)
    (d / "graph" / "message" / "m1.md").write_text("hello", encoding="utf-8")
    (d / "audit").mkdir()
    (d / "audit" / "2026-10.jsonl").write_text("{}\n", encoding="utf-8")
    (d / "limits.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    (d / "PAUSE").write_text("x", encoding="utf-8")
    (d / "daikon.log").write_text("noise", encoding="utf-8")
    return d


def test_copies_graph_audit_and_limits_into_a_dated_folder(tmp_path: Path) -> None:
    d = data(tmp_path)
    out = daily_backup(d, D1)
    assert out == d / "backups" / "2026-10-14"
    assert (out / "graph" / "message" / "m1.md").read_text(encoding="utf-8") == "hello"
    assert (out / "audit" / "2026-10.jsonl").exists() and (out / "limits.json").exists()


def test_does_not_copy_the_pause_file_logs_or_earlier_backups(tmp_path: Path) -> None:
    d = data(tmp_path)
    daily_backup(d, D1)
    out = daily_backup(d, D1 + timedelta(days=1))
    assert out is not None
    names = {p.name for p in out.iterdir()}
    assert names == {"graph", "audit", "limits.json"}
    assert not (out / "backups").exists()


def test_a_second_call_the_same_day_does_nothing(tmp_path: Path) -> None:
    d = data(tmp_path)
    assert daily_backup(d, D1) is not None
    assert daily_backup(d, D1 + timedelta(hours=5)) is None


def test_only_the_newest_seven_backups_are_kept(tmp_path: Path) -> None:
    d = data(tmp_path)
    for i in range(10):
        daily_backup(d, D1 + timedelta(days=i), keep=7)
    kept = sorted(p.name for p in (d / "backups").iterdir())
    assert kept == [f"2026-10-{day}" for day in range(17, 24)]


def test_a_half_written_backup_is_not_mistaken_for_a_finished_one(tmp_path: Path) -> None:
    d = data(tmp_path)
    (d / "backups" / ".tmp-2026-10-14").mkdir(parents=True)
    out = daily_backup(d, D1)
    assert out is not None and out.name == "2026-10-14"
    assert not (d / "backups" / ".tmp-2026-10-14").exists()


def test_missing_optional_parts_are_fine(tmp_path: Path) -> None:
    d = tmp_path / "daikon-data"
    d.mkdir()
    out = daily_backup(d, D1)
    assert out is not None and list(out.iterdir()) == []
