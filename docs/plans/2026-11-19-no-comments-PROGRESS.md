# PROGRESS: no-comments (plan: 2026-11-19-no-comments.md)

- [x] Task 1 Python stripper | done | 2026-11-19
- [x] Task 2 Web/other stripper | done | 2026-11-19
- [x] Task 3 CLI strip/check | done | 2026-11-19
- [x] Task 4 Apply to this repo | done | 2026-11-19
- [ ] Task 5 Enforcement (hook, CI, CLAUDE.md) | doing | 2026-11-19
- [ ] Task 6 Other repos + future repos | todo | 2026-11-19

## Notes
- Assumption: docstrings and tooling directives count as comments and are removed.
- Assumption: other repos not reachable here; delivered via bootstrap script.
- Assumption: wp-content, wp-includes, _site, minified and generated files excluded.
- Plan prep (multi-agent-job-runner): P1 JEV and P2 simplify done by haiku workers. Work copies: 26_1119_no-comments_plan_jev.md, 26_1119_no-comments_plan_simplified.md. Cuts: attribution line, self-review section, per-step max-3-tries (kept inline, redundant), Task 4 below-0.70 line (kept inline). Nothing requested was removed.
- Autopilot: session mode keep-working, orchestrator current session, confidence 0.9. Template repo = skip, other repos = instructions_only, no add_repo without user OK.
- Baseline: audio-recorder 128 passed, 1 skipped (pip install soundfile numpy was needed).
- Task 4: 287 comment lines in 40 files before, 0 after. Verified: AST equal (23 .py, docstrings ignored), html.parser events equal (7 html/htm/xml), libsass compressed css equal (4 scss), yaml.safe_load equal, ps1 only header comments removed, compileall ok, audio-recorder 128 passed 1 skipped, tools 34 passed. jekyll not available.
- Task 4 bug found in review: IE conditional comment swallowed markup. Root cause regex; fixed with test_html_ie_conditional_kept. Also removed accidentally tracked pycache and added .gitignore.
- Assumption: .claude/skills/code-graph/scripts/codegraph.py is repo code and was stripped too (confidence 0.8, reversible via git).
