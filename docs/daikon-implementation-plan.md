# Daikon — Implementation Plan (simplified)

Status: **Approved to start by Dai (2026-10-14): "implement, test, replan, repeat".** Sources: `CLAUDE.md`, `docs/daikon-design.md`, `docs/daikon-red-team-plan.md`. This file is the single source of truth for build order. It was simplified with `/simplify` + JEV (see §10). Nothing the red-team plan requires for the approval gate was cut.

## Progress (updated after each milestone)

| Milestone | Status |
|---|---|
| M1 Foundations and walking skeleton (M1.1–M1.10) | **Done** (395 tests across all milestones now; at M1: 171 tests, ruff and mypy clean, CI green on Windows + Linux for M1.1–M1.7; skeleton e2e covers happy path, Dai-only mode, spoofed/unauthenticated OK, quoted/forwarded OK, lockout, model-chosen recipients, draft tampering, undo, defanged links, untrusted prompt wrapping, audit chain |
| M2 Gmail intake | **Done** except the live check: parser, trusted auth-header parsing, sender flags, person book, rule filter, mailbox (history polling, threaded send), OAuth helpers, runner (backoff, heartbeat, instance lock), CLI `auth-gmail` and `smoke`. The real run (M2.5) waits for Dai's Day-0 Google setup |
| M3 Worker | **Done**: `anthropic_api` gateway (no tools, schema output, caps, cost, privacy label, error kinds), prompt escaping, at-least-once processing with retry/refusal/cap handling, voice guide, model notes with cost estimate (about $10–15/month at 30 drafted emails a day) |
| M4 Second Brain | **Done**: `ScopedDrive` (tree-confined, read-only, text-only), retriever (trust tagging, code-based sensitivity withholding), retrieve-then-draft with cited notes and one extra round |
| M5 Notifications and approvals | **Mostly done**: digest, notifier, command channel (OK/NO/EDIT/UNDO/PAUSE/RESUME with codes), EDIT redraft, composition root (`app.py`, `doctor`, CLI). M5.2 reminders (24h) and expiry notices done. M5.5 SMS code done and tested with a fake (inactive until `twilio_number` is set). Remaining: SMS digest short form and the second-channel confirmation flow |
| M6 Sender and hardening | **Mostly done** (588 tests, ruff and mypy clean): sender, policy, exactly-once and crash recovery (M6.2), Task Scheduler XML (M6.3), runbook (M6.4), RT traceability test (M6.5), daily backup. Remaining: M6.6 repo protections (manual), lockfile, Action SHA pins |


## 1. How we work

**Loop per task (superpowers):** failing test → minimal code → run tests → refactor → review the diff → verify → commit → **replan** (edit this file if anything learned changes the next tasks) → repeat.

**JEV step decision** (record in the commit body for every non-simple task):
`{"task_complexity":"simple|medium|complex","decision_type":"classification|routing|scoring|judgment","confidence":0.0,"escalate":false}`

| Confidence | Action |
|---|---|
| ≥ 0.85 | Do it |
| 0.70–0.84 | Do it, note the doubt in the commit |
| < 0.70 | Stop, lay out options with trade-offs, ask Dai if it changes scope, security or cost |

Security-sensitive tasks (policy gate, approvals, sender, untrusted input, Drive scoping) are never `simple`. Open-ended writing stays prose.

**Definition of done:** test written first and passing; ruff and mypy clean; no secrets or private data in the diff; audit entry for every external action (guaranteed by the policy gate, not by convention); docs updated if behavior changed; one small commit. A failing security test stops feature work.

## 2. Decisions (only what is not already in `CLAUDE.md`)

Runtime, identity, Second Brain, autonomy, backends and budget are in `CLAUDE.md` "Decisions so far" and `docs/daikon-design.md`; they are not repeated here. Plan-level choices:

- Python 3.12; `pytest`, `ruff`, `mypy`. Reuse libraries instead of hand-rolling: `filelock`, `keyring`, `google-api-python-client` + `google-auth`, `anthropic` SDK retries or `tenacity`, `jsonschema` or `pydantic`, `secrets` + `hmac.compare_digest`, `gitleaks`, `pip-audit`, Dependabot, `schtasks`/exported task XML.
- **v1 = the smallest safe email loop.** Weekly sync, skills, alternate models and voice are later releases (§5, §6).
- v1 sends **email only** to others (after G2); SMS goes to Dai only. SMS to third parties is a later, separately reviewed capability.
- v1 sends only text to Anthropic's API. Sensitive Second Brain excerpts are excluded from model input unless Dai approves that item (replaces privacy routing until other backends exist).
- Triage output keeps a `confidence` field for later calibration; thresholds and escalation (JEV routing) come with alternate models.

## 3. Releases

| Release | Scope | Enter when |
|---|---|---|
| **v1** | Gmail intake → Second Brain context → Claude draft → approval digest (email, SMS when ready) → send after approval | This plan, M1–M6 |
| v1.1 | Weekly task, skills sync from `09 Claude Skills`, text-only skills in the mail lane | v1 live and stable 1 week |
| v1.2 | Skills lane (tools, fenced), docx skill first | v1.1 + RT-08 and RT-10 green |
| v1.3 | `openai_compat` backend, JEV routing, qualification harness, local embeddings, privacy routing for non-Anthropic backends | v1 stable; Dai wants it |
| v1.4 | Dead-man's switch, cost report, quarterly drill checklist, timed revoke drill | Anytime after v1 |
| v2 | Phone calls (OpenRouter `call` role) | v1 stable 2 weeks |

## 4. Dai's tasks

**Day 0 (one session, start the long-lead items first):**
P1 Daikon Gmail account · P2 Google Cloud project, Gmail + Drive APIs, OAuth client, consent screen "In production", scopes Gmail read+send and Drive read-only, **then a real-token smoke test (M2.5)** · P3 share the Second Brain with Daikon's account as Viewer (disable download/copy/re-share if allowed) and test one file read · P5 Twilio account, number, scoped API key, 2FA, number lock, spend cap, **start A2P 10DLC registration now** · P6 Anthropic API key with a monthly spend limit · P8 confirm Dai's mobile number and personal email as the only command identities · P11 hardening: passkey or security key on Daikon's Gmail, Google and GitHub; carrier port-out PIN and SIM lock; BitLocker; password manager · P7 Windows: Python 3.12, Git, never sleep on AC, update active hours.

**Soon after M2 works:** P4 Gmail filter forwarding chosen mail to Daikon (start with one label).

**Later releases only:** `daikon-jobs` Windows user (v1.2); Ollama/LM Studio and 50 labeled emails (v1.3).

The step-by-step version for Dai is `docs/day-0-checklist.md`.

## 5. Repository layout and rules

```
daikon/
  pyproject.toml  uv.lock or hashed requirements  models.yaml.example
  src/daikon/ config.py clock.py secrets.py graph/ audit.py limiter.py approvals.py
              policy.py untrusted.py alerter.py gateway/ worker.py gmail/ drive/ sms/
              digest.py notifier.py commands.py sender.py runner.py cli.py
  tests/ unit/ security/(corpus/*.yaml) contract/ e2e/   # markers: unit, security, live
.github/workflows/daikon-ci.yml  .github/dependabot.yml  .pre-commit-config.yaml
```

Rules: one task = one small commit. CI runs the full suite on Windows and unit tests on Linux; `live` tests (real Gmail, Drive, Twilio) never run in CI, only manually or nightly on Dai's laptop. Every external action goes through `OutboundPolicy`. Every model call goes through the gateway. The existing Jekyll site is untouched.

## 6. v1 milestones

### M1 — Foundations and walking skeleton (no external services)
| ID | Task | Test first |
|---|---|---|
| M1.1 | Skeleton + CI + markers; hashed lockfile, `pip-audit`, Dependabot (pip + Actions), Actions pinned to SHAs; `gitleaks` pre-commit and CI; `.gitignore`; `daikon-data` path guard | CI green; sample token and data path blocked (RT-14) |
| M1.2 | Config loader; injectable `Clock`; `SecretStore` (keyring, in-memory fake, expiry metadata, 14-day warning) | Missing keys error clearly; clock fakes work; secrets never read from files |
| M1.3 | Graph store: atomic write (`os.replace`), `filelock` single-instance lock, hubs, simple queries | Crash keeps old file; second instance refuses; Windows-safe IDs |
| M1.4 | Audit log: append-only JSONL, **hash chain from the first entry**, redaction, verifier | Tamper detected; no secrets logged (RT-17) |
| M1.5 | `Limiter`: `check_and_consume(scope, key, amount)` for model runs, dollars, sends, SMS, approvals, per-sender hourly | Caps trip; persisted across restarts (RT-07, RT-12) |
| M1.6 | `ApprovalRequest` core: kinds (`send`, later `skill_activation`, `job_run`, `call_brief`); states incl. held/undone; single-use `secrets` code; expiry; lockout; constant-time compare; exactly-once `sending` | Every legal/illegal transition; replay, stale, wrong code, lockout (RT-04, RT-21) |
| M1.7 | `OutboundPolicy.evaluate()` → allow / hold(tier, extra channel) / deny(reason), with automatic audit: Dai-only until G2, `PAUSE` file, caps via `Limiter`, first-time recipient, hold-and-undo window | Non-Dai recipient denied; PAUSE blocks; every decision audited (RT-05, RT-20 base) |
| M1.8 | `Untrusted` type + normalization: HTML→text, strip invisible content, size caps, split quoted/forwarded text, instruction-like flag; shared injection corpus runner (`tests/security/corpus/*.yaml`) | Hidden text, oversize, forwarded-instruction cases (RT-01, 11, 12, 13) |
| M1.9 | `Alerter`: severity, rate limit, email/SMS fallback | Burst is rate-limited; fallback works |
| M1.10 | Walking skeleton E2E with fakes: fake Gmail → fake gateway → draft → console notifier → approval → fake sender | One email reaches an approved send; spoofed approval fails |

### M2 — Gmail intake
| ID | Task | Test first |
|---|---|---|
| M2.1 | Gmail wrapper over `google-api-python-client` + fake; `live` contract tests | Fake and real satisfy one interface |
| M2.2 | Message → `message`/`thread`/`person` nodes, dedupe; sender display (real address, display-name and reply-to mismatch, lookalike, new sender); SPF/DKIM from the Gmail-added `Authentication-Results` only | Fixtures (RT-19) |
| M2.3 | Rule filter: newsletters/no-reply, trust levels, daily model-run cap via `Limiter` | Table-driven |
| M2.4 | Poll loop with backoff, heartbeat gap → `Alerter`; `daikon auth gmail` (InstalledAppFlow, token in `SecretStore`) | Simulated errors back off |
| M2.5 | Live smoke test: list one message, send one message to Dai | Passes on Dai's laptop |

### M3 — Worker
| ID | Task | Test first |
|---|---|---|
| M3.1 | Research note: current model IDs, prices, limits, structured-output support (docs) | — |
| M3.2 | Gateway interface + `anthropic_api`: no tools, JSON schema output, SDK retries, spend cap via `Limiter`, cost logging, pinned model version, backend data class declared (deny-by-default) | Tool request rejected; cap blocks calls |
| M3.3 | Prompt builder accepting only `Untrusted`; delimiter escaping | Snapshots; delimiter-break fails |
| M3.4 | Draft schema `{category, urgency, confidence, needs_dai, summary, draft_body, citations, sensitivity_flags}` + validator, one retry then flag | Valid/invalid/oversize/extra-field |
| M3.5 | Worker triage → draft with fake gateway; default style file | Canned outputs make correct nodes |

### M4 — Second Brain
| ID | Task | Test first |
|---|---|---|
| M4.1 | `ScopedDrive(root_id, deny, max_bytes, mime_allow)` is the only Drive object; `drive.readonly`; skips `99 Superseded`; out-of-tree IDs raise; fake + `live` tests | Out-of-tree and superseded rejected |
| M4.2 | Excerpts with caps and citation links; trust tagging (owner, last editor); instruction-like text flag | Non-Dai files cannot set recipients (RT-09) |
| M4.3 | Two-round retrieve-then-draft | Max two rounds |
| M4.4 | Sensitivity by code (folders `06`, `07`, patterns); sensitive excerpts excluded from model input unless Dai approves the item | Flagged text never reaches the fake gateway |

### M5 — Notifications and approvals
| ID | Task | Test first |
|---|---|---|
| M5.1 | Digest formatter: plain text, header fields written by code (raw sender, auth result, new-sender flag), model summary below a divider, defanged URLs; SMS short form | Golden files (RT-02, RT-03) |
| M5.2 | Notifier (email) through `OutboundPolicy`; reminders and expiry via `Clock` | Time-travel tests |
| M5.3 | `CommandChannel.authenticate()` → `VerifiedCommand` (identity, SPF/DKIM or Twilio evidence, top-level text only); command registry OK/NO/EDIT/UNDO/PAUSE | Spoof, forward, quoted-instruction cases (RT-04, RT-11) |
| M5.4 | Approval handler on `ApprovalRequest`; EDIT creates version n+1 with a new code | Stale version rejected |
| M5.5 | Twilio wrapper and SMS channel: poll inbound, verify From, daily SMS cap, scoped key. **Does not block shadow mode** (email approvals first) | Spoofed From ignored (RT-07) |

### M6 — Sender and hardening (finish during shadow week, before G2)
| ID | Task | Test first |
|---|---|---|
| M6.1 | Sender through `OutboundPolicy`: exact stored body, hash re-check, one send per approval, hold-and-undo | Double approval sends once. **Needed before shadow mode (restricted to Dai)** |
| M6.2 | Crash recovery: check Sent folder before retry | Crash at each step |
| M6.3 | Task Scheduler XML in repo (start at logon, restart on failure); nightly copy of `daikon-data` | Dry-run output reviewed |
| M6.4 | `docs/runbook.md`: re-auth, kill switch, key rotation, revoke-everything, lost laptop; one manual revoke drill | Dai reviews |
| M6.5 | RT traceability test: fails if any in-scope RT ID has no test; injection corpus and golden checks re-run in CI when prompt files or `models.yaml` change (RT-18) | Missing-ID case fails |
| M6.6 | Repo protections: branch protection, secret scanning, 2FA; decide on a private repo (RT-15) | Checklist verified |

## 7. Later releases (task lists, built after v1 is live)

- **v1.1:** weekly runner entry on the `Clock`/due-at seam; `ScopedDrive` read of `09 Claude Skills`; file allowlist, caps, script hashes; staging and `OK SKILLS <code>` as an `ApprovalRequest(kind=skill_activation)`; skill diff in digest and local pinned manifest (RT-08); text-only skills in the mail lane; weekly health report; index refresh into `source-note` nodes only if retrieval needs it.
- **v1.2:** `JobFS` (canonical paths, reparse-point/UNC rejection) + `ToolRegistry` (argv-list-only tools) built first; own tool loop; `daikon-jobs` user, ACLs, Job Object limits, outbound firewall rule; command intake from Dai only; enable **docx** only after RT-10 and a written review.
- **v1.3:** `openai_compat` backend; JEV thresholds and one escalation; `daikon qualify` harness with labeled emails; local embeddings; privacy routing by backend data class (`local | allowlisted | cloud`).
- **v1.4:** dead-man's switch; cost report with 80% alert; quarterly drill checklist; timed revoke drill.
- **v2:** call assist, then goal-based calls (design §9, RT-22). Community call booking (decided 2026-10-14): `call-booking` skill with one-question-at-a-time interview and recommended answers; approved call brief; AI disclosure, interpreter request, optional approved no-show fee; local `call`/`provider` graph nodes plus full report to Dai after each call; weekly filing into the Second Brain by Dai's task and read-back through `ScopedDrive`; reuse of service-level knowledge only, never person-specific data; call notes treated as untrusted. Design doc: `docs/daikon-call-skill-design.md` (milestones C0-C7, RT-22 to RT-30); includes info-only calls and inbound callbacks from numbers Daikon called first. No code until Dai approves it.

## 8. Rollout and gates

| Stage | What runs | Gate |
|---|---|---|
| Shadow mode (1 week) | Intake, triage, drafts, email digests to Dai only; sender restricted to Dai | M1–M5 and M6.1 done; Day-0 tasks done |
| During shadow week | M6.2–M6.6; SMS joins when A2P clears | — |
| **G1 quality** | Dai reviews ~20 real drafts: usefulness, voice, citations, sensitive handling | Dai signs off |
| **G2 security** | In-scope RT tests green: RT-01–07, 09, 11–15, 17–21; revoke drill done; kill switch and caps tested | All green |
| Live | Sender may deliver approved drafts to others (email) | G1 + G2 |
| Per-capability gates | RT-08 for skills sync, RT-10 for skills lane, RT-22 for voice | Each green before that capability is enabled |

## 9. Red-team traceability (in-scope for v1)

| RT | Task | RT | Task |
|---|---|---|---|
| 01 | M1.8 | 12 | M1.5, M1.8 |
| 02, 03 | M5.1 | 13 | M1.8 |
| 04 | M1.6, M5.3 | 14 | M1.1 |
| 05 | M1.7, M6.1 | 15 | M1.1, M6.6 |
| 06 | Day-0 P11 (manual checklist) | 17 | M1.4 |
| 07 | M1.5, M5.5 | 18 | M6.5 |
| 09 | M4.2 | 19 | M2.2 |
| 11 | M1.8, M5.3 | 20 | M1.7 |
| 16 | M6.4 (manual drill) | 21 | M1.6 |
| 08, 10, 22 | later releases | | |

## 10. Simplification record (JEV)

| Change | Confidence | Source finding |
|---|---|---|
| Weekly task, skills sync and skills lane moved to v1.1/v1.2 (deferred, not removed) | 0.95 | Simplification #1, #2 |
| Alternate-model track (openai_compat, qualification, embeddings, privacy routing) moved to v1.3 | 0.9 | Simplification #3, #5, #6 |
| JEV thresholds deferred; `confidence` field kept | 0.8 (noted) | #4 |
| Privacy routing replaced in v1 by "exclude sensitive from model input" | 0.8 (noted) | #7 |
| Dead-man's switch, quarterly drill checklist, timed drill, cost report moved to v1.4 | 0.85 / 0.75 | #8, #9 |
| Audit hash chain merged into audit log; digest hardening merged into formatter | 0.85 / 0.7 | Reuse #4, Altitude #11 |
| One `OutboundPolicy`, one `ApprovalRequest`, one `Untrusted` type, one `Limiter`, plus `Clock`, `SecretStore`, `Alerter` foundations replace ~20 scattered tasks | 0.8–0.85 | Altitude #1, #2, #3, #7, #8 |
| Libraries replace custom code (`filelock`, `gitleaks`, `keyring`, Dependabot, SDK retries, `secrets`) | 0.75–0.85 | Reuse #3, #5, #6, #10, #11 |
| Walking skeleton first; Day-0 Dai batch; shadow mode starts after M5 + M6.1; SMS non-blocking; `live` tests out of CI | 0.75–0.85 | Efficiency #1–#5, #10 |
| Explicit G2 RT list; later capabilities gated by their own RT tests | 0.8 | Altitude #4 |
| **Not changed (< 0.70):** M1.3 graph trim, nightly-copy vs snapshot task, per-task JEV record rule | 0.5–0.65 | Simplification #10, #13; Efficiency note |

## 11. Decisions log

| Date | Decision / surprise | Effect |
|---|---|---|
| 2026-10-14 | Plan simplified; skills and weekly sync deferred to v1.1/v1.2 | Dai's skills work arrives after v1 is live; revisit if Dai wants it earlier |
| 2026-10-14 | Dai chose to keep the Windows laptop as the runtime (cloud VM analysis declined) | Plan stays Windows-centric; `SecretStore` and scheduler seams keep a later move cheap |
| 2026-10-14 | M1 built test-first; skeleton wired real policy, approvals, audit with fake Gmail/model | Replan items below |
| 2026-10-14 | **Gap:** policy `hold` (second channel required) currently makes the sender mark the approval `failed` | M6.5 adds an approval state `needs_confirmation` and a second-channel confirm flow; until then high-risk sends fail closed |
| 2026-10-14 | **Gap:** `approvals` daily cap (Limiter scope) is defined but not consumed anywhere | Consume it in `ApprovalManager.approve` when M5.4 wires the handler |
| 2026-10-14 | **Gap:** PAUSE verb and the SMS channel are not in `commands.py`; messages from Dai that are not commands are only audited | M5.3 adds PAUSE, SMS, and decides what to do with free-text from Dai |
| 2026-10-14 | **Gap:** hold length is hard-coded (60 s) in the pipeline's "approved" notice | Read it from `ApprovalManager` config (small cleanup in M5.4) |
| 2026-10-14 | **Gap:** `known_recipient` for the policy is a callable; no graph-backed implementation yet | Add a `person`-node lookup in M2.2 (sent-to history) |
| 2026-10-14 | `GraphStore` got a read cache (mtime+size) after the approval tests exposed O(n²) YAML parsing | Keep; cache is per-process only |
| 2026-10-14 | Actions are pinned by version tag, hashed lockfile not yet generated | Pin to commit SHAs and generate the lockfile in M6.6 (needs network to resolve) |
| 2026-10-14 | **Found:** substring secret-key matching flagged `max_tokens`/`input_tokens`; now word-based | Fixed in M3 prerequisites; audit keeps token counters |
| 2026-10-14 | **Found:** the Gmail marker advances after a fetch, so a temporary model failure would have lost mail | Messages are stored before any model call and retried oldest-first in batches (at-least-once) |
| 2026-10-14 | **Found:** whitespace/case variants of the untrusted tag could break out of the prompt block | Escape widened; covered by tests |
| 2026-10-14 | **Decision:** structured-output schema keywords (min/max/length) are stripped from the API copy and enforced locally | Verify against the live API in the first shadow-mode run |
| 2026-10-14 | **Replan:** M4.8 (excerpt trust tagging) merged into M4.2; M4.5/M4.7 reduced to "sensitive notes are withheld by code" for v1 | Matches the simplified plan |
| 2026-10-14 | **Accepted risk:** an attacker-chosen search term can pull non-sensitive notes into a draft | Dai sees the draft and "notes used" before approving; sensitive notes are withheld; listed in the red-team plan §8 |
| 2026-10-14 | Design doc still mentions Pro login and `claude -p` in places | Update design in a docs task alongside M1 |
| 2026-10-14 | **Built:** composition root, `doctor`, CLI, runbook, Task Scheduler XML, daily backup (7 kept, run from the runner; failure alerts but never fails a tick), RT traceability test (`rt_map.yaml`; RT-08/10/22 deferred to later releases) | M6.3-M6.5 done |
| 2026-10-14 | **Replan:** next order is M5.2 reminders/expiry, then `needs_confirmation` second-channel flow and the `approvals` cap, then M5.5 SMS (after A2P). Live checks (M2.5, structured-output keywords) wait for Dai's Day-0 setup | Shadow mode is blocked only on Day-0 tasks |
| 2026-10-14 | **Built:** M5.2 one reminder at 24h and one expiry notice (email to Dai only, no codes in reminders; reminded flag on the approval node) | Next: `needs_confirmation` flow and `approvals` cap |
| 2026-10-14 | **Fixed gap:** the `approvals` daily cap is now enforced (checked before OK, consumed only by a successful approval; Dai is told when it is reached) | Remaining gaps: `needs_confirmation` flow, configurable hold length, SMS |
| 2026-10-14 | **Replan:** the `needs_confirmation` flow needs a second channel (SMS), so it moves behind M5.5. Meanwhile an approved reply that policy refuses now tells Dai ("not sent, reply yourself") instead of failing silently | Remaining gaps: configurable hold length, SMS, M6.6, lockfile |
| 2026-10-14 | **Fixed gap:** hold length is now `hold_seconds` in `models.yaml` (10-600, default 60) and the "approved" notice reads it from `ApprovalManager` | Remaining: SMS (M5.5), M6.6, lockfile and Action pins, live checks |
| 2026-10-14 | **Built:** M5.5 SMS channel: `SmsInbox` (From must be Dai's number, To our number, under 2h old, once per SID, body never stored), `DaiSms` through policy, `TwilioTransport` over REST with a scoped API key, config `twilio_number`, doctor checks the three Twilio secrets. **Residual risk:** SMS From can be spoofed in rare cases; mitigated because every command except PAUSE needs a one-time code only Dai received | Untested against live Twilio until Day-0 + A2P |
| 2026-10-14 | **Decided:** (a) no-show fee = Daikon prepays the service, $5 kept on no-show, rest refunded: needs a payment method, limits and a red-team row (RT-25 extended) before phase 2; (b) first-time recipient confirmation = one-time text to Dai's phone, built after SMS is live (`needs_confirmation` state). Day-0 steps in `docs/day-0-checklist.md` | Next code task: the confirmation flow, once SMS can be tested |
| 2026-10-14 | **Decided:** the call-booking prepayment uses Dai's own credit card, repaid later by the person helped. Card number must never reach the model, transcripts, logs or repo; each payment approved by Dai with caps; the hand-over route to the business is chosen in the phase 2 design | RT-25 covers it; no payment code before then |
| 2026-10-14 | **Built:** second-channel confirmation. Policy `hold` now parks the approval in `needs_confirmation`, texts Dai a one-time `CONFIRM <code>` (30 min, hashed, shared lockout), accepted from SMS only (email CONFIRM is ignored), then resumes the same exactly-once send. No SMS or a failed text fails closed with a notice to Dai; expiry notifies; pause blocks | Closes the earlier `hold` gap |
| 2026-10-14 | **Done in the Second Brain:** new area `10 Daikon Calls` (Hub, Entities, Templates), `Graph - Daikon Calls` and a setup Log in `00 Control`, Index v26 (v25 moved to 99 Superseded). **Decided:** every call asks the office to call back Daikon's own number (mandatory, cannot be disabled). Retriever now withholds `10 ` and any "Daikon Calls" path from email drafts | Weekly task still needs extending (Dai) |
| 2026-10-14 | **Decided:** exactly two command/talk channels (email, text); interview one-by-one by text plus the full set by email; call reports go to the existing Handovers folder (create-only write, RT-31) and the Saturday task files them with GraphRAG. Full updated task prompt in `docs/saturday-task.md` (not yet applied to the live task) | Interview texts need their own SMS cap; Dai to share the Handovers folder with Daikon as Editor at C4 |
| 2026-10-14 | **Applied** the updated Saturday task prompt to the live task (`docs/saturday-task.md`); verified identical, schedule and connectors unchanged. First run with it: Saturday 2026-10-17 | Until a Daikon call handover exists, STEP 2F reports "Daikon Calls: no new handovers" |
