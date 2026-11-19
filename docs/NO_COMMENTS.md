# No comments policy

Rule: code has no comments or docstrings, in every repo, old and new.

## This repo
- `python tools/nocomments.py check` lists comments (`path:line`), exit 1 if any.
- `python tools/nocomments.py strip` removes them in place.
- `python tools/nocomments.py check --staged` checks what is staged. The pre-commit hook runs it.
- Once per clone: `git config core.hooksPath .githooks`.
- CI: `.github/workflows/nocomments.yml`.
- Covered: `.py .js .css .scss .html .htm .xml .yml .yaml .ps1`, plus Liquid `{% comment %}`.
- Skipped: `.git _site .sass-cache wp-content wp-includes node_modules *.min.js *.min.css *~ *.scssc`.
- Kept on purpose: shebang, Python encoding line, IE conditional comments.

## Another existing repo
1. Clone it next to this one.
2. `sh tools/bootstrap-nocomments.sh ../other-repo`
3. Review `git diff` in that repo, run its tests, commit on a branch, open a PR.

The script copies the tool, hook and CI workflow, adds the rule to the repo's `CLAUDE.md`, sets `core.hooksPath`, strips, then checks. Safe to run twice.

Checks to run for every repo after stripping: its own test suite, compile or build step, and `git diff` for anything that is not a comment. Languages the tool does not cover (for example TypeScript, C, SQL) still hold comments: `check` will not see them.

## Every future repo and every Claude session
Add this line to `~/.claude/CLAUDE.md` on your own machine (it applies to all repos):

    - Never write comments or docstrings in code (any language), in any repo. If a repo has tools/nocomments.py, run `python tools/nocomments.py check` before every commit.

For a new repo, run the bootstrap script once. Optional: make a GitHub template repo that already contains `tools/`, `.githooks/`, `.github/workflows/nocomments.yml` and the CLAUDE.md rule (not created; needs your approval).
