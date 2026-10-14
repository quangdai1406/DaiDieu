# Daikon — Design Document (v1 + phase 2 outline)

Status: **Draft, awaiting Dai's approval.** Inputs: decisions in `CLAUDE.md`.

## 1. Goals and non-goals

**Goals (v1)**
- Daikon watches his own Gmail inbox (which receives mail Dai forwards), triages it, researches context in Dai's Google Drive "Second Brain", and prepares ready-to-send reply drafts.
- Daikon texts Dai a short approval digest. Dai replies Approve / Edit / Reject. Only an approved draft is ever sent.
- Daikon can run Claude Skills for delegated tasks (research, documents) and return the finished result for approval.
- Runs on Dai's always-on laptop, on Claude Pro plus about $1–3/month of Twilio.

**Non-goals (v1)**
- No phone calls (phase 2). No autonomous sending of any kind. No access to Dai's own Gmail account. No writing to the Second Brain. No public web server.

## 2. Architecture

```
 Dai's Gmail ──filter forward──▶ Daikon's Gmail
                                       │ (Gmail API, poll 2 min)
                                       ▼
┌──────────────── Daikon runner (local Python, one process) ─────────────────┐
│ 1 Fetch ─▶ 2 Rule filter ─▶ 3 Queue ─▶ 4 Claude worker (headless) ─▶ 5 Draft node
│                                           ▲ read-only Drive tools only        │
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
| 2 | Rule filter | Plain-code triage: dedupe, newsletters/no-reply (List-Unsubscribe header), allowlist checks, per-day Claude run cap | Label, ignore |
| 3 | Queue | Graph nodes with `status` frontmatter | — |
| 4 | Claude worker | `claude -p` per batch item: classify, research Second Brain, draft reply or run a Skill. Returns **JSON only** | Read Drive; produce text |
| 5 | Draft store | Writes validated JSON into a `draft` node (versioned, hashed) | Write graph |
| 6 | Notifier | Sends Dai the digest by SMS (short) and email (full draft) | Send to Dai only |
| 7 | Approval handler | Parses Dai's replies, verifies sender and code, advances state | Change state |
| 8 | Sender | Sends the exact approved draft body by Gmail API; one send per approval | Send mail |

**Key principle:** the only components that can send anything are 6 (to Dai) and 8 (to others, only for an `APPROVED` draft with a matching hash). Claude (component 4) has **no send, delete or write capability**; it only returns text.

**Technology (assumptions to confirm):** Python 3.12, `google-api-python-client` (Gmail), `twilio`, `pyyaml`, `pytest`. Scheduler: a long-running loop supervised by launchd/systemd/Task Scheduler (laptop OS to confirm). Gmail OAuth: see risk R3.

## 3. Data flow (email reply, the main v1 loop)

1. Fetcher pulls new messages from Daikon's inbox; creates a `message` node and links it to a `thread` and `person` node.
2. Rule filter: skip newsletters/automated mail (digest only), skip already-handled message IDs, enforce the daily Claude run cap. Survivors become `task` nodes with `status: triaged`.
3. Worker batch (every 10–15 min, or on a Dai command): for each task, run `claude -p` with a fixed system prompt, the message wrapped in an untrusted-data block, and the person/thread context. The worker searches the Second Brain (read-only Drive tools) for the sender, project and prior decisions, then returns JSON: `{category, urgency, summary, needs_decision, draft_body, citations[], sensitivity_flags[], recommendation}`.
4. Runner validates JSON against a schema; invalid or oversize output is discarded and retried once, then flagged for Dai.
5. A `draft` node is created (`version: 1`, `body_sha256`, `status: pending_approval`, random 4-character `approval_code`).
6. Notifier texts Dai: one line per item with id, sender, urgency, recommendation, and reply options. The full draft and citations (links to source notes) go to Dai's personal email.
7. Dai replies `OK 7K2F`, `NO 7K2F`, or `EDIT 7K2F make it shorter and decline the Friday call`.
8. Approval handler verifies sender and code, then: OK → Sender; NO → `rejected`; EDIT → new worker run producing `version: n+1` and a fresh code.
9. Sender re-checks the hash, sends, records the Gmail message ID, marks `sent`, and writes an audit entry.

**Skills tasks** (e.g. "research X and make a one-page brief") arrive as commands from Dai's verified number/email. The worker runs the named Skill and returns the finished artifact as a `draft`-type node of kind `deliverable`; sending it anywhere still needs approval.

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
| `skill-run` | A Claude Skill execution | skill name, inputs ref, output ref |
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
- **Read-only, enforced twice:** (1) the worker is launched with an explicit tool allowlist containing only Drive search/read/metadata tools and no write tools, and no Gmail/Calendar/other connectors; (2) the runner verifies from the stream output that no disallowed tool was called, and discards the run if one was.
- Folder scoping: every lookup query includes the root ID; results whose ancestry is outside the tree are dropped.
- Output rules: facts taken from notes carry a citation (Drive link). Notes flagged sensitive (folders such as `06 Trading and Investments`, personal/health/finance/credentials) are never quoted in a draft unless Dai approves that specific item; the draft's `sensitivity_flags` shows the reason.
- Content is context, never instructions (see §7). Link-nodes (`source-note`) store pointers only.
- **Assumption A1:** the Drive connector available to headless `claude -p` is the one linked to Dai's Claude account. If it is not available in headless mode, fallback is a read-only local mirror synced from Drive (e.g. rclone, read-only scope) that the worker reads from disk.

## 7. Security and threat model

| Threat | Control |
|---|---|
| Prompt injection in email, SMS or notes | Untrusted content wrapped in delimited data blocks; worker prompt says it is data; **worker has no send/write tools**, so injection cannot cause an action; output must pass JSON-schema validation; any instruction-like text from non-allowlisted senders is just summarized |
| Spoofed commands (forged From / SMS) | Commands accepted only from Dai's verified number or personal email; email requires SPF/DKIM pass in `Authentication-Results`; **every approval needs the per-draft random code** that an attacker cannot guess |
| Sending the wrong or changed content | Approval bound to body hash and version; Sender sends the stored body only |
| Data leak to recipients | Sensitivity flags; no second-brain content quoted without item-level approval; recipients list fixed at draft time and shown in the digest |
| Credential theft | Secrets only in env vars / OS keychain; never in repo or graph; Gmail token scope limited to Daikon's account; Twilio auth token not logged |
| Runaway cost or loops | Daily cap on Claude runs; max turns per run; per-sender rate limit; kill switch file `~/daikon-data/PAUSE` stops all sending |
| Private data in a public repo | Graph and audit stored outside the repo; `.gitignore` guards; a pre-commit check blocks files containing tokens or `daikon-data` content |
| Tampering/forensics | Append-only audit JSONL: every fetch, Claude run (input hash, tool list, output hash), notification, approval, send |

Least privilege summary: Daikon's Gmail (read, send), Twilio (send/receive on his number), Drive (read only, one folder tree), no access to Dai's Gmail or calendar.

## 8. Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| Laptop asleep/offline | Heartbeat gap | Resume polling on wake; messages are not lost (stay in Gmail/Twilio); digest notes the delay |
| Claude Pro limit hit | Non-zero exit / limit message | Back off, stop non-urgent runs, tell Dai once by SMS; urgent items get a plain "needs your attention" notice without a draft |
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
- Flow: Twilio Voice → Media Streams WebSocket → speech-to-text (local Whisper or cloud) → `claude-haiku-5-5` → text-to-speech (local Piper or cloud) → back to the call.
- Needs a public endpoint (Cloudflare Tunnel) with Twilio signature validation, and an API key.
- Every outbound call needs an approved `call` node: goal, facts Daikon may share, hard limits (e.g. never agree to a price), max duration, and numbers he may call. After the call: transcript node plus an SMS summary.
- Call assist (screen, transcribe, summarize inbound calls) ships before outbound calls.
- v1 prepares for this by keeping approvals, nodes and the Twilio number channel-agnostic.

## 10. Cost (estimates, verify before budgeting)

| Item | v1 | Phase 2 |
|---|---|---|
| Claude | Pro subscription (existing) | API key; Haiku-class model for live calls, a few cents/min |
| Twilio number + SMS | ~$1.15/mo + ~$0.008 per SMS | + voice ~$0.01–0.02/min |
| Gmail, Drive | Free | Free |
| Speech | — | Free if local; cloud adds ~$0.01–0.10/min |

One-time: Twilio A2P 10DLC registration (US) before reliable SMS; allow several days.

## 11. Testing strategy (for the plan phase)

- Unit tests: rule filter, JSON schema validation, state machine transitions (including illegal ones), approval-code and hash binding, graph read/write/traversal, sender idempotency.
- Contract tests with recorded fixtures for Gmail and Twilio responses; a fake Claude worker returning canned JSON.
- Security tests: injection corpus (emails and notes containing instructions) must produce no tool calls and no state change; spoofed approval attempts must fail; replayed and stale codes must fail.
- End-to-end dry run: fake inbox → draft → SMS approval → send to a test address, with the kill switch tested.

## 12. v1 milestones

1. Repo skeleton, graph store, audit log, state machine (no external services).
2. Gmail fetcher and rule filter, writing nodes.
3. Claude worker wrapper (tool allowlist, schema validation) with fake worker tests.
4. Second Brain lookup and citations.
5. Notifier and approval handler (email first, then Twilio SMS after A10DLC clears).
6. Sender with exactly-once guarantees; kill switch; expiry.
7. Hardening: injection tests, rate limits, backups, runbook.

## 13. Risks and open decisions for Dai

| ID | Item | Recommendation |
|---|---|---|
| R1 | Using a Pro login for unattended `claude -p` runs may conflict with Anthropic's terms or usage limits | Check current terms before building; design allows switching to an API key with no rework |
| R2 | Headless runs may not expose the Drive connector (A1) | Test early in milestone 3; fallback is a read-only local mirror |
| R3 | Gmail OAuth: apps in "Testing" mode get refresh tokens that expire after 7 days | Publish the app as "In production" (personal use, unverified warning) or use IMAP/SMTP with an app password |
| R4 | Laptop OS (affects scheduler and keychain) | Confirm: macOS, Windows or Linux? |
| R5 | Approval digest on SMS is short; long drafts are read by email | Accept, or add a local web page for review in v1.1 |
| R6 | Which folders count as "sensitive" in the Second Brain | Proposed: `06 Trading and Investments`, `07 Personal and Working Style`, anything tagged private. Confirm |
| R7 | Draft voice | Use Dai's existing `dai-email-drafting` skill as the style source |

**Awaiting your approval to proceed.** Answer R4 and R6, or tell me to proceed on the recommendations, and I will write the implementation plan.
