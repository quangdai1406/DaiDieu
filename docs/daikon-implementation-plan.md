# Daikon — Implementation Plan (v1)

Status: **Draft, awaiting Dai's approval.** Based on `docs/daikon-design.md` v4 and the decisions below. No code is written until this plan is approved.

## 0. Decisions applied from the design's open questions

| Q | Decision (recommendation accepted) |
|---|---|
| Q5 Claude access | **Anthropic API key with a monthly spend cap** set in the Console. Mail lane calls the **Messages API directly with no tools** (no Claude Code needed). Skills lane uses Claude Agent SDK / headless Claude Code with the same key, inside the fenced job folder. Pro login is not used. |
| Q6 First script skill | **Word (.docx) builder** first. Excel, PDF and PowerPoint builders later, one at a time, each after a security review. |
| Skills source | `09 Claude Skills` in the Second Brain (filled by Dai's weekly task). |
| Design changes | Model gateway backends become `anthropic_api` (mail lane), `claude_agent` (skills lane), `openrouter` (phase 2 calls only). `claude_cli` is dropped. Budget: API pay-per-token plus Twilio. |

Model IDs live only in `models.yaml` (not in code). Defaults at implementation time: a small, fast model for `triage`, a stronger one for `draft`/`research`; confirm current IDs and prices on Anthropic's pages in task M3.1.

## 1. Prerequisites that need Dai (do these in parallel with M1–M2)

| # | Action | Needed by | Notes |
|---|---|---|---|
| P1 | Create Daikon's Gmail account | M2 | Turn on 2-step verification |
| P2 | Google Cloud project, enable Gmail API and Drive API, OAuth client; set consent screen to **In production** (personal use) so tokens do not expire after 7 days | M2 | Scopes: Gmail read + send for Daikon's account; Drive **read-only** |
| P3 | Share the **Second Brain** with Daikon's Google account as **Viewer**; disable viewer download/copy/re-share if Workspace allows. If the Workspace blocks external sharing, tell me | M4 | Folder ID `1j8kRB_OiGRirovIVL6gOfjIIhge0ktBk`; get the ID of `09 Claude Skills` too |
| P4 | Gmail filter on Dai's account: forward chosen mail to Daikon's Gmail | M2 | Start narrow (one label) |
| P5 | Twilio account, buy a number, **start A2P 10DLC registration now** (takes days) | M5 | Store credentials in Windows Credential Manager, not files |
| P6 | Anthropic Console: create an API key for Daikon, set a **monthly spend limit** | M3 | Separate key just for Daikon |
| P7 | Windows: install Python 3.12 and Git; create local user `daikon-jobs` (standard user) for the skills lane; set laptop to never sleep on AC; set active hours for updates | M1, M7b | |
| P8 | Give Daikon's phone-approval number: Dai's own verified mobile and personal email | M5 | The only command identities |

## 2. Repository layout and global rules

```
daikon/
  pyproject.toml          # Python 3.12, pytest, ruff, mypy
  models.yaml.example     # roles -> backend + model id + limits (real file lives outside repo)
  src/daikon/
    config.py  audit.py  graph/  statemachine.py  filters.py
    gateway/ (base, anthropic_api, claude_agent, openrouter)
    gmail/  drive/  sms/  retrieval.py  worker.py  drafts.py
    approvals.py  sender.py  notifier.py  weekly/  skills/  runner.py  cli.py
  tests/  (unit/, contract/, security/, e2e/, fixtures/)
  docs link: ../docs/
.github/workflows/daikon-ci.yml   # pytest + ruff + mypy on windows-latest and ubuntu-latest
```

Global rules:
- **Test first.** Each task starts with a failing test, then the minimum code, then refactor. One task = one small commit.
- The existing Jekyll site is untouched; changes are limited to `daikon/`, `docs/`, `.github/workflows/daikon-ci.yml`, and `.gitignore` additions.
- **No secrets and no personal data in the repo.** Runtime data lives in `%USERPROFILE%\daikon-data\`. A pre-commit check (task M1.7) blocks token-like strings and `daikon-data` paths.
- Every external action goes through one `Sender`/`Notifier` seam that the tests can fake. Until the **security gate (G2)** passes, the sender is hard-wired to only allow Dai's own address and number.
- Every model call goes through the gateway, which logs to the audit file and enforces caps.

## 3. Milestones and tasks

### M1 — Foundations (no external services; runs on Windows)
| Task | Tests written first | Done when |
|---|---|---|
| M1.1 Project skeleton, tooling, CI on Windows + Linux | CI runs an empty pytest | Green CI on both |
| M1.2 Config loader (`models.yaml`, paths under `daikon-data`, limits) with validation | Missing/invalid keys fail with clear errors; secrets never read from files | Unit tests pass |
| M1.3 Graph store: node read/write (frontmatter + body), atomic write, single-process lock | Round-trip; crash mid-write leaves old file intact; second instance refuses to start; Windows-safe IDs | Unit tests pass |
| M1.4 Graph index and traversal (links, typed edges, hubs, queries like "open tasks linked to person X") | Fixture graph; query results; hub regeneration idempotent | Unit tests pass |
| M1.5 Audit log (append-only JSONL, monthly files, input/output hashes) | Append-only; rotation; no secrets logged (redaction test) | Unit tests pass |
| M1.6 Approval state machine (design §5) | Every legal transition; every illegal one raises; expiry; exactly-once `sending` rule | 100% of transition table covered |
| M1.7 Pre-commit secret/data guard + `.gitignore` | Sample token and `daikon-data` file are blocked | Hook works locally and in CI |

### M2 — Gmail intake and rule filter
| Task | Tests first | Done when |
|---|---|---|
| M2.1 Gmail client wrapper (list new, get, send, labels) behind an interface; fake for tests | Contract fixtures recorded from sample responses | Fake and real share one test suite |
| M2.2 Message → graph nodes (`message`, `thread`, `person`), dedupe by Message-ID | Duplicate delivery creates one node set | Idempotent |
| M2.3 Header authentication parsing (SPF/DKIM from `Authentication-Results`) | Pass/fail/missing fixtures | Result stored on `message` |
| M2.4 Rule filter: newsletters/no-reply (List-Unsubscribe), automated senders, trust levels, daily model-run cap | Table-driven cases | Matches design §2 |
| M2.5 Poll loop with backoff and heartbeat | Simulated API errors back off; heartbeat written | Unit tests pass |
| M2.6 OAuth setup command (`daikon auth gmail`) storing tokens in Credential Manager (`keyring`) | Token store/retrieve with a fake keyring | Works on Dai's laptop (manual check) |

### M3 — Model gateway and worker (mail lane)
| Task | Tests first | Done when |
|---|---|---|
| M3.1 Confirm current model IDs, limits, pricing and structured-output support from Anthropic's docs; record in `docs/` | — (research task) | Short note with source links |
| M3.2 Gateway interface + `anthropic_api` backend: no tools, JSON schema output, retries, per-role timeouts, token/cost accounting, daily spend cap | Fake HTTP: retry on 429/5xx; cap trips and blocks calls; costs logged; **a request containing tools is rejected** | Unit + contract tests pass |
| M3.3 Prompt builder: system prompt, untrusted-data wrapping, schema | Snapshot tests; delimiters can't be closed by input (escaping test) | Snapshots reviewed by Dai |
| M3.4 Draft JSON schema + validator; one retry, then flag | Valid/invalid/oversize/extra-field cases | Matches design §3 step 4 |
| M3.5 Worker: triage → draft with citations, using a fake gateway | Canned outputs produce correct nodes; invalid output flows to "flag for Dai" | Unit tests pass |
| M3.6 Style source: load `dai-email-drafting` instructions from the synced skills (placeholder until M7) | Falls back to a default style file | Unit tests pass |

### M4 — Second Brain retrieval
| Task | Tests first | Done when |
|---|---|---|
| M4.1 Drive client wrapper (list, search, export text) behind an interface; scope `drive.readonly` | Fake + contract fixtures | Real client works with P3 done |
| M4.2 Tree scoping: every query restricted to the Second Brain tree; skip `99 Superseded`; reject files outside the tree | Out-of-tree and superseded results are dropped | Unit tests pass |
| M4.3 Excerpt builder: size caps, text-only types, citation links | Caps enforced; citations present | Unit tests pass |
| M4.4 Two-round retrieve-then-draft in the worker | Round 1 search terms → retriever → round 2 draft; max two rounds | Unit tests pass |
| M4.5 Sensitivity tagging (folders `06`, `07`, credential/health/finance patterns) → `sensitivity_flags` | Flagged excerpts never appear in draft body unless approved flag set | Security test passes |

### M5 — Notifier, approvals and SMS
| Task | Tests first | Done when |
|---|---|---|
| M5.1 Draft node creation: versioning, `body_sha256`, random 4-char code | Hash changes with body; codes unique and unguessable length | Unit tests pass |
| M5.2 Digest formatter (SMS short form, email full form with citations) | Length limits; golden files | Reviewed by Dai |
| M5.3 Notifier to Dai only (email first); recipient fixed to Dai's address | Attempt to notify anyone else raises | Unit tests pass |
| M5.4 Approval parser: `OK/NO/EDIT <code> …`, case/whitespace tolerant | Table-driven incl. malformed input | Unit tests pass |
| M5.5 Approval handler: verify sender identity, SPF/DKIM (email), code, version, hash, expiry | Wrong sender, wrong code, stale version, expired draft, replay all rejected | Security tests pass |
| M5.6 Twilio client wrapper: poll inbound, send; verify From == Dai's number | Fake + fixtures; spoofed From ignored | Unit tests pass (real SMS after P5 clears) |
| M5.7 Reminders (24 h) and expiry (72 h) | Time-travel tests | Unit tests pass |

### M6 — Sender, safety rails
| Task | Tests first | Done when |
|---|---|---|
| M6.1 Sender: send exactly the stored body, re-verify hash, one send per approval | Double approval sends once; modified body blocked | Unit tests pass |
| M6.2 Crash safety: `sending` recovery checks the Sent folder before retry | Simulated crash at each step | Never double-sends |
| M6.3 Kill switch (`PAUSE` file) and global send allowlist (Dai-only until gate G2) | Presence of file blocks all sends; non-Dai recipient blocked pre-G2 | Unit tests pass |
| M6.4 Rate limits per sender and per day | Burst tests | Unit tests pass |

### M7 — Weekly task and skills
| Task | Tests first | Done when |
|---|---|---|
| M7.1 Weekly scheduler entry and task node (`kind: weekly`) | Runs once per window; resumes after downtime | Unit tests pass |
| M7.2 Index refresh: changed-files walk, `source-note` create/update/retire, hubs | Fixture diffs | Unit tests pass |
| M7.3 Skills sync from `09 Claude Skills`: allowlist file types, size caps, hash scripts, read declared tool needs | Scripts detected and hashed; disallowed types rejected | Unit tests pass |
| M7.4 Staging and activation via `OK SKILLS <code>`; hash pinning; changed script re-staged and old pinned version stays active | Tamper test: modified script never runs before approval | Security test passes |
| M7.5 Weekly health check and report (mail round trip, Twilio, Drive access, token expiry, spend) | Failure injection | Report email sent to Dai |
| M7.6 Skill-based drafting for mail lane (instruction-only skills, no tools) | Skill text included as trusted instruction block; mail content stays untrusted | Unit tests pass |

### M7b — Skills lane (tool-enabled, fenced)
| Task | Tests first | Done when |
|---|---|---|
| M7b.1 Command intake: only Dai's verified number/email can start a skill job | Spoofed command ignored; mail from others never starts a job | Security test passes |
| M7b.2 Job folder manager: per-job throwaway folder, input files copied in, output files copied out, cleanup | Path traversal attempts blocked | Unit tests pass |
| M7b.3 `claude_agent` backend: per-skill tool allowlist (named scripts only, no general shell), time/size/turn limits, no inherited secrets, no network by default | Test harness verifies denied tools are refused and env is clean | Unit + integration tests pass |
| M7b.4 Run as the restricted Windows user `daikon-jobs`; ACLs deny access to `daikon-data` | Manual verification script; automated ACL check on Windows CI where possible | Verified on Dai's laptop |
| M7b.5 Enable the **docx** skill only; deliverable stored as `draft` kind `deliverable`, sent to Dai for approval | End-to-end: Dai's command → .docx → approval digest | Dai accepts the result |
| M7b.6 Security review of the lane, then enable further skills one at a time | Review checklist signed off | Written review in `docs/` |

### M8 — Operations and hardening
| Task | Tests first | Done when |
|---|---|---|
| M8.1 Task Scheduler setup script (start at logon, restart on failure) and runbook | Dry-run mode prints actions; manual verification | Runner survives reboot |
| M8.2 Injection test corpus (emails, notes, skill text, SMS) run in CI | No state change beyond "draft awaiting approval"; no tool use in mail lane | Gate G2 criterion |
| M8.3 Backups: daily graph snapshot, retention | Restore test | Documented |
| M8.4 Cost and usage report in weekly digest; alert at 80% of spend cap | Fake usage data | Unit tests pass |
| M8.5 Runbook: re-auth steps, kill switch, rotate keys, what to do if the laptop is lost | Reviewed by Dai | In `docs/` |

## 4. Rollout and gates

| Stage | What runs | Gate to enter |
|---|---|---|
| **Shadow mode** (1 week) | Intake, triage, drafts, digests to Dai only. Sender can only send to Dai | M1–M5 done, P1–P6 done |
| **G1: Quality review** | Dai reviews ~20 real drafts: usefulness, voice, citation accuracy, sensitive-content handling | Dai signs off |
| **G2: Security gate** | Injection corpus passes; spoof tests pass; hash/code binding tests pass; kill switch tested; spend cap tested | All M8.2 tests green |
| **Live (draft-and-approve)** | Sender allowed to send approved drafts to recipients | G1 + G2 |
| **Skills lane live** | docx skill enabled | M7b.6 review signed off |
| **Phase 2 planning** | Voice design starts | v1 stable for 2 weeks |

## 5. Risks retired by milestone

| Risk (design §13) | Retired by |
|---|---|
| R1 Claude access / usage | API key with spend cap (M3.2, M8.4) |
| R3 Gmail token expiry | P2 "In production", M2.6 |
| R8 Workspace blocks sharing | P3 early check; fallback mirror task added if needed |
| R11 Retrieval quality | M4.4 plus G1 review; tune the search before widening |
| R12 Whole Second Brain visible | `drive.readonly` scope, Credential Manager, M4.5 flags |
| Skills lane abuse | M7b.1–M7b.6, G2 |

## 6. Assumptions to confirm

- Dai is comfortable with a GitHub Actions workflow being added to this repo (it also hosts the website). If not, CI moves to a separate private repo.
- Python is acceptable as the implementation language.
- Monthly spend cap amount for the Anthropic key (suggest starting low and raising after the first week's usage report).

**Awaiting your approval to proceed.** If you approve, I start M1 (foundations) test-first, in `daikon/`, one small commit per task.
