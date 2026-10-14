# Daikon — Red-Team Plan and Long-Term Prevention

Status: **Draft, awaiting Dai's approval.** Scope: design-level review of the system in `docs/daikon-design.md` (v4.1) and `docs/daikon-implementation-plan.md`. Authorized by the system owner (Dai). No exploit code is included.

**Why this matters.** Daikon reads untrusted mail, can see the whole Second Brain, can send mail on Dai's behalf (after approval), and later can run scripts and make phone calls. An attacker's goals are therefore: (1) steal private data, (2) make Daikon say or do something in Dai's name, (3) take over the laptop or accounts, (4) burn money, (5) quietly stay in.

## 1. Attacker profiles

| Profile | Capability | Typical goal |
|---|---|---|
| **P1 Outsider with an email address** | Can send mail to Dai or Daikon, craft text, HTML, links, attachments | Prompt injection, phishing Dai through Daikon, data theft |
| **P2 Spoofer** | Forges From addresses, SMS sender IDs, lookalike domains | Fake commands or fake approvals |
| **P3 Account thief** | Phishes or reuses passwords; SIM swap or number port-out | Take over Daikon's Gmail, Twilio, Dai's phone, Dai's GitHub |
| **P4 Supply-chain attacker** | Malicious package, GitHub Action, skill, or model update | Run code on the laptop |
| **P5 Local attacker** | Malware on the laptop, or a stolen or borrowed laptop | Read tokens and data, change files |
| **P6 Malicious or breached provider** | Sees what is sent to a model API (OpenRouter, others) | Harvest private text |
| **P7 Phone caller (phase 2)** | Talks to Daikon, clones voices | Social engineering, toll fraud |
| **P8 Dai himself, tired** | Approves without reading | Accidental leak or bad send |

## 2. Attack surface map

Inbound: Daikon's Gmail, Twilio SMS, (phase 2) voice, Drive notes, `09 Claude Skills`, model outputs, Python and Actions dependencies. Outbound: Gmail send, SMS, Drive reads, model API calls, skill scripts. Stores: `daikon-data` (graph, audit, tokens in Credential Manager), the public GitHub repo.

## 3. Attack scenarios, controls and tests

Legend: **Have** = already in the design or plan. **Add** = new control from this review (see §7). Test IDs are `RT-xx`.

| ID | Attacker move | Impact | Existing control | Gap / new control | Test |
|---|---|---|---|---|---|
| A1 | Email contains hidden instructions (invisible text, HTML comments, long quoted threads) telling the model to put Second Brain data in a reply | Data leak in a draft | Model has no tools; draft needs Dai's approval; sensitivity flags (Have) | **Add:** convert HTML to plain text and strip invisible content before the model sees it; digest shows a "contains hidden text" warning; draft never auto-includes content from sensitive folders | RT-01 |
| A2 | Draft or digest includes a remote image or link that leaks data when Dai opens it (tracking or data in URL) | Silent exfiltration via Dai's mail client | None | **Add:** digests are plain text; all URLs shown defanged (no clickable remote content); drafts sent to others contain no model-invented links unless Dai approves each URL | RT-02 |
| A3 | Injected text steers the summary or recommendation ("URGENT, approve immediately") to rush Dai | Bad approval | Approval gate (Have) | **Add:** digest shows the raw sender, SPF/DKIM result and "new sender" flag in fixed fields the model cannot edit; model text is placed below a divider and labeled "model summary"; urgency words from the model do not change formatting | RT-03 |
| A4 | Forged approval: fake "OK 7K2F" by email or SMS | Unauthorized send | Verified identity, SPF/DKIM, per-draft random code, hash binding (Have) | **Add:** code is single-use and expires; three wrong codes lock approvals for an hour | RT-04 |
| A5 | SIM swap or number port-out on Dai's phone: attacker receives digests and can reply | Valid-looking approvals | Code only helps if the attacker cannot see the digest (weak against SIM swap) | **Add:** high-risk sends (new recipient, attachment, money, credentials, anything flagged sensitive) need a second channel (confirm by email from Dai's authenticated account); carrier port-out PIN and SIM lock; **60-second to 10-minute hold with an UNDO command** before any send | RT-05 |
| A6 | Phish or reuse the password of Daikon's Gmail, or steal its OAuth token | Read forwarded mail, send as Daikon | 2-step on the account (planned P1) | **Add:** passkey or hardware key, unique password in a password manager, narrow OAuth scopes, security alerts to Dai, review of "devices and third-party access" quarterly | RT-06 (manual checklist) |
| A7 | Take over the Twilio account or port out the Daikon number; set up a webhook elsewhere; run up charges | Impersonation, cost | Spend cap on Twilio (planned) | **Add:** Twilio 2FA, number lock, API key with limited scope instead of master token, usage alerts; daily SMS cap in code | RT-07 |
| A8 | Malicious or modified skill in `09 Claude Skills` (Drive account compromised, or a bad skill added by mistake) | Code execution on laptop, behavior change | Staging, `OK SKILLS`, hash pinning, Lane 2 fence (Have) | **Add:** the activation digest shows a plain-language diff of instructions and script changes, flags new network or tool needs; a pinned manifest hash is stored locally (not on Drive); skill folders cannot add executables outside the allowlist | RT-08 |
| A9 | Poisoned Second Brain note (instructions placed in a shared doc or saved email) | Behavior steering, leaks | Notes are context, not instructions (Have) | **Add:** each excerpt is tagged with owner and last editor; notes not owned by Dai are lower trust and cannot influence recipients or attachments; instruction-like text in notes is flagged to Dai once | RT-09 |
| A10 | Escape from the skills lane: path traversal, symlinks or junctions, UNC paths, alternate data streams, 8.3 short names, case tricks, argument injection into a script | Read or write outside the job folder, run other programs | Job folder, restricted Windows user (Have) | **Add:** canonicalize every path and reject reparse points, junctions and UNC paths; run scripts with a list of arguments (never through a shell); Windows Job Object limits (CPU, memory, process count, time); outbound firewall rule blocking the `daikon-jobs` user; deny that user access to `daikon-data` and tokens | RT-10 |
| A11 | Instruction in a forwarded or quoted email ("Dai said do X") treated as Dai's command | Command injection via Dai's own identity | Only Dai's verified identity can command (Have) | **Add:** only the new, top-level text from a directly authenticated Dai message is a command; forwarded and quoted parts are always untrusted data; commands from Dai's email require the same code step as approvals | RT-11 |
| A12 | Mail flood or huge or many attachments to burn API budget or fill disk | Cost, denial of service | Rule filter, daily caps, spend cap (Have) | **Add:** size limits on bodies and attachments before any model call; per-sender and global hourly caps; attachments are never opened in v1; backoff when caps hit | RT-12 |
| A13 | Malicious attachment or link (macro, exploit, tracking page) | Malware | Daikon does not browse (design) | **Add:** make it explicit and tested: v1 never opens attachments or fetches URLs; attachment metadata only; any future feature goes through a threat entry first | RT-13 |
| A14 | Dependency or Action compromise (typosquat, hijacked package, malicious update) | Code execution, token theft | Minimal dependencies (Have) | **Add:** lockfile with hashes, `pip-audit` in CI, Dependabot alerts, review of every update, GitHub Actions pinned to commit SHAs, no secrets in CI, install from a clean virtual environment | RT-14 |
| A15 | Public-repo risks: leaked secrets in history, hijacked GitHub account, malicious PR | Secret theft, code tampering | Pre-commit guard, `.gitignore` (Have) | **Add:** GitHub 2FA with a security key, branch protection, require review for `daikon/`, secret scanning on, no secrets ever in Actions; consider moving Daikon to a private repo | RT-15 |
| A16 | Local compromise or theft: malware reads tokens (Credential Manager is readable by the same Windows user), or laptop is stolen | Full takeover | Credential Manager, `daikon-data` outside repo (Have) | **Add:** BitLocker, strong Windows login, Windows Defender on, separate low-privilege day-to-day account if possible; short-lived tokens where available; documented **revoke-everything runbook**; remote lock/wipe enabled | RT-16 (drill) |
| A17 | Tamper with logs to hide activity | No forensics | Append-only audit (Have) | **Add:** hash-chain each audit line; weekly digest includes the latest chain hash; copy of weekly hash held outside the laptop (Dai's email) | RT-17 |
| A18 | Provider-side exposure of prompts (OpenRouter or others), or a model update that changes behavior | Privacy loss, new failure modes | Sensitivity routing, provider allowlist, qualification harness (Have) | **Add:** pin model versions; re-run the injection corpus and golden set on every model, prompt or skill change; minimum necessary text only | RT-18 |
| A19 | Lookalike sender (display-name spoof, reply-to mismatch, homoglyph domain) | Fraud | SPF/DKIM parse (Have) | **Add:** show the real address and domain in the digest; flag display-name vs address mismatch, reply-to mismatch, newly seen or lookalike domains | RT-19 |
| A20 | Approval fatigue: Dai taps OK on everything | Bad sends | Digest design (Have) | **Add:** risk tiers with different friction; "first time sending to this person" flag; daily approval cap; spot-check mode where Daikon occasionally asks Dai to re-read a low-risk item; weekly report of what was approved | RT-20 |
| A21 | Race or replay: reuse old codes, double send, edit between approval and send | Wrong content sent | Version, hash, single send (Have) | Covered; **Add:** a regression test in CI | RT-04, RT-21 |
| A22 | Phase 2 voice: caller social-engineers Daikon, or a cloned voice of Dai tries to command him; premium or international number fraud | Data leak, cost, fraud | Brief-only call model, approved goal (Have) | **Add:** Daikon never authenticates anyone by voice; no commands by voice; allowlist of numbers he may call; block premium-rate and unapproved international prefixes; per-call and daily minute caps; call model has no tools | RT-22 |

## 4. Detection and response

**Alerts to Dai (SMS, rate-limited):** a burst of rejected approvals; sends to a never-seen recipient; spend over 80% of the monthly cap; audit chain mismatch; Daikon offline over 24 hours; token or OAuth change; skill change pending; Lane 2 job outside limits.

**Incident runbook (one page, to be written as `docs/runbook-incident.md`):**
1. **Stop:** create the `PAUSE` file, or text `PAUSE <code>` (stopping is always allowed and cannot cause a send).
2. **Contain:** revoke in this order: Daikon's Google sessions and OAuth grant, Anthropic and OpenRouter keys, Twilio keys and number lock, GitHub tokens, Dai's Drive sharing with Daikon.
3. **Preserve:** copy `daikon-data\audit` and the graph to a safe place before changing anything.
4. **Assess:** from the audit, list every send, every external recipient, every model call and every skill run since the last good state.
5. **Recover:** new passwords and keys, fresh OAuth grants, restore the graph from a snapshot, re-run the test suite and the red-team tests, then resume in shadow mode.
6. **Notify:** anyone who received something wrong, and any provider as needed.
7. **Learn:** add a scenario row and a test.

## 5. Long-term prevention ("later in life")

Software and accounts age. Most real breaches come from neglect, not from clever attacks. This program keeps Daikon safe for years.

| Cadence | Action |
|---|---|
| **Daily (automatic)** | Spend and volume anomaly alerts; audit chain check; token expiry warnings |
| **Weekly** | Read the weekly health digest (spend, sends, new recipients, rejected approvals, skills changes); approve or reject staged skills |
| **Monthly** | Apply dependency and OS updates in a test run first; run `pip-audit`; check Dependabot; verify backups restore; confirm kill switch works |
| **Quarterly** | Rotate API keys and Twilio keys; review Google "third-party access" and sharing for Daikon's account and the Second Brain; review who can see the repo; **re-run this red-team plan (RT-01 to RT-22) and the injection corpus**; check model deprecations |
| **Every change** | Any new capability (a tool, a skill with scripts, a new channel, a new data source, a model change) needs a new row in §3 and a passing test before it is enabled |
| **Annually** | Full permission review (what can Daikon read, send and run?); delete data past retention; renew domains and numbers; confirm Python and Windows are still supported; re-assess whether each feature is still worth its risk; update the incident runbook |

**Things that expire or change over time**
- **Credentials and tokens:** calendar every expiry; Daikon warns 14 days before.
- **Python, Windows, libraries, models and APIs:** versions get end-of-lifed. The qualification harness and the CI suite are the safety net for upgrades.
- **Your own habits:** over time people approve faster. The approval-fatigue controls (A20) stay on, and the spot-check mode is not removed.
- **Scope creep:** every added feature widens the attack surface. Default answer to a new capability is "not yet".

**If Dai is unavailable (travel, illness, long absence).** A **dead-man's switch**: if Dai has not interacted with Daikon for N days (default 14), Daikon stops all sending, drafts nothing new, answers only with a fixed out-of-office note if Dai chooses to enable it, and waits. A trusted second person (optional) can be given only the **runbook and PAUSE/revoke steps**, never approval rights. Recovery codes and key locations are stored in Dai's password manager or sealed offline.

**Decommissioning.** If Daikon is ever retired: revoke all keys and grants, delete the Gmail account or its data, release the Twilio number, remove Drive sharing, delete `daikon-data` securely, and archive the repo.

## 6. Red-team test plan

Run in CI (automated) and as quarterly drills (manual). All tests use fake accounts and synthetic data; nothing targets third parties.

| Group | Tests | How |
|---|---|---|
| **Injection corpus** | RT-01, 02, 03, 09, 11, 13, 19 | A growing library of synthetic emails, notes and skill texts (hidden text, fake urgency, fake "from Dai", quoted instructions, lookalike senders). Expect: no tool call in the mail lane, no sensitive text in drafts, no state beyond "draft awaiting approval", correct digest warnings |
| **Identity and approvals** | RT-04, 05, 21 | Forged, replayed, stale, wrong-code and wrong-sender attempts; lock-out after wrong codes; hold and undo window; high-risk second channel |
| **Lane 2 fence** | RT-08, 10 | Traversal, junction, symlink, UNC, alternate stream, argument-injection and network attempts must fail; changed script must not run until re-approved; environment must hold no secrets |
| **Cost and flood** | RT-07, 12, 22 | Flood fakes hit caps; Twilio and API caps trip; premium numbers blocked |
| **Supply chain and repo** | RT-14, 15 | CI fails on a known-vulnerable dependency, an unpinned Action, or a secret pattern |
| **Local and logs** | RT-16, 17 | Revoke drill timed (target: everything revoked in under 30 minutes); audit tamper detected |
| **Model change** | RT-18, 20 | Golden set plus corpus re-run on every model or prompt change; approval-fatigue controls verified |

**Pass criteria.** Zero sends to anyone except Dai in shadow mode; every RT test green before gate G2; quarterly drill findings turned into tasks within a week.

## 7. New tasks to add to the implementation plan

| Task | Milestone | Covers |
|---|---|---|
| M1.8 Hash-chained audit lines and weekly chain hash in the digest | M1 | A17 |
| M2.7 Email normalization: HTML → plain text, strip invisible content, size limits, forwarded/quoted-part separation | M2 | A1, A11, A12 |
| M2.8 Sender trust display: real address, display-name/reply-to mismatch, lookalike domain, new-sender flag | M2 | A19 |
| M4.8 Excerpt trust tagging (owner, last editor) and instruction-like text flag | M4 | A9 |
| M5.8 Plain-text digests, defanged URLs, fixed-field header the model cannot edit | M5 | A2, A3 |
| M5.9 Single-use codes, expiry, lock-out after wrong attempts; commands from email also need a code | M5 | A4, A11 |
| M6.5 Hold-and-undo window; risk tiers; second channel for high-risk sends; daily approval cap and spot-check mode | M6 | A5, A20 |
| M7.7 Skill-change diff in the activation digest; local pinned manifest hash | M7 | A8 |
| M7b.7 Windows hardening for the skills lane: path canonicalization, reparse-point denial, list-args only, Job Object limits, outbound firewall rule, ACLs | M7b | A10 |
| M8.6 Dead-man's switch and out-of-office note | M8 | §5 |
| M8.7 Dependency hygiene: hashed lockfile, `pip-audit`, Dependabot, Actions pinned to SHAs | M8 | A14 |
| M8.8 Incident runbook and timed revoke drill | M8 | §4 |
| M8.9 Quarterly red-team drill script and checklist (`docs/red-team-drill.md`) | M8 | §5, §6 |
| P11 Account hardening checklist for Dai: passkeys or security key on Daikon's Gmail, Google and GitHub; carrier port-out PIN and SIM lock; Twilio 2FA and number lock; BitLocker; password manager | Prerequisite | A5, A6, A7, A15, A16 |

The G2 security gate in the plan now requires **all RT tests** to pass, not only the injection corpus.

## 8. Residual risks Dai accepts (for now)

- A determined attacker who controls both Dai's phone and the Daikon mailbox can still impersonate approvals on low-risk items. The second channel, hold-and-undo and caps limit the damage but do not remove it.
- Prompt injection cannot be fully solved for any model. The design depends on containment (no tools in the mail lane, approval, hold-and-undo), not on the model resisting.
- Third-party model providers see the text sent to them. Sensitive items stay local or are withheld.
- The laptop is a single point of failure for availability. Messages wait in Gmail and Twilio when it is down.

**Awaiting your approval to proceed.** If approved, I add the tasks in §7 to the implementation plan and start M1.
