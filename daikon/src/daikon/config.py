"""Load and validate Daikon's configuration. Secrets are never read from config files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from daikon.guard import is_secret_key
from daikon.identity import DaiIdentity

BACKENDS = frozenset({"anthropic_api", "openai_compat"})
DATA_CLASSES = frozenset({"local", "allowlisted", "cloud"})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
REQUIRED_ROLES = ("triage", "draft")


class ConfigError(ValueError):
    """Raised for invalid configuration."""


@dataclass(frozen=True)
class Price:
    """USD per million tokens (copy from the provider's pricing page; note the date)."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None


@dataclass(frozen=True)
class RoleConfig:
    backend: str
    model: str
    data_class: str
    max_tokens: int = 2000
    effort: str | None = None
    timeout_s: float = 60.0
    price: Price | None = None


@dataclass(frozen=True)
class Limits:
    model_runs_per_day: int = 200
    dollars_per_month: float = 20.0
    sends_per_day: int = 30
    sms_per_day: int = 20
    approvals_per_day: int = 50
    per_sender_per_hour: int = 10
    alerts_per_day: int = 20


@dataclass(frozen=True)
class Config:
    data_dir: Path
    roles: dict[str, RoleConfig]
    limits: Limits
    identity: DaiIdentity
    dai_email: str
    outbound_mode: str = "dai_only"
    second_brain_root_id: str | None = None
    style_file: Path | None = None
    hold_seconds: int = 60


def _reject_secret_keys(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if is_secret_key(str(key)):
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
    effort = raw.get("effort")
    if effort is not None and effort not in EFFORTS:
        raise ConfigError(f"role {name!r}: unknown effort {effort!r}")
    return RoleConfig(
        backend=backend, model=model, data_class=data_class,
        max_tokens=int(raw.get("max_tokens", 2000)), effort=effort,
        timeout_s=float(raw.get("timeout_s", 60)), price=_price(name, raw.get("price")),
    )


def _price(role: str, raw: Any) -> Price | None:
    if raw is None:
        return None
    try:
        values = {k: float(v) for k, v in raw.items()}
        price = Price(values["input"], values["output"], values.get("cache_read"),
                      values.get("cache_write"))
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ConfigError(f"role {role!r}: price needs numeric input and output") from None
    if min(v for v in (price.input, price.output) ) < 0:
        raise ConfigError(f"role {role!r}: price values must not be negative")
    return price


def _identity(raw: Any) -> tuple[DaiIdentity, str]:
    if not isinstance(raw, dict) or not raw.get("emails"):
        raise ConfigError("identity.emails is required (Dai's own addresses)")
    emails = [str(e).strip().lower() for e in raw["emails"]]
    if any("@" not in e for e in emails):
        raise ConfigError("identity.emails must be email addresses")
    phones = set()
    for p in raw.get("phones") or []:
        cleaned = re.sub(r"[\s\-().]", "", str(p))
        if not re.fullmatch(r"\+\d{8,15}", cleaned):
            raise ConfigError(f"identity.phones: bad phone number {p!r} (use +countrycode...)")
        phones.add(cleaned)
    return DaiIdentity(frozenset(emails), frozenset(phones)), emails[0]


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
    identity, dai_email = _identity(raw.get("identity"))
    mode = raw.get("outbound_mode", "dai_only")
    if mode not in ("dai_only", "live"):
        raise ConfigError(f"outbound_mode must be dai_only or live, got {mode!r}")
    hold = raw.get("hold_seconds", 60)
    if not isinstance(hold, int) or isinstance(hold, bool) or not 10 <= hold <= 600:
        raise ConfigError(f"hold_seconds must be a whole number from 10 to 600, got {hold!r}")
    style = raw.get("style_file")
    return Config(
        data_dir=data_dir, roles=roles, limits=limits, identity=identity, dai_email=dai_email,
        outbound_mode=mode, second_brain_root_id=raw.get("second_brain_root_id") or None,
        style_file=(data_dir / str(style)) if style else None, hold_seconds=hold,
    )
