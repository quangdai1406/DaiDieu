"""M5.3: PAUSE and RESUME through the pipeline."""

from datetime import timedelta
from pathlib import Path

import pytest

from tests.e2e.test_skeleton import DAI, Rig, rig

pytestmark = [pytest.mark.unit, pytest.mark.security]


def digest_code(r: Rig, index: int = 0) -> str:
    bodies = [m.body for m in r.mailbox.sent if m.to == [DAI] and "\nOK " in m.body]
    return next(ln.split()[1] for ln in bodies[index].splitlines() if ln.startswith("OK "))


def resume_code(r: Rig) -> str:
    note = next(m for m in r.mailbox.sent if m.to == [DAI] and "RESUME" in m.body)
    return next(ln.split()[1] for ln in note.body.splitlines() if ln.startswith("RESUME "))


def approved_and_waiting(tmp_path: Path) -> Rig:
    r = rig(tmp_path)
    r.inbound("m1", "bob@example.org", "Hello")
    r.pipe.poll()
    r.inbound("c1", DAI, f"OK {digest_code(r)}")
    r.pipe.poll()
    return r


def test_pause_blocks_sends_and_resume_with_the_code_releases_them(tmp_path: Path) -> None:
    r = approved_and_waiting(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    assert (tmp_path / "PAUSE").exists()
    r.clock.advance(timedelta(minutes=5))
    r.pipe.release_due()
    assert r.sent_to("bob@example.org") == []
    r.inbound("r1", DAI, f"RESUME {resume_code(r)}")
    r.pipe.poll()
    r.pipe.release_due()
    assert len(r.sent_to("bob@example.org")) == 1 and not (tmp_path / "PAUSE").exists()


def test_new_mail_is_still_drafted_while_paused_but_nothing_is_sent(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    r.inbound("m1", "bob@example.org", "Hello")
    r.pipe.poll()
    assert any("\nOK " in m.body for m in r.sent_to(DAI))


def test_wrong_resume_codes_keep_it_paused(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    r.inbound("r1", DAI, "RESUME ZZZZ")
    r.pipe.poll()
    assert (tmp_path / "PAUSE").exists()


def test_a_forged_or_quoted_pause_does_nothing(tmp_path: Path) -> None:
    from daikon.mail import AuthResults

    r = rig(tmp_path)
    r.inbound("p1", "evil@example.net", "PAUSE")
    r.inbound("p2", DAI, "PAUSE", auth=AuthResults())
    r.inbound("p3", DAI, "FYI\n> PAUSE")
    r.pipe.poll()
    assert not (tmp_path / "PAUSE").exists()


def test_the_pause_notice_goes_to_dai_and_never_to_anyone_else(tmp_path: Path) -> None:
    r = rig(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    assert all(m.to == [DAI] for m in r.mailbox.sent) and r.mailbox.sent


def test_approvals_that_wait_too_long_during_a_pause_expire_instead_of_sending(tmp_path: Path) -> None:
    r = approved_and_waiting(tmp_path)
    r.inbound("p1", DAI, "PAUSE")
    r.pipe.poll()
    r.clock.advance(timedelta(days=2))
    r.pipe.housekeeping()
    r.inbound("r1", DAI, f"RESUME {resume_code(r)}")
    r.pipe.poll()
    r.pipe.release_due()
    assert r.sent_to("bob@example.org") == []
    assert {n.status for n in r.store.find(type="approval")} == {"expired"}
