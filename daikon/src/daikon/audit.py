"""Append-only, hash-chained audit log (JSONL, one file per month).

Each entry's hash covers the previous entry's hash, so edits, deletions and reordering are
detectable. Truncating the tail is detectable only against an externally stored head hash
(the weekly digest carries it). Secret-looking keys and values are redacted before hashing.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daikon.clock import Clock
from daikon.guard import contains_secret, is_secret_key

GENESIS = "0" * 64
REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    ts: str
    actor: str
    action: str
    data: dict[str, Any]
    prev: str
    hash: str


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    bad_seq: int | None = None
    reason: str = ""
    head: str = GENESIS


def _canonical(body: dict[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(prev: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev + _canonical(body)).encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if is_secret_key(str(k)) else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and contains_secret(value):
        return REDACTED
    return value


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("????-??.jsonl")) if directory.is_dir() else []


class AuditLog:
    def __init__(self, directory: Path, clock: Clock) -> None:
        self._dir = directory
        self._clock = clock
        self._lock = threading.Lock()
        self._seq, self._head = 0, GENESIS
        files = _files(directory)
        if files:
            last = [ln for ln in files[-1].read_text(encoding="utf-8").splitlines() if ln][-1]
            entry = json.loads(last)
            self._seq, self._head = entry["seq"], entry["hash"]

    def head(self) -> str:
        return self._head

    def append(self, actor: str, action: str, /, **data: Any) -> AuditEntry:
        with self._lock:
            now = self._clock.now()
            body = {
                "seq": self._seq + 1,
                "ts": now.isoformat(),
                "actor": actor,
                "action": action,
                "data": _redact(data),
            }
            digest = _digest(self._head, body)
            record = {**body, "prev": self._head, "hash": digest}
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{now:%Y-%m}.jsonl"
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False, default=str) + "\n")
                fh.flush()
            self._seq, self._head = body["seq"], digest
            return AuditEntry(
                body["seq"], body["ts"], actor, action, body["data"], record["prev"], digest
            )


def verify(directory: Path, expected_head: str | None = None) -> VerifyResult:
    prev, seq = GENESIS, 0
    for path in _files(directory):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            rec = json.loads(line)
            body = {k: rec[k] for k in ("seq", "ts", "actor", "action", "data")}
            if rec["seq"] != seq + 1:
                return VerifyResult(False, rec["seq"], "sequence gap", prev)
            if rec["prev"] != prev:
                return VerifyResult(False, rec["seq"], "broken link", prev)
            if _digest(prev, body) != rec["hash"]:
                return VerifyResult(False, rec["seq"], "hash mismatch", prev)
            prev, seq = rec["hash"], rec["seq"]
    if expected_head is not None and expected_head != prev:
        return VerifyResult(False, None, "head mismatch (tail truncated or replaced)", prev)
    return VerifyResult(True, None, "", prev)
