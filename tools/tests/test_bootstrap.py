import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "bootstrap-nocomments.sh"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def target(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text('"""d"""\nx = 1  # c\n')
    (tmp_path / "b.js").write_text("var a = 'http://x'; // c\n")
    git(tmp_path, "add", "-A")
    return tmp_path


def run(target):
    return subprocess.run(["sh", str(SCRIPT), str(target)], capture_output=True, text=True)


def test_bootstrap_on_temp_repo(target):
    result = run(target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "tools" / "nocomments.py").is_file()
    assert (target / ".githooks" / "pre-commit").is_file()
    assert (target / ".github" / "workflows" / "nocomments.yml").is_file()
    assert (target / "a.py").read_text() == "x = 1\n"
    assert (target / "b.js").read_text() == "var a = 'http://x';\n"
    assert git(target, "config", "core.hooksPath").strip() == ".githooks"
    assert "tools/nocomments.py check" in (target / "CLAUDE.md").read_text()
    check = subprocess.run(
        ["python3", "tools/nocomments.py", "check"], cwd=target, capture_output=True, text=True
    )
    assert check.returncode == 0


def test_bootstrap_is_idempotent(target):
    run(target)
    first = (target / "CLAUDE.md").read_text()
    assert run(target).returncode == 0
    assert (target / "CLAUDE.md").read_text() == first
    assert first.count("tools/nocomments.py check") == 1


def test_bootstrap_keeps_existing_claude_md(target):
    (target / "CLAUDE.md").write_text("# Mine\n- rule\n")
    run(target)
    text = (target / "CLAUDE.md").read_text()
    assert text.startswith("# Mine\n- rule\n")
    assert "tools/nocomments.py check" in text


def test_bootstrap_rejects_non_repo(tmp_path):
    result = run(tmp_path)
    assert result.returncode != 0
