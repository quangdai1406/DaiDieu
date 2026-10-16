"""M4.1: ScopedDrive is the only Drive object. Read-only, inside the Second Brain tree, text only."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.drive.scoped import DriveAccessError, GoogleDriveApi, ScopedDrive
from tests.contract.fake_drive import DOC, FOLDER, FakeDrive

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def tree() -> FakeDrive:
    d = FakeDrive()
    d.add("root", "Second Brain", ["drive-root"], FOLDER)
    d.add("f-control", "00 Control", ["root"], FOLDER)
    d.add("f-aisi", "02 AISI (Quality Engineering)", ["root"], FOLDER)
    d.add("f-qual", "Quality", ["f-aisi"], FOLDER)
    d.add("f-sup", "99 Superseded", ["root"], FOLDER)
    d.add("n1", "Control Plan.md", ["f-aisi"], text="pfmea notes")
    d.add("n2", "Weekly Review", ["f-control"], DOC, "weekly review of supplier audit")
    d.add("n3", "deep.md", ["f-qual"], text="nested note about gauges")
    d.add("n4", "Combined.md", ["f-qual"], text="pfmea and supplier together")
    d.add("quote", "Quote.md", ["f-aisi"], text="it's a \\ tricky 'quoted' note")
    d.add("old1", "old.md", ["f-sup"], text="supplier audit old")
    d.add("ext1", "outside.md", ["elsewhere"], text="supplier audit outside", owner="x@y.org")
    d.add("multi", "both.md", ["f-aisi", "f-sup"], text="supplier audit multi")
    d.add("pdf1", "spec.pdf", ["f-aisi"], "application/pdf", "supplier audit in a pdf")
    d.add("tr1", "trashed.md", ["f-aisi"], text="supplier audit trashed", trashed=True)
    d.add("short", "link", ["f-aisi"], "application/vnd.google-apps.shortcut", "supplier audit")
    d.add("big", "huge.md", ["f-aisi"], text="x", size=10_000_000)
    d.add("long", "long.md", ["f-aisi"], text="y" * 20_000)
    return d


def make(tmp_path: Path, api: FakeDrive | None = None, **kw: Any) -> tuple[ScopedDrive, FakeDrive, FakeClock]:
    clock = FakeClock(T0)
    api = api or tree()
    return ScopedDrive(api, "root", clock, AuditLog(tmp_path / "audit", clock), **kw), api, clock


def ids(files: list[Any]) -> list[str]:
    return [f.id for f in files]


def test_allowed_folders_are_the_tree_without_denied_branches(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    assert drive.folder_ids() == frozenset({"root", "f-control", "f-aisi", "f-qual"})


def test_search_returns_only_readable_text_files_inside_the_tree(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    got = drive.search(["supplier audit"])
    assert ids(got) == ["n2"]  # not: old1 (superseded), ext1 (outside), multi (also superseded),
    # pdf1 (type), tr1 (trashed), short (shortcut)


def test_results_carry_path_and_authorship_for_trust_decisions(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    (hit,) = drive.search(["nested note"])
    assert hit.path == "02 AISI (Quality Engineering)/Quality/deep.md"
    assert hit.owner == "dai@example.com" and hit.last_modifier == "dai@example.com"


def test_multiple_terms_rank_files_matching_more_terms_first(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    assert ids(drive.search(["pfmea", "supplier"]))[0] == "n4"
    assert set(ids(drive.search(["pfmea", "supplier"]))) == {"n4", "n1", "n2"}


def test_quotes_and_backslashes_in_terms_are_escaped(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    assert ids(drive.search(["it's a \\ tricky"])) == ["quote"]
    assert ids(drive.search(["x' or name contains '"])) == []


def test_term_count_length_and_control_characters_are_limited(tmp_path: Path) -> None:
    drive, api, _ = make(tmp_path)
    drive.refresh()
    before = api.calls.count("list")
    drive.search(["a1", "b2", "c3", "d4", "e5", "f6", "g7"])
    assert api.calls.count("list") - before == 5
    assert drive.search([]) == [] and drive.search(["", "   ", "\n"]) == []


def test_read_returns_text_for_markdown_and_google_docs(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    assert drive.read("n1").text == "pfmea notes"
    assert drive.read("n2").text == "weekly review of supplier audit"


@pytest.mark.parametrize(
    ("file_id", "kind"),
    [("ext1", "outside"), ("old1", "denied"), ("multi", "denied"), ("pdf1", "mime"),
     ("short", "mime"), ("big", "too_large"), ("nope", "not_found"), ("f-aisi", "mime")],
)
def test_forbidden_reads_fail_with_a_specific_kind_and_are_audited(
    tmp_path: Path, file_id: str, kind: str
) -> None:
    drive, _, _ = make(tmp_path)
    with pytest.raises(DriveAccessError) as info:
        drive.read(file_id)
    assert info.value.kind == kind
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    assert '"drive.denied"' in raw and "supplier audit" not in raw


def test_long_text_is_truncated_and_flagged(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path, max_chars=5000)
    out = drive.read("long")
    assert len(out.text) == 5000 and out.truncated is True
    assert drive.read("n1").truncated is False


def test_folder_listing_is_cached_until_it_goes_stale(tmp_path: Path) -> None:
    drive, api, clock = make(tmp_path, refresh_after=timedelta(hours=1))
    drive.search(["pfmea"])
    first = api.calls.count("list")
    drive.search(["pfmea"])
    assert api.calls.count("list") == first + 1  # only the term query
    clock.advance(timedelta(hours=2))
    drive.search(["pfmea"])
    assert api.calls.count("list") > first + 2  # tree walked again


def test_audit_records_counts_and_ids_but_never_content(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    drive.search(["supplier audit"])
    drive.read("n1")
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    actions = [json.loads(x)["action"] for x in raw.splitlines()]
    assert "drive.search" in actions and "drive.read" in actions
    assert "pfmea notes" not in raw and "weekly review" not in raw


def test_there_is_no_write_surface(tmp_path: Path) -> None:
    drive, _, _ = make(tmp_path)
    public = {n for n in dir(drive) if not n.startswith("_")}
    assert public == {"refresh", "folder_ids", "search", "read"}
    adapter = {n for n in dir(GoogleDriveApi) if not n.startswith("_")}
    assert adapter == {"list_files", "get_file", "export_text", "get_media"}


class _Exec:
    def __init__(self, value: Any, log: list[tuple[str, dict[str, Any]]], name: str, kw: dict[str, Any]) -> None:
        log.append((name, kw))
        self._value = value

    def execute(self) -> Any:
        return self._value


def test_google_adapter_uses_read_only_calls_with_minimal_fields() -> None:
    log: list[tuple[str, dict[str, Any]]] = []
    files = SimpleNamespace(
        list=lambda **kw: _Exec({"files": []}, log, "list", kw),
        get=lambda **kw: _Exec({"id": "x"}, log, "get", kw),
        export=lambda **kw: _Exec(b"text", log, "export", kw),
        get_media=lambda **kw: _Exec(b"bytes", log, "get_media", kw),
    )
    api = GoogleDriveApi(SimpleNamespace(files=lambda: files))
    api.list_files("q", "tok")
    api.get_file("abc")
    assert api.export_text("abc") == b"text" and api.get_media("abc") == b"bytes"
    names = [n for n, _ in log]
    assert names == ["list", "get", "export", "get_media"]
    list_kw = log[0][1]
    assert list_kw["q"] == "q" and list_kw["pageToken"] == "tok" and "fields" in list_kw
    assert log[2][1]["mimeType"] == "text/plain"
