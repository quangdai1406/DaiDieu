"""M5.5: SMS channel. Only Dai's verified number can command; sends go through policy."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.graph.store import GraphStore
from daikon.identity import DaiIdentity
from daikon.sms import DaiSms, InboundSms, SmsInbox, TwilioTransport

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
DAI_PHONE, OURS = "+15550001111", "+15550009999"
IDENT = DaiIdentity(frozenset({"dai@example.com"}), frozenset({DAI_PHONE}))


class FakeTransport:
    def __init__(self) -> None:
        self.inbound: list[InboundSms] = []
        self.sent: list[tuple[str, str]] = []

    def list_inbound(self) -> list[InboundSms]:
        return list(self.inbound)

    def send(self, to: str, body: str) -> str:
        self.sent.append((to, body))
        return "SMsent"


def sms(id_: str, body: str, frm: str = DAI_PHONE, to: str = OURS, age_min: int = 1) -> InboundSms:
    return InboundSms(id_, frm, to, body, T0 - timedelta(minutes=age_min))


def inbox(tmp_path: Path) -> tuple[SmsInbox, FakeTransport]:
    clock = FakeClock(T0)
    t = FakeTransport()
    return SmsInbox(t, GraphStore(tmp_path / "g"), IDENT, OURS, clock,
                    AuditLog(tmp_path / "a", clock)), t


def test_a_command_from_dais_number_is_accepted(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "ok 7k2f")]
    (cmd,) = box.fetch_commands()
    assert (cmd.verb, cmd.code, cmd.actor) == ("OK", "7K2F", DAI_PHONE)


def test_pause_and_edit_arguments_work(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "PAUSE"), sms("S2", "EDIT 7K2F shorter please")]
    pause, edit = box.fetch_commands()
    assert pause.verb == "PAUSE" and edit.arg == "shorter please"


@pytest.mark.parametrize("frm", ["+15559998888", "+15550001112", "dai@example.com", ""])
def test_other_numbers_are_ignored(tmp_path: Path, frm: str) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "OK 7K2F", frm=frm)]
    assert box.fetch_commands() == []


def test_a_message_not_addressed_to_our_number_is_ignored(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "OK 7K2F", to="+15551230000")]
    assert box.fetch_commands() == []


def test_each_message_is_processed_once(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "OK 7K2F")]
    assert len(box.fetch_commands()) == 1
    assert box.fetch_commands() == []


def test_old_messages_are_not_replayed(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "OK 7K2F", age_min=3 * 60)]
    assert box.fetch_commands() == []


def test_chatter_and_embedded_commands_are_not_commands(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)
    t.inbound = [sms("S1", "hello there"), sms("S2", "thanks. OK 7K2F"), sms("S3", "")]
    assert box.fetch_commands() == []


def test_transport_failure_returns_nothing_and_is_audited(tmp_path: Path) -> None:
    box, t = inbox(tmp_path)

    def boom() -> list[InboundSms]:
        raise OSError("net")

    t.list_inbound = boom  # type: ignore[method-assign]
    assert box.fetch_commands() == []


# ---------- sending ----------
class StubPolicy:
    def __init__(self, verdict: str = "allow") -> None:
        self.verdict = verdict
        self.seen: list[Any] = []

    def evaluate(self, action: Any) -> Any:
        self.seen.append(action)
        return type("D", (), {"verdict": self.verdict})()


def test_sms_to_dai_goes_through_policy_and_is_trimmed() -> None:
    t, p = FakeTransport(), StubPolicy()
    assert DaiSms(t, p, DAI_PHONE).send("x" * 500) is True  # type: ignore[arg-type]
    assert t.sent == [(DAI_PHONE, "x" * 320)]
    assert p.seen[0].recipients == (DAI_PHONE,)


def test_sms_denied_by_policy_is_not_sent() -> None:
    t = FakeTransport()
    assert DaiSms(t, StubPolicy("deny"), DAI_PHONE).send("hi") is False  # type: ignore[arg-type]
    assert t.sent == []


def test_sms_send_failure_returns_false() -> None:
    t = FakeTransport()

    def boom(to: str, body: str) -> str:
        raise OSError("net")

    t.send = boom  # type: ignore[method-assign]
    assert DaiSms(t, StubPolicy(), DAI_PHONE).send("hi") is False  # type: ignore[arg-type]


# ---------- Twilio REST ----------
def test_twilio_lists_only_inbound_to_our_number_and_sends_with_basic_auth() -> None:
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def http(method: str, url: str, auth: tuple[str, str], data: dict[str, str] | None) -> dict:
        calls.append((method, url, data))
        assert auth == ("SKkey", "secret")
        if method == "GET":
            return {"messages": [
                {"sid": "SM1", "from": DAI_PHONE, "to": OURS, "body": "OK 7K2F",
                 "direction": "inbound", "date_sent": "Wed, 14 Oct 2026 08:59:00 +0000"},
                {"sid": "SM2", "from": OURS, "to": DAI_PHONE, "body": "out",
                 "direction": "outbound-api", "date_sent": "Wed, 14 Oct 2026 08:58:00 +0000"},
            ]}
        return {"sid": "SM9"}

    t = TwilioTransport("ACxx", "SKkey", "secret", OURS, http)
    (m,) = t.list_inbound()
    assert m == InboundSms("SM1", DAI_PHONE, OURS, "OK 7K2F", datetime(2026, 10, 14, 8, 59, tzinfo=UTC))
    assert "To=%2B15550009999" in calls[0][1] and "/Accounts/ACxx/Messages.json" in calls[0][1]
    assert t.send(DAI_PHONE, "hello") == "SM9"
    assert calls[1][0] == "POST" and calls[1][2] == {"To": DAI_PHONE, "From": OURS, "Body": "hello"}
