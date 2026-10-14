from pathlib import Path

import pytest

from daikon.config import ConfigError, load_config

pytestmark = pytest.mark.unit

GOOD = """
data_dir: {data}
identity: {{emails: [dai@example.com]}}
roles:
  triage: {{backend: anthropic_api, model: small-model, data_class: cloud}}
  draft:  {{backend: anthropic_api, model: big-model,   data_class: cloud}}
limits:
  model_runs_per_day: 200
  dollars_per_month: 20
  sends_per_day: 30
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_valid_config(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, GOOD.format(data=tmp_path / "d")))
    assert cfg.roles["triage"].backend == "anthropic_api"
    assert cfg.limits.sends_per_day == 30
    assert cfg.data_dir == tmp_path / "d"


def test_unknown_backend_rejected(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path).replace("anthropic_api", "mystery", 1)
    with pytest.raises(ConfigError, match="backend"):
        load_config(write(tmp_path, text))


def test_unknown_data_class_rejected(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path).replace("cloud", "public", 1)
    with pytest.raises(ConfigError, match="data_class"):
        load_config(write(tmp_path, text))


def test_missing_required_role_rejected(tmp_path: Path) -> None:
    text = ("data_dir: x\nidentity: {emails: [dai@example.com]}\n"
            "roles: {triage: {backend: anthropic_api, model: m, data_class: cloud}}\n")
    with pytest.raises(ConfigError, match="draft"):
        load_config(write(tmp_path, text))


def test_secret_like_keys_in_file_are_rejected(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path) + "api_key: sk-whatever\n"
    with pytest.raises(ConfigError, match="secret"):
        load_config(write(tmp_path, text))


def test_nested_secret_key_rejected(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path).replace("model: small-model", "model: m, token: abc", 1)
    with pytest.raises(ConfigError, match="secret"):
        load_config(write(tmp_path, text))


def test_default_data_dir_is_under_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    text = GOOD.format(data="").replace("data_dir: \n", "")
    cfg = load_config(write(tmp_path, text))
    assert cfg.data_dir == Path.home() / "daikon-data"


ROLE_FULL = """
data_dir: {data}
identity: {{emails: [dai@example.com]}}
roles:
  triage:
    backend: anthropic_api
    model: small-model
    data_class: cloud
    max_tokens: 800
    effort: low
    timeout_s: 30
    price: {{input: 0.10, output: 0.50, cache_read: 0.01}}
  draft: {{backend: anthropic_api, model: big-model, data_class: cloud}}
"""


def test_role_settings_are_parsed(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, ROLE_FULL.format(data=tmp_path)))
    t = cfg.roles["triage"]
    assert (t.max_tokens, t.effort, t.timeout_s) == (800, "low", 30.0)
    assert t.price is not None and (t.price.input, t.price.output, t.price.cache_read) == (0.1, 0.5, 0.01)
    d = cfg.roles["draft"]
    assert d.max_tokens == 2000 and d.effort is None and d.price is None


def test_unknown_effort_is_rejected(tmp_path: Path) -> None:
    text = ROLE_FULL.format(data=tmp_path).replace("effort: low", "effort: extreme")
    with pytest.raises(ConfigError, match="effort"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("bad", ["input: -1, output: 1", "input: 1", "input: x, output: 1"])
def test_bad_prices_are_rejected(tmp_path: Path, bad: str) -> None:
    text = ROLE_FULL.format(data=tmp_path).replace("input: 0.10, output: 0.50, cache_read: 0.01", bad)
    with pytest.raises(ConfigError, match="price"):
        load_config(write(tmp_path, text))


APP_CFG = """
data_dir: {data}
identity:
  emails: [Dai@Example.com, dai.work@example.com]
  phones: ["+1 (555) 000-1111"]
outbound_mode: dai_only
second_brain_root_id: 1j8kRB_OiGRirovIVL6gOfjIIhge0ktBk
style_file: style.md
roles:
  triage: {{backend: anthropic_api, model: small-model, data_class: cloud}}
  draft:  {{backend: anthropic_api, model: big-model,   data_class: cloud}}
"""


def test_app_settings_are_parsed_and_normalized(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, APP_CFG.format(data=tmp_path)))
    assert cfg.identity.emails == frozenset({"dai@example.com", "dai.work@example.com"})
    assert cfg.identity.phones == frozenset({"+15550001111"})
    assert cfg.outbound_mode == "dai_only" and cfg.dai_email == "dai@example.com"
    assert cfg.second_brain_root_id == "1j8kRB_OiGRirovIVL6gOfjIIhge0ktBk"
    assert cfg.style_file == tmp_path / "style.md"


def test_identity_is_required_and_needs_an_email(tmp_path: Path) -> None:
    without = GOOD.format(data=tmp_path).replace("identity: {emails: [dai@example.com]}\n", "")
    with pytest.raises(ConfigError, match="identity"):
        load_config(write(tmp_path, without))
    text = APP_CFG.format(data=tmp_path).replace("[Dai@Example.com, dai.work@example.com]", "[]")
    with pytest.raises(ConfigError, match="identity"):
        load_config(write(tmp_path, text))


def test_outbound_mode_defaults_to_the_safe_value_and_rejects_unknown(tmp_path: Path) -> None:
    text = APP_CFG.format(data=tmp_path).replace("outbound_mode: dai_only\n", "")
    assert load_config(write(tmp_path, text)).outbound_mode == "dai_only"
    bad = APP_CFG.format(data=tmp_path).replace("dai_only", "yolo")
    with pytest.raises(ConfigError, match="outbound_mode"):
        load_config(write(tmp_path, bad))


def test_second_brain_and_style_are_optional(tmp_path: Path) -> None:
    text = (APP_CFG.format(data=tmp_path)
            .replace("second_brain_root_id: 1j8kRB_OiGRirovIVL6gOfjIIhge0ktBk\n", "")
            .replace("style_file: style.md\n", ""))
    cfg = load_config(write(tmp_path, text))
    assert cfg.second_brain_root_id is None and cfg.style_file is None


def test_bad_phone_numbers_are_rejected(tmp_path: Path) -> None:
    text = APP_CFG.format(data=tmp_path).replace("+1 (555) 000-1111", "call me")
    with pytest.raises(ConfigError, match="phone"):
        load_config(write(tmp_path, text))


def test_hold_seconds_defaults_to_60_and_accepts_10_to_600(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path / "d")
    assert load_config(write(tmp_path, text)).hold_seconds == 60
    assert load_config(write(tmp_path, text + "hold_seconds: 120\n")).hold_seconds == 120


@pytest.mark.parametrize("bad", ["0", "9", "601", "true", "'60'", "1.5"])
def test_hold_seconds_out_of_range_is_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match="hold_seconds"):
        load_config(write(tmp_path, GOOD.format(data=tmp_path / "d") + f"hold_seconds: {bad}\n"))


def test_twilio_number_is_optional_and_must_be_e164(tmp_path: Path) -> None:
    text = GOOD.format(data=tmp_path / "d")
    assert load_config(write(tmp_path, text)).twilio_number is None
    ok = load_config(write(tmp_path, text + 'twilio_number: "+15550009999"\n'))
    assert ok.twilio_number == "+15550009999"
    with pytest.raises(ConfigError, match="twilio_number"):
        load_config(write(tmp_path, text + 'twilio_number: "555-1234"\n'))
