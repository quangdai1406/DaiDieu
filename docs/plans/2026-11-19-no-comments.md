# No-Comments Policy Implementation Plan

> For agentic workers: use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Remove every comment from existing code, and make all new code comment-free, in this repo and every other repo.

**Architecture:** One stdlib-only tool `tools/nocomments.py` with two modes: `strip` (rewrite files) and `check` (exit 1 if any comment found). `check` is enforced by pre-commit hook and CI. The rule is written into CLAUDE.md (per repo) and `~/.claude/CLAUDE.md` (all future repos). A bootstrap script rolls the tool, hook, CI and rule into any other repo.

**Tech Stack:** Python 3 stdlib (`tokenize`, `ast`, `re`), pytest, git hooks, GitHub Actions.

## Global Constraints
- Scope of "comment": Python `#`, JS/TS `//` and `/* */`, CSS/SCSS `/* */` and SCSS `//`, HTML `<!-- -->`, Liquid `{% comment %}`, PowerShell `#` and `<# #>`, YAML `#`, XML `<!-- -->`.
- Kept: shebang line, Python encoding line, `<?xml?>`, Jekyll front matter, IE conditional comments, license-critical `/*! */`: none exist here so no exception code unless found.
- Excluded paths: `.git`, `_site`, `.sass-cache`, `wp-content`, `wp-includes`, `node_modules`, `*.min.js`, `*.min.css`, `*~`, `*.scssc` (third party or generated).
- Python docstrings count as comments and are removed. Tool never changes runtime behavior.
- Markdown prose is documentation, not code: untouched.

## Review Focus
- Comment markers inside strings/URLs (`"http://x"`, `"# not comment"`, regex literals) must survive.
- Python file with only comments/docstring still parses after strip.
- A block emptied by stripping (`if x:\n    # todo`) must still be valid (insert `pass` is NOT done; tool reports error instead).
- Files with CRLF line endings keep CRLF.
- Re-running `strip` is a no-op (idempotent).

## Assumptions (recorded per CLAUDE.md)
- Docstrings removed. Tooling directives (`# noqa`, `# type:`) removed too, since the user said all comments.
- Other repos are not reachable from this session; they get the bootstrap script and instructions.

### Task 1: Python stripper
**Files:** Create `tools/nocomments.py`, `tools/tests/test_py.py`
**Interfaces:** Produces `strip_python(src: str) -> str`, `find_python(src: str) -> list[int]` (line numbers).
- [ ] Test `test_removes_hash_and_inline_comment`, `test_keeps_hash_in_string`, `test_removes_docstrings`, `test_keeps_shebang`, `test_ast_equal_minus_docstrings`, `test_crlf_preserved`.
- [ ] Run `pytest tools/tests/test_py.py -q`, expect FAIL.
- [ ] Implement with `tokenize` (drop COMMENT tokens, rstrip trailing whitespace) and `ast` for docstring spans; raise `ValueError` if a block becomes empty.
- [ ] Run test, expect PASS. Commit.

### Task 2: Web/other stripper
**Files:** Modify `tools/nocomments.py`; Create `tools/tests/test_web.py`
**Interfaces:** Produces `strip_c_like(src, line_comments: bool)`, `strip_html(src)`, `strip_hash(src)`, and `strip_text(path: str, src: str) -> str` dispatching on extension (`.py .js .css .scss .html .xml .yml .yaml .ps1`).
- [ ] Tests: `test_js_url_in_string_kept`, `test_js_regex_with_slashes_kept`, `test_css_block_comment`, `test_scss_line_comment`, `test_html_comment_multiline`, `test_liquid_comment_block`, `test_yaml_hash_in_quotes_kept`, `test_idempotent`.
- [ ] Run, expect FAIL. Implement small state-machine scanner (tracks `'` `"` `` ` `` strings) for C-like; regex for HTML/Liquid; line scanner for hash. Run, expect PASS. Commit.

### Task 3: CLI (`strip` / `check`)
**Files:** Modify `tools/nocomments.py`; Create `tools/tests/test_cli.py`
**Interfaces:** `main(argv: list[str]) -> int`; `check` lists `path:line` per comment, returns 1 if any; default file set is `git ls-files` minus excluded paths.
- [ ] Tests on a temp git repo: `test_check_fails_with_comment`, `test_check_passes_clean`, `test_excluded_paths_skipped`, `test_strip_then_check_clean`.
- [ ] Run FAIL, implement, run PASS. Commit.

### Task 4: Apply to this repo
**Files:** all tracked `.py .js .css .scss .html .xml .yml .ps1` outside exclusions.
- [ ] Before: `python tools/nocomments.py check | wc -l` (record count in PROGRESS).
- [ ] Run `python tools/nocomments.py strip`.
- [ ] Verify: `check` exits 0; `python -m compileall -q audio-recorder`; AST-equality script over all `.py` (docstrings ignored) passes; existing test suite passes; `git diff --stat` reviewed for non-comment changes (spot-check HTML/JS renders: `jekyll build` if available).
- [ ] Commit `Remove all comments`.

### Task 5: Enforcement for new code
**Files:** Create `.githooks/pre-commit`, `.github/workflows/nocomments.yml`; Modify `CLAUDE.md`
- [ ] Test `test_hook_blocks_commit_with_comment` in `tools/tests/test_cli.py` (runs hook script in temp repo).
- [ ] Hook runs `python tools/nocomments.py check --staged`; add `--staged` option. CI runs `check` on push and PR.
- [ ] Add to CLAUDE.md Rules: "Never write comments or docstrings in code. Run `python tools/nocomments.py check` before commit." Set `git config core.hooksPath .githooks` (documented in README, and in the bootstrap).
- [ ] Run full suite and check. Commit.

### Task 6: All other repos and future repos
**Files:** Create `tools/bootstrap-nocomments.sh`, `docs/NO_COMMENTS.md`
- [ ] Script copies `nocomments.py`, hook, workflow into a target repo, appends the rule to its CLAUDE.md, sets hooksPath, runs `strip` then `check`. Test `test_bootstrap_on_temp_repo` (bash via pytest).
- [ ] Global rule: write the same rule to `~/.claude/CLAUDE.md` so every future Claude session in any repo follows it (done in this container; user must copy to their own machine, instructions in `docs/NO_COMMENTS.md`).
- [ ] Optional: GitHub template repo with the files so new repos start compliant.
- [ ] Run each other repo through bootstrap on the user's machine or add them to this session via `add_repo`.
- [ ] Commit.

## Self-review
Covers job 1 (Tasks 1-4, 6) and job 2 (Tasks 5-6). Names consistent across tasks.
