"""A stand-in for googleapiclient's Gmail service: same call chains, same response shapes."""

from __future__ import annotations

from typing import Any

import httplib2
from googleapiclient.errors import HttpError


def http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": str(status)}), b"{}")


class _Req:
    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def execute(self) -> Any:
        return self._fn()


class FakeGmail:
    def __init__(self, address: str = "daikon@example.com") -> None:
        self.address = address
        self.history_id = 100
        self.resources: dict[str, dict[str, Any]] = {}
        self.history_pages: list[dict[str, Any]] = []   # each: {"added": [ids], "historyId": "n"}
        self.history_error: int | None = None
        self.get_errors: dict[str, int] = {}
        self.listed_ids: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.sent_listed: list[str] = []
        self.last_list_q = ""
        self.send_error: Exception | None = None
        self.calls: list[str] = []

    # users().xxx chain
    def users(self) -> FakeGmail:
        return self

    def getProfile(self, userId: str) -> _Req:  # noqa: N802 - mirrors the Google client
        self.calls.append("getProfile")
        return _Req(lambda: {"emailAddress": self.address, "historyId": str(self.history_id)})

    def history(self) -> FakeGmail:
        return _History(self)  # type: ignore[return-value]

    def messages(self) -> FakeGmail:
        return _Messages(self)  # type: ignore[return-value]


class _History:
    def __init__(self, g: FakeGmail) -> None:
        self.g = g

    def list(self, userId: str, startHistoryId: str, historyTypes: list[str], labelId: str,  # noqa: N803
             pageToken: str | None = None) -> _Req:
        self.g.calls.append("history.list")

        def run() -> dict[str, Any]:
            if self.g.history_error:
                raise http_error(self.g.history_error)
            index = int(pageToken or 0)
            page = self.g.history_pages[index] if index < len(self.g.history_pages) else {"added": []}
            out: dict[str, Any] = {
                "history": [{"id": "1", "messagesAdded": [
                    {"message": {"id": i, "threadId": i, "labelIds": self.g.resources[i]["labelIds"]}}
                    for i in page["added"]]}],
                "historyId": page.get("historyId", str(self.g.history_id)),
            }
            if index + 1 < len(self.g.history_pages):
                out["nextPageToken"] = str(index + 1)
            return out

        return _Req(run)


class _Messages:
    def __init__(self, g: FakeGmail) -> None:
        self.g = g

    def list(self, userId: str, q: str = "", pageToken: str | None = None,  # noqa: N803
             maxResults: int | None = None) -> _Req:  # noqa: N803
        self.g.calls.append("messages.list")
        self.g.last_list_q = q
        source = self.g.sent_listed if "in:sent" in q else self.g.listed_ids
        ids = source[:maxResults] if maxResults else source
        return _Req(lambda: {"messages": [{"id": i, "threadId": i} for i in ids]})

    def get(self, userId: str, id: str, format: str = "full",  # noqa: A002, N803
            metadataHeaders: list[str] | None = None) -> _Req:  # noqa: N803
        self.g.calls.append(f"messages.get:{format}")

        def run() -> dict[str, Any]:
            if id in self.g.get_errors:
                raise http_error(self.g.get_errors[id])
            return self.g.resources[id]

        return _Req(run)

    def send(self, userId: str, body: dict[str, Any]) -> _Req:  # noqa: N803
        self.g.calls.append("messages.send")

        def run() -> dict[str, Any]:
            if self.g.send_error is not None:
                raise self.g.send_error
            self.g.sent.append(body)
            return {"id": f"sent{len(self.g.sent)}", "threadId": body.get("threadId", "newthread")}

        return _Req(run)
