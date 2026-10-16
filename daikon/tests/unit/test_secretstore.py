from datetime import UTC, datetime, timedelta

import pytest

from daikon.secretstore import MemorySecretStore, SecretNotFoundError

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def test_set_and_get_round_trip() -> None:
    s = MemorySecretStore()
    s.set("anthropic_api_key", "value-1")
    assert s.get("anthropic_api_key") == "value-1"


def test_missing_secret_raises() -> None:
    with pytest.raises(SecretNotFoundError):
        MemorySecretStore().get("nope")


def test_expiring_within_lists_only_close_expiries() -> None:
    s = MemorySecretStore()
    s.set("soon", "a", expires_at=NOW + timedelta(days=10))
    s.set("later", "b", expires_at=NOW + timedelta(days=60))
    s.set("never", "c")
    assert s.expiring_within(timedelta(days=14), now=NOW) == ["soon"]


def test_expired_secret_is_listed_too() -> None:
    s = MemorySecretStore()
    s.set("old", "a", expires_at=NOW - timedelta(days=1))
    assert s.expiring_within(timedelta(days=14), now=NOW) == ["old"]


def test_repr_never_contains_secret_values() -> None:
    s = MemorySecretStore()
    s.set("k", "super-secret-value")
    assert "super-secret-value" not in repr(s)



def _install_memory_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring

    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))


def test_keyring_store_round_trip_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    from daikon.secretstore import KeyringSecretStore

    _install_memory_keyring(monkeypatch)
    s = KeyringSecretStore("daikon-test")
    s.set("gmail_token", "tok", expires_at=NOW + timedelta(days=3))
    s.set("twilio_key", "key")
    assert s.get("gmail_token") == "tok"
    assert s.expiring_within(timedelta(days=14), now=NOW) == ["gmail_token"]
    with pytest.raises(SecretNotFoundError):
        s.get("missing")
    assert "tok" not in repr(s)
