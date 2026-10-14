"""PAUSE / RESUME: the message-controlled kill switch.

Pausing is always allowed: it writes ``<data_dir>/PAUSE``, which the outbound policy checks
before any send to another person. Resuming needs the single-use code that was issued when
Daikon paused (stored only as a salted hash), limited to three attempts an hour. A PAUSE file
that Dai created by hand has no code, so only deleting it by hand resumes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from daikon.approvals import CODE_ALPHABET, CODE_LENGTH
from daikon.audit import AuditLog
from daikon.clock import Clock
from daikon.limiter import Limiter


def _hash(salt: str, code: str) -> str:
    return hashlib.sha256((salt + code).encode("utf-8")).hexdigest()


class PauseSwitch:
    def __init__(self, data_dir: Path, clock: Clock, audit: AuditLog, limiter: Limiter) -> None:
        self._path = data_dir / "PAUSE"
        self._clock, self._audit, self._limiter = clock, audit, limiter

    def is_paused(self) -> bool:
        return self._path.exists()

    def pause(self, actor: str) -> str | None:
        """Pause and return the resume code; ``None`` if already paused."""
        if self._path.exists():
            return None
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        salt = secrets.token_hex(8)
        record = {"salt": salt, "code_hash": _hash(salt, code),
                  "paused_at": self._clock.now().isoformat(), "by": actor}
        tmp = self._path.with_name(f".PAUSE.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, self._path)
        self._audit.append("pause", "pause.on", by=actor)
        return code

    def resume(self, code: str, actor: str) -> bool:
        if not self._path.exists():
            return False
        if not self._limiter.check_and_consume("resume_attempts").allowed:
            self._audit.append("pause", "pause.resume_failed", reason="rate_limited", by=actor)
            return False
        try:
            record = json.loads(self._path.read_text(encoding="utf-8"))
            stored, salt = str(record["code_hash"]), str(record["salt"])
        except (ValueError, KeyError, TypeError):
            self._audit.append("pause", "pause.resume_failed", reason="manual_pause", by=actor)
            return False
        if not hmac.compare_digest(_hash(salt, code.strip().upper()), stored):
            self._audit.append("pause", "pause.resume_failed", reason="wrong_code", by=actor)
            return False
        self._path.unlink(missing_ok=True)
        self._audit.append("pause", "pause.off", by=actor)
        return True
