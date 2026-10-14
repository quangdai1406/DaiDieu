from pathlib import Path

import pytest

from daikon.config import load_config

pytestmark = pytest.mark.unit
EXAMPLE = Path(__file__).parents[2] / "models.yaml.example"


def test_the_example_config_loads_and_every_cloud_role_has_a_price() -> None:
    cfg = load_config(EXAMPLE)
    assert {"triage", "draft"} <= set(cfg.roles)
    for name, role in cfg.roles.items():
        if role.backend == "anthropic_api":
            assert role.price is not None, name
    assert cfg.limits.dollars_per_month > 0
