# Daikon — Design Document (v1 + phase 2 outline)

Status: **Draft v4, awaiting Dai's approval.** Inputs: decisions in `CLAUDE.md`.

What changed in v4: Claude is allowed to use tools for skills, in a separate, tightly fenced **skills lane** (§2); the Claude authentication options are spelled out (§13, R1); and skills come from `09 Claude Skills`, filled by Dai's own weekly Second Brain task (§6).

What changed since v2: OpenRouter is used **only for the phone-call model (phase 2)**. Email and skill work in v1 use Claude (Dai's Claude Pro login via headless `claude -p`). The laptop is **Windows**. Daikon's Google account gets **Viewer access to the whole Second Brain**. A **weekly task** refreshes the Second Brain index and syncs Dai's Claude skills.

## 1. Goals and non-goals

**Goals (v1)**
- Daikon watches his own Gmail inbox (which receives mail Dai forwards), triages it, looks up context in Dai's Google Drive "Second Brain", and prepares ready-to-send reply drafts.
- Daikon texts Dai a short approval digest. Dai replies Approve / Edit / Reject. Only an approved draft is ever sent.
- Daikon runs Dai's Claude skills for delegated tasks (research, documents) and returns the finished result for approval.
- A weekly task keeps Daikon's view of the Second Brain and his skills up to date.
- Runs on Dai's always-on **Windows** laptop on Claude Pro plus about $1–3/month of Twilio.

**Non-goals (v1)**
- No phone calls (phase 2). No autonomous sending. No access to Dai's own Gmail. No writing to the Second Brain. No public web server.

## 2. Architecture

```
 Dai's Gmail ──filter forward──▶ Daikon's Gmail
                                       │ (Gmail API, poll 2 min)
                                       ▼
┌──────────────── Daikon runner (local Python, one process) ─────────────────┐
│ 1 Fetch ─▶ 2 Rule filter ─▶ 3 Queue ─▶ 4 Retrieve (Drive API, read-only)   │
│                                              │ excerpts                    │
│                                              ▼                             │
│                       5 Worker: `claude -p`, NO tools ─▶ 6 Draft node      │
│ 9 Sender ◀─ 8 Approval handler ◀─ 7 Notifier (SMS + email digest to Dai)   │
│ Weekly task: Second Brain index refresh + skills sync                      │
└───────────────┬───────────────────────────────────┬─────────────────────────┘
                │ Gmail API (send, after approval)  │ Twilio REST (poll inbound, send)
                ▼                                   ▼
        recipients                          Dai's phone / personal email
   Graph store + audit log: %USERPROFILE%\daikon-data\  (outside this git repo)
```

| # | Component | Responsibility | Has authority to |
|---|---|---|---|
| 1 | Fetcher | Poll Daikon's Gmail and Twilio inbound SMS | Read only |
| 2 | Rule filter | Plain-code triage: dedupe, newsletters/no-reply (List-Unsubscribe header), allowlist checks, per-day model-run cap | Label, ignore |
| 3 | Queue | Graph nodes with `status` frontmatter | — |
| 4 | Retriever | Runner code searches the Second Brain through the Drive API (Daikon's Viewer account) and cuts relevant excerpts | Read Drive |
| 5 | Worker | `claude -p` with **no tools enabled**. Input: untrusted message, context, excerpts, optional skill. Output: **JSON only** | Produce text |
| 6 | Draft store | Validates JSON, writes a versioned, hashed `draft` node | Write graph |
| 7 | Notifier | Sends Dai the digest by SMS (short) and email (full draft) | Send to Dai only |
| 8 | Approval handler | Parses Dai's replies, verifies sender and code, advances state | Change state |
| 9 | Sender | Sends the exact approved draft by Gmail API; one send per approval | Send mail |

**Key principle:** the only components that can send anything are 7 (to Dai) and 9 (to others, only for an `approved` draft with a matching hash). Claude is a **pure text function**: it has no tools, no connectors, no file or network access. It cannot read Drive, send, write or delete. Everything it knows is what the runner puts in the prompt.

**Two execution lanes.** Whether Claude may use tools depends on who controls the input, because anything an outsider can write (an email) could try to steer a tool-using Claude.

| | **Lane 1: Mail lane** | **Lane 2: Skills lane** |
|---|---|---|
| Triggered by | Inbound mail from anyone | A command from Dai's verified number or personal email only |
| Input | Untrusted email text, plus Second Brain excerpts | Dai's own request, plus trusted files and an approved skill |
| Model tools | **None** | Daikon's own tool loop: only what the skill needs, from an allowlist (run one named script, read and write inside the job folder); backend-agnostic |
| Where it runs | The runner process | A separate job folder under a restricted Windows user, no access to `daikon-data`, no mail or Drive tokens in its environment |
| Output | JSON draft | A finished file or text, stored as a `deliverable` draft |
| Send/post/delete | Not possible | Not possible (code-level gate, §5) |

A mail that asks for a script-based task never starts Lane 2 by itself. Daikon drafts a text reply or a "Dai, do you want me to run X?" item. Only your command starts the skills lane.

**Retrieve-then-draft (instead of letting Claude search Drive):** step A, the worker proposes search terms from the message (JSON); step B, the retriever runs the searches and returns short excerpts with Drive links; step C, the worker drafts using those excerpts and cites them. At most two retrieval rounds per task.

**Model gateway.** One small interface with two backends, chosen **per role** in `models.yaml`:

| Backend | Covers | Notes |
|---|---|---|
| `anthropic_api` (default for text roles) | Claude models via Dai's API key with a monthly spend cap | Messages API; tools disabled in the mail lane |
| `openai_compat` | **OpenRouter**, Ollama, LM Studio, llama.cpp server, or a thin wrapper around AirLLM | Base URL, key and model per role; flags for tool-call and JSON-mode support |

| Role | Default backend | Used for |
|---|---|---|
| `triage` | `anthropic_api` (small, fast model); can move to a local model after qualification | Classify urgency/category, summarize, with confidence |
| `draft`, `research` | `anthropic_api` | Search terms, drafts in Dai's voice |
| `skills` | `anthropic_api`, through Daikon's own tool loop | Skills lane (see lanes above) |
| `call` (phase 2) | `openai_compat` → OpenRouter | Live phone conversation, see §9 |

Any role can be pointed at OpenRouter (**all-OpenRouter is a supported configuration**) or at a local model by editing config only. A role may switch only after it passes the **qualification harness** (a golden set of Dai's labeled emails: schema pass rate, accuracy, confidence calibration, latency, cost, injection cases).

**JEV-style routing.** Short decisions use typed JSON with a confidence number, and only uncertain ones escalate (this follows Dai's `jev-system-one` skill):

| Confidence (starting values, tuned on real emails) | Action |
|---|---|
| ≥ 0.85 | Use the result |
| 0.70 – 0.84 | Use it and mark the item "low confidence" in the digest |
| < 0.70 | Escalate once to the next role/model (for example local `triage` → cloud `triage`), then stop |

Confidence **only selects a model tier**. It never relaxes an approval, a lane boundary or the sender gate, and any "confidence" text inside an email is ignored.

**Privacy-aware routing.** Sensitivity is decided by code (folder, patterns) before any model call. Items flagged sensitive may go only to roles whose backend is marked `local` or to an approved provider list; otherwise they are withheld and Dai is told. The audit log records which backend saw which item.

**Local option (Dai's laptop: 8 GB GPU, 32 GB RAM).** Small 7–8B-class models run well for triage and sensitive items. Mid-size models are slower. 70B-class models would need AirLLM (very slow, batch only). Live calls and tool-heavy skills stay on cloud models. Optional local embeddings improve Second Brain search without sending notes anywhere.

**Technology (assumptions to confirm):** Python 3.12 for Windows, `google-api-python-client` (Gmail, Drive), `httpx`, `twilio`, `keyring` (Windows Credential Manager), `pyyaml`, `jsonschema`, `pytest`. Scheduling: **Windows Task Scheduler** (details in §8).

## 3. Data flow (email reply, the main v1 loop)

1. Fetcher pulls new messages from Daikon's inbox; creates a `message` node linked to a `thread` and `person` node.
2. Rule filter: skip newsletters/automated mail (digest only), already-handled IDs, and enforce the daily model-run cap. Survivors become `task` nodes (`status: triaged`).
3. Worker batch (every 10–15 min, or on a Dai command): for each task, run retrieve-then-draft (§2). The message is wrapped in an untrusted-data block. The worker returns JSON: `{category, urgency, summary, needs_decision, draft_body, citations[], sensitivity_flags[], recommendation}`.
4. Runner validates JSON against a schema; invalid or oversize output is discarded and retried once, then flagged for Dai.
5. A `draft` node is created (`version: 1`, `body_sha256`, `status: pending_approval`, random 4-character `approval_code`).
6. Notifier texts Dai: one line per item with id, sender, urgency, recommendation and reply options. The full draft and citations (links to source notes) go to Dai's personal email.
7. Dai replies `OK 7K2F`, `NO 7K2F`, or `EDIT 7K2F make it shorter and decline the Friday call`.
8. Approval handler verifies sender and code, then: OK → Sender; NO → `rejected`; EDIT → new worker run producing `version: n+1` and a fresh code.
9. Sender re-checks the hash, sends, records the Gmail message ID, marks `sent`, writes an audit entry.

**Skill tasks** (e.g. "research X and make a one-page brief") arrive as commands from Dai's verified number or email. The runner loads the named skill (§6) and gives its instructions to the worker. Instruction-only skills run in Lane 1 style (no tools). Skills that need scripts or file builders (for example .docx, .pdf, .pptx, .xlsx generation) run in **Lane 2** (§2): tools limited to the skill's declared allowlist, inside a throwaway job folder, no network unless the skill declares it and Dai approved that. The finished text or file is stored as a `draft` node of kind `deliverable`; sending it anywhere still needs approval.

## 4. Graph file system

Data lives in `%USERPROFILE%\daikon-data\graph\`, **outside the git repo** (it contains private mail). The repo holds only code, docs and a sample graph for tests.

Each node is one Markdown file `<type>\<id>.md`:

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
| `task` | A unit of work for Daikon | kind (reply, skill, research, weekly), due, status |
| `draft` | Proposed outbound content or deliverable | version, body_sha256, approval_code, recipients |
| `decision` | Dai's approve/reject/edit outcome | draft ref, choice, channel, time |
| `source-note` | Lightweight pointer to a Drive note | drive_file_id, title, area folder, modified time, content hash — **no content copy** |
| `skill` | A synced skill | name, version hash, source file id, status (staged / active / retired) |
| `skill-run` | One skill execution | skill ref, inputs ref, output ref |
| `call` (phase 2) | A phone call | goal, brief ref, transcript ref |
| `hub` | Index per type; entry point for traversal | generated |

**Edge types:** `replies_to`, `relates_to`, `blocked_by`, `derived_from`, `approved_by`, `cites`. Edges are `[[id]]` links in frontmatter `links:` and are the source of truth.

**Traversal:** a small `graph` module loads frontmatter, builds an in-memory adjacency index and answers queries ("open tasks linked to person X", "all drafts citing note Y"). Hubs are regenerated from the index. Writes are atomic (write a temp file, then `os.replace`) under a single-process lock (a lock file; one runner instance only). Audit is an append-only `audit\YYYY-MM.jsonl`. No database in v1. Windows note: keep node IDs to safe characters (no `:` or reserved names such as `CON`) and keep paths short.

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

## 6. Second Brain and skills

### Access
- Source: Google Drive folder `Second Brain` (ID in `CLAUDE.md`), including all numbered areas. Dai shares the **whole folder with Daikon's Google account as Viewer**. Google itself prevents any write, so read-only does not depend on our code.
- Share with **Viewer only**, and turn off "Viewers can download, print and copy" and re-sharing if the Workspace allows it, so the account cannot hand the files on.
- The retriever restricts every query to the folder tree, caps bytes read per file and per task, and reads only text-like files (Docs exported as text, Markdown, plain text) in v1. `99 Superseded` is skipped.
- **Sensitive areas:** because everything is shared, safety moves into the drafts. Excerpts from `06 Trading and Investments`, `07 Personal and Working Style` and any file the retriever tags as private (credentials, health, finance) are only used if the task needs them, are never quoted in a draft without item-level approval, and set `sensitivity_flags`. Text from notes goes to Anthropic only (v1 uses no other model provider).
- Content is context, never instructions (§7). Facts from notes carry a citation (Drive link). `source-note` nodes store pointers only.
- **Assumption A1:** the folder is owned by `admin@closeby230.com`, which looks like a Google Workspace account. If the admin blocks sharing with outside accounts, either allow sharing for this folder, use a Daikon account inside the Workspace, or fall back to a read-only local mirror.

### Weekly task (Sunday, 03:00 local, configurable)
Run by the same runner as a `task` of kind `weekly`. Steps:
1. **Index refresh:** walk the Second Brain tree through the Drive API (only files changed since the last run), create or update `source-note` link-nodes (title, area, modified time, content hash), retire nodes for deleted files, regenerate hubs.
2. **Skills sync:** read the skills source folder, mirror skills into `%USERPROFILE%\daikon-data\skills\`, and compare with what is active.
   - **Source (confirmed by Dai):** the Second Brain folder `09 Claude Skills`, filled by Dai's own weekly Second Brain task with all the skills he has created, one folder per skill (`SKILL.md` plus reference files and any scripts). Daikon only reads it. Folder ID to be recorded in `CLAUDE.md` once it exists in Drive.
   - **Safety:** every skill is checked on arrival: file types are allowlisted, sizes capped, scripts and their SHA-256 hashes listed, declared tool needs read from the skill. New or changed skills are **staged**, not active.
   - **Activation:** the weekly digest email lists new, changed and removed skills with a diff summary and flags any that contain scripts or request tools or network access. A skill becomes active when Dai replies `OK SKILLS <code>`; for script skills, activation pins the approved hashes. A script that later changes on Drive is staged again and the old pinned version keeps running until Dai approves. Until then the previous version stays active.
3. **Health check:** self-test (a test email round trip, Twilio status, Drive access, token expiry dates) and a short report to Dai.
4. **Housekeeping:** snapshot the graph, prune old audit logs per retention, report spend and run counts.

## 7. Security and threat model

| Threat | Control |
|---|---|
| Prompt injection in email, SMS, notes or skills | Untrusted content in delimited data blocks; the system prompt says it is data; **Claude has no tools** so injection cannot cause an action; output must pass JSON-schema validation; instruction-like text from non-allowlisted senders is just summarized; all outbound text still needs Dai's approval |
| Spoofed commands (forged From / SMS) | Commands accepted only from Dai's verified number or personal email; email requires SPF/DKIM pass in `Authentication-Results`; **every approval needs the per-draft random code** |
| Sending the wrong or changed content | Approval bound to body hash and version; Sender sends the stored body only |
| Data leak to recipients | Sensitivity flags; no sensitive note content quoted without item-level approval; recipients fixed at draft time and shown in the digest |
| Poisoned or malicious skill file or script | Skills staged until Dai approves the diff; script hashes pinned at approval; changed scripts never run until re-approved; version hash recorded in every `skill-run`; Lane 2 limits (below) |
| Tool-using Claude abused through input (Lane 2) | Lane 2 starts only from Dai's verified command; runs as a separate low-privilege Windows user in a throwaway job folder; tool allowlist per skill (named scripts, no general shell); no mail, Drive or Twilio secrets in its environment; no network by default; time and size limits; outputs are only files in the job folder that go through the normal approval gate |
| Credential theft | Secrets in Windows Credential Manager (via `keyring`) or environment variables; never in repo, graph or logs; Google tokens are Daikon's account only; OpenRouter key (phase 2) has a spend limit; the data folder is readable by Dai's Windows user only |
| Runaway cost or loops | Daily cap on model runs; max retrieval rounds and max output size per task; per-sender rate limit; kill switch file `%USERPROFILE%\daikon-data\PAUSE` stops all sending |
| Private data in a public repo | Graph and audit stored outside the repo; `.gitignore` guards; pre-commit check blocks tokens and `daikon-data` content |
| Tampering/forensics | Append-only audit JSONL: every fetch, model run (role, backend, input hash, output hash), retrieval (which file IDs were read), notification, approval, skill activation, send |
| Confidence or routing manipulation | Confidence selects only a model tier; email-supplied confidence text is ignored; approvals, lanes and sender gate never depend on it |
| Sensitive notes sent to third-party providers | Code-based sensitivity tagging; sensitive items go only to `local` or allowlisted backends; audit of which backend saw what |
| Phone-call model sees too much (phase 2) | The `call` model gets only the approved call brief, never Drive access or inbox content (§9) |

Least privilege summary: Daikon's Gmail (read, send), Twilio (his number), Drive (Viewer on the Second Brain), no access to Dai's Gmail or calendar, no tools for the model.

## 8. Failure modes and Windows operations

| Failure | Detection | Behavior |
|---|---|---|
| Laptop sleeps, restarts for Windows Update, or is offline | Heartbeat gap | Resume on wake/logon; mail and texts wait in Gmail/Twilio; digest mentions the delay |
| Claude Pro usage limit hit | Non-zero exit / limit message | Back off, stop non-urgent runs, tell Dai once by SMS; urgent items get a plain "needs your attention" notice with no draft |
| Claude CLI login expired | Auth error | Alert Dai with the re-login step; sending of approved drafts continues |
| Worker returns bad JSON | Schema validation | Retry once, then flag item for manual handling |
| Gmail/Twilio/Drive API error | Exceptions | Exponential backoff; after N failures text Dai |
| OAuth token expired | 401 | Alert Dai with re-auth steps; sending pauses |
| Duplicate processing | Message-ID dedupe | Idempotent node creation |
| Crash mid-send | `sending` state on restart | Check Sent folder before retry; never double-send |
| Dai doesn't answer | Expiry timer | Reminder at 24 h, expire at 72 h; never auto-send |
| Forwarding filter misconfigured | No mail arrives | Weekly self-test email from Daikon to Dai and back |
| Weekly task fails or skills source missing | Task status, health report | Keep current skills active; report to Dai |
| Graph corruption | Atomic writes, daily snapshot | Restore from snapshot; audit log is replayable |

**Windows setup notes (for the plan):**
- **Scheduler:** Task Scheduler task "Daikon runner" starts at logon, restarts on failure (every minute, up to a limit), runs as Dai's user (the Claude login is per user). A second task runs the weekly job, or the runner triggers it internally.
- **Power:** set the laptop to never sleep on AC power, and decide the lid-close action. Pause Windows Update restarts during active hours.
- **Claude Code on Windows:** install and log in once under the same Windows user. Headless runs use `claude -p`; Claude Code on Windows may need Git for Windows, so confirm in milestone 3.
- **Skills lane account:** create a separate local Windows user (for example `daikon-jobs`) with access only to the job folder and the Python/tools needed; Lane 2 jobs run under that user via the runner (`runas` or a scheduled task). Windows Sandbox is a stronger option if the laptop's Windows edition has it (Pro/Enterprise), and can be added later.
- **Paths and files:** use `pathlib`, `os.replace` for atomic writes, UTF-8 everywhere, no reliance on POSIX file permissions (use the user-profile folder ACLs instead).
- **Secrets:** Windows Credential Manager through `keyring`.

## 9. Phase 2: phone calls (outline only)

- Daikon speaks as himself, discloses he is an AI assistant and that the call is recorded/transcribed.
- **OpenRouter is used only here.** Flow: Twilio Voice → Media Streams WebSocket → speech-to-text (local Whisper or cloud) → the `call` model through OpenRouter (a fast, cheap model; a Haiku-class Claude model was Dai's preference and is available on OpenRouter) → text-to-speech (local Piper or cloud) → back to the call.
- Latency matters most: choose the `call` model by measured time to first token, and test OpenRouter's added latency before committing. If too slow, the `call` backend can point at that vendor's API directly.
- **The call model never sees the Second Brain or the inbox.** It receives only the approved `call` brief: goal, facts it may share, hard limits (for example never agree to a price), max duration, and numbers it may call. Third-party model providers therefore see only what Dai approved for that call.
- Needs a public endpoint (Cloudflare Tunnel) with Twilio signature validation. Windows: run `cloudflared` as a service.
- After the call: transcript node plus an SMS summary. Call assist (screen, transcribe, summarize inbound calls) ships before outbound calls.
- Set OpenRouter privacy options (deny prompt training/logging where available; verify current option names in OpenRouter's docs) and a spend limit on the key.

## 10. Cost (estimates, verify before budgeting)

| Item | v1 | Phase 2 |
|---|---|---|
| Claude | Pro subscription (existing) | Same |
| OpenRouter (calls only) | — | `call` model, a few cents/min; spend limit on key |
| Twilio number + SMS | ~$1.15/mo + ~$0.008 per SMS | + voice ~$0.01–0.02/min |
| Gmail, Drive | Free | Free |
| Speech | — | Free if local; cloud adds ~$0.01–0.10/min |

One-time: Twilio A2P 10DLC registration (US) before reliable SMS; allow several days.

## 11. Testing strategy (for the plan phase)

- Unit tests: rule filter, JSON schema validation, state machine transitions (including illegal ones), approval-code and hash binding, graph read/write/traversal, sender idempotency, retriever scoping, weekly index diff, skill validator (rejects scripts, stages changes).
- Contract tests with recorded fixtures for Gmail, Drive and Twilio responses; a fake model gateway returning canned JSON.
- Security tests: injection corpus (emails, notes and skill text containing instructions) must produce no state change beyond a draft awaiting approval; spoofed approval attempts must fail; replayed and stale codes must fail.
- End-to-end dry run: fake inbox → draft → SMS approval → send to a test address, with the kill switch tested.
- Windows tests: run the suite on Windows (paths, atomic writes, locking, Task Scheduler restart).

## 12. v1 milestones

1. Repo skeleton, graph store, audit log, state machine (no external services). Runs on Windows.
2. Gmail fetcher and rule filter, writing nodes.
3. Model gateway with `anthropic_api` and `openai_compat` backends (no-tools mail lane, schema validation, spend caps), JEV-style routing, and the qualification harness, tested with fake gateways.
4. Drive retriever (Viewer account), retrieve-then-draft, citations.
5. Notifier and approval handler (email first, then Twilio SMS after A2P registration clears).
6. Sender with exactly-once guarantees; kill switch; expiry.
7. Weekly task: Second Brain index refresh, skills sync with staging, health check.
7b. Skills lane: restricted Windows user, job-folder runner, per-skill tool allowlists, hash pinning; start with one script skill (for example docx) and review before enabling others.
8. Task Scheduler setup, hardening (injection tests, rate limits, backups), runbook.

## 13. Risks and open decisions for Dai

| ID | Item | Recommendation |
|---|---|---|
| R1 | Using a Pro login for unattended `claude -p` runs may conflict with Anthropic's terms or hit Pro usage limits | Options in order of preference: **(a)** an Anthropic API key (Console) with a monthly spend cap, used by the same `claude -p` or the Claude Agent SDK; API use is meant for automation, and tools and skills work the same; **(b)** keep the Pro login only for a short prototype at low volume after checking the current terms; **(c)** use OpenRouter for these roles (loses native Claude Code tools). The gateway makes this a config change |
| R3 | Gmail OAuth: apps in "Testing" mode get refresh tokens that expire after 7 days | Publish the app as "In production" (personal use, unverified warning) or use IMAP/SMTP with an app password |
| R5 | Approval digest on SMS is short; long drafts are read by email | Accept, or add a local web page for review in v1.1 |
| R7 | Draft voice | Use Dai's `dai-email-drafting` skill, synced by the weekly task |
| R8 | Workspace may block sharing the Second Brain with Daikon's account (A1) | Test sharing first; fallbacks in §6 |
| R10 | Script-based skills carry more risk than text skills | Lane 2 fencing and hash pinning (§2, §6); enable one skill at a time |
| R11 | Tool-less Claude can't search Drive by itself, so retrieval quality depends on our search | Two-round retrieve-then-draft; improve with the `source-note` index; measure in testing |
| R13 | Local or alternate models may be worse at drafting, JSON or tool calls | Qualification harness before any switch; fallback to the default backend |
| R14 | Model-claimed confidence is poorly calibrated, especially in small models | Calibrate on real emails; thresholds are config |
| R15 | Own tool loop must be built and secured (instead of using the Agent SDK) | Small allowlist-only design, tested against both backends (plan M7b.3) |
| R12 | Whole Second Brain visible to Daikon increases the impact of a leaked token | Narrow OAuth scope to `drive.readonly`, keep tokens in Credential Manager, restrict Viewer download/copy |

**Resolved:** skills source is `09 Claude Skills`, filled by Dai's weekly Second Brain task.
**Resolved (Dai accepted recommendations):** Q5 Claude access is an Anthropic API key with a monthly spend cap (backend `anthropic_api`); the mail lane uses the Messages API with no tools. Q6 the first script skill enabled is the Word (docx) builder. Later additions (v4.1): `openai_compat` backend for OpenRouter/local models, Daikon's own tool loop for the skills lane (replacing the Agent SDK), JEV-style confidence routing, privacy-aware routing, optional local embeddings, and a qualification harness. See `docs/daikon-implementation-plan.md` §0.

**Open questions for Dai**
- **Q5:** Claude authentication for Daikon: API key with a spend cap (recommended), Pro login for a prototype only, or OpenRouter? (R1)
- **Q6:** Which script-based skills do you want first (for example the Word, PDF, PowerPoint or Excel builders)? I will enable one at a time.

**Awaiting your approval to proceed.** Answer Q5 and Q6, or tell me to proceed on the recommendations, and I will write the implementation plan.
