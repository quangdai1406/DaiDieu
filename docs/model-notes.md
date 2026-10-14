# Model notes (task M3.1)

Source: the Claude API reference bundled with Claude Code (cached 2026-10-06). **Re-check
prices and IDs on Anthropic's pricing and models pages before relying on the monthly cap.**

## Roles and defaults

| Role | Model ID | Why | Price per 1M tokens (in / out / cache read) |
|---|---|---|---|
| `triage` | `claude-haiku-5-5` | Cheapest current model; classification and short summaries | $0.10 / $0.50 / $0.01 (prompts up to 100K tokens; $0.50 / $2.50 beyond) |
| `draft` | `claude-sonnet-5-5` | Good writing for replies at a moderate price | $2.00 / $10.00 / $0.20 |
| (later, if drafts are weak) | `claude-opus-5-5` | Stronger model, only if G1 shows a need | $4.00 / $20.00 / $0.20 |

Model IDs are exact strings with no date suffix. They live in `models.yaml`, never in code.

## API behavior that shaped the gateway

- **Structured output:** `output_config={"format": {"type": "json_schema", "schema": {...}}}`;
  the first content block is text holding valid JSON. Object schemas must set
  `additionalProperties: false`. Keywords such as min/max/length/pattern are not relied on in
  the API copy of the schema; Daikon re-validates the full schema locally.
- **No sampling parameters:** Haiku 5.5 and Sonnet 5.5 return a 400 for non-default
  `temperature`/`top_p`/`top_k`. The gateway never sends them.
- **Thinking:** on by default (adaptive) for these models; thinking tokens are billed as
  output. `effort` (`low`...`max`) is the cost/quality control. Defaults: Haiku 5.5 `medium`,
  Sonnet 5.5 `high`, so both are set explicitly in config (`low` for triage, `medium` for drafts).
- **Forced tool use and prefill are not supported** on these models. Daikon uses neither: the
  mail lane has no tools at all.
- **Refusals:** a request can end with `stop_reason: "refusal"` (HTTP 200). The gateway raises
  `ModelRefusalError`; the pipeline treats it as "needs Dai", not as a crash.
- **Usage fields:** `usage.input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`. Cost is computed from them using the configured prices.
- **Errors/retries:** the SDK retries connection errors, 408, 409, 429 and 5xx (we set 3
  retries, 60 s timeout, 5 s connect). The gateway maps the rest to `GatewayError.kind`:
  `rate_limit`, `auth`, `bad_request`, `server`, `timeout`, `connection`.
- **SDK:** `anthropic` 1.x (uses `httpx2`, not `httpx`).

## Rough monthly cost (estimate, not a quote)

Assumptions: 30 emails a day need a model run; each triage call is about 2,000 input and 300
output tokens; each draft call is about 3,500 input and 500 output tokens. Thinking tokens add
to output; the multiplier below allows for that.

| Item | Per day | Per month (30 d) |
|---|---|---|
| Triage on Haiku 5.5: 30 x (2,000 x $0.10 + 300 x $0.50) / 1M | $0.01 | $0.32 |
| Draft on Sonnet 5.5: 30 x (3,500 x $2 + 500 x $10) / 1M | $0.36 | $10.80 |
| Subtotal | $0.37 | $11.1 |
| With thinking and retries (x1.5 on output-heavy parts) | about $0.50 | about $15 |

So plan for roughly **$10-15 a month** at 30 drafted emails a day, much less at lower volume.
Cheaper options if needed: draft on Haiku 5.5 (about $0.50 a month for the same volume, with
lower quality), or draft only for mail that triage marks as needing Dai. The example config
sets `dollars_per_month: 15`; raise it after the first week's usage report.

Twilio adds about $1-3 a month; Gmail and Drive are free.
