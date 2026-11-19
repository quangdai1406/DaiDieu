# PROGRESS: no-comments (plan: 2026-11-19-no-comments.md)

- [x] Task 1 Python stripper | done | 2026-11-19
- [x] Task 2 Web/other stripper | done | 2026-11-19
- [x] Task 3 CLI strip/check | done | 2026-11-19
- [ ] Task 4 Apply to this repo | doing | 2026-11-19
- [ ] Task 5 Enforcement (hook, CI, CLAUDE.md) | todo | 2026-11-19
- [ ] Task 6 Other repos + future repos | todo | 2026-11-19

## Notes
- Assumption: docstrings and tooling directives count as comments and are removed.
- Assumption: other repos not reachable here; delivered via bootstrap script.
- Assumption: wp-content, wp-includes, _site, minified and generated files excluded.
- Plan prep (multi-agent-job-runner): P1 JEV and P2 simplify done by haiku workers. Work copies: 26_1119_no-comments_plan_jev.md, 26_1119_no-comments_plan_simplified.md. Cuts: attribution line, self-review section, per-step max-3-tries (kept inline, redundant), Task 4 below-0.70 line (kept inline). Nothing requested was removed.
- Autopilot: session mode keep-working, orchestrator current session, confidence 0.9. Template repo = skip, other repos = instructions_only, no add_repo without user OK.
- Baseline: audio-recorder 128 passed, 1 skipped (pip install soundfile numpy was needed).
