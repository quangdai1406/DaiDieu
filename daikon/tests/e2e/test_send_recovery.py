"""M6.2: exactly-once sending across crashes and ambiguous failures."""

from datetime import timedelta
from pathlib import Path

import pytest

from daikon.mail import PermanentSendError
from tests.e2e.test_skeleton import DAI, Rig, rig

pytestmark = [pytest.mark.unit, pytest.mark.security]


def approved(tmp_path: Path) -> Rig:
    r = rig(tmp_path)
    r.inbound("m1", "bob@example.org", "Hello")
    r.pipe.poll()
    code = next(ln.split()[1] for ln in r.mailbox.sent[0].body.splitlines() if ln.startswith("OK "))
    r.inbound("c1", DAI, f"OK {code}")
    r.pipe.poll()
    r.clock.advance(timedelta(seconds=61))
    return r


def state(r: Rig) -> str:
    return r.store.find(type="approval")[0].status


def to_bob(r: Rig) -> int:
    return len(r.sent_to("bob@example.org"))


def test_a_lost_response_after_a_real_send_is_resolved_from_the_sent_folder(tmp_path: Path) -> None:
    r = approved(tmp_path)
    r.mailbox.fail_with, r.mailbox.record_before_fail = ConnectionError("reset"), True
    r.pipe.release_due()
    assert state(r) == "sending" and to_bob(r) == 1  # it did go out, but we never heard back
    r.mailbox.fail_with = None
    r.clock.advance(timedelta(minutes=2))
    r.pipe.housekeeping()
    assert state(r) == "sent" and to_bob(r) == 1
    assert r.people.is_known("bob@example.org")


def test_a_failure_before_anything_was_sent_is_not_retried_blindly(tmp_path: Path) -> None:
    r = approved(tmp_path)
    r.mailbox.fail_with = ConnectionError("down")
    r.pipe.release_due()
    r.mailbox.fail_with = None
    r.clock.advance(timedelta(minutes=2))
    r.pipe.housekeeping()
    assert state(r) == "sending" and to_bob(r) == 0  # still waiting: Sent folder might lag
    r.pipe.release_due()
    assert to_bob(r) == 0  # a sending request is never sent again
    r.clock.advance(timedelta(minutes=10))
    r.pipe.housekeeping()
    assert state(r) == "failed" and to_bob(r) == 0
    note = [m for m in r.sent_to(DAI) if "couldn't confirm" in m.subject.lower()]
    assert len(note) == 1 and "bob@example.org" in note[0].body


def test_a_definite_rejection_fails_immediately_without_waiting(tmp_path: Path) -> None:
    r = approved(tmp_path)
    r.mailbox.fail_with = PermanentSendError("invalid recipient")
    r.pipe.release_due()
    assert state(r) == "failed" and to_bob(r) == 0


def test_a_crash_between_begin_send_and_the_send_is_recovered_without_a_double_send(tmp_path: Path) -> None:
    r = approved(tmp_path)
    (req,) = r.approvals.held_requests()
    assert r.approvals.begin_send(req.id).ok  # process "dies" here
    r.clock.advance(timedelta(minutes=2))
    r.pipe.housekeeping()
    assert state(r) == "sending"  # not found yet, not old enough to give up
    r.clock.advance(timedelta(minutes=10))
    r.pipe.housekeeping()
    assert state(r) == "failed" and to_bob(r) == 0


def test_recovery_leaves_fresh_sends_alone(tmp_path: Path) -> None:
    r = approved(tmp_path)
    (req,) = r.approvals.held_requests()
    r.approvals.begin_send(req.id)
    r.pipe.housekeeping()  # < 1 minute old
    assert state(r) == "sending"


def test_recovery_never_resends_even_when_called_repeatedly(tmp_path: Path) -> None:
    r = approved(tmp_path)
    r.mailbox.fail_with, r.mailbox.record_before_fail = TimeoutError("t"), True
    r.pipe.release_due()
    r.mailbox.fail_with = None
    for _ in range(5):
        r.clock.advance(timedelta(minutes=3))
        r.pipe.housekeeping()
        r.pipe.release_due()
    assert to_bob(r) == 1 and state(r) == "sent"
