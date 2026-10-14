"""Gmail OAuth helpers. Tokens live in the SecretStore (Windows Credential Manager), never on disk.

``authorize`` is interactive (opens a browser once) and is exercised manually; it is the
``live`` part of M2.4/M2.5. ``credentials_from_store`` is pure and unit tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials

from daikon.secretstore import SecretStore

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",  # Second Brain, shared with Daikon as Viewer
]
TOKEN_NAME = "gmail_token"  # noqa: S105 - the secret store key name, not a secret


def credentials_from_store(store: SecretStore) -> Credentials:
    info = json.loads(store.get(TOKEN_NAME))
    creds: Credentials = Credentials.from_authorized_user_info(info, SCOPES)  # type: ignore[no-untyped-call]
    return creds


def save_credentials(store: SecretStore, creds: Credentials) -> None:
    store.set(TOKEN_NAME, creds.to_json())  # type: ignore[no-untyped-call]


def authorize(client_secrets_file: Path, store: SecretStore) -> Credentials:
    from google_auth_oauthlib.flow import InstalledAppFlow  # imported lazily: interactive only

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    creds: Credentials = flow.run_local_server(port=0)
    save_credentials(store, creds)
    return creds


def build_drive_service(creds: Credentials) -> Any:
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def build_service(creds: Credentials) -> Any:
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
