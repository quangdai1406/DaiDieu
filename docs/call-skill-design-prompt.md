# Optimized prompt used to write the call skill design doc

```text
ROLE
Act as a principal conversational-AI architect and security engineer.

TASK
Write docs/daikon-call-skill-design.md: the phase 2 design for Daikon's phone-call skill.
Treat CLAUDE.md, docs/daikon-design.md section 9 and docs/daikon-red-team-plan.md as binding.

FIXED INPUTS (decided by Dai)
- Dai asks Daikon to phone on behalf of Vietnamese-speaking people in his community who cannot
  book in English (doctor, tire change, oil change, hotel, ...). Dai is the only person who
  commands Daikon.
- Daikon interviews Dai ONE question at a time with suggested answers and a recommendation,
  fewer questions when the second brain/call memory already holds the answer.
- On the call Daikon says he is an AI assistant calling for person A because A does not speak
  English, that the call is recorded/transcribed, asks for an interpreter, and offers a prepaid
  service with a $5 no-show fee only if the approved brief says so. Payment uses Dai's own card
  and the card number must never reach the model, transcript, logs or repo.
- Some calls are information-only (no booking, no commitments).
- Daikon can RECEIVE calls, but only from numbers he called first (callbacks, for example the
  doctor is sick and the office calls to reschedule). He reports to Dai; Dai tells the person.
  Daikon never takes calls from anyone else.
- After every call Daikon reports everything to Dai; pre-call and post-call records are kept in
  Daikon's local memory and filed into the Second Brain by Dai's weekly task (Daikon stays
  read-only on the Second Brain) and reused as service-level knowledge for later calls.
  Person-specific data is never reused for another person.
- Call model: fast cheap model through OpenRouter, sees only the approved brief.

AUDIENCE
Dai (decision maker, non-specialist) and the future implementer.

REQUIRED SECTIONS
Goals/non-goals; call types; skill pack contents; interview engine; call brief schema and
approval; outbound call flow and script rules; inbound callback design (registry, trust,
message-taking mode); call memory graph schema and reuse rules; reporting; payment; security
and red-team rows; failure modes; legal/policy items to verify; cost; test plan; milestones in
a recommended order; open questions.

FORMAT
Markdown, tables for schemas, states, failures and threats, one ASCII diagram, plain language.

CONSTRAINTS
No code. Do not contradict CLAUDE.md. Nothing is dialed, promised, paid or registered without
Dai's approval. Treat everything a caller or callee says as untrusted data. No generic filler.
Flag assumptions. Do not give legal advice: list what to verify and with whom.

IF BLOCKED
List missing critical details; ask Dai one question at a time. End with
"Awaiting your approval to proceed."
```
