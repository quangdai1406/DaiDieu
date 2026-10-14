"""First reply to a new person: Dai approves, then confirms once by SMS. Email cannot confirm."""

import re
from datetime import timedelta
from pathlib import Path

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.graph.store import GraphStore
from daikon.sms import DaiSms, SmsInbox
from tests.e2e.test_skeleton import DAI, T0, Rig, rig
from tests.unit.test_sms import DAI_PHONE, IDENT, OURS, FakeTransport, sms

pytestmark = [pytest.mark.unit, pytest.mark.security]
STRANGER = "stranger@example.net"


class AllowAll:
    def evaluate(self, action: object) -> object:
        return type("D", (), {"verdict": "allow"})()


def build(tmp_path: Path, with_sms: bool = True) -> tuple[Rig, FakeTransport]:
    t = FakeTransport()
    clock = FakeClock(T0)
    inbox = SmsInbox(t, GraphStore(tmp_path / "sg"), IDENT, OURS, clock,
                     AuditLog(tmp_path / "sa", clock))
    r = rig(tmp_path, known=set(), sms=inbox if with_sms else None,
            dai_sms=DaiSms(t, AllowAll(), DAI_PHONE) if with_sms else None)  # type: ignore[arg-type]
    inbox._clock = r.clock  # noqa: SLF001 - one shared test clock
    return r, t


def approved_waiting(tmp_path: Path, with_sms: bool = True) -> tuple[Rig, FakeTransport]:
    r, t = build(tmp_path, with_sms)
    r.inbound("m1", STRANGER, "Hello", subject="Intro")
    r.pipe.poll()
    r.inbound("c1", DAI, f"OK {r.digest_code()}")
    r.pipe.poll()
    r.clock.advance(timedelta(seconds=61))
    r.pipe.release_due()
    return r, t


def confirm_code(t: FakeTransport) -> str:
    text = next(b for to, b in t.sent if to == DAI_PHONE and "CONFIRM" in b)
    return re.search(r"CONFIRM ([A-Z0-9]{4})", text).group(1)  # type: ignore[union-attr]


def states(r: Rig) -> set[str]:
    return {n.status for n in r.store.find(type="approval")}


def test_a_first_reply_waits_for_a_confirmation_text(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    assert r.sent_to(STRANGER) == [] and states(r) == {"needs_confirmation"}
    (text,) = [b for to, b in t.sent if to == DAI_PHONE]
    assert STRANGER in text and "CONFIRM" in text


def test_confirming_by_sms_sends_once_and_marks_the_person_known(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    t.inbound = [sms("S1", f"CONFIRM {confirm_code(t)}")]
    r.pipe.poll()
    assert len(r.sent_to(STRANGER)) == 1 and states(r) == {"sent"}
    assert r.people.is_known(STRANGER)
    t.inbound = [sms("S2", f"CONFIRM {confirm_code(t)}")]
    r.pipe.poll()
    assert len(r.sent_to(STRANGER)) == 1  # one-time


def test_confirm_by_email_is_ignored(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    r.inbound("c2", DAI, f"CONFIRM {confirm_code(t)}")
    r.pipe.poll()
    assert r.sent_to(STRANGER) == [] and states(r) == {"needs_confirmation"}


def test_confirm_from_another_number_is_ignored(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    t.inbound = [sms("S1", f"CONFIRM {confirm_code(t)}", frm="+15557770000")]
    r.pipe.poll()
    assert r.sent_to(STRANGER) == [] and states(r) == {"needs_confirmation"}


def test_wrong_codes_lock_out_and_the_right_code_then_fails(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    right = confirm_code(t)
    t.inbound = [sms(f"W{i}", "CONFIRM " + c) for i, c in enumerate(["2222", "3333", "4444"])]
    r.pipe.poll()
    t.inbound = [sms("R1", f"CONFIRM {right}")]
    r.pipe.poll()
    assert r.sent_to(STRANGER) == [] and states(r) == {"needs_confirmation"}


def test_an_unconfirmed_request_expires_and_dai_is_told(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    r.clock.advance(timedelta(minutes=31))
    r.pipe.housekeeping()
    t.inbound = [sms("S1", f"CONFIRM {confirm_code(t)}", age_min=0)]
    r.pipe.poll()
    assert r.sent_to(STRANGER) == [] and states(r) == {"expired"}
    assert any("expired" in m.subject for m in r.sent_to(DAI))


def test_without_sms_the_reply_still_fails_closed_and_dai_is_told(tmp_path: Path) -> None:
    r, _ = approved_waiting(tmp_path, with_sms=False)
    assert r.sent_to(STRANGER) == [] and states(r) == {"failed"}
    assert any("not sent" in m.subject for m in r.sent_to(DAI))


def test_a_failed_text_means_fail_closed(tmp_path: Path) -> None:
    r, t = build(tmp_path)

    def boom(to: str, body: str) -> str:
        raise OSError("net")

    t.send = boom  # type: ignore[method-assign]
    r.inbound("m1", STRANGER, "Hello")
    r.pipe.poll()
    r.inbound("c1", DAI, f"OK {r.digest_code()}")
    r.pipe.poll()
    r.clock.advance(timedelta(seconds=61))
    r.pipe.release_due()
    assert r.sent_to(STRANGER) == [] and states(r) == {"failed"}


def test_confirming_while_paused_does_not_send(tmp_path: Path) -> None:
    r, t = approved_waiting(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    t.inbound = [sms("S1", f"CONFIRM {confirm_code(t)}")]
    r.pipe.poll()
    assert r.sent_to(STRANGER) == [] and states(r) == {"needs_confirmation"}
