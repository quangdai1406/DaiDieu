from pathlib import Path

import pytest

from daikon.config import ConfigError, load_config

pytestmark = pytest.mark.unit

GOOD = """
data_dir: {data}
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
    text = "data_dir: x\nroles: {triage: {backend: anthropic_api, model: m, data_class: cloud}}\n"
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
