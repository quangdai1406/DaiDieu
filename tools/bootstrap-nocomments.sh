#!/bin/sh
set -eu
target=${1:?usage: bootstrap-nocomments.sh TARGET_REPO}
here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here")
if ! root=$(git -C "$target" rev-parse --show-toplevel 2>/dev/null); then
    echo "not a git repo: $target" >&2
    exit 1
fi
py=$(command -v python3 || command -v python)
rule='- Never write comments or docstrings in code (any language). Run `python tools/nocomments.py check` before every commit. Enable the hook once per clone: `git config core.hooksPath .githooks`.'

mkdir -p "$root/tools" "$root/.githooks" "$root/.github/workflows"
if [ "$root" != "$src" ]; then
    cp "$here/nocomments.py" "$root/tools/nocomments.py"
    cp "$src/.githooks/pre-commit" "$root/.githooks/pre-commit"
fi
chmod +x "$root/.githooks/pre-commit"

cat > "$root/.github/workflows/nocomments.yml" <<'YAML'
name: no-comments
on:
  push:
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python tools/nocomments.py check
YAML

claude_md="$root/CLAUDE.md"
if [ ! -f "$claude_md" ]; then
    printf '# Rules\n%s\n' "$rule" > "$claude_md"
elif ! grep -q 'tools/nocomments.py check' "$claude_md"; then
    if [ -n "$(tail -c 1 "$claude_md")" ]; then
        printf '\n' >> "$claude_md"
    fi
    printf '%s\n' "$rule" >> "$claude_md"
fi

git -C "$root" config core.hooksPath .githooks

status=0
"$py" "$root/tools/nocomments.py" strip --root "$root" || status=1
"$py" "$root/tools/nocomments.py" check --root "$root" || status=1
exit "$status"
