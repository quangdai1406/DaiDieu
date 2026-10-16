"""File-backed graph store: atomic writes, single-instance lock, hubs, simple queries."""

from __future__ import annotations

import contextlib
import copy
import os
from collections.abc import Collection
from pathlib import Path

import filelock

from daikon.graph.node import Node, from_markdown, to_markdown, validate_name

HUB_DIR = "_hubs"


class AlreadyRunningError(RuntimeError):
    """Another Daikon runner holds the lock on this data directory."""


class InstanceLock:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._lock = filelock.FileLock(str(root / ".daikon.lock"), timeout=0)

    def acquire(self) -> None:
        try:
            self._lock.acquire()
        except filelock.Timeout:
            raise AlreadyRunningError("another Daikon instance is running") from None

    def release(self) -> None:
        self._lock.release()


class GraphStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        # path -> (mtime_ns, size, node); copies are handed out so callers cannot corrupt it
        self._cache: dict[Path, tuple[int, int, Node]] = {}

    def _path(self, type_: str, id_: str) -> Path:
        return self.root / validate_name(type_) / f"{validate_name(id_)}.md"

    def write(self, node: Node) -> None:
        path = self._path(node.type, node.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(to_markdown(node))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            self._remember(path, node)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def _remember(self, path: Path, node: Node) -> None:
        st = path.stat()
        self._cache[path] = (st.st_mtime_ns, st.st_size, copy.deepcopy(node))

    def read(self, type_: str, id_: str) -> Node:
        path = self._path(type_, id_)
        st = path.stat()
        hit = self._cache.get(path)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return copy.deepcopy(hit[2])
        node = from_markdown(path.read_text(encoding="utf-8"))
        self._cache[path] = (st.st_mtime_ns, st.st_size, copy.deepcopy(node))
        return node

    def exists(self, type_: str, id_: str) -> bool:
        return self._path(type_, id_).is_file()

    def list_ids(self, type_: str) -> list[str]:
        folder = self.root / validate_name(type_)
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.md") if not p.name.startswith("."))

    def _types(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
        )

    def find(
        self,
        type: str | None = None,  # noqa: A002
        status: Collection[str] | None = None,
        links_to: str | None = None,
    ) -> list[Node]:
        types = [type] if type else self._types()
        found = [self.read(t, i) for t in types for i in self.list_ids(t)]
        if status is not None:
            found = [n for n in found if n.status in status]
        if links_to is not None:
            found = [n for n in found if links_to in n.linked_ids()]
        return sorted(found, key=lambda n: (n.type, n.id))

    def rebuild_hubs(self) -> bool:
        """Write one hub per type listing its nodes. Returns True if any hub changed."""
        changed = False
        hubs = self.root / HUB_DIR
        for t in self._types():
            ids = self.list_ids(t)
            lines = "\n".join(f"- [[{i}]]" for i in ids)
            text = f"---\nid: hub-{t}\ntype: hub\nfor_type: {t}\ncount: {len(ids)}\n---\n{lines}\n"
            path = hubs / f"{t}.md"
            if path.is_file() and path.read_text(encoding="utf-8") == text:
                continue
            hubs.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            changed = True
        return changed
