# Daikon — Design Document (v1 + phase 2 outline)

Status: **Draft v2, awaiting Dai's approval.** Inputs: decisions in `CLAUDE.md`.

Change from v1 of this doc: Daikon is **model-agnostic**. All model calls go through **OpenRouter** (one API, many vendors' models, including Claude), so Dai is not tied to Claude Pro or to any single vendor. This replaces the earlier `claude -p` / Claude Pro design.

## 1. Goals and non-goals

**Goals (v1)**
- Daikon watches his own Gmail inbox (which receives mail Dai forwards), triages it, researches context in Dai's Google Drive "Second Brain", and prepares ready-to-send reply drafts.
- Daikon texts Dai a short approval digest. Dai replies Approve / Edit / Reject. Only an approved draft is ever sent.
- Daikon can run reusable "skills" (instruction files, including Dai's existing Claude skill files) for delegated tasks such as research and documents, and return the finished result for approval.
- Runs on Dai's always-on laptop. Model costs are pay-per-token via OpenRouter (cheap models for triage, stronger ones only where needed), plus about $1–3/month of Twilio.
- Switching a model or vendor is a one-line config change, with no code change.

**Non-goals (v1)**
- No phone calls (phase 2). No autonomous sending of any kind. No access to Dai's own Gmail account. No writing to the Second Brain. No public web server.

## 2. Architecture

```
 Dai's Gmail ──filter forward──▶ Daikon's Gmail
                                       │ (Gmail API, poll 2 min)
                                       ▼
┌──────────────── Daikon runner (local Python, one process) ─────────────────┐
│ 1 Fetch ─▶ 2 Rule filter ─▶ 3 Queue ─▶ 4 Worker (own tool loop) ─▶ 5 Draft node
│                                  │ model calls          ▲ read-only Drive tools │
│                                  ▼                      │ only                 │
│                         Model gateway ─▶ OpenRouter ─▶ chosen model          │
│ 8 Sender ◀─ 7 Approval handler ◀─ 6 Notifier (SMS + email digest to Dai)     │
└───────────────┬───────────────────────────────────┬─────────────────────────┘
                │ Gmail API (send, after approval)  │ Twilio REST (poll inbound, send)
                ▼                                   ▼
        recipients                          Dai's phone / personal email
   Graph store + audit log: ~/daikon-data/  (outside this git repo)
```

| # | Component | Responsibility | Has authority to |
|---|---|---|---|
| 1 | Fetcher | Poll Daikon's Gmail (and Twilio inbound SMS) | Read only |
| 2 | Rule filter | Plain-code triage: dedupe, newsletters/no-reply (List-Unsubscribe header), allowlist checks, per-day model-call cap | Label, ignore |
| 3 | Queue | Graph nodes with `status` frontmatter | — |
| 4 | Worker + model gateway | Daikon's own small agent loop. Per batch item: calls the model through OpenRouter, lets it use a fixed set of read-only tools (`drive_search`, `drive_read`, `graph_lookup`), then returns **JSON only** (classify, research, draft, or run a skill) | Read Drive and graph; produce text |
| 5 | Draft store | Writes validated JSON into a `draft` node (versioned, hashed) | Write graph |
| 6 | Notifier | Sends Dai the digest by SMS (short) and email (full draft) | Send to Dai only |
| 7 | Approval handler | Parses Dai's replies, verifies sender and code, advances state | Change state |
| 8 | Sender | Sends the exact approved draft body by Gmail API; one send per approval | Send mail |

**Key principle:** the only components that can send anything are 6 (to Dai) and 8 (to others, only for an `APPROVED` draft with a matching hash). The model (component 4) has **no send, delete or write tool**; it only returns text. Because Daikon owns the tool loop, the tool list is enforced in code, not by prompt.

**Model gateway.** One thin client for OpenRouter's OpenAI-compatible chat API. A config file `models.yaml` maps **roles** to model IDs, so models can be swapped or mixed freely:

| Role | Used for | Selection criteria |
|---|---|---|
| `triage` | Classify urgency/category, summarize | Cheapest model with reliable JSON output |
| `draft` | Reply drafts in Dai's voice, skill deliverables | Best writing quality you are willing to pay for |
| `research` | Second-Brain lookups with tool calls | Strong tool-calling support |
| `call` (phase 2) | Live phone conversation | Low latency, cheap |

Each role also has an ordered fallback list (OpenRouter model fallbacks or our own retry), a max tokens limit, and a per-day spend cap. Exact model IDs are chosen at implementation time from OpenRouter's current catalog; models used for tool-calling roles must support tool calls.

**Technology (assumptions to confirm):** Python 3.12, `google-api-python-client` (Gmail, Drive), `httpx` or the OpenAI-compatible SDK (OpenRouter), `twilio`, `pyyaml`, `jsonschema`, `pytest`. Scheduler: a long-running loop supervised by launchd/systemd/Task Scheduler (laptop OS to confirm). Gmail OAuth: see risk R3.

## 3. Data flow (email reply, the main v1 loop)

1. Fetcher pulls new messages from Daikon's inbox; creates a `message` node and links it to a `thread` and `person` node.
2. Rule filter: skip newsletters/automated mail (digest only), skip already-handled message IDs, enforce the daily model-call cap. Survivors become `task` nodes with `status: triaged`.
3. Worker batch (every 10–15 min, or on a Dai command): for each task, call the `triage` then `draft` models through the gateway with a fixed system prompt, the message wrapped in an untrusted-data block, and the person/thread context. The worker may call the read-only tools (`drive_search`, `drive_read`) to find the sender, project and prior decisions in the Second Brain, up to a max number of turns. It returns JSON: `{category, urgency, summary, needs_decision, draft_body, citations[], sensitivity_flags[], recommendation}`.
4. Runner validates JSON against a schema; invalid or oversize output is discarded and retried once, then flagged for Dai.
5. A `draft` node is created (`version: 1`, `body_sha256`, `status: pending_approval`, random 4-character `approval_code`).
6. Notifier texts Dai: one line per item with id, sender, urgency, recommendation, and reply options. The full draft and citations (links to source notes) go to Dai's personal email.
7. Dai replies `OK 7K2F`, `NO 7K2F`, or `EDIT 7K2F make it shorter and decline the Friday call`.
8. Approval handler verifies sender and code, then: OK → Sender; NO → `rejected`; EDIT → new worker run producing `version: n+1` and a fresh code.
9. Sender re-checks the hash, sends, records the Gmail message ID, marks `sent`, and writes an audit entry.

**Skill tasks** (e.g. "research X and make a one-page brief") arrive as commands from Dai's verified number/email. A **skill** is a folder of instructions (`SKILL.md` plus reference files) loaded from `daikon/skills/`. Dai's existing Claude skill files (for example `dai-email-drafting`) can be copied in and used as instructions. The worker follows the skill with the `draft` or `research` model and returns the finished artifact as a `draft` node of kind `deliverable`; sending it anywhere still needs approval. In v1, skills are instruction-only (no scripts run); web research, if wanted, is added later as another read-only tool.

*Note:* Anthropic's own Skills runtime is not available through OpenRouter, so Daikon reads skill files himself. Skills that depend on scripts or file-generation tools (e.g. .docx/.pdf builders) are out of scope for v1 and listed in the plan as a later add-on.

## 4. Graph file system

Data lives in `~/daikon-data/graph/`, **outside the git repo** (it contains private mail). The repo holds only code, docs, and a sample/empty graph used by tests.

Each node is one Markdown file `<type>/<id>.md`:

```yaml
---
id: draft-2026-10-14-0007
type: draft
status: pending_approval
created: 2026-10-14T09:12:00-04:00
tags: [email, urgent]
links:
  replies_to: [[message-…]]
  relates_to: [[person-…]]
  derived_from: [[source-note-…]]
---
body / notes in Markdown
```

| Node type | Purpose | Key fields |
|---|---|---|
| `person` | Someone Daikon has seen | emails, phones, org, `trust` (allowlisted / known / unknown) |
| `thread` | An email conversation | gmail_thread_id, subject, status |
| `message` | One inbound or outbound message | gmail_id, from, date, headers_auth (SPF/DKIM result) |
| `task` | A unit of work for Daikon | kind (reply, skill, research), due, status |
| `draft` | Proposed outbound content or deliverable | version, body_sha256, approval_code, recipients |
| `decision` | Dai's approve/reject/edit outcome | draft ref, choice, channel, time |
| `source-note` | Lightweight pointer to a Drive note | drive_file_id, title, area folder — **no content copy** |
| `skill-run` | A skill execution | skill name, inputs ref, output ref |
| `call` (phase 2) | A phone call | goal, brief ref, transcript ref |
| `hub` | Index per type; entry point for traversal | generated |

**Edge types:** `replies_to`, `relates_to`, `blocked_by`, `derived_from`, `approved_by`, `cites`. Edges are `[[id]]` links in frontmatter `links:`; they are the source of truth.

**Traversal:** a small `graph` module loads frontmatter, builds an in-memory adjacency index, and answers queries ("open tasks linked to person X", "all drafts citing note Y"). Hubs are regenerated from the index. Writes are atomic (temp file then rename) under a single-process lock. Operational audit is an append-only `audit/YYYY-MM.jsonl` (see §7). No database in v1.

## 5. Approval state machine (draft)

| State | Meaning | Next states |
|---|---|---|
| `triaged` | Task passed the rule filter | `drafting`, `ignored` |
| `drafting` | Worker running | `pending_approval`, `failed` |
| `pending_approval` | Digest sent, awaiting Dai | `approved`, `rejected`, `edit_requested`, `expired` |
| `edit_requested` | Dai asked for changes | `drafting` (version +1, new code) |
| `approved` | Valid OK received | `sending` |
| `sending` | Gmail send in progress | `sent`, `failed` |
| `sent` / `rejected` / `expired` / `ignored` / `failed` | Terminal | — |

Rules: an approval binds to `(draft id, version, body_sha256, approval_code)`; any edit changes version and code, so an old "OK" can never send a new body. Drafts expire after 72 hours (configurable) and are never sent after expiry. Exactly-once send: `sending` is written before the API call, and on restart a `sending` draft is checked against the Sent folder before any retry.

## 6. Second Brain access

- Source: Google Drive folder `Second Brain` (ID in `CLAUDE.md`), numbered areas, `99 Superseded` ignored.
- **Access method:** the worker's `drive_search` / `drive_read` tools call the Google Drive API using **Daikon's own Google account**, which Dai has given **Viewer** access to the folder. Viewer access means Google itself prevents any write, so read-only does not depend on our code or on a prompt.
- **Least privilege by sharing:** share only the areas Daikon should see (for example `00 Control`, `02 AISI`, `03 Landlord`, `04 Book Writing Business`, `05 Other Businesses`, `08 Ryder's Workshop`) and leave sensitive areas (proposed: `06 Trading and Investments`, `07 Personal and Working Style`) unshared. Whatever is not shared cannot be read, and cannot be leaked to a model provider. Sharing the whole root is possible but weaker.
- Code-side checks as well: every lookup is restricted to the shared tree IDs; results from elsewhere are dropped; read size per file is capped; only text-like types (Docs exported as text, Markdown, plain text) are read in v1.
- Output rules: facts taken from notes carry a citation (Drive link). Anything the draft quotes from a note flagged sensitive needs item-level approval; the draft's `sensitivity_flags` shows the reason.
- Content is context, never instructions (see §7). Link-nodes (`source-note`) store pointers only.
- **Assumption A1:** the folder is owned by `admin@closeby230.com`, which looks like a Google Workspace account. Workspace admins can block sharing with outside accounts. If so, either allow sharing for this folder, or give Daikon a Google account inside that Workspace, or fall back to a read-only local mirror synced from Drive.
- **Privacy note:** text read from notes is sent to the model provider chosen through OpenRouter. See §7.

## 7. Security and threat model

| Threat | Control |
|---|---|
| Prompt injection in email, SMS or notes | Untrusted content wrapped in delimited data blocks; the system prompt says it is data; **the model has no send/write tools and the tool list is enforced in our code**, so injection cannot cause an action; the tool loop has a max turns limit; output must pass JSON-schema validation; instruction-like text from non-allowlisted senders is just summarized |
| Spoofed commands (forged From / SMS) | Commands accepted only from Dai's verified number or personal email; email requires SPF/DKIM pass in `Authentication-Results`; **every approval needs the per-draft random code** that an attacker cannot guess |
| Sending the wrong or changed content | Approval bound to body hash and version; Sender sends the stored body only |
| Data leak to recipients | Sensitivity flags; no second-brain content quoted without item-level approval; recipients list fixed at draft time and shown in the digest |
| Credential theft | Secrets (OpenRouter key, Twilio, Google tokens) only in env vars / OS keychain; never in repo, graph or logs; Google tokens are Daikon's account only; OpenRouter key has a spend limit set in the OpenRouter dashboard |
| Data exposed to model providers via OpenRouter | Send the minimum needed (subject, body, a few note excerpts); do not share sensitive Drive areas with Daikon; configure OpenRouter account/provider settings to deny training on prompts and to avoid providers that log or retain data where possible (verify the current option names in OpenRouter's docs); keep an allowlist of approved model IDs/providers in `models.yaml`; log which model saw which item in the audit |
| Model/provider outage or silent model change | Fallback list per role; pinned model IDs; schema validation catches format drift; golden-test set re-run when a model is changed |
| Runaway cost or loops | Daily cap on model calls and a daily spend cap in code, plus the OpenRouter key limit; max turns and max tokens per run; per-sender rate limit; kill switch file `~/daikon-data/PAUSE` stops all sending |
| Private data in a public repo | Graph and audit stored outside the repo; `.gitignore` guards; a pre-commit check blocks files containing tokens or `daikon-data` content |
| Tampering/forensics | Append-only audit JSONL: every fetch, model call (role, model ID, input hash, tools used, output hash, tokens, cost), notification, approval, send |

Least privilege summary: Daikon's Gmail (read, send), Twilio (send/receive on his number), Drive (Viewer on selected folders only), OpenRouter (inference only, with a spend limit), no access to Dai's Gmail or calendar.

## 8. Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| Laptop asleep/offline | Heartbeat gap | Resume polling on wake; messages are not lost (stay in Gmail/Twilio); digest notes the delay |
| OpenRouter credit exhausted, rate limit or provider outage | HTTP 402/429/5xx | Try the role's fallback model; if all fail, back off, tell Dai once by SMS; urgent items get a plain "needs your attention" notice without a draft |
| Chosen model ignores the JSON format or tool-call rules | Schema validation fails twice | Escalate to fallback model; flag the item; log the model for review |
| Worker returns bad JSON | Schema validation | Retry once, then flag item for manual handling |
| Gmail/Twilio API error | Exceptions | Exponential backoff; after N failures text Dai |
| OAuth token expired | 401 | Alert Dai with re-auth steps; sending pauses |
| Duplicate processing | Message-ID dedupe | Idempotent node creation |
| Crash mid-send | `sending` state on restart | Check Sent folder before retry; never double-send |
| Dai doesn't answer | Expiry timer | Reminder at 24 h, expire at 72 h; no automatic send |
| Forwarding filter misconfigured | No mail arrives | Weekly self-test email from Daikon to Dai and back |
| Disk/graph corruption | Atomic writes, daily snapshot | Restore from snapshot; audit log is replayable |

## 9. Phase 2: phone calls (outline only)

- Daikon speaks as himself, discloses he is an AI assistant and that the call is recorded/transcribed.
- Flow: Twilio Voice → Media Streams WebSocket → speech-to-text (local Whisper or cloud) → the `call` role model through OpenRouter (a fast, cheap model; Dai's earlier preference was a Haiku-class Claude model, available on OpenRouter) → text-to-speech (local Piper or cloud) → back to the call.
- Latency matters most here: choose the `call` model by measured time to first token, and test OpenRouter's added latency before committing; if too slow, call that vendor's API directly for this role only (the gateway supports a per-role base URL).
- Needs a public endpoint (Cloudflare Tunnel) with Twilio signature validation.
- Every outbound call needs an approved `call` node: goal, facts Daikon may share, hard limits (e.g. never agree to a price), max duration, and numbers he may call. After the call: transcript node plus an SMS summary.
- Call assist (screen, transcribe, summarize inbound calls) ships before outbound calls.
- v1 prepares for this by keeping approvals, nodes and the Twilio number channel-agnostic.

## 10. Cost (estimates, verify before budgeting)

| Item | v1 | Phase 2 |
|---|---|---|
| Models (OpenRouter, pay per token) | Roughly a few dollars/month for light email volume with a cheap `triage` model and a mid-tier `draft` model; scales with mail volume and the model you pick. Set a monthly spend limit on the OpenRouter key. OpenRouter may add a small fee on credit purchases | `call` model, a few cents/min |
| Twilio number + SMS | ~$1.15/mo + ~$0.008 per SMS | + voice ~$0.01–0.02/min |
| Gmail, Drive | Free | Free |
| Speech | — | Free if local; cloud adds ~$0.01–0.10/min |

Because you are no longer on Claude Pro, model cost is now a real monthly line item, but also fully controllable: cap it, pick cheaper models, or run triage on a free/very cheap model.

One-time: Twilio A2P 10DLC registration (US) before reliable SMS; allow several days.

## 11. Testing strategy (for the plan phase)

- Unit tests: rule filter, JSON schema validation, state machine transitions (including illegal ones), approval-code and hash binding, graph read/write/traversal, sender idempotency.
- Contract tests with recorded fixtures for Gmail and Twilio responses; a fake model gateway returning canned JSON and tool calls.
- Model tests: a small golden set of emails whose expected category/draft properties are checked whenever a model ID in `models.yaml` changes; schema-conformance rate must stay above a threshold.
- Security tests: injection corpus (emails and notes containing instructions) must produce no tool calls and no state change; spoofed approval attempts must fail; replayed and stale codes must fail.
- End-to-end dry run: fake inbox → draft → SMS approval → send to a test address, with the kill switch tested.

## 12. v1 milestones

1. Repo skeleton, graph store, audit log, state machine (no external services).
2. Gmail fetcher and rule filter, writing nodes.
3. Model gateway (OpenRouter client, roles, fallbacks, spend caps) and worker tool loop (tool allowlist, schema validation), tested with a fake gateway.
4. Second Brain lookup via Drive API (Viewer account) and citations.
5. Notifier and approval handler (email first, then Twilio SMS after A10DLC clears).
6. Sender with exactly-once guarantees; kill switch; expiry.
7. Hardening: injection tests, rate limits, backups, runbook.

## 13. Risks and open decisions for Dai

| ID | Item | Recommendation |
|---|---|---|
| R1 | Per-token model cost replaces the flat Pro plan | Set spend limits; start with cheap models; measure for two weeks before choosing `draft` models |
| R2 | Text from emails and notes goes to third-party model providers through OpenRouter | Do not share sensitive Drive areas; set OpenRouter privacy options; allowlist providers (see §7) |
| R3 | Gmail OAuth: apps in "Testing" mode get refresh tokens that expire after 7 days | Publish the app as "In production" (personal use, unverified warning) or use IMAP/SMTP with an app password |
| R8 | Workspace may block sharing the Second Brain with Daikon's account (A1) | Test sharing first; fallbacks listed in §6 |
| R9 | Not every model on OpenRouter supports tool calls or strict JSON | Choose models per role by capability; the gateway requires parameter support and validates output |
| R10 | Claude's Skills runtime (scripts, file builders) is not available | v1 uses instruction-only skills; revisit script-based skills with a sandbox later |
| R4 | Laptop OS (affects scheduler and keychain) | Confirm: macOS, Windows or Linux? |
| R5 | Approval digest on SMS is short; long drafts are read by email | Accept, or add a local web page for review in v1.1 |
| R6 | Which Second Brain areas to share with Daikon | Proposed: share all except `06 Trading and Investments` and `07 Personal and Working Style`. Confirm |
| R7 | Draft voice | Use Dai's existing `dai-email-drafting` skill as the style source |

**Awaiting your approval to proceed.** Answer R4 and R6, or tell me to proceed on the recommendations, and I will write the implementation plan.
