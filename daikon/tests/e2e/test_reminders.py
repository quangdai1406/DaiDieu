"""M5.2: one reminder after 24h, an expiry notice at 72h. Both go to Dai only, never twice."""

from datetime import timedelta
from pathlib import Path

import pytest

from tests.e2e.test_skeleton import DAI, Rig, rig

pytestmark = [pytest.mark.unit, pytest.mark.security]


def waiting(tmp_path: Path) -> Rig:
    r = rig(tmp_path)
    r.inbound("m1", "bob@example.org", "Lunch?", subject="Lunch plans")
    r.pipe.poll()
    return r


def to_dai(r: Rig) -> list:
    return r.sent_to(DAI)


def test_no_reminder_before_24_hours(tmp_path: Path) -> None:
    r = waiting(tmp_path)
    r.clock.advance(timedelta(hours=23))
    r.pipe.housekeeping()
    assert len(to_dai(r)) == 1


def test_one_reminder_after_24_hours_and_never_a_second(tmp_path: Path) -> None:
    r = waiting(tmp_path)
    r.clock.advance(timedelta(hours=25))
    r.pipe.housekeeping()
    r.pipe.housekeeping()
    r.clock.advance(timedelta(hours=10))
    r.pipe.housekeeping()
    notes = to_dai(r)
    assert len(notes) == 2
    assert "Lunch plans" in notes[1].subject and "reminder" in notes[1].subject.lower()
    assert r.digest_code() not in notes[1].body  # codes appear only in the digest


def test_expiry_notice_is_sent_once_with_the_subject(tmp_path: Path) -> None:
    r = waiting(tmp_path)
    r.clock.advance(timedelta(hours=73))
    r.pipe.housekeeping()
    r.pipe.housekeeping()
    notes = to_dai(r)
    assert [n.subject for n in notes[1:]] == ["Daikon: expired without an answer: Re: Lunch plans"]
    assert r.sent_to("bob@example.org") == []


def test_an_answered_request_gets_no_reminder(tmp_path: Path) -> None:
    r = waiting(tmp_path)
    r.inbound("c1", DAI, f"NO {r.digest_code()}")
    r.pipe.poll()
    count = len(to_dai(r))
    r.clock.advance(timedelta(hours=30))
    r.pipe.housekeeping()
    assert len(to_dai(r)) == count
