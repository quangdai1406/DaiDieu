"""ScopedDrive: the only Drive object in the codebase (RT-09, RT-12).

  * read-only: the public surface is refresh / folder_ids / search / read, and the adapter
    over the Google client has only four read calls; Google also enforces Viewer access;
  * confined to the Second Brain tree: a file is reachable only if a parent folder is inside
    the tree, and never if a parent is a denied folder (``99 Superseded``);
  * text only: Markdown, plain text and Google Docs (exported as text); shortcuts, folders,
    PDFs and everything else are refused;
  * size-capped, trashed files hidden, search terms escaped and limited;
  * the audit log records ids, counts and refusal kinds, never file content.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from googleapiclient.errors import HttpError

from daikon.audit import AuditLog
from daikon.clock import Clock

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
ALLOWED_MIME = frozenset({"text/plain", "text/markdown", DOC_MIME})
MAX_TERMS, MAX_TERM_LEN, MAX_FOLDERS, MAX_PAGES = 5, 60, 2000, 3
_META = (
    "id,name,mimeType,modifiedTime,size,parents,trashed,"
    "owners(emailAddress),lastModifyingUser(emailAddress)"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class DriveApi(Protocol):
    def list_files(self, q: str, page_token: str | None = None) -> dict[str, Any]: ...
    def get_file(self, file_id: str) -> dict[str, Any]: ...
    def export_text(self, file_id: str) -> bytes: ...
    def get_media(self, file_id: str) -> bytes: ...


class GoogleDriveApi:
    """Thin adapter over googleapiclient. Four read calls, nothing that can change Drive."""

    def __init__(self, service: Any) -> None:
        self._svc = service

    def list_files(self, q: str, page_token: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self._svc.files().list(
            q=q, fields=f"nextPageToken,files({_META})", pageSize=100, pageToken=page_token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        return result

    def get_file(self, file_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._svc.files().get(
            fileId=file_id, fields=_META, supportsAllDrives=True
        ).execute()
        return result

    def export_text(self, file_id: str) -> bytes:
        data: bytes = self._svc.files().export(fileId=file_id, mimeType="text/plain").execute()
        return data

    def get_media(self, file_id: str) -> bytes:
        data: bytes = self._svc.files().get_media(fileId=file_id).execute()
        return data


class DriveAccessError(PermissionError):
    """A read was refused. ``kind``: outside, denied, mime, too_large, not_found."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime: str
    modified: str
    size: int | None
    parents: tuple[str, ...]
    owner: str | None
    last_modifier: str | None
    path: str


@dataclass(frozen=True)
class DriveText:
    file: DriveFile
    text: str
    truncated: bool


def _escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("'", "\\'")


def _clean_terms(terms: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for raw in terms:
        term = re.sub(r"\s+", " ", _CONTROL.sub(" ", raw)).strip()[:MAX_TERM_LEN]
        if term and term not in seen:
            seen.append(term)
    return seen[:MAX_TERMS]


class ScopedDrive:
    def __init__(
        self,
        api: DriveApi,
        root_id: str,
        clock: Clock,
        audit: AuditLog,
        *,
        deny_names: tuple[str, ...] = ("99 Superseded",),
        max_chars: int = 8000,
        max_bytes: int = 5_000_000,
        refresh_after: timedelta = timedelta(hours=1),
    ) -> None:
        self._api, self._root, self._clock, self._audit = api, root_id, clock, audit
        self._deny_names, self._max_chars, self._max_bytes = deny_names, max_chars, max_bytes
        self._refresh_after = refresh_after
        self._folders: dict[str, str] = {}
        self._denied: set[str] = set()
        self._refreshed_at: datetime | None = None

    # ---------- tree ----------
    def refresh(self) -> None:
        folders: dict[str, str] = {self._root: ""}
        denied: set[str] = set()
        queue: deque[str] = deque([self._root])
        while queue and len(folders) < MAX_FOLDERS:
            parent = queue.popleft()
            for child in self._pages(f"'{parent}' in parents and trashed=false"):
                if child["mimeType"] != FOLDER_MIME:
                    continue
                if child["name"] in self._deny_names:
                    denied.add(child["id"])
                    continue
                base = folders[parent]
                folders[child["id"]] = f"{base}/{child['name']}" if base else child["name"]
                queue.append(child["id"])
        self._folders, self._denied = folders, denied
        self._refreshed_at = self._clock.now()
        self._audit.append("drive", "drive.refresh", folders=len(folders), denied=len(denied))

    def _ensure(self) -> None:
        last = self._refreshed_at
        if last is None or self._clock.now() - last > self._refresh_after:
            self.refresh()

    def folder_ids(self) -> frozenset[str]:
        self._ensure()
        return frozenset(self._folders)

    def _pages(self, q: str) -> Iterable[dict[str, Any]]:
        token: str | None = None
        for _ in range(MAX_PAGES):
            page = self._api.list_files(q, token)
            yield from page.get("files", [])
            token = page.get("nextPageToken")
            if not token:
                return

    # ---------- classification ----------
    def _refusal(self, meta: dict[str, Any]) -> str | None:
        parents = set(meta.get("parents", []))
        if parents & self._denied:
            return "denied"
        if not parents & self._folders.keys():
            return "outside"
        if meta.get("trashed"):
            return "not_found"
        if meta.get("mimeType") not in ALLOWED_MIME:
            return "mime"
        return None

    def _to_file(self, meta: dict[str, Any]) -> DriveFile:
        parents = tuple(meta.get("parents", []))
        base = next((self._folders[p] for p in parents if p in self._folders), "")
        owners = meta.get("owners") or [{}]
        return DriveFile(
            id=meta["id"], name=meta["name"], mime=meta["mimeType"],
            modified=meta.get("modifiedTime", ""),
            size=int(meta["size"]) if meta.get("size") else None,
            parents=parents, owner=owners[0].get("emailAddress"),
            last_modifier=(meta.get("lastModifyingUser") or {}).get("emailAddress"),
            path=f"{base}/{meta['name']}" if base else meta["name"],
        )

    # ---------- search ----------
    def search(self, terms: Iterable[str], limit: int = 10) -> list[DriveFile]:
        self._ensure()
        hits: dict[str, int] = {}
        metas: dict[str, dict[str, Any]] = {}
        cleaned = _clean_terms(terms)
        for term in cleaned:
            for meta in self._pages(f"fullText contains '{_escape(term)}' and trashed=false"):
                if self._refusal(meta) is None:
                    hits[meta["id"]] = hits.get(meta["id"], 0) + 1
                    metas[meta["id"]] = meta
        ranked = sorted(hits, key=lambda i: (-hits[i], _neg(metas[i].get("modifiedTime", "")), i))
        files = [self._to_file(metas[i]) for i in ranked[:limit]]
        self._audit.append("drive", "drive.search", terms=len(cleaned), results=len(files))
        return files

    # ---------- read ----------
    def read(self, file_id: str) -> DriveText:
        self._ensure()
        try:
            meta = self._api.get_file(file_id)
        except HttpError as exc:
            if int(exc.resp.status) == 404:
                raise self._deny(file_id, "not_found") from None
            raise
        kind = self._refusal(meta)
        if kind is None and int(meta.get("size") or 0) > self._max_bytes:
            kind = "too_large"
        if kind is not None:
            raise self._deny(file_id, kind)
        raw = (
            self._api.export_text(file_id) if meta["mimeType"] == DOC_MIME
            else self._api.get_media(file_id)
        )
        text = _CONTROL.sub("", raw.decode("utf-8", errors="replace"))
        truncated = len(text) > self._max_chars
        self._audit.append("drive", "drive.read", file_id=file_id,
                           chars=min(len(text), self._max_chars), truncated=truncated)
        return DriveText(self._to_file(meta), text[: self._max_chars], truncated)

    def _deny(self, file_id: str, kind: str) -> DriveAccessError:
        self._audit.append("drive", "drive.denied", file_id=file_id, kind=kind)
        return DriveAccessError(kind)


def _neg(modified: str) -> tuple[int, ...]:
    """Sort key that puts newer ISO timestamps first."""
    return tuple(-ord(c) for c in modified)
