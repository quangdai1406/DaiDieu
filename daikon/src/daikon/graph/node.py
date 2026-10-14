"""Graph node model, name validation and Markdown (YAML frontmatter) serialization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
RESERVED_KEYS = frozenset({"id", "type", "status", "created", "tags", "links"})
_WIKILINK = re.compile(r"^\[\[([a-z0-9][a-z0-9._-]{0,79})\]\]$")


class InvalidNameError(ValueError):
    """Raised for node ids or types that are unsafe as file names (incl. on Windows)."""


def validate_name(name: str) -> str:
    if (
        not _NAME_RE.match(name)
        or name.endswith(".")
        or name.split(".")[0] in _WINDOWS_RESERVED
    ):
        raise InvalidNameError(f"invalid node name: {name!r}")
    return name


@dataclass
class Node:
    id: str
    type: str
    status: str
    created: datetime
    tags: list[str] = field(default_factory=list)
    links: dict[str, list[str]] = field(default_factory=dict)
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_name(self.id)
        validate_name(self.type)
        if self.created.tzinfo is None:
            raise ValueError("created must be timezone-aware")
        clash = RESERVED_KEYS & set(self.extra)
        if clash:
            raise ValueError(f"extra uses reserved keys: {sorted(clash)}")

    def linked_ids(self) -> set[str]:
        return {i for ids in self.links.values() for i in ids}


def to_markdown(node: Node) -> str:
    front: dict[str, Any] = {
        "id": node.id,
        "type": node.type,
        "status": node.status,
        "created": node.created.isoformat(),
        "tags": list(node.tags),
        "links": {rel: [f"[[{i}]]" for i in ids] for rel, ids in node.links.items()},
        **node.extra,
    }
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{head}\n---\n{node.body}"


def from_markdown(text: str) -> Node:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.index("\n---\n", 4)
    front = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :]
    links: dict[str, list[str]] = {}
    for rel, items in (front.pop("links", None) or {}).items():
        ids = []
        for item in items:
            m = _WIKILINK.match(str(item))
            if not m:
                raise ValueError(f"bad link {item!r}")
            ids.append(m.group(1))
        links[rel] = ids
    node_id, node_type, status = front.pop("id"), front.pop("type"), front.pop("status")
    created = datetime.fromisoformat(str(front.pop("created")))
    tags = [str(t) for t in front.pop("tags", [])]
    return Node(node_id, node_type, status, created, tags, links, body, dict(front))
