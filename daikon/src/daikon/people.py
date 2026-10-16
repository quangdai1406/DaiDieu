"""Person nodes: who Daikon has seen, and who counts as known.

"Known" means Dai has had a reply sent to that address before. It only lowers friction for
repeat recipients; it never relaxes authentication, approvals or caps.
"""

from __future__ import annotations

import hashlib

from daikon.clock import Clock
from daikon.graph.node import Node
from daikon.graph.store import GraphStore


class PersonBook:
    def __init__(self, store: GraphStore, clock: Clock) -> None:
        self._store, self._clock = store, clock

    @staticmethod
    def _id(address: str) -> str:
        digest = hashlib.sha1(address.encode("utf-8"), usedforsecurity=False).hexdigest()
        return f"person-{digest[:12]}"

    def ensure(self, address: str, name: str = "") -> Node:
        address = address.strip().lower()
        pid = self._id(address)
        if self._store.exists("person", pid):
            node = self._store.read("person", pid)
            if name and not node.extra.get("name"):
                node.extra["name"] = name
                self._store.write(node)
            return node
        node = Node(
            id=pid, type="person", status="unknown", created=self._clock.now(),
            extra={"email": address, "name": name, "sent_before": False,
                   "first_seen": self._clock.now().isoformat()},
        )
        self._store.write(node)
        return node

    def is_known(self, address: str) -> bool:
        pid = self._id(address.strip().lower())
        if not self._store.exists("person", pid):
            return False
        node = self._store.read("person", pid)
        return bool(node.extra.get("sent_before")) and node.status != "blocked"

    def is_blocked(self, address: str) -> bool:
        pid = self._id(address.strip().lower())
        if not self._store.exists("person", pid):
            return False
        return self._store.read("person", pid).status == "blocked"

    def block(self, address: str) -> None:
        node = self.ensure(address)
        node.status = "blocked"
        self._store.write(node)

    def mark_contacted(self, address: str) -> None:
        node = self.ensure(address)
        node.extra["sent_before"] = True
        if node.status != "blocked":  # contacting someone never unblocks them
            node.status = "known"
        self._store.write(node)

    def known_addresses(self) -> set[str]:
        return {str(n.extra["email"]) for n in self._store.find(type="person", status={"known"})}
