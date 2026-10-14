# Optimized prompt used to write the Daikon design doc

```text
Act as a principal AI-agent architect. Write docs/daikon-design.md for Daikon, Dai's
personal assistant, using the decisions recorded in CLAUDE.md as fixed inputs.

Audience: Dai (decision maker, non-specialist reader) and the future implementer.
Required sections: goals/non-goals; architecture and components; data flow; graph file
schema; approval state machine; second-brain access; security and threat model;
failure modes; phase 2 voice; cost; testing strategy; v1 milestones; open decisions.
Format: Markdown, tables for schemas/states/failures, one ASCII diagram, plain language.
Constraints: no code; do not contradict CLAUDE.md; every external action must pass the
approval gate; flag assumptions explicitly; keep secrets and personal data out of the repo.
Before writing, list any critical detail that is missing and ask only if it blocks the design.
```
