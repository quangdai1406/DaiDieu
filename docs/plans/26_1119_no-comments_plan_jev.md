# No-Comments Policy Implementation Plan (JEV)

Source: 2026-11-19-no-comments.md. Goal, architecture, tech stack, Global Constraints, Review Focus and Assumptions are unchanged from the source plan.

## JEV Routing (applies to every step)
- Tiers: T1 routine gate (haiku, low effort). T2 scored or routed decision with reason (haiku, or sonnet if criteria are hard). T3 ambiguity or escalation flag (sonnet). T4 full reasoning (opus).
- Routine decisions (pass/fail, next task, blocked or not, skill needed) are one short JSON object. Code, tests and design are written in normal reasoning, not JSON.
- Gate shape: `{"decision": "pass|fail|...", "confidence": 0.00-1.00, "escalate": false}`.
- Confidence: 0.85 or higher, act. 0.70 to 0.84, act and add one PROGRESS note saying what is uncertain. Below 0.70, think once in full; if still below 0.70, mark `blocked`.
- Escalation default: 3 failed tries on a task, mark `blocked`, note why, take next task. Ask the user only for missing credentials, irreversible actions, or a task blocked 3 times.
- Every commit ends with the attribution lines from the session instructions.

### Task 1: Python stripper
Files: `tools/nocomments.py`, `tools/tests/test_py.py`. Produces `strip_python(src: str) -> str`, `find_python(src: str) -> list[int]`.
- [ ] Tests: `test_removes_hash_and_inline_comment`, `test_keeps_hash_in_string`, `test_removes_docstrings`, `test_keeps_shebang`, `test_ast_equal_minus_docstrings`, `test_crlf_preserved`. T1. Bar 0.85. Escalate: a test that cannot express its requirement goes to T3 once.
- [ ] Run `pytest tools/tests/test_py.py -q`, expect FAIL. T1. `{"decision": "expected_fail|unexpected_pass|error", "failing_tests": [], "confidence": 0.00, "escalate": false}`. Escalate on unexpected_pass or error: fix the test first (T3).
- [ ] Implement with `tokenize` (drop COMMENT tokens, rstrip trailing whitespace) and `ast` for docstring spans; raise `ValueError` if a block becomes empty (never insert `pass`). T4. Bar 0.85.
- [ ] Run test, expect PASS. Commit. T1. `{"decision": "pass|fail", "failing_tests": [], "confidence": 0.00, "escalate": false}` with pytest output shown. On fail: root cause (T4), max 3 tries, then `blocked`.

### Task 2: Web/other stripper
Files: modify `tools/nocomments.py`; create `tools/tests/test_web.py`. Produces `strip_c_like(src, line_comments: bool)`, `strip_html(src)`, `strip_hash(src)`, `strip_text(path: str, src: str) -> str` dispatching on `.py .js .css .scss .html .xml .yml .yaml .ps1`.
- [ ] Tests: `test_js_url_in_string_kept`, `test_js_regex_with_slashes_kept`, `test_css_block_comment`, `test_scss_line_comment`, `test_html_comment_multiline`, `test_liquid_comment_block`, `test_yaml_hash_in_quotes_kept`, `test_idempotent`. T2. Bar 0.85. Escalate: any Review Focus case without a test goes to T3.
- [ ] Run, expect FAIL. T1, same gate shape as Task 1.
- [ ] Implement small state-machine scanner (tracks `'` `"` `` ` `` strings) for C-like; regex for HTML/Liquid; line scanner for hash. T4. Bar 0.85. Escalate: any case where a marker inside a string might be stripped stops the step.
- [ ] Run, expect PASS. Commit. T1. Max 3 tries, then `blocked`.

### Task 3: CLI (`strip` / `check`)
Files: modify `tools/nocomments.py`; create `tools/tests/test_cli.py`. `main(argv: list[str]) -> int`; `check` lists `path:line`, returns 1 if any; default file set is `git ls-files` minus excluded paths.
- [ ] Tests on a temp git repo: `test_check_fails_with_comment`, `test_check_passes_clean`, `test_excluded_paths_skipped`, `test_strip_then_check_clean`. T1. Bar 0.85.
- [ ] Run FAIL, implement (T2), run PASS, commit. Gates T1 as in Task 1. Escalate: an exclusion mismatch goes to T3.

### Task 4: Apply to this repo
Files: all tracked `.py .js .css .scss .html .xml .yml .ps1` outside exclusions.
- [ ] Before: `python tools/nocomments.py check | wc -l`, record the count in PROGRESS. T1. `{"comment_count_before": 0, "confidence": 0.00, "escalate": false}`. Escalate if the count is 0: confirm the file set (T2).
- [ ] Run `python tools/nocomments.py strip`. T1. `{"decision": "stripped|error", "files_changed": 0, "errors": [], "confidence": 0.00, "escalate": false}`. On error (an emptied block): T3 review per file, never bypass the tool.
- [ ] Verify: `check` exits 0; `python -m compileall -q audio-recorder`; AST-equality over all `.py` (docstrings ignored); existing tests pass; `git diff --stat` reviewed for non-comment changes; `jekyll build` if available. T3. `{"decision": "accept|reject", "non_comment_changes": [], "confidence": 0.00, "escalate": false}`; `{"jekyll": "built|not_available|failed"}`. Reject: fix the tool (T4), strip again. Below 0.70: `blocked`.
- [ ] Commit `Remove all comments`. T1. Only after verification passed.

### Task 5: Enforcement for new code
Files: create `.githooks/pre-commit`, `.github/workflows/nocomments.yml`; modify `CLAUDE.md`.
- [ ] Test `test_hook_blocks_commit_with_comment` in `tools/tests/test_cli.py`. T1. Bar 0.85.
- [ ] Hook runs `python tools/nocomments.py check --staged`; add `--staged` option. CI runs `check` on push and PR. T2. Escalate: unclear `--staged` semantics (staged blob vs working tree): T4 once.
- [ ] Add to CLAUDE.md Rules: "Never write comments or docstrings in code. Run `python tools/nocomments.py check` before commit." Set `git config core.hooksPath .githooks` (documented in README and the bootstrap). T1. `{"decision": "done|missing", "files": [], "confidence": 0.00, "escalate": false}`.
- [ ] Run full suite and check. Commit. T1. Max 3 tries, then `blocked`.

### Task 6: All other repos and future repos
Files: create `tools/bootstrap-nocomments.sh`, `docs/NO_COMMENTS.md`.
- [ ] Script copies `nocomments.py`, hook, workflow into a target repo, appends the rule to its CLAUDE.md without duplicates, sets hooksPath, runs `strip` then `check`. Test `test_bootstrap_on_temp_repo`. T2. Bar 0.85.
- [ ] Global rule: append the same rule to `~/.claude/CLAUDE.md` (append only, never overwrite; user copies to their own machine, instructions in `docs/NO_COMMENTS.md`). T2. `{"decision": "written|skipped", "path": "~/.claude/CLAUDE.md", "confidence": 0.00, "escalate": false}`.
- [ ] Optional GitHub template repo. T2. `{"decision": "skip|create", "confidence": 0.00, "escalate": true}`. Default skip (external, hard to reverse); needs the user's approval.
- [ ] Other repos: default `instructions_only`; `add_repo` only with the user's approval. T2. `{"decision": "instructions_only|add_repo", "confidence": 0.00, "escalate": false}`.
- [ ] Commit. T1. After the bootstrap test passes.

## Self-review
Covers job 1 (Tasks 1-4, 6) and job 2 (Tasks 5-6). No steps added.
