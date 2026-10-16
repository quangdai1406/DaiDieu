"""In-memory stand-in for the Drive v3 calls ScopedDrive needs (same field names as the API)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"


def http_error_500() -> HttpError:
    return HttpError(httplib2.Response({"status": "500"}), b"{}")


def not_found() -> HttpError:
    return HttpError(httplib2.Response({"status": "404"}), b"{}")


@dataclass
class FakeDrive:
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    content: dict[str, bytes] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail_search: Exception | None = None

    def add(self, id_: str, name: str, parents: list[str], mime: str = "text/markdown",
            text: str = "", *, size: int | None = None, trashed: bool = False,
            owner: str = "dai@example.com", modifier: str = "dai@example.com") -> str:
        self.files[id_] = {
            "id": id_, "name": name, "mimeType": mime, "parents": parents, "trashed": trashed,
            "modifiedTime": "2026-10-10T10:00:00Z", "owners": [{"emailAddress": owner}],
            "lastModifyingUser": {"emailAddress": modifier},
            "size": str(size if size is not None else len(text.encode())),
        }
        self.content[id_] = text.encode()
        return id_

    # ----- the API surface used by ScopedDrive -----
    def list_files(self, q: str, page_token: str | None = None) -> dict[str, Any]:
        self.calls.append("list")
        m = re.match(r"'([^']+)' in parents and trashed=false", q)
        if m:
            hits = [f for f in self.files.values() if m.group(1) in f["parents"] and not f["trashed"]]
        else:
            if self.fail_search is not None:
                raise self.fail_search
            t = re.search(r"fullText contains '((?:[^'\\]|\\.)*)'", q)
            term = (t.group(1) if t else "").replace("\\'", "'").replace("\\\\", "\\").lower()
            hits = [f for f in self.files.values()
                    if not f["trashed"] and f["mimeType"] != FOLDER
                    and (term in f["name"].lower() or term in self.content[f["id"]].decode().lower())]
        return {"files": [dict(f) for f in hits]}

    def get_file(self, file_id: str) -> dict[str, Any]:
        self.calls.append("get")
        if file_id not in self.files:
            raise not_found()
        return dict(self.files[file_id])

    def export_text(self, file_id: str) -> bytes:
        self.calls.append("export")
        return self.content[file_id]

    def get_media(self, file_id: str) -> bytes:
        self.calls.append("media")
        return self.content[file_id]
