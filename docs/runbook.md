# Daikon runbook (Windows)

For Dai. Plain steps, in order. Commands run in PowerShell. Anything marked **(you)** needs your
hands; Daikon cannot do it for you.

## 1. What runs where

- Daikon runs on your always-on Windows laptop as a background task. Everything he knows is in
  `C:\Users\<you>\daikon-data\` (never in the git repo).
- He reads mail at his own Gmail address, looks things up in your Second Brain (read-only), asks
  Claude to draft a reply, and emails you a digest. **Nothing goes to anyone but you until you
  reply `OK <code>`.**

## 2. Day-0 setup (do these once, in one sitting)

Start the long-lead items first.

1. **(you)** Create Daikon's Gmail account. Turn on 2-step verification.
2. **(you)** Twilio: create the account, buy a number, create a **scoped API key** (not the master
   token), turn on 2FA and number lock, set a spend cap, and **start the US A2P 10DLC registration
   now** (it takes days). SMS support is added after it clears.
3. **(you)** Anthropic Console: create an API key just for Daikon and set a **monthly spend limit**
   (start around $15).
4. **(you)** Google Cloud: create a project, enable the **Gmail API** and **Drive API**, create an
   OAuth client (desktop app), and set the consent screen to **In production** (otherwise sign-in
   expires every 7 days). Scopes used: Gmail read, Gmail send, Drive read-only.
5. **(you)** Share your **Second Brain** folder with Daikon's Google account as **Viewer**. If you
   can, turn off "viewers can download, print and copy". Open one file as Daikon's account to
   check it works. If your Workspace blocks sharing outside the company, tell me.
6. **(you)** In your own Gmail, create a filter that **forwards** the mail you want handled to
   Daikon's address (start with one label, e.g. `daikon`).
7. **(you)** Windows: install Python 3.12 and Git; set the laptop to **never sleep on AC power**
   and set Windows Update "active hours" so it does not restart during the day.
8. **(you)** Do the checklists in sections 9 and 10.

## 3. Install

```powershell
git clone https://github.com/quangdai1406/DaiDieu.git
cd DaiDieu\daikon
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
mkdir $HOME\daikon-data
copy models.yaml.example $HOME\daikon-data\models.yaml
notepad $HOME\daikon-data\models.yaml
```

In `models.yaml` set `identity` (your own email addresses and mobile number) and
`second_brain_root_id` (the Drive folder id). **Leave `outbound_mode: dai_only`** for now.

## 4. First run

```powershell
python -m daikon set-secret anthropic_api_key        # paste the key when prompted
# Only after the Twilio A2P registration clears (then also set twilio_number in models.yaml):
# python -m daikon set-secret twilio_account_sid ; twilio_api_key_sid ; twilio_api_key_secret
python -m daikon auth-gmail --client-secrets C:\path\to\client_secret.json   # sign in AS DAIKON
python -m daikon smoke --dai-email you@example.com   # reads one message, sends you one test mail
python -m daikon doctor                               # every line should say ok
python -m daikon run --once                           # one cycle
```

`doctor` never prints secrets. `FAIL` lines must be fixed; `WARN` lines are information.

## 5. Run it all the time

1. Edit `daikon\deploy\windows\daikon-task.xml`: replace `YOUR-WINDOWS-USER` and the two paths.
2. Create the task: `schtasks /Create /TN Daikon /XML daikon\deploy\windows\daikon-task.xml`
3. It starts when you log in, restarts itself after a failure, and keeps only one copy running.
4. Stop it: `schtasks /End /TN Daikon`. Remove it: `schtasks /Delete /TN Daikon /F`.

## 6. Shadow week

For the first week Daikon only emails **you**. Each digest shows the sender (with SPF/DKIM/DMARC
results and warning flags), a draft reply, the Second Brain notes used (and any sensitive notes
that were kept from the model), and your options. Review about 20 real drafts: are they useful,
in your voice, with correct sources?

## 7. What you can send Daikon

Reply to the digest, or email Daikon's address **from your own address**. Only the first line
counts, and only from you (mail that fails SPF/DKIM/DMARC is ignored).

| You write | What happens |
|---|---|
| `OK 7K2F` | Approve the reply. It waits 60 seconds first |
| `UNDO 9XQ3` | Cancel during that 60 seconds (the code is in the "approved" notice) |
| `NO 7K2F` | Discard |
| `EDIT 7K2F make it shorter and decline Friday` | New draft, new code (up to 5 revisions) |
| `CONFIRM 5HT9` | **By text message only.** Sent to your phone for the first reply to a new person; valid 30 minutes, one use. Ignore it to cancel. Email cannot confirm |
| `PAUSE` | Stop all sends to other people; Daikon replies with a resume code |
| `RESUME 4MZ8` | Resume (3 tries an hour) |

Codes are one-time and change with every draft. Three wrong codes lock approvals for an hour.

## 8. Going live (only after both gates)

- **Gate 1, quality:** you reviewed ~20 real drafts and are happy.
- **Gate 2, security:** `pytest` is green including `tests/security`, the checklists below are
  done, the revoke drill (section 11) has been done once, and the kill switch has been tested.
- Then set `outbound_mode: live` in `models.yaml` and restart the task. The first reply to any new
  person still needs an extra confirmation step (currently it fails safe and tells you).

## 9. Account hardening checklist

- [ ] Passkey or security key on Daikon's Google account, your Google account and GitHub
- [ ] Unique passwords in a password manager; no password reuse
- [ ] Carrier **port-out PIN** and **SIM lock** on your phone number
- [ ] Twilio: 2FA, number lock, scoped API key, spend cap, usage alerts
- [ ] Anthropic: spend limit set; key used only by Daikon
- [ ] BitLocker on the laptop; strong Windows sign-in; Find My Device on
- [ ] Windows Defender on; Windows Update active hours set
- [ ] Review "third-party access" in both Google accounts every quarter

## 10. Repository protections

- [ ] GitHub: security key 2FA; secret scanning and push protection on
- [ ] Branch protection on `master`: require pull request and passing checks
- [ ] Dependabot alerts on (the repo has `.github/dependabot.yml`)
- [ ] Decide: keep Daikon in this public repo, or move `daikon/` to a private repo
- [ ] No secrets in the repo or in CI settings (secrets live in Windows Credential Manager)

## 11. Revoke everything (incident drill)

Do this if you suspect a leak, and once as a practice drill before going live. Target: under 30
minutes. Practise with new keys, so nothing is lost.

1. **Stop:** send `PAUSE`, or create the file `daikon-data\PAUSE`, or `schtasks /End /TN Daikon`.
2. **Preserve:** copy `daikon-data\audit` and `daikon-data\graph` somewhere safe.
3. **Revoke, in this order:**
   1. Daikon's Google account: sign out all sessions; remove the app under "Third-party access".
   2. Anthropic Console: delete the Daikon key.
   3. Twilio: delete the API key; lock the number.
   4. GitHub: revoke tokens; check recent activity.
   5. Your Google account: stop sharing the Second Brain with Daikon.
4. **Assess:** `python -m daikon doctor` (checks the audit chain), then read `daikon-data\audit\*.jsonl`
   for sends and model calls since the last good state.
5. **Recover:** new passwords and keys, `set-secret`, `auth-gmail`, re-share the Second Brain,
   restore `daikon-data` from a backup if needed, run `doctor`, return to shadow mode.
6. **Learn:** tell Claude what happened so it becomes a new test.

## 12. Backups and restore

Daikon copies `graph`, `audit` and `limits.json` once a day into `daikon-data\backups\<date>\`
(last 7 kept). To restore: stop the task, copy a backup's folders back over `daikon-data`, run
`doctor`, start the task. Test a restore once.

## 13. Lost or stolen laptop

Use section 11 from another device, then wipe the laptop remotely (Find My Device). Rebuild on a
new machine with section 3.

## 14. Reading `doctor`

| Line | Meaning |
|---|---|
| `FAIL missing secret: ...` | Run `set-secret` or `auth-gmail` |
| `FAIL audit chain: BROKEN` | The log was edited or damaged: treat as an incident (section 11) |
| `WARN PAUSED` | Sends are stopped; `RESUME <code>` or delete `PAUSE` |
| `WARN outbound_mode is LIVE` | Approved replies go to other people |
| `WARN secret expiring` | Renew it before the date |
