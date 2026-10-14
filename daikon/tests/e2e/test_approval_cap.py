"""The daily approvals cap is consumed by successful approvals only."""

from pathlib import Path

import pytest

from daikon.config import Limits
from tests.e2e.test_skeleton import DAI, rig

pytestmark = [pytest.mark.unit, pytest.mark.security]


def codes(r) -> list[str]:
    bodies = [m.body for m in r.mailbox.sent if m.to == [DAI]]
    return [ln.split()[1] for b in bodies for ln in b.splitlines() if ln.startswith("OK ")]


def test_approvals_beyond_the_daily_cap_are_refused_and_dai_is_told(tmp_path: Path) -> None:
    r = rig(tmp_path, limits=Limits(approvals_per_day=1))
    r.inbound("m1", "bob@example.org", "One")
    r.inbound("m2", "bob@example.org", "Two")
    r.pipe.poll()
    first, second = codes(r)
    r.inbound("c1", DAI, f"OK {first}")
    r.inbound("c2", DAI, f"OK {second}")
    r.pipe.poll()
    states = sorted(n.status for n in r.store.find(type="approval"))
    assert states == ["held", "pending"]
    assert any("daily approval limit" in m.subject.lower() for m in r.sent_to(DAI))


def test_a_wrong_code_does_not_use_up_the_cap(tmp_path: Path) -> None:
    r = rig(tmp_path, limits=Limits(approvals_per_day=1))
    r.inbound("m1", "bob@example.org", "One")
    r.pipe.poll()
    r.inbound("c0", DAI, "OK ZZZZ")
    r.inbound("c1", DAI, f"OK {codes(r)[0]}")
    r.pipe.poll()
    assert [n.status for n in r.store.find(type="approval")] == ["held"]
