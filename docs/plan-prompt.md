# Optimized prompt used to write the Daikon implementation plan

```text
Act as a principal engineer writing an implementation plan for Daikon (see CLAUDE.md and
docs/daikon-design.md v4, which are fixed inputs). Audience: Dai (approver, non-specialist)
and the implementer (a coding agent working test-first on Windows).
Required sections: decisions and prerequisites that need Dai's hands; repo layout; global
rules (TDD, commits, CI); milestones M1-M8 matching the design; for each task: goal, files,
tests written first, done criteria; rollout (shadow mode, then live) with go/no-go gates;
risks and how each milestone retires them.
Format: Markdown, numbered tasks small enough for one commit each, tables where useful.
Constraints: no application code in the plan; nothing may send to anyone but Dai until the
security gate passes; secrets never in the repo; keep v1 minimal; Daikon lives in daikon/.
Ask Dai only if a missing detail blocks a task; otherwise state the assumption.
```
