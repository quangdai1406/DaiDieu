"""Shared injection corpus: every case in tests/security/corpus/*.yaml must hold (RT-01/02/11/12/13)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from daikon.untrusted import Source, Trust, Untrusted, normalize_email

pytestmark = [pytest.mark.unit, pytest.mark.security]
CORPUS = Path(__file__).parent / "corpus"


def _cases() -> list[Any]:
    out = []
    for path in sorted(CORPUS.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")):
            out.append(pytest.param(case, id=f"{path.stem}:{case['id']}"))
    return out


def _run(case: dict[str, Any]) -> Untrusted:
    kind = case["kind"]
    text = case.get("text")
    if "repeat" in case:
        text = case["repeat"]["unit"] * case["repeat"]["times"]
    if kind == "email_html":
        return normalize_email(text=None, html=case["html"], origin="x@evil.test")
    return normalize_email(text=text, html=None, origin="x@evil.test")


@pytest.mark.parametrize("case", _cases())
def test_corpus_case(case: dict[str, Any]) -> None:
    result = _run(case)
    exp = case["expect"]
    assert result.source is Source.EMAIL and result.trust is Trust.UNTRUSTED
    for s in exp.get("text_includes", []):
        assert s in result.text
    for s in exp.get("text_excludes", []):
        assert s not in result.text
    for s in exp.get("quoted_includes", []):
        assert s in result.quoted_text
    for f in exp.get("flags_include", []):
        assert f in result.flags, f"missing flag {f}: {sorted(result.flags)}"
    for f in exp.get("flags_exclude", []):
        assert f not in result.flags, f"unexpected flag {f}"
    if "max_length" in exp:
        assert len(result.text) <= exp["max_length"]


def test_corpus_is_not_empty_and_covers_the_in_scope_rt_ids() -> None:
    rts = {c.values[0]["rt"] for c in _cases()}
    assert {"RT-01", "RT-02", "RT-11", "RT-12", "RT-13"} <= rts
