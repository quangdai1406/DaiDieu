# Daikon Day-0: what Dai does

Plain steps for you, in order. Each step says **why**, **how long**, and **how to know it worked**.
Do the first block now, because those items take days to approve. Total hands-on time: about
2-3 hours spread over a day, plus waiting.

Nothing here puts secrets in the repo. Secrets go into Windows Credential Manager through
`python -m daikon set-secret ...` (step 8).

## Block A: start the slow items first (about 30 minutes)

### A1. Twilio account and number, then start the A2P registration
**Why:** US texting needs "A2P 10DLC" registration. It can take days, so start it first.
1. Create the Twilio account. Turn on **2FA** for your login. On the sign-up questions choose **Messaging** and **Voice** (voice is for phase 2 calls) and **With code**. These answers only tailor the console; they are not a commitment. Leave Email, Verification, Customer data and Conversational AI unticked (Daikon uses Gmail and his own AI). Upgrade the trial account to a paid one (small prepaid balance): trial accounts can only reach verified numbers and add a trial prefix to messages.
2. Buy one US number with **both SMS and Voice** capability. This is Daikon's number.
3. In the Twilio console, turn on **number lock** (so it cannot be ported out).
4. Create a **scoped API key** (Console > Account > API keys), not the master auth token.
   Write down the Account SID, the Key SID and the Key Secret. The secret is shown once.
5. Set a **monthly spend cap** (suggest $10) and usage alerts.
6. Start the **A2P 10DLC registration** (Brand, then Campaign). Use case: "Personal assistant
   notifications to the account owner only". Sample messages: "Reply OK 7K2F to approve" and
   "Daikon: a reply is waiting for you".
**Done when:** the number exists, the key is saved in your password manager, and registration
shows "pending". SMS support is switched on only after it shows "approved".

### A2. Daikon's Gmail account
**Why:** Daikon needs his own mailbox. He has no access to your Gmail.
1. Create a new Gmail account for Daikon (for example `daikon.assistant.xxx@gmail.com`).
2. Turn on **2-step verification** and add a **passkey or security key**.
3. Use a unique password from your password manager.
**Done when:** you can sign in as Daikon with the passkey.

### A3. Anthropic API key with a spend limit
**Why:** this pays for the drafts (about $10-15 a month at 30 drafted emails a day).
1. In the Anthropic Console create a key named `daikon` used only by Daikon.
2. Set a **monthly spend limit** of about **$15**.
**Done when:** the key is saved in your password manager and the limit is visible in the console.

### A4. Share the Handovers folder with Daikon (create-only access, accepted 2026-10-14)
Not needed for v1 email. Do this before the phone-call milestone (C4): in Drive, share the existing **Handovers** folder (id `11FPz6dYllie6zSH175ponTbiCHzBE2K2`) with Daikon's Gmail address as **Editor**, and nothing else outside the Second Brain. Daikon's code can only create new files there.

## Block B: Google setup (about 45 minutes)

### B1. Google Cloud project and OAuth (signed in as DAIKON's account)
**Why:** lets Daikon's own program read and send mail as Daikon and read the Second Brain.
1. Create a project called `daikon`.
2. Enable the **Gmail API** and the **Google Drive API**.
3. OAuth consent screen: user type External, add yourself and Daikon as test users, add the
   scopes `gmail.readonly`, `gmail.send` and `drive.readonly` only.
4. Set the publishing status to **"In production"**. If you leave it in "Testing", the sign-in
   expires every 7 days and Daikon stops.
5. Create an **OAuth client ID** of type **Desktop app**. Download `client_secret.json` to a
   folder outside the git repo.
**Done when:** you have `client_secret.json`, and the consent screen says "In production".

### B2. Share the Second Brain with Daikon as Viewer
**Why:** Daikon reads your notes for context. Google enforces read-only.
1. In Drive, open the folder `Second Brain` (ID `1j8kRB_OiGRirovIVL6gOfjIIhge0ktBk`).
2. Share with Daikon's Gmail address, role **Viewer**.
3. If shown, turn off "Viewers and commenters can see the option to download, print, and copy".
4. Sign in as Daikon in a private window and open one note.
**Done when:** Daikon's account can open a note but cannot edit it. If your organization blocks
sharing outside the company, tell Claude: we will need a different route.

### B3. Forward chosen mail to Daikon (later, after step 9 works)
1. In your Gmail make a label `daikon`.
2. Add Daikon's address under Settings > Forwarding. Daikon's account receives a confirmation
   code; give it to Gmail.
3. Create a filter that forwards mail with that label. **Start with one label only.**

## Block C: your laptop (about 45 minutes)

### C1. Windows basics
1. Install **Python 3.12** and **Git**.
2. Settings > System > Power: **never sleep when plugged in**.
3. Windows Update > Advanced > **Active hours** set so it will not restart during the day.
4. Turn on **BitLocker** and **Find My Device**. Keep Windows Defender on.
**Done when:** `py -3.12 --version` and `git --version` both print versions.

### C2. Install Daikon
Follow `docs/runbook.md` section 3, then:
```powershell
copy models.yaml.example $HOME\daikon-data\models.yaml
notepad $HOME\daikon-data\models.yaml
```
Set `identity.emails` to your personal email, `identity.phones` to your mobile number,
`dai_email` to your email, and `second_brain_root_id` to the folder ID above.
**Leave `outbound_mode: dai_only`. Leave `twilio_number` commented out for now.**

## Block D: first run (about 30 minutes)
```powershell
python -m daikon set-secret anthropic_api_key
python -m daikon auth-gmail --client-secrets C:\path\to\client_secret.json   # sign in AS DAIKON
python -m daikon smoke --dai-email you@example.com
python -m daikon doctor
python -m daikon run --once
```
Optional now, required when A2P is approved: `set-secret` for `twilio_account_sid`,
`twilio_api_key_sid`, `twilio_api_key_secret`, then uncomment `twilio_number`.
**Done when:** the smoke test emails you one test message and `doctor` shows no `FAIL` lines.
Then tell Claude the results of the live checks (Gmail history, Drive read, Anthropic
structured output). Claude fixes anything that behaves differently from the fakes.

## Block E: lock-down checklist (about 30 minutes)
Do the list in `docs/runbook.md` sections 9 and 10. The short version:
- Passkey or security key on Daikon's Google account, your Google account and GitHub
- Carrier **port-out PIN** and **SIM lock** on your mobile number
- A password manager with unique passwords
- GitHub: 2FA with a security key, secret scanning and push protection on, branch protection
  on `master` (require a pull request and passing checks), Dependabot alerts on
- Decide: keep Daikon in this public repo, or move `daikon/` to a private repo
- Do the **revoke drill** (runbook section 11) once with throwaway keys

## Block F: shadow week
Run Daikon as a background task (runbook section 5). For a week he only emails **you**. Review
about 20 real drafts: useful, in your voice, correct sources? Report problems to Claude. Only
after that, and the security checks pass, set `outbound_mode: live`.

## What I (Claude) need back from you
| After | Tell Claude |
|---|---|
| A1 | Whether the A2P registration is accepted or needs changes |
| B1, B2 | Any errors, especially a blocked share or an expiring sign-in |
| D | The `smoke` and `doctor` output (no secrets) |
| Block F | Which drafts were wrong or off-voice |

## Decisions already made (so you do not need to re-decide)
- Daikon only drafts; **you approve everything**. Nothing leaves without your reply.
- Only your own phone and personal email can command Daikon.
- First reply to any new person needs a **one-time confirmation text** to your phone (built;
  it works once SMS is approved).
- Phone calls and the community call-booking skill come after v1 has run stably for two weeks.
