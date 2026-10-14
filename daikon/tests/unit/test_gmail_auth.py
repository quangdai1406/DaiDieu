import json

import pytest

from daikon.gmail.auth import SCOPES, TOKEN_NAME, credentials_from_store
from daikon.secretstore import MemorySecretStore

pytestmark = pytest.mark.unit


def test_scopes_are_read_only_except_gmail_send() -> None:
    assert SCOPES == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    writers = [s for s in SCOPES if not s.endswith(".readonly")]
    assert writers == ["https://www.googleapis.com/auth/gmail.send"]


def test_credentials_load_from_the_secret_store_without_network() -> None:
    store = MemorySecretStore()
    store.set(TOKEN_NAME, json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "id", "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token",
    }))
    creds = credentials_from_store(store)
    assert creds.refresh_token == "r" and set(creds.scopes or []) == set(SCOPES)
