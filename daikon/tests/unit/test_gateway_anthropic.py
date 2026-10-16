"""M3.2: anthropic_api gateway backend. No tools, schema output, caps, cost, privacy, errors."""

import inspect
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from daikon.audit import AuditLog
from daikon.clock import FakeClock
from daikon.config import ConfigError, Limits, Price, RoleConfig
from daikon.gateway.anthropic_api import (
    AnthropicGateway,
    BadModelOutputError,
    GatewayCapError,
    GatewayError,
    ModelRefusalError,
    PrivacyBlockedError,
    TruncatedOutputError,
    api_schema,
)
from daikon.limiter import Limiter, default_rules

pytestmark = [pytest.mark.unit, pytest.mark.security]
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
SCHEMA = {
    "type": "object",
    "required": ["category", "confidence"],
    "properties": {"category": {"type": "string", "maxLength": 20},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}
PRICE = Price(input=0.10, output=0.50, cache_read=0.01)


def response(text: str = '{"category":"scheduling","confidence":0.9}', *, stop: str = "end_turn",
             inp: int = 1000, out: int = 200, cache_read: int = 0, blocks: list[Any] | None = None,
             request_id: str = "req_123") -> Any:
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=text)]
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out,
                            cache_read_input_tokens=cache_read, cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, _request_id=request_id)


@dataclass
class FakeClient:
    result: Any = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result if self.result is not None else response()


@dataclass
class Env:
    gw: AnthropicGateway
    client: FakeClient
    limiter: Limiter
    root: Path


def env(tmp_path: Path, *, limits: Limits | None = None, roles: dict[str, RoleConfig] | None = None,
        client: FakeClient | None = None) -> Env:
    clock = FakeClock(T0)
    audit = AuditLog(tmp_path / "audit", clock)
    limiter = Limiter(tmp_path / "limits.json", clock, default_rules(limits or Limits()))
    fake = client or FakeClient()
    roles = roles or {"triage": RoleConfig("anthropic_api", "small-model", "cloud", max_tokens=500,
                                           effort="low", timeout_s=30, price=PRICE)}
    return Env(AnthropicGateway(fake, roles, limiter, audit), fake, limiter, tmp_path)


def audit_records(root: Path) -> list[dict[str, Any]]:
    path = root / "audit" / "2026-10.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def http_response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
                           headers={"request-id": "req_err"})


def test_request_shape_has_no_tools_no_sampling_and_asks_for_schema_output(tmp_path: Path) -> None:
    e = env(tmp_path)
    out = e.gw.complete_json("triage", "SYSTEM", "USER", SCHEMA)
    assert out == {"category": "scheduling", "confidence": 0.9}
    (call,) = e.client.calls
    assert call["model"] == "small-model" and call["max_tokens"] == 500 and call["timeout"] == 30
    assert call["system"] == "SYSTEM" and call["messages"] == [{"role": "user", "content": "USER"}]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    for forbidden in ("tools", "tool_choice", "temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in call


def test_the_gateway_signature_cannot_carry_tools() -> None:
    params = inspect.signature(AnthropicGateway.complete_json).parameters
    assert not {"tools", "tool_choice", "temperature"} & set(params)


def test_effort_is_omitted_when_not_configured(tmp_path: Path) -> None:
    roles = {"triage": RoleConfig("anthropic_api", "m", "cloud", price=PRICE)}
    e = env(tmp_path, roles=roles)
    e.gw.complete_json("triage", "s", "u", SCHEMA)
    assert "effort" not in e.client.calls[0]["output_config"]


def test_api_schema_forbids_extra_fields_and_drops_unsupported_keywords() -> None:
    original = json.loads(json.dumps(SCHEMA))
    out = api_schema(SCHEMA)
    assert out["additionalProperties"] is False
    assert "maxLength" not in out["properties"]["category"]
    assert "minimum" not in out["properties"]["confidence"]
    assert SCHEMA == original  # the caller's schema is not mutated


def test_cost_is_computed_recorded_and_audited_without_prompt_text(tmp_path: Path) -> None:
    client = FakeClient(result=response(inp=100_000, out=20_000, cache_read=50_000))
    e = env(tmp_path, client=client)
    e.gw.complete_json("triage", "SECRET-SYSTEM", "PRIVATE-USER", SCHEMA)
    expected = (100_000 * 0.10 + 20_000 * 0.50 + 50_000 * 0.01) / 1_000_000
    assert e.limiter.peek("dollars").used == pytest.approx(expected)
    rec = audit_records(tmp_path)[-1]
    assert rec["action"] == "model.call" and rec["data"]["cost_usd"] == pytest.approx(expected)
    assert rec["data"]["input_tokens"] == 100_000 and rec["data"]["request_id"] == "req_123"
    raw = (tmp_path / "audit" / "2026-10.jsonl").read_text(encoding="utf-8")
    assert "PRIVATE-USER" not in raw and "SECRET-SYSTEM" not in raw and len(rec["data"]["input_sha256"]) == 64


def test_daily_run_cap_blocks_before_any_api_call(tmp_path: Path) -> None:
    e = env(tmp_path, limits=Limits(model_runs_per_day=1))
    e.gw.complete_json("triage", "s", "u", SCHEMA)
    with pytest.raises(GatewayCapError, match="daily_model_cap"):
        e.gw.complete_json("triage", "s", "u", SCHEMA)
    assert len(e.client.calls) == 1


def test_monthly_spend_cap_blocks_and_overshoot_is_still_recorded(tmp_path: Path) -> None:
    client = FakeClient(result=response(inp=1_000_000, out=0))  # costs $0.10
    e = env(tmp_path, limits=Limits(dollars_per_month=0.05), client=client)
    e.gw.complete_json("triage", "s", "u", SCHEMA)  # allowed: nothing spent yet
    assert e.limiter.peek("dollars").used == pytest.approx(0.10)  # overshoot recorded
    with pytest.raises(GatewayCapError, match="monthly_spend_cap"):
        e.gw.complete_json("triage", "s", "u", SCHEMA)
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("kwargs", "exc"),
    [
        ({"stop": "refusal"}, ModelRefusalError),
        ({"stop": "max_tokens"}, TruncatedOutputError),
        ({"text": "not json"}, BadModelOutputError),
        ({"text": '["a list"]'}, BadModelOutputError),
        ({"blocks": []}, BadModelOutputError),
    ],
)
def test_bad_outputs_raise_specific_errors_but_cost_is_still_recorded(
    tmp_path: Path, kwargs: dict[str, Any], exc: type[Exception]
) -> None:
    e = env(tmp_path, client=FakeClient(result=response(**kwargs)))
    with pytest.raises(exc):
        e.gw.complete_json("triage", "s", "u", SCHEMA)
    assert e.limiter.peek("dollars").used > 0
    assert audit_records(tmp_path)[-1]["action"] == "model.call"


def test_sensitive_data_is_blocked_from_cloud_roles_only(tmp_path: Path) -> None:
    e = env(tmp_path)
    with pytest.raises(PrivacyBlockedError):
        e.gw.complete_json("triage", "s", "u", SCHEMA, data_label="sensitive")
    assert e.client.calls == []
    roles = {"triage": RoleConfig("anthropic_api", "m", "allowlisted", price=PRICE)}
    ok = env(tmp_path / "b", roles=roles)
    assert ok.gw.complete_json("triage", "s", "u", SCHEMA, data_label="sensitive")


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (anthropic.RateLimitError("slow down", response=http_response(429), body=None), "rate_limit"),
        (anthropic.AuthenticationError("bad key", response=http_response(401), body=None), "auth"),
        (anthropic.BadRequestError("bad", response=http_response(400), body=None), "bad_request"),
        (anthropic.InternalServerError("oops", response=http_response(500), body=None), "server"),
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), "timeout"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "connection"),
    ],
)
def test_sdk_errors_are_classified_audited_and_never_leak_content(
    tmp_path: Path, error: Exception, kind: str
) -> None:
    e = env(tmp_path, client=FakeClient(error=error))
    with pytest.raises(GatewayError) as info:
        e.gw.complete_json("triage", "s", "PRIVATE-USER", SCHEMA)
    assert info.value.kind == kind
    rec = audit_records(tmp_path)[-1]
    assert rec["action"] == "model.error" and rec["data"]["kind"] == kind
    assert "PRIVATE-USER" not in json.dumps(rec)


def test_unknown_role_and_wrong_backend_are_refused(tmp_path: Path) -> None:
    e = env(tmp_path)
    with pytest.raises(GatewayError, match="unknown role"):
        e.gw.complete_json("nope", "s", "u", SCHEMA)
    roles = {"call": RoleConfig("openai_compat", "m", "cloud")}
    other = env(tmp_path / "b", roles=roles)
    with pytest.raises(GatewayError, match="not served by this backend"):
        other.gw.complete_json("call", "s", "u", SCHEMA)


def test_missing_price_is_a_startup_error_so_the_spend_cap_cannot_be_bypassed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="price"):
        env(tmp_path, roles={"triage": RoleConfig("anthropic_api", "m", "cloud")})


def test_make_client_configures_retries_without_network() -> None:
    from daikon.gateway.anthropic_api import make_client

    client = make_client("sk-ant-test-" + "x" * 20)
    assert client.max_retries == 3
