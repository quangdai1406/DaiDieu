"""M6.3: the Windows Task Scheduler definition keeps Daikon running, once, without privileges."""

import xml.etree.ElementTree as ET  # noqa: S405
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
XML = Path(__file__).parents[2] / "deploy" / "windows" / "daikon-task.xml"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def root() -> ET.Element:
    return ET.fromstring(XML.read_text(encoding="utf-16"))  # noqa: S314 (repo-owned file)


def text(path: str) -> str:
    node = root().find(path, NS)
    assert node is not None, path
    return node.text or ""


def test_starts_at_logon_and_only_one_copy_runs() -> None:
    assert root().find("t:Triggers/t:LogonTrigger", NS) is not None
    assert text("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"


def test_restarts_itself_and_never_times_out() -> None:
    assert text("t:Settings/t:RestartOnFailure/t:Interval") == "PT1M"
    assert int(text("t:Settings/t:RestartOnFailure/t:Count")) >= 100
    assert text("t:Settings/t:ExecutionTimeLimit") == "PT0S"


def test_keeps_running_on_battery_and_catches_up_after_sleep() -> None:
    assert text("t:Settings/t:DisallowStartIfOnBatteries") == "false"
    assert text("t:Settings/t:StopIfGoingOnBatteries") == "false"
    assert text("t:Settings/t:StartWhenAvailable") == "true"


def test_runs_without_elevated_rights() -> None:
    assert text("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"


def test_runs_the_run_command_without_a_console_window() -> None:
    assert text("t:Actions/t:Exec/t:Command").endswith("pythonw.exe")
    args = text("t:Actions/t:Exec/t:Arguments")
    assert args.startswith("-m daikon run") and "--config" in args


def test_ships_placeholders_not_a_real_user_or_any_secret() -> None:
    raw = XML.read_text(encoding="utf-16").lower()
    assert "your-windows-user" in raw
    for bad in ("password", "api_key", "secret", "sk-ant", "bearer"):  # InteractiveToken is fine
        assert bad not in raw
