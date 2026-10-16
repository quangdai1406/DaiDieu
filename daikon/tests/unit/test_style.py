"""M3.6: the voice guide that is added to the drafting prompt."""

from pathlib import Path

import pytest

from daikon.style import DEFAULT_STYLE, MAX_STYLE_CHARS, load_style

pytestmark = pytest.mark.unit


def test_missing_file_uses_the_default_voice(tmp_path: Path) -> None:
    assert load_style(tmp_path / "style.md") == DEFAULT_STYLE
    assert "short" in DEFAULT_STYLE.lower() and "formal" in DEFAULT_STYLE.lower()


def test_file_content_replaces_the_default(tmp_path: Path) -> None:
    p = tmp_path / "style.md"
    p.write_text("Be warm.\nSign off with 'Best, Dai'.", encoding="utf-8")
    assert load_style(p) == "Be warm.\nSign off with 'Best, Dai'."


def test_empty_file_falls_back_to_the_default(tmp_path: Path) -> None:
    p = tmp_path / "style.md"
    p.write_text("  \n", encoding="utf-8")
    assert load_style(p) == DEFAULT_STYLE


def test_long_files_are_capped_and_control_characters_removed(tmp_path: Path) -> None:
    p = tmp_path / "style.md"
    p.write_text("a\x00b" * 5000, encoding="utf-8")
    out = load_style(p)
    assert len(out) <= MAX_STYLE_CHARS and "\x00" not in out


def test_a_file_that_looks_like_it_holds_a_secret_is_refused(tmp_path: Path) -> None:
    p = tmp_path / "style.md"
    p.write_text("Be brief. key sk-ant-" + "A" * 30, encoding="utf-8")
    with pytest.raises(ValueError, match="secret"):
        load_style(p)
