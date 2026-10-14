# Daikon Call Skill: Design (phase 2)

Status: **draft v1 for Dai's approval. No code until approved and until v1 has run stably for two weeks.**
Prompt used to write this: `docs/call-skill-design-prompt.md`.
Binding inputs: `CLAUDE.md`, `docs/daikon-design.md` §9, `docs/daikon-red-team-plan.md` (RT-22 to RT-30).

## 1. Goals and non-goals

**Goals**
1. Dai asks "Daikon, call X for person A". Daikon interviews Dai, prepares a call brief, Dai approves it, Daikon makes the call, and reports everything back.
2. Three call types: **book** (make an appointment or reservation), **info** (ask questions only, no commitments), **callback** (receive a call from a number Daikon already called).
3. Each call makes the next cheaper: Daikon remembers how a business works (hours, how they book, what they ask) and asks Dai fewer questions the next time.
4. Daikon is always honest on the call: an AI assistant, calling on behalf of person A, the call is recorded, asks for an interpreter.

**Non-goals (this design)**
- Daikon never talks to person A directly. Dai is the only person who commands Daikon and the only contact for A.
- No calls in Vietnamese in the first release (English calls; Dai's summaries and a draft message for A in Vietnamese).
- No cloned or imitated voice. No impersonating Dai or A.
- No answering of unknown callers (see §7). No outbound telemarketing, no bulk calling.
- No payments until the last milestone and its red-team test pass (§9).

## 2. Call types

| Type | Purpose | May commit to something? | Example |
|---|---|---|---|
| `book` | Make an appointment, reservation or service booking | Only inside the approved brief (date window, price ceiling) | Flat tire repair tomorrow; dentist next week |
| `info` | Ask questions, collect facts | **No.** Hard rule: no booking, no payment, no names beyond what the brief allows | "Do you do walk-ins for flat tires? What does a patch cost?" |
| `callback` | Receive a call from an organization Daikon already called | **No.** Message-taking only (§7) | Office calls: the doctor is sick, appointment moved |

## 3. Architecture

```
Dai (SMS / email, verified)
   |  "call Joe's Tire for Mr. Nguyen: flat tire"
   v
[Interview engine]  <-- question sets (skill pack) + call memory (local graph, Second Brain read-only)
   |  one question at a time, suggested answers, recommendation
   v
[Call brief]  --- Dai approves (OK code, edits allowed) --->  approval queue
   |
   v
[Call runner]  Twilio Voice  <->  Media Streams (WebSocket)  <->  STT  ->  `call` model (OpenRouter)  ->  TTS
   |  sees ONLY the approved brief
   v
[Transcript + structured result]  -->  report to Dai (email + short SMS)  -->  local call memory
                                                                   |
Dai's weekly task files records into the Second Brain  <-----------+   (Daikon reads back, read-only)

Inbound:  Twilio webhook (signature checked) -> caller on the callback registry? -> yes: message-taking mode
                                                                                 -> no: fixed message, hang up, no model
```

New pieces (all local, behind the existing seams):
- `call/` package: interview engine, brief builder, call state machine, registry, report builder. No vendor code outside `gateway/` (the `call` role uses the `openai_compat` backend).
- A **public endpoint** for Twilio webhooks: Cloudflare Tunnel, Twilio signature validation on every request, run as a Windows service.
- Roles in `models.yaml`: `call` (OpenRouter, Haiku-class, fastest to first token), `call_prep` and `call_summary` (Anthropic, as today).
- Approval kinds already reserved in code: `call_brief`. New: `caller_registration` (§7.4).

The model never gets tools. All actions (dialing, registry changes, saving records, reporting) are done by code from the model's JSON.

## 4. The skill pack

The "skill" is a folder of data that the runner reads. It is edited by Dai and changes only through the existing staged-approval path (weekly sync, v1.1).

```
call-booking/
  SKILL.md                  # purpose, interview rules, tone, hard rules (human-readable)
  question-sets/
    medical.md  dental.md  auto.md  hotel.md  restaurant.md  generic.md  info.md
  brief.schema.json         # call brief fields (§6)
  script/
    opening.md  interpreter.md  confirm-back.md  voicemail-ivr.md  inbound-message.md
  report-templates/
    pre-call.md  post-call.md  inbound-message.md  vietnamese-note-for-A.md
```

Each question-set entry has: `id`, the question in plain words, `why we ask`, `suggested answers`, `default recommendation (with reason)`, `scope` (`service` or `person`), `sensitive` (yes or no), `ask_if` (rule, for example "unless memory has it").

## 5. Interview engine

Rules (enforced by code, not by the model):
1. **One question per message.** Dai replies by SMS or email with a number (the suggested answer) or free text.
2. Every question shows 2 to 4 suggested answers plus "something else", with one marked **Recommended** and a one-line reason.
3. The next question is chosen by code from the question set for the call type, minus questions already answered by memory.
4. **Memory first.** If a `provider` node holds service-level facts (for example "Joe's Tire: walk-ins OK, asks make/model/year, patch about $25"), Daikon shows them as a single confirmation: "Same shop as last time. Still right? 1. Yes (Recommended) 2. Changed". Person-level questions (name, preferred time, phone) are always asked for a new person.
5. Sensitive questions (health reason, insurance ID, date of birth) are asked only if the call type needs them. Each answer is tagged "may share on the call: yes/no". Anything not marked yes is never sent to the call model.
6. The interview can be resumed, edited ("EDIT 3 ...") and cancelled. State lives in a graph node (`interview`), so a crash loses nothing.
7. The interview ends with the **brief** (§6) and a one-screen summary for approval.

Intake note: v1 treats free text from Dai as audit-only. The interview needs a dialogue intake: free text from Dai's verified number or address is accepted **only while an `interview` node is open**, and only as an answer to the current question. It can never trigger anything else.

## 6. The call brief

The brief is the only thing the call model sees. It is a JSON document, stored as a graph node `call-brief`, hashed, and approved like a draft (bound to its hash; any change invalidates the approval).

| Field | Meaning |
|---|---|
| `id`, `version`, `created` | Identity |
| `type` | `book`, `info` or `callback_context` |
| `callee` | Business name, E.164 number (checked against the allowlist, §9) |
| `on_behalf_of` | Person A's name as it should be spoken. No other identity data unless marked shareable |
| `consent_of_A` | Dai confirms A agreed to be called for (yes/no, required) |
| `purpose` | One sentence |
| `shareable_facts` | List of facts the model may say, each with a label |
| `questions_to_ask` | For `info` calls and for confirmation (hours, price, wait, documents needed) |
| `acceptable` | Date/time window, price ceiling, alternatives allowed |
| `hard_limits` | For example "never agree above $X", "never give date of birth", "never agree to a different day" |
| `interpreter` | `request` (always yes) and preferred mode (in person, phone, video) |
| `no_show_offer` | Absent by default. If present: amount, who is charged, how (§9). Only said if present |
| `register_callback_numbers` | Allowed to ask for a callback number and add it (Dai approves, §7.4) |
| `max_minutes`, `retries`, `retry_window` | Limits. Defaults: 8 min, 2 retries, business hours only |
| `on_voicemail` | `hang_up` (default) or a fixed approved message |
| `success_criteria`, `stop_conditions` | When the call is done, when to stop and report |

Approval state machine for a brief:

| State | Meaning | Moves to |
|---|---|---|
| `drafting` | Interview in progress | `pending` |
| `pending` | Waiting for Dai (OK / EDIT / NO, 72 h, reminder at 24 h) | `approved`, `rejected`, `expired`, `drafting` (edit) |
| `approved` | Dai approved this hash | `dialing` (when due) |
| `dialing` | Call in progress or in retry window | `done`, `failed`, `no_answer` |
| `done` / `failed` / `no_answer` | Final; report sent | – |

Dai approves the **brief**, not the transcript. Anything outside the brief is refused on the call.

## 7. Receiving calls (callbacks)

### 7.1 Rule
Daikon takes a call **only from a number he called first** (or one Dai approved later, §7.4). Everyone else gets a fixed message and no model, no recording.

### 7.2 The callback registry
A graph node type `callback-entry`:

| Field | Meaning |
|---|---|
| `number` | E.164, normalized |
| `provider` | Link to the `provider` node |
| `call` | Link to the outbound call that created the entry |
| `source` | `dialed` (we called this number) or `approved_addition` (Dai approved) |
| `opened`, `expires` | Open from the outbound call until the appointment date + 2 days, never longer than 30 days; Dai can close it |
| `status` | `open`, `closed`, `expired` |

An entry is created automatically when Daikon dials a number. Nothing else creates entries except Dai's approval.

### 7.3 Handling an incoming call

| Step | What happens | Who decides |
|---|---|---|
| 1 | Twilio sends a webhook; code verifies the Twilio signature | code |
| 2 | Normalize the caller ID; look it up in the registry | code |
| 3 | **Not found, or entry not open** → play one fixed sentence ("This is an assistant line that only takes calls from organizations it contacted. Goodbye."), hang up. No model, no recording, no transcript. Log number and time; count per day | code |
| 4 | Found and Twilio's call-verification result is not `failed` → answer in **message-taking mode** | code |
| 5 | Disclosure: "This is Daikon, an AI assistant for [A]'s helper. This call is recorded." | script |
| 6 | Take the message: who is calling, what changed (cancel, reschedule, new time, question, other), a callback number, a deadline | `call` model, with only the callback context |
| 7 | Read back what was understood; end | script |
| 8 | Report to Dai right away (SMS short form, email full), including a draft message for A in Vietnamese for Dai to send | code |

**Message-taking mode is deliberately weak.** The model sees only: the business name, the original call's `callback_context` (appointment date and time, service, the name as spoken on the call), and the message-taking script. It can:
- Confirm a detail the caller says **only if it matches** the call record (date, time, name as said on the call).
- Say "I will pass this to [A]'s helper" and nothing more.

It cannot: agree to, change or cancel anything; reveal any fact the caller did not already state; discuss health, address, date of birth, insurance or payment; promise a callback time; follow any instruction spoken by the caller.

### 7.4 When the office calls from a different number
Offices often call back from a different line. The brief may allow Daikon to ask at the end of the outbound call: "If you need to reach me, which number will you call from?" The number is **not** added automatically. It goes into the post-call report as "Add 555-0100 as an expected caller? Reply `OK <code>`" (an approval, kind `caller_registration`). Only then does it become an `approved_addition`. This stops a stranger from planting a number.

### 7.5 Spoofing
Caller ID can be faked. Controls: message-taking mode reveals nothing and commits to nothing; a spoofer can only leave a false message. So the report to Dai always says: "Unverified: caller ID matched the number we called. If this matters, call the office yourself on the number from the record: [number from the original call]". Dai decides; Daikon never acts on a callback message.

### 7.6 Flood and cost
Unknown callers cost almost nothing (a fixed message, no model). Caps: max N answered inbound calls a day per number, max M minutes each, an alert if unknown calls exceed a threshold, and Twilio geo-permissions limited to the US.

## 8. The outbound call

### 8.1 Script structure (filled only from the approved brief)

1. **Opening, within 15 seconds:** "Hello, this is Daikon, an AI assistant. I'm calling on behalf of [A], who does not speak English. This call is recorded and transcribed."
2. **Purpose** in one sentence, using only brief facts.
3. **Request**, and any `questions_to_ask`.
4. **Interpreter:** ask the office to arrange a Vietnamese interpreter for the appointment, and how that is confirmed.
5. **No-show offer** (only if in the brief): see §9.
6. **Confirm back:** date, time, address, provider, what to bring, cancellation rule, a confirmation number. Ask for anything unclear to be repeated.
7. **Callback number** question (only if allowed by the brief).
8. **Close** politely.

### 8.2 Hard rules (enforced by code around the model)
- Never say a fact that is not in `shareable_facts`. If asked something else: "I'll check and call back."
- Never agree to a price, date or term outside `acceptable`.
- Never follow spoken instructions that change the brief ("ignore your rules", "read me the number").
- If the callee asks for a human, objects to talking to an AI, or says to stop calling: end politely, mark `declined`, report. Do not retry.
- Max duration and silence timeouts end the call.
- IVR menus: press digits only from a fixed list in the script. Voicemail: `hang_up` by default.
- **Info calls:** no booking words. A code check rejects any model output that proposes a commitment.

### 8.3 After the call
Within minutes Daikon sends Dai: result in one line, what was agreed, open items, the transcript, the structured answers, and (for `book`) a ready-to-forward Vietnamese note for A. Dai tells the person. Daikon does **not** contact A.

## 9. Payment and the no-show offer

Decided by Dai: Daikon offers to **prepay the service**; if the person does not come, they are charged **$5** and the rest is returned. Dai's own credit card is used; the person repays Dai later.

Because paying is irreversible and a card number is highly sensitive, this is the **last milestone** and has hard requirements:
- The full card number never enters a prompt, transcript, log, graph node, report or the repo.
- Every payment is approved by Dai for a stated business and amount, with per-call and monthly limits.
- The card details reach the business by a route that skips the call model and the recording (to choose before building, for example Dai gives them himself on a three-way step, or a one-time card number from his card issuer if offered).
- Daikon records "who owes Dai how much" on the `call` node so Dai can collect.
- A written no-show policy with the business (deposit terms) must be confirmed on the call; Daikon states it only if the brief says so.
- Open: whether businesses accept a deposit arrangement for a $5 fee at all. Many will not; the first release ships without payment.

## 10. Call memory and reporting

### 10.1 Graph nodes (local, under `daikon-data/graph/`)

| Type | Key fields | Links |
|---|---|---|
| `interview` | call type, answers so far, current question | `produced` → `call-brief` |
| `call-brief` | all §6 fields, hash, state | `for` → `person`, `to` → `provider` |
| `call` | type, direction, start/end, duration, outcome, structured answers, transcript path, cost, amount owed to Dai | `derived_from` → `call-brief`, `with` → `provider` |
| `provider` | name, numbers, hours, how they book, questions they ask, prices quoted, interpreter availability, tips (all **service-level**) | `relates_to` → other `call`s |
| `callback-entry` | §7.2 | `from` → `call`, `of` → `provider` |
| `inbound-message` | caller, time, message summary, matched entry, verified-flag, report sent | `about` → `call` |
| `person-case` | A's name, language, notes (all **person-level**) | `for` → `call-brief`s |

Every field carries `scope: service` or `scope: person`.

### 10.2 Reuse rules
- Reuse **only** `scope: service`. Person-level data is shown to Dai only when the same person is the subject again.
- Calls to the same business for a different person reuse the `provider` node, which is how the interview gets shorter.
- Facts quoted from the callee (prices, hours) are stored with a date and "as said on the call". Daikon shows the age ("said 3 months ago, confirm?").
- Stored call text is **untrusted data**: structured fields with length caps, wrapped as untrusted when read back, never instructions.

### 10.3 Second Brain
Daikon stays read-only. After each call he emails Dai the full pre-call and post-call report. Dai's weekly task files the records under a Second Brain area (suggested `09 Calls`, to be chosen by Dai); Daikon reads them back through `ScopedDrive`. Until filed, Daikon uses his local copy. The call-log area is treated as sensitive and is never used for unrelated email drafts.

## 11. Security

New rows (also added to the red-team plan; each is deferred to v2 and needs a passing test before the capability is enabled):

| ID | Attack | Control | Test |
|---|---|---|---|
| RT-22 | Caller social-engineers Daikon, premium/international number fraud | Never authenticate by voice; number allowlist; caps | Premium prefix refused; per-call and daily minute cap |
| RT-23 | A callee's words, saved in notes, steer a later call | Structured, capped notes; untrusted wrapping; new brief still needs approval | Injected note does not change a later brief |
| RT-24 | A's health or ID data reused or said on B's call | `scope` tags; sensitive fields need per-call "may share" | B's brief never contains A's person-level fields |
| RT-25 | Unapproved money terms or card exposure | Money terms only from brief; card number never in prompts/logs | Card-like strings blocked by the guard; no-show text only when approved |
| RT-26 | Sensitive call data leaks through the Second Brain | Filed by Dai's task; call area withheld from unrelated drafts | Retriever withholds the call area |
| RT-27 | **Spoofed callback** fishes for facts or plants a false message | Registry only; message-taking mode reveals/commits nothing; report says "unverified" | Spoofed number not in registry rejected; in-registry spoof leaves only an unverified message |
| RT-28 | **Unknown-caller flood / toll cost** | Fixed message, no model, no recording; daily caps; US-only geo | 100 unknown calls cost 0 model calls |
| RT-29 | **Registry poisoning** (callee names a number to add; attacker adds a number) | Additions only by Dai's approval (`caller_registration`) | Number stated on a call is not added without OK |
| RT-30 | **Relayed message injection**: the caller's words attack Dai's digest or commands | Message text is defanged data in the report; never contains codes; Dai's commands only from Dai's verified channels | Injected "OK ABCD" in a message does nothing |

Also reused: the outbound allowlist (Daikon only dials numbers in an approved brief), the approval gate, audit log of every call, the `Untrusted` type for transcripts, privacy labels so only the brief goes to OpenRouter, and OpenRouter privacy options plus a spend limit.

## 12. Failure modes

| Failure | Behavior |
|---|---|
| No answer / busy | Retry up to `retries` inside `retry_window`, then report `no_answer` |
| Voicemail | Hang up (default) or leave the approved fixed message; report |
| IVR loop / long hold | Press only listed digits; hang up after the timeout; report |
| Callee confused or hostile | End politely; report; never retry after "stop" |
| Wrong business / number | End; report; do not retry; flag the provider note |
| Call model or OpenRouter down | Do not dial; tell Dai; the brief becomes a **cheat sheet** Dai can use for his own call |
| STT/TTS problem or high latency | End call politely if it exceeds the latency budget; report |
| Tunnel or webhook down | Inbound callers hear Twilio's default; Dai gets a health alert; outbound unaffected |
| Laptop asleep or offline | Same as v1: runner restarts; inbound calls are missed; Twilio's fallback message plays; Dai alerted when back |
| Crash mid-call | `dialing` call is reconciled from Twilio's call log; never re-dialed automatically |
| Report cannot be sent | Retried; Dai alerted by the other channel |

## 13. Legal and policy items to verify before enabling (not legal advice)

1. Call recording and transcription consent rules in the callee's state (some states need all parties' consent). The opening disclosure is designed for this; confirm with a lawyer.
2. US rules for calls that use an AI-generated voice, including federal robocall/consent rules. Confirm that calls to businesses on A's behalf are permitted and what disclosure is required.
3. Health-privacy: offices may refuse to discuss a patient with a third party without A's authorization. Decide how A's consent is recorded (the brief's `consent_of_A`) and whether offices want a signed form.
4. Twilio's acceptable-use policy for voice and AI.
5. OpenRouter and the chosen STT/TTS vendors: data handling and retention for call audio and text.
6. Interpreter-request wording: confirm what offices call it (language line, qualified medical interpreter).

## 14. Cost (estimates, verify before budgeting)

| Item | Estimate |
|---|---|
| Twilio voice, outbound US | about $0.014 per minute, plus about $1 a month for the number; inbound about $0.0085 per minute |
| Call model through OpenRouter (Haiku-class) | a few cents per minute |
| STT / TTS | local Whisper and Piper: $0; cloud: a few cents per minute |
| Typical 5-minute call | about $0.10 to $0.40 |
| Monthly at 30 calls | about $3 to $12, plus the v1 cost |

Set a spend limit on the OpenRouter key and a per-call and daily minute cap.

## 15. Test plan

- **Interview:** unit tests for question selection, memory skipping, one-question rule, sensitive-field tagging, resume and edit.
- **Brief:** schema validation, hash binding, approval state machine, tamper tests.
- **Call simulator:** a fake callee (scripted and adversarial) drives the whole call logic with a fake model. No real number is dialed until the simulator suite passes.
- **Script guards:** outputs outside the brief are rejected (extra facts, price outside range, commitments in `info` calls).
- **Inbound:** registry hit and miss, unknown caller costs zero model calls, spoofed number in registry yields only an unverified message, registry addition needs approval, injected text in a message is inert.
- **Memory:** person-level fields never appear in another person's brief; stored text wrapped as untrusted.
- **Live:** a labeled `live` test calls Dai's own phone first, then a friendly business, never in CI.
- Every new RT row has a test before its capability is enabled (the traceability test fails otherwise).

## 16. Milestones (recommended order, lowest risk first)

| Step | Deliverable | Gate |
|---|---|---|
| C0 | v1 live and stable for 2 weeks; Twilio voice enabled; tunnel with signature check | Dai approves this design |
| C1 | Interview engine and call-brief approval, **no calling** (output is a brief and a cheat sheet Dai can use himself) | Interview tests green; Dai tries 5 real interviews |
| C2 | Call simulator and script guards | Simulator suite green |
| C3 | **Outbound `info` calls** (no commitments), first to Dai's own phone, then friendly businesses | RT-22, RT-23, RT-24 pass |
| C4 | Call memory and reporting, Second Brain read-back | RT-26 passes; Dai reviews 10 reports |
| C5 | **Outbound `book` calls** (with interpreter request), no payment | Dai reviews 10 calls |
| C6 | **Inbound callbacks** (registry, message-taking mode, approvals for additions) | RT-27 to RT-30 pass |
| C7 | **Payment / no-show offer**, last | RT-25 passes; payment route chosen; legal items cleared |

## 17. Open questions for Dai

1. Where in the Second Brain should call records live (suggested `09 Calls`)?
2. May Daikon ask offices for a callback number (§7.4), with your approval before it is added?
3. Inbound unknown callers: a fixed message then hang up (recommended), or voicemail-only recording of a short message that you review?
4. Which businesses should be the first test (a friendly business you know)?
5. How should person A's consent be recorded (Dai's confirmation only, or a short text in Vietnamese that A can show)?
6. Payment route for C7 (§9). Can wait until C6 is done.

Assumptions flagged: Twilio and OpenRouter latency and price are estimates; callbacks often come from a different number (hence §7.4); STIR/SHAKEN call-verification data may not always be present; offices may not accept a $5 no-show deposit.

Awaiting your approval to proceed.
