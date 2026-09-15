# ABOUTME: 全议题准则披露要求覆盖审计，防止 required 要求静默脱离 schema 承载。
# ABOUTME: 审定结果读 data/standard_disclosure_requirement_coverage.yaml；本测试只校验审定表与要求库、章节模板三者一致。
from pathlib import Path

import pytest
import yaml
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]
REQUIREMENTS_DIR = SSE_PACKAGE.standard_disclosure_requirements_dir
SECTIONS_DIR = SSE_PACKAGE.topic_sections_dir
COVERAGE_PATH = SSE_PACKAGE.requirement_coverage_path

COVERAGE_STATUSES = {
    "bound_to_block",
    "metric_disclosure_catalog",
    "integrated_report_level",
    "excluded_for_simplified",
    "conditional_applicability",
}
# 有意不承载必须给出理由码，构成对用户的产品承诺。
RATIONALE_REQUIRED_STATUSES = {"excluded_for_simplified", "integrated_report_level"}


def _coverage() -> dict:
    return (yaml.safe_load(COVERAGE_PATH.read_text()) or {})["topicRequirementCoverage"]


def _requirements(topic: str) -> list[dict]:
    raw = yaml.safe_load((REQUIREMENTS_DIR / f"{topic}.yaml").read_text()) or {}
    return [
        requirement
        for group in raw.get("topicStandardDisclosureRequirementGroups") or []
        for requirement in group["standardDisclosureRequirements"]
    ]


def _referenced_requirement_keys(node) -> "list[str]":
    if isinstance(node, dict):
        yield from node.get("standardDisclosureRequirementKeys") or []
        for value in node.values():
            yield from _referenced_requirement_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _referenced_requirement_keys(item)


def _section_referenced_keys(topic: str) -> set[str]:
    path = SECTIONS_DIR / f"{topic}.yaml"
    if not path.exists():
        return set()
    return set(_referenced_requirement_keys(yaml.safe_load(path.read_text()) or {}))


TOPICS = sorted(path.stem for path in REQUIREMENTS_DIR.glob("*.yaml"))


def test_coverage_table_covers_every_requirement_library_topic():
    assert set(_coverage()) == set(TOPICS)


@pytest.mark.parametrize("topic", TOPICS)
def test_every_required_requirement_has_explicit_coverage_status(topic: str):
    entry = _coverage()[topic]
    requirements = _requirements(topic)
    if entry["topicStatus"] == "requirements_pending":
        assert requirements == [], f"{topic} 已有要求条目，不应仍标 requirements_pending"
        return
    required_keys = {
        requirement["standardDisclosureRequirementKey"]
        for requirement in requirements
        if requirement["disclosureRequirementObligationLevel"] == "required"
    }
    assert required_keys - set(entry["requirements"]) == set()


@pytest.mark.parametrize("topic", TOPICS)
def test_coverage_entries_resolve_to_requirement_library(topic: str):
    entry = _coverage()[topic]
    known = {requirement["standardDisclosureRequirementKey"] for requirement in _requirements(topic)}
    assert set(entry["requirements"]) - known == set()


@pytest.mark.parametrize("topic", TOPICS)
def test_bound_to_block_requirements_are_referenced_by_schema(topic: str):
    entry = _coverage()[topic]
    referenced = _section_referenced_keys(topic)
    expected = {
        key
        for key, value in entry["requirements"].items()
        if value["coverageStatus"] == "bound_to_block"
    }
    assert expected - referenced == set()


@pytest.mark.parametrize("topic", TOPICS)
def test_coverage_status_values_and_rationale_codes(topic: str):
    for key, value in _coverage()[topic]["requirements"].items():
        status = value["coverageStatus"]
        assert status in COVERAGE_STATUSES, f"{key} 使用了未定义的 coverageStatus：{status}"
        if status in RATIONALE_REQUIRED_STATUSES:
            assert value.get("exclusionRationaleCode"), f"{key} 标记 {status} 但缺少 exclusionRationaleCode"


@pytest.mark.parametrize("topic", TOPICS)
def test_schema_references_resolve_to_requirement_library(topic: str):
    known = {requirement["standardDisclosureRequirementKey"] for requirement in _requirements(topic)}
    assert _section_referenced_keys(topic) - known == set()
