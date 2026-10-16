"""M6: the composition root wires every part together; `doctor` checks a setup."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from daikon.app import App, build_app, doctor
from daikon.audit import verify
from daikon.clock import FakeClock
from daikon.config import Config, load_config
from daikon.mail import AuthResults, InboundEmail
from daikon.secretstore import MemorySecretStore
from daikon.testing import FakeGateway, FakeMailbox
from tests.contract.fake_drive import FOLDER, FakeDrive

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
DAI = "dai@example.com"
PASS = AuthResults("pass", "pass", "pass")
CFG = """
data_dir: {data}
identity: {{emails: [dai@example.com], phones: ["+15550001111"]}}
outbound_mode: {mode}
second_brain_root_id: root
roles:
  triage: {{backend: anthropic_api, model: small, data_class: cloud, price: {{input: 0.1, output: 0.5}}}}
  draft:  {{backend: anthropic_api, model: big, data_class: cloud, price: {{input: 2, output: 10}}}}
"""


def config(tmp_path: Path, mode: str = "dai_only") -> Config:
    p = tmp_path / "models.yaml"
    p.write_text(CFG.format(data=tmp_path / "data", mode=mode), encoding="utf-8")
    return load_config(p)


def drive() -> FakeDrive:
    d = FakeDrive()
    d.add("root", "Second Brain", ["drive-root"], FOLDER)
    d.add("a1", "Audit.md", ["root"], text="Acme audit is on March 3.")
    return d


def app(tmp_path: Path, mode: str = "dai_only", script: list[Any] | None = None
        ) -> tuple[App, FakeMailbox, FakeClock, FakeGateway]:
    clock, mailbox, gateway = FakeClock(T0), FakeMailbox(), FakeGateway(script=script)
    built = build_app(config(tmp_path, mode), MemorySecretStore(), clock, mailbox=mailbox,
                      gateway=gateway, drive_api=drive())
    return built, mailbox, clock, gateway


def mail(id_: str, frm: str, text: str, clock: FakeClock) -> InboundEmail:
    return InboundEmail(id=id_, thread_id=id_, from_addr=frm, to=("daikon@example.com",),
                        subject="Audit", text=text, html=None, auth=PASS, received=clock.now())


def test_one_tick_turns_mail_into_a_digest_using_the_second_brain(tmp_path: Path) -> None:
    built, mailbox, clock, gateway = app(tmp_path, script=[{"terms": ["Acme"]}, None])
    mailbox.inbox.append(mail("m1", "bob@example.org", "When is the Acme audit?", clock))
    assert built.runner.tick() is True
    (note,) = [m for m in mailbox.sent if m.to == [DAI]]
    assert "Audit.md" in note.body and "OK " in note.body
    assert gateway.roles == ["triage", "draft"]  # term proposal + draft


def test_shadow_mode_by_default_never_sends_to_anyone_else(tmp_path: Path) -> None:
    built, mailbox, clock, _ = app(tmp_path)
    mailbox.inbox.append(mail("m1", "bob@example.org", "Hello", clock))
    built.runner.tick()
    code = next(ln.split()[1] for ln in mailbox.sent[0].body.splitlines() if ln.startswith("OK "))
    mailbox.inbox.append(mail("c1", DAI, f"OK {code}", clock))
    built.runner.tick()
    clock.advance(timedelta(seconds=61))
    built.runner.tick()
    assert all(m.to == [DAI] for m in mailbox.sent)
    assert verify(tmp_path / "data" / "audit").ok


def test_live_mode_sends_the_approved_reply_to_a_known_recipient(tmp_path: Path) -> None:
    built, mailbox, clock, _ = app(tmp_path, mode="live")
    built.people.mark_contacted("bob@example.org")
    mailbox.inbox.append(mail("m1", "bob@example.org", "Hello", clock))
    built.runner.tick()
    code = next(ln.split()[1] for ln in mailbox.sent[0].body.splitlines() if ln.startswith("OK "))
    mailbox.inbox.append(mail("c1", DAI, f"OK {code}", clock))
    built.runner.tick()
    clock.advance(timedelta(seconds=61))
    built.runner.tick()
    assert [m.to for m in mailbox.sent if m.to != [DAI]] == [["bob@example.org"]]


def test_a_second_app_on_the_same_data_dir_cannot_run(tmp_path: Path) -> None:
    from daikon.graph.store import AlreadyRunningError

    first, _, _, _ = app(tmp_path)
    first.lock.acquire()
    try:
        second, _, _, _ = app(tmp_path)
        with pytest.raises(AlreadyRunningError):
            second.run(lambda: True)
    finally:
        first.lock.release()


def test_doctor_reports_a_healthy_setup(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    secrets.set("anthropic_api_key", "sk-ant-test-" + "x" * 20)
    secrets.set("gmail_token", "{}")
    report = doctor(config(tmp_path), secrets, FakeClock(T0))
    assert report.ok, report.lines
    text = "\n".join(report.lines)
    assert "outbound_mode: dai_only" in text and "audit chain: ok" in text


def test_doctor_flags_missing_secrets_pause_and_live_mode(tmp_path: Path) -> None:
    cfg = config(tmp_path, mode="live")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "PAUSE").write_text("", encoding="utf-8")
    report = doctor(cfg, MemorySecretStore(), FakeClock(T0))
    text = "\n".join(report.lines)
    assert not report.ok
    assert "missing secret: anthropic_api_key" in text and "missing secret: gmail_token" in text
    assert "PAUSED" in text and "LIVE" in text


def test_doctor_detects_a_tampered_audit_log(tmp_path: Path) -> None:
    built, mailbox, clock, _ = app(tmp_path)
    mailbox.inbox.append(mail("m1", "bob@example.org", "Hello", clock))
    built.runner.tick()
    log = next((tmp_path / "data" / "audit").glob("*.jsonl"))
    log.write_text(log.read_text(encoding="utf-8").replace('"pipeline.ingest"', '"pipeline.xxxxxx"'))
    secrets = MemorySecretStore()
    secrets.set("anthropic_api_key", "sk-ant-test-" + "x" * 20)
    secrets.set("gmail_token", "{}")
    report = doctor(config(tmp_path), secrets, clock)
    assert not report.ok and any("audit chain: BROKEN" in ln for ln in report.lines)


def test_a_backup_is_made_during_normal_running(tmp_path: Path) -> None:
    built, mailbox, clock, _ = app(tmp_path)
    mailbox.inbox.append(mail("m1", "bob@example.org", "Hello", clock))
    built.runner.tick()
    backup = tmp_path / "data" / "backups" / "2026-10-14"
    assert (backup / "graph").is_dir() and (backup / "audit").is_dir()
    built.runner.tick()  # same day: no second copy, no error
    assert len(list((tmp_path / "data" / "backups").iterdir())) == 1
