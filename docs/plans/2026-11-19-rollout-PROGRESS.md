# PROGRESS: rollout (plan: 2026-11-19-rollout.md)

- [x] R1 Extend tool | done | 2026-11-19
- [x] R2 Verification helpers | done | 2026-11-19
- [ ] R3 markdown-to-pdf-editor | todo | 2026-11-19
- [ ] R4 aisi_mes | todo | 2026-11-19
- [ ] R5 daikon | todo | 2026-11-19
- [ ] R6 photo2step | todo | 2026-11-19
- [ ] R7 kdp-book-pipeline | todo | 2026-11-19
- [ ] R8 0dte-spy | todo | 2026-11-19
- [ ] R9 inspect-pro | todo | 2026-11-19
- [ ] R10 daikonai | todo | 2026-11-19
- [ ] R11 design-os | todo | 2026-11-19
- [ ] R12 vision-station | todo | 2026-11-19
- [ ] R13 eme121_spring2016 | todo | 2026-11-19
- [ ] R14 quangdai1406.github.io | todo | 2026-11-19
- [ ] R15 daitran | todo | 2026-11-19
- [ ] R16 Tool PR | todo | 2026-11-19

## Notes
- Assumption: all 13 repos, user did not narrow the list. Forks and 2016 repos included, each as a draft PR.
- Survey (current tool, before extension): markdown-to-pdf-editor 17, aisi_mes 545, daikon 1115, photo2step 328, kdp-book-pipeline 528, 0dte-spy 0, inspect-pro 5, daikonai 0, design-os 0, vision-station 2085, eme121_spring2016 80, quangdai1406.github.io 146, daitran 0. Counts miss TS, SQL, TOML, shell until R1 is done.
- Existing repo CLAUDE.md files have no comment rules; append only.
- Not covered by design: .md, .ipynb, .txt, .gitignore, .json.
- R1: tool now covers ts tsx jsx mjs cjs rules sql toml sh bash bat cmd. 65 tools tests pass. JSX comment {/* c */} leaves {} (valid, compiles identically); removing the braces is unsafe in plain TS.
- R2: verifier (scratch, not committed): /tmp/claude-0/verify_repo.py REPO BASE. TS/JS by typescript transpile removeComments equality, SQL by pglast AST (function bodies masked, plpgsql compared), TOML tomllib, YAML safe_load, HTML parser events, Python AST, sh bash -n. Self-test on DaiDieu and a synthetic repo passed.
