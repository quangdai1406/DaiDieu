from datetime import UTC, datetime
from pathlib import Path

import pytest

from daikon.clock import FakeClock
from daikon.graph.store import GraphStore
from daikon.people import PersonBook

pytestmark = pytest.mark.unit


def book(tmp_path: Path) -> PersonBook:
    return PersonBook(GraphStore(tmp_path), FakeClock(datetime(2026, 10, 14, tzinfo=UTC)))


def test_ensure_creates_once_and_normalizes(tmp_path: Path) -> None:
    b = book(tmp_path)
    first = b.ensure("Bob@Example.COM", "Bob")
    second = b.ensure("bob@example.com")
    assert first.id == second.id and first.id.startswith("person-")
    assert second.extra["email"] == "bob@example.com" and second.extra["name"] == "Bob"


def test_person_ids_are_filesystem_safe(tmp_path: Path) -> None:
    node = book(tmp_path).ensure("we!rd+tag/../x@ex.com")
    assert "/" not in node.id and ".." not in node.id


def test_unknown_until_contacted(tmp_path: Path) -> None:
    b = book(tmp_path)
    b.ensure("bob@example.com")
    assert not b.is_known("bob@example.com") and not b.is_known("nobody@example.com")
    b.mark_contacted("bob@example.com")
    assert b.is_known("BOB@example.com")


def test_known_addresses_lists_only_known(tmp_path: Path) -> None:
    b = book(tmp_path)
    b.ensure("a@x.org")
    b.mark_contacted("b@x.org")
    assert b.known_addresses() == {"b@x.org"}


def test_state_persists_across_instances(tmp_path: Path) -> None:
    b = book(tmp_path)
    b.mark_contacted("bob@example.com")
    assert book(tmp_path).is_known("bob@example.com")


def test_blocked_people_are_reported(tmp_path: Path) -> None:
    b = book(tmp_path)
    assert not b.is_blocked("x@y.org")
    b.block("X@Y.org")
    assert b.is_blocked("x@y.org") and not b.is_known("x@y.org")
    b.mark_contacted("x@y.org")  # contacting never unblocks
    assert b.is_blocked("x@y.org")
