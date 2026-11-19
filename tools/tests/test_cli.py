import shutil
import subprocess
from pathlib import Path

import pytest

from nocomments import main


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


def add(repo, files):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, newline="")
    git(repo, "add", "-A")


def test_check_fails_with_comment(repo, capsys):
    add(repo, {"a.py": "x = 1  # c\n"})
    assert main(["check", "--root", str(repo)]) == 1
    assert "a.py:1" in capsys.readouterr().out


def test_check_passes_clean(repo):
    add(repo, {"a.py": "x = 1\n", "b.js": "var a = 1;\n", "notes.md": "# heading\n"})
    assert main(["check", "--root", str(repo)]) == 0


def test_excluded_paths_skipped(repo):
    add(
        repo,
        {
            "_site/x.js": "// c\n",
            "wp-content/y.css": "/* c */\n",
            "wp-includes/z.js": "// c\n",
            "a.min.js": "// c\n",
            "b.min.css": "/* c */\n",
            "q.scssc": "// c\n",
            "node_modules/m.js": "// c\n",
        },
    )
    assert main(["check", "--root", str(repo)]) == 0


def test_strip_then_check_clean(repo):
    add(
        repo,
        {
            "a.py": '"""d"""\nx = 1  # c\r\n',
            "b.js": "var a = 'http://x'; // c\n",
            "c.scss": "a{} // c\n",
            "d.html": "<!-- c --><p>x</p>\n",
            "e.yml": "a: 1 # c\n",
        },
    )
    assert main(["strip", "--root", str(repo)]) == 0
    assert main(["check", "--root", str(repo)]) == 0
    assert (repo / "a.py").read_bytes() == b"x = 1\r\n"
    assert (repo / "b.js").read_text() == "var a = 'http://x';\n"


def test_strip_reports_empty_block_and_leaves_file(repo, capsys):
    add(repo, {"a.py": "if x:\n    # todo\n", "b.py": "y = 1  # c\n"})
    assert main(["strip", "--root", str(repo)]) == 2
    assert (repo / "a.py").read_text() == "if x:\n    # todo\n"
    assert (repo / "b.py").read_text() == "y = 1\n"
    assert "a.py" in capsys.readouterr().out


def test_explicit_paths_only(repo, capsys):
    add(repo, {"a.py": "x = 1  # c\n", "b.py": "y = 2  # c\n"})
    assert main(["check", "--root", str(repo), "b.py"]) == 1
    out = capsys.readouterr().out
    assert "b.py:1" in out and "a.py" not in out


def test_binary_and_unknown_suffix_ignored(repo):
    add(repo, {"img.jpg": "# not text\n", "data.txt": "# keep\n"})
    assert main(["check", "--root", str(repo)]) == 0


def test_staged_checks_index_not_worktree(repo, capsys):
    add(repo, {"a.py": "x = 1\n"})
    git(repo, "commit", "-qm", "init")
    (repo / "a.py").write_text("x = 1  # c\n")
    git(repo, "add", "a.py")
    (repo / "a.py").write_text("x = 1\n")
    assert main(["check", "--staged", "--root", str(repo)]) == 1
    assert "a.py:1" in capsys.readouterr().out
    git(repo, "add", "a.py")
    (repo / "a.py").write_text("x = 1  # dirty worktree only\n")
    assert main(["check", "--staged", "--root", str(repo)]) == 0


def test_staged_ignores_deleted_files(repo):
    add(repo, {"a.py": "x = 1  # c\n"})
    git(repo, "commit", "-qm", "init")
    git(repo, "rm", "-q", "a.py")
    assert main(["check", "--staged", "--root", str(repo)]) == 0


def install_hook(repo):
    root = Path(__file__).resolve().parents[2]
    (repo / "tools").mkdir()
    shutil.copy(root / "tools" / "nocomments.py", repo / "tools" / "nocomments.py")
    hooks = repo / ".githooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    shutil.copy(root / ".githooks" / "pre-commit", hook)
    hook.chmod(0o755)
    git(repo, "config", "core.hooksPath", ".githooks")


def test_hook_blocks_commit_with_comment(repo):
    install_hook(repo)
    (repo / "a.py").write_text("x = 1  # c\n")
    git(repo, "add", "a.py")
    blocked = subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, capture_output=True, text=True)
    assert blocked.returncode != 0
    assert "a.py:1" in blocked.stdout + blocked.stderr
    (repo / "a.py").write_text("x = 1\n")
    git(repo, "add", "a.py")
    ok = subprocess.run(["git", "commit", "-qm", "good"], cwd=repo, capture_output=True, text=True)
    assert ok.returncode == 0


def test_default_vendored_patterns_skipped(repo):
    add(
        repo,
        {
            "lib/marked.umd.js": "// c\n",
            "lib/app.bundle.js": "// c\n",
            "vendor/x.js": "// c\n",
            "dist/y.js": "// c\n",
            "src/app.js": "var a;\n",
        },
    )
    assert main(["check", "--root", str(repo)]) == 0


def test_nocommentsignore_file(repo, capsys):
    add(
        repo,
        {
            ".nocommentsignore": "legacy/\n*.gen.py\nexact.py\n",
            "legacy/a.py": "x = 1  # c\n",
            "b.gen.py": "x = 1  # c\n",
            "exact.py": "x = 1  # c\n",
            "kept.py": "x = 1  # c\n",
        },
    )
    assert main(["check", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "kept.py:1" in out
    for skipped in ("legacy", "b.gen.py", "exact.py"):
        assert skipped not in out
