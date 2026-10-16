"""``anthropic_api`` backend: the Anthropic Messages API for text roles.

Properties enforced here (and tested):
  * no tools, no tool_choice, no sampling parameters and no thinking override are ever sent:
    the method signature cannot carry them, so a prompt injection has no tool to reach;
  * structured output via ``output_config.format`` (JSON schema; unsupported keywords are
    stripped from the API copy and enforced locally by the caller);
  * a daily run cap and a monthly dollar cap are checked before every call; the real cost is
    recorded afterwards even when it overshoots, and a role without a price cannot start;
  * sensitive-labelled input is refused for ``cloud`` roles;
  * the audit entry holds counts, cost and an input hash, never prompt text;
  * SDK errors are classified into ``GatewayError.kind``; the SDK itself retries 408/409/429/5xx
    and connection errors (configured in ``make_client``).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import anthropic

from daikon.audit import AuditLog
from daikon.config import ConfigError, Price, RoleConfig
from daikon.limiter import Limiter

BACKEND = "anthropic_api"
_UNSUPPORTED = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "minItems", "maxItems", "pattern",
})


class GatewayError(RuntimeError):
    """A model call could not produce a usable answer. ``kind`` says why."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class GatewayCapError(GatewayError):
    def __init__(self, reason: str) -> None:
        super().__init__("cap", reason)


class PrivacyBlockedError(GatewayError):
    def __init__(self, role: str) -> None:
        super().__init__("privacy", f"sensitive input is not allowed for cloud role {role!r}")


class ModelRefusalError(GatewayError):
    def __init__(self) -> None:
        super().__init__("refusal", "the model declined the request")


class TruncatedOutputError(GatewayError):
    def __init__(self) -> None:
        super().__init__("truncated", "the model hit max_tokens before finishing")


class BadModelOutputError(GatewayError):
    def __init__(self, why: str) -> None:
        super().__init__("bad_output", why)


def api_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of ``schema`` for the API: objects forbid extra fields; unsupported keywords removed."""

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _UNSUPPORTED:
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = walk(value)
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
        return out

    result: dict[str, Any] = walk(copy.deepcopy(dict(schema)))
    return result


def make_client(api_key: str) -> anthropic.Anthropic:
    """Production client: SDK retries (3) with a short connect timeout."""
    return anthropic.Anthropic(
        api_key=api_key, max_retries=3, timeout=anthropic.Timeout(60.0, connect=5.0)
    )


def _kind(exc: Exception) -> str:
    if isinstance(exc, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limit"
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return "auth"
    if isinstance(exc, anthropic.APIStatusError):
        return "server" if exc.status_code >= 500 else "bad_request"
    return "unexpected"


class AnthropicGateway:
    def __init__(self, client: Any, roles: Mapping[str, RoleConfig], limiter: Limiter,
                 audit: AuditLog) -> None:
        for name, cfg in roles.items():
            if cfg.backend == BACKEND and cfg.price is None:
                raise ConfigError(f"role {name!r}: price is required so the spend cap works")
        self._client, self._roles, self._limiter, self._audit = client, roles, limiter, audit

    # ---------- public ----------
    def complete_json(
        self,
        role: str,
        system: str,
        user: str,
        schema: Mapping[str, Any] | None = None,
        data_label: str = "normal",
    ) -> dict[str, Any]:
        cfg = self._role(role)
        self._admit(role, cfg, data_label)
        kwargs: dict[str, Any] = {
            "model": cfg.model, "max_tokens": cfg.max_tokens, "timeout": cfg.timeout_s,
            "system": system, "messages": [{"role": "user", "content": user}],
        }
        output_config: dict[str, Any] = {}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": api_schema(schema)}
        if cfg.effort:
            output_config["effort"] = cfg.effort
        if output_config:
            kwargs["output_config"] = output_config
        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            kind = _kind(exc)
            self._audit.append("gateway", "model.error", role=role, model=cfg.model, kind=kind,
                               status=getattr(exc, "status_code", None),
                               request_id=getattr(exc, "request_id", None))
            raise GatewayError(kind, f"{kind} error from the model API") from exc
        return self._finish(role, cfg, system, user, response)

    # ---------- internals ----------
    def _role(self, role: str) -> RoleConfig:
        cfg = self._roles.get(role)
        if cfg is None:
            raise GatewayError("config", f"unknown role {role!r}")
        if cfg.backend != BACKEND:
            raise GatewayError("config", f"role {role!r} is not served by this backend")
        return cfg

    def _admit(self, role: str, cfg: RoleConfig, data_label: str) -> None:
        if data_label == "sensitive" and cfg.data_class == "cloud":
            self._audit.append("gateway", "model.blocked", role=role, reason="privacy")
            raise PrivacyBlockedError(role)
        if not self._limiter.peek("dollars").allowed:
            self._audit.append("gateway", "model.blocked", role=role, reason="monthly_spend_cap")
            raise GatewayCapError("monthly_spend_cap")
        if not self._limiter.check_and_consume("model_runs").allowed:
            self._audit.append("gateway", "model.blocked", role=role, reason="daily_model_cap")
            raise GatewayCapError("daily_model_cap")

    @staticmethod
    def _cost(price: Price, usage: Any) -> tuple[float, dict[str, int]]:
        counts = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
        }
        cache_read = price.cache_read if price.cache_read is not None else price.input
        cache_write = price.cache_write if price.cache_write is not None else price.input
        cost = (
            counts["input_tokens"] * price.input
            + counts["output_tokens"] * price.output
            + counts["cache_read_input_tokens"] * cache_read
            + counts["cache_creation_input_tokens"] * cache_write
        ) / 1_000_000
        return cost, counts

    def _finish(
        self, role: str, cfg: RoleConfig, system: str, user: str, response: Any
    ) -> dict[str, Any]:
        assert cfg.price is not None  # guaranteed at construction
        cost, counts = self._cost(cfg.price, response.usage)
        self._limiter.record("dollars", cost)  # real spend is always recorded, even past the cap
        self._audit.append(
            "gateway", "model.call", role=role, model=cfg.model, stop_reason=response.stop_reason,
            cost_usd=round(cost, 6), request_id=getattr(response, "_request_id", None),
            input_sha256=hashlib.sha256(f"{system}\n\n{user}".encode()).hexdigest(), **counts,
        )
        if response.stop_reason == "refusal":
            raise ModelRefusalError
        if response.stop_reason == "max_tokens":
            raise TruncatedOutputError
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise BadModelOutputError("no text block in the response")
        try:
            data = json.loads(text)
        except ValueError:
            raise BadModelOutputError("response is not valid JSON") from None
        if not isinstance(data, dict):
            raise BadModelOutputError("response JSON is not an object")
        return data
