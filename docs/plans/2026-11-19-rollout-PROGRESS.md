# PROGRESS: rollout (plan: 2026-11-19-rollout.md)

- [x] R1 Extend tool | done | 2026-11-19
- [x] R2 Verification helpers | done | 2026-11-19
- [x] R3 markdown-to-pdf-editor | done | 2026-11-19
- [x] R4 aisi_mes | done | 2026-11-19
- [x] R5 daikon | done | 2026-11-19
- [x] R6 photo2step | done | 2026-11-19
- [x] R7 kdp-book-pipeline | done | 2026-11-19
- [x] R8 0dte-spy | done | 2026-11-19
- [x] R9 inspect-pro | done | 2026-11-19
- [x] R10 daikonai | done | 2026-11-19
- [x] R11 design-os | done | 2026-11-19
- [x] R12 vision-station | done | 2026-11-19
- [x] R13 eme121_spring2016 | done | 2026-11-19
- [x] R14 quangdai1406.github.io | done | 2026-11-19
- [x] R15 daitran | done | 2026-11-19
- [x] R16 Tool PR | done | 2026-11-19

## Notes
- Assumption: all 13 repos, user did not narrow the list. Forks and 2016 repos included, each as a draft PR.
- Survey (current tool, before extension): markdown-to-pdf-editor 17, aisi_mes 545, daikon 1115, photo2step 328, kdp-book-pipeline 528, 0dte-spy 0, inspect-pro 5, daikonai 0, design-os 0, vision-station 2085, eme121_spring2016 80, quangdai1406.github.io 146, daitran 0. Counts miss TS, SQL, TOML, shell until R1 is done.
- Existing repo CLAUDE.md files have no comment rules; append only.
- Not covered by design: .md, .ipynb, .txt, .gitignore, .json.
- R1: tool now covers ts tsx jsx mjs cjs rules sql toml sh bash bat cmd. 65 tools tests pass. JSX comment {/* c */} leaves {} (valid, compiles identically); removing the braces is unsafe in plain TS.
- R2: verifier (scratch, not committed): /tmp/claude-0/verify_repo.py REPO BASE. TS/JS by typescript transpile removeComments equality, SQL by pglast AST (function bodies masked, plpgsql compared), TOML tomllib, YAML safe_load, HTML parser events, Python AST, sh bash -n. Self-test on DaiDieu and a synthetic repo passed.
- Rollout done: 13 draft PRs on branch no-comments. Docs-only repos (0DTE-SPY, DaikonAI, design-os, DaiTran) got tool, hook, CI and rule only.
- Verified per repo with verify_repo.py: AST (py), compiler output (ts js tsx), pglast (sql), tomllib, yaml.safe_load, html.parser, bash -n. 0 bad after fixes.
- Tool fixes found during rollout: docstring-only bodies to pass, __doc__ readers to DOC_TEXT, inline docstring raises, legal comments kept, vendored defaults and .nocommentsignore, UTF-16 support, JSX closing tag read as regex, verifier false alarms (position offsets).
- Not run: full test suites for daikon, vision-station, aisi_mes, inspect-pro (deps), photo2step (cut off at 280s, identical progress), no site builds. User asked to go faster, so skipped.
- Needs review: AISI_MES edits already-applied SQL migrations (comment lines only). GitHub Pages repos (EME121_Spring2016, quangdai1406.github.io) publish on merge.
- Template repo skipped (needs user OK).
