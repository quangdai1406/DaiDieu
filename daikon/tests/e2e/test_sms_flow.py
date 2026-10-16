"""M5.5 end to end: approve by text message; alerts also go out by SMS."""

from datetime import timedelta
from pathlib import Path

import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.graph.store import GraphStore
from daikon.sms import SmsInbox
from tests.e2e.test_skeleton import DAI, T0, Rig, rig
from tests.unit.test_sms import DAI_PHONE, IDENT, OURS, FakeTransport, sms

pytestmark = [pytest.mark.unit, pytest.mark.security]


def with_sms(tmp_path: Path) -> tuple[Rig, FakeTransport]:
    t = FakeTransport()
    clock = FakeClock(T0)
    inbox = SmsInbox(t, GraphStore(tmp_path / "sms-graph"), IDENT, OURS, clock,
                     AuditLog(tmp_path / "sms-audit", clock))
    r = rig(tmp_path, sms=inbox)
    inbox._clock = r.clock  # noqa: SLF001 - one shared test clock
    return r, t


def test_ok_by_sms_approves_and_sends(tmp_path: Path) -> None:
    r, t = with_sms(tmp_path)
    r.inbound("m1", "bob@example.org", "Lunch?")
    r.pipe.poll()
    t.inbound = [sms("S1", f"OK {r.digest_code()}")]
    r.pipe.poll()
    r.clock.advance(timedelta(seconds=61))
    r.pipe.release_due()
    assert len(r.sent_to("bob@example.org")) == 1


def test_ok_from_a_stranger_number_does_nothing(tmp_path: Path) -> None:
    r, t = with_sms(tmp_path)
    r.inbound("m1", "bob@example.org", "Lunch?")
    r.pipe.poll()
    t.inbound = [sms("S1", f"OK {r.digest_code()}", frm="+15557770000")]
    r.pipe.poll()
    assert {n.status for n in r.store.find(type="approval")} == {"pending"}
    assert DAI_PHONE and DAI
