"""M6.5: every red-team scenario (docs/daikon-red-team-plan.md) is covered, deferred or manual.

``rt_map.yaml`` maps each RT id to one of:
  tests:    [path::test_name, ...]  - tests that must exist (checked by parsing the files)
  ci:       {file, contains}        - a CI/config rule that must be present
  manual:   {doc, anchor}           - a human checklist that must exist in docs/
  deferred: release name            - capability not enabled yet; must not be silently dropped
Scenarios in scope for gate G2 may not be deferred.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.security]
ROOT = Path(__file__).parents[2]           # daikon/
REPO = ROOT.parent
RT_MAP = yaml.safe_load((Path(__file__).parent / "rt_map.yaml").read_text(encoding="utf-8"))
PLAN = (REPO / "docs" / "daikon-red-team-plan.md").read_text(encoding="utf-8")
G2_SCOPE = (
    [f"RT-{i:02d}" for i in range(1, 8)] + ["RT-09"] + [f"RT-{i:02d}" for i in range(11, 16)]
    + [f"RT-{i:02d}" for i in range(17, 22)]
)


def plan_ids() -> set[str]:
    return set(re.findall(r"\| (RT-\d{2})\b", PLAN)) | set(re.findall(r"\bRT-\d{2}\b(?= \|)", PLAN))


def test_the_plan_lists_rt_01_to_rt_22() -> None:
    ids = set(re.findall(r"RT-\d{2}", PLAN))
    assert {f"RT-{i:02d}" for i in range(1, 23)} <= ids


def test_every_scenario_in_the_plan_has_an_entry_in_the_map() -> None:
    ids = set(re.findall(r"RT-\d{2}", PLAN))
    assert ids == set(RT_MAP), f"missing: {ids - set(RT_MAP)}, unknown: {set(RT_MAP) - ids}"


@pytest.mark.parametrize("rt", G2_SCOPE)
def test_g2_scenarios_are_not_deferred(rt: str) -> None:
    assert "deferred" not in RT_MAP[rt], f"{rt} is in scope for gate G2 and cannot be deferred"


def _test_exists(ref: str) -> bool:
    path, _, name = ref.partition("::")
    file = ROOT / path
    if not file.is_file():
        return False
    tree = ast.parse(file.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree))


def _cases() -> list[tuple[str, str]]:
    return [(rt, ref) for rt, entry in RT_MAP.items() for ref in entry.get("tests", [])]


@pytest.mark.parametrize(("rt", "ref"), _cases())
def test_mapped_tests_exist(rt: str, ref: str) -> None:
    assert _test_exists(ref), f"{rt}: test not found: {ref}"


@pytest.mark.parametrize("rt", sorted(RT_MAP))
def test_each_entry_has_exactly_one_kind_of_evidence(rt: str) -> None:
    kinds = {"tests", "ci", "manual", "deferred"} & set(RT_MAP[rt])
    assert len(kinds) >= 1, rt
    if "deferred" in kinds:
        assert kinds == {"deferred"}, f"{rt}: a deferred scenario cannot also claim coverage"


@pytest.mark.parametrize("rt", [r for r, e in RT_MAP.items() if "ci" in e])
def test_ci_rules_are_really_present(rt: str) -> None:
    rule = RT_MAP[rt]["ci"]
    text = (REPO / rule["file"]).read_text(encoding="utf-8")
    assert rule["contains"] in text, f"{rt}: {rule['file']} lacks {rule['contains']!r}"


@pytest.mark.parametrize("rt", [r for r, e in RT_MAP.items() if "manual" in e])
def test_manual_checklists_exist_in_the_docs(rt: str) -> None:
    item = RT_MAP[rt]["manual"]
    text = (REPO / item["doc"]).read_text(encoding="utf-8")
    assert item["anchor"] in text, f"{rt}: {item['doc']} lacks the section {item['anchor']!r}"


def test_deferred_scenarios_name_a_release() -> None:
    for rt, entry in RT_MAP.items():
        if "deferred" in entry:
            assert re.fullmatch(r"v\d(\.\d)?", entry["deferred"]), rt
