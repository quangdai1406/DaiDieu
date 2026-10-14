"""Load and validate Daikon's configuration. Secrets are never read from config files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

BACKENDS = frozenset({"anthropic_api", "openai_compat"})
DATA_CLASSES = frozenset({"local", "allowlisted", "cloud"})
REQUIRED_ROLES = ("triage", "draft")
_SECRET_WORDS = ("api_key", "apikey", "token", "password", "secret", "authorization")


class ConfigError(ValueError):
    """Raised for invalid configuration."""


@dataclass(frozen=True)
class RoleConfig:
    backend: str
    model: str
    data_class: str


@dataclass(frozen=True)
class Limits:
    model_runs_per_day: int = 200
    dollars_per_month: float = 20.0
    sends_per_day: int = 30


@dataclass(frozen=True)
class Config:
    data_dir: Path
    roles: dict[str, RoleConfig]
    limits: Limits


def _reject_secret_keys(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if any(w in str(key).lower() for w in _SECRET_WORDS):
                raise ConfigError(f"secret-like key {path}{key!r} is not allowed in config files")
            _reject_secret_keys(value, f"{path}{key}.")
    elif isinstance(node, list):
        for item in node:
            _reject_secret_keys(item, path)


def _role(name: str, raw: Any) -> RoleConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"role {name!r} must be a mapping")
    backend, model, data_class = raw.get("backend"), raw.get("model"), raw.get("data_class")
    if backend not in BACKENDS:
        raise ConfigError(f"role {name!r}: unknown backend {backend!r}")
    if data_class not in DATA_CLASSES:
        raise ConfigError(f"role {name!r}: unknown data_class {data_class!r}")
    if not model or not isinstance(model, str):
        raise ConfigError(f"role {name!r}: model is required")
    return RoleConfig(backend=backend, model=model, data_class=data_class)


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    _reject_secret_keys(raw)
    roles_raw = raw.get("roles") or {}
    for required in REQUIRED_ROLES:
        if required not in roles_raw:
            raise ConfigError(f"missing required role {required!r}")
    roles = {name: _role(name, body) for name, body in roles_raw.items()}
    data_dir = Path(raw["data_dir"]) if raw.get("data_dir") else Path.home() / "daikon-data"
    limits = Limits(**(raw.get("limits") or {}))
    return Config(data_dir=data_dir, roles=roles, limits=limits)
