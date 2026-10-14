"""Block secrets and private runtime data from entering the repository (gitleaks adds depth)."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass

_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("secret-anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("secret-private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("secret-twilio-sid", re.compile(r"\bAC[0-9a-fA-F]{32}\b")),
    ("secret-openrouter-key", re.compile(r"sk-or-[A-Za-z0-9_\-]{20,}")),
)
_DATA_DIR = "daikon-data"
SECRET_KEY_WORDS = ("api_key", "apikey", "token", "password", "secret", "authorization")


def is_secret_key(key: str) -> bool:
    """True if a field name looks like it holds a secret (used by config and audit)."""
    lowered = key.lower()
    return any(word in lowered for word in SECRET_KEY_WORDS)


def contains_secret(text: str) -> bool:
    """True if text matches a known secret pattern."""
    return any(pattern.search(text) for _, pattern in _SECRET_RULES)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str


def _is_private_data_path(path: str) -> bool:
    parts = re.split(r"[\\/]", path)
    return _DATA_DIR in parts


def find_violations(files: Mapping[str, str]) -> list[Violation]:
    """Return violations for {path: text}. A private-data path is reported once, unread."""
    found: list[Violation] = []
    for path, text in files.items():
        if _is_private_data_path(path):
            found.append(Violation(path, 0, "private-data-path"))
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule, pattern in _SECRET_RULES:
                if pattern.search(line):
                    found.append(Violation(path, lineno, rule))
    return found


def _staged_files() -> dict[str, str]:
    names = subprocess.run(  # noqa: S603
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files: dict[str, str] = {}
    for name in names:
        try:
            with open(name, encoding="utf-8") as fh:
                files[name] = fh.read()
        except (UnicodeDecodeError, OSError):
            files[name] = ""
    return files


def main() -> int:
    violations = find_violations(_staged_files())
    for v in violations:
        print(f"{v.path}:{v.line}: {v.rule}", file=sys.stderr)  # noqa: T201
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
