"""M1.3: graph store (atomic writes, instance lock, hubs, simple queries)."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from daikon.graph.node import InvalidNameError, Node, validate_name
from daikon.graph.store import AlreadyRunningError, GraphStore, InstanceLock

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def make(id_: str = "task-1", type_: str = "task", status: str = "open", **kw: object) -> Node:
    return Node(id=id_, type=type_, status=status, created=T0, **kw)  # type: ignore[arg-type]


def test_round_trip_with_links_tags_extra_body(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    n = make(
        tags=["email", "urgent"],
        links={"relates_to": ["person-1"], "blocked_by": ["task-0"]},
        body="Line one\n---\nTiếng Việt ✓\n",
        extra={"gmail_id": "abc123"},
    )
    store.write(n)
    assert store.read("task", "task-1") == n


def test_links_are_written_as_wikilinks(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    store.write(make(links={"relates_to": ["person-1"]}))
    assert "[[person-1]]" in (tmp_path / "task" / "task-1.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad",
    [
        "../x", "a/b", "a\\b", "A", "a b", "x:y", "CON", "nul", "com1",
        "lpt9.txt", "a.", "", "-a", "a" * 81,
    ],
)
def test_invalid_names_rejected(bad: str) -> None:
    with pytest.raises(InvalidNameError):
        validate_name(bad)


def test_valid_names_accepted() -> None:
    for ok in ["task-1", "message-2026-10-14.0007", "a", "abc_def", "console1"]:
        assert validate_name(ok) == ok


def test_extra_cannot_shadow_reserved_fields() -> None:
    with pytest.raises(ValueError, match="reserved"):
        make(extra={"status": "hacked"})


def test_exists_and_list_ids(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    assert not store.exists("task", "task-1")
    store.write(make("task-2"))
    store.write(make("task-1"))
    assert store.exists("task", "task-1")
    assert store.list_ids("task") == ["task-1", "task-2"]
    assert store.list_ids("person") == []


def test_read_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        GraphStore(tmp_path).read("task", "nope")


def test_read_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(InvalidNameError):
        GraphStore(tmp_path).read("../etc", "passwd")


def test_failed_write_keeps_old_file_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GraphStore(tmp_path)
    store.write(make(body="old"))

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.write(make(body="new"))
    monkeypatch.undo()
    assert store.read("task", "task-1").body == "old"
    assert [p.name for p in (tmp_path / "task").iterdir()] == ["task-1.md"]


def test_second_instance_is_refused(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            InstanceLock(tmp_path).acquire()
    finally:
        first.release()
    again = InstanceLock(tmp_path)
    again.acquire()
    again.release()


def test_hubs_list_nodes_and_are_idempotent(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    store.write(make("task-2"))
    store.write(make("task-1"))
    store.write(make("person-1", "person", "known"))
    assert store.rebuild_hubs() is True
    hub = (tmp_path / "_hubs" / "task.md").read_text(encoding="utf-8")
    assert hub.index("[[task-1]]") < hub.index("[[task-2]]")
    assert store.rebuild_hubs() is False
    store.write(make("task-3"))
    assert store.rebuild_hubs() is True


def test_find_by_type_status_and_link(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    store.write(make("task-1", links={"relates_to": ["person-1"]}))
    store.write(make("task-2", status="done", links={"relates_to": ["person-1"]}))
    store.write(make("task-3", links={"relates_to": ["person-2"]}))
    store.write(make("person-1", "person", "known"))
    got = store.find(type="task", status={"open"}, links_to="person-1")
    assert [n.id for n in got] == ["task-1"]
    assert [n.id for n in store.find(links_to="person-1")] == ["task-1", "task-2"]
    assert [n.id for n in store.find(type="person")] == ["person-1"]
