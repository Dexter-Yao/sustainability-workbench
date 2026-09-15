# ABOUTME: 准则披露覆盖判定单测——覆盖 bound/omitted/条件未触发/有意排除四类处置与报告级义务判定。
# ABOUTME: 关键边界：conditional 要求被省略不构成留意项，required 要求被静默省略必须产出留意项。
from pathlib import Path

import pytest

from sustainability_desk.contract.disclosure_coverage import (
    evaluate_disclosure_coverage,
    load_report_level_obligations,
    load_requirement_coverage,
)
from sustainability_desk.planner import assemble_report, load_topic_templates
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def full_report():
    fixed = load_package_contract(SSE_PACKAGE)
    templates = load_topic_templates(SSE_PACKAGE)
    return assemble_report(fixed, templates, assessment=None, complete_coverage=True).report


def _omit_blocks(report, requirement_key: str):
    """把承载某准则要求的全部块置为证据门控省略态。"""
    touched = 0
    for block in report.iter_blocks():
        keys = (block.generation.standardDisclosureRequirementKeys if block.generation else None) or []
        if requirement_key in keys:
            block.state = "omitted"
            touched += 1
    return touched


def test_full_coverage_report_has_no_attention_items(full_report):
    coverage = evaluate_disclosure_coverage(full_report)
    assert coverage.attention_findings == ()
    assert coverage.attention_obligations == ()
    assert coverage.covered_requirement_count > 0


def test_required_requirement_silently_omitted_becomes_attention_item(full_report):
    report = full_report.model_copy(deep=True)
    requirement_key = "water_resource_management.iro.saving_target_and_measures"
    assert _omit_blocks(report, requirement_key) > 0

    coverage = evaluate_disclosure_coverage(report)
    attention = {finding.requirementKey for finding in coverage.attention_findings}
    assert requirement_key in attention
    finding = next(f for f in coverage.attention_findings if f.requirementKey == requirement_key)
    assert finding.code == "requirement_omitted_needs_statement"
    assert finding.reportSectionId == "water_resource_management"
    assert finding.requirementTitle  # 审阅稿展示业务语言标题，不展示内部 key


def test_conditional_requirement_not_triggered_is_not_an_attention_item(full_report):
    coverage = evaluate_disclosure_coverage(full_report)
    conditional = [
        finding for finding in coverage.findings
        if finding.code == "requirement_conditional_not_triggered"
    ]
    assert conditional, "气候情景分析等条件适用要求应产出条件未触发结论"
    assert all(finding not in coverage.attention_findings for finding in conditional)


def test_excluded_requirements_carry_rationale_code(full_report):
    coverage = evaluate_disclosure_coverage(full_report)
    excluded = [f for f in coverage.findings if f.code == "requirement_excluded_by_design"]
    assert excluded
    assert all(finding.exclusionRationaleCode for finding in excluded)


def test_pending_topics_are_reported_not_silently_skipped(full_report):
    coverage = evaluate_disclosure_coverage(full_report)
    pending = {f.reportSectionId for f in coverage.findings if f.code == "topic_requirements_pending"}
    assert pending == {"due_diligence", "risk_management"}


def test_structural_obligations_are_satisfied_by_report_skeleton(full_report):
    coverage = evaluate_disclosure_coverage(full_report)
    structural = {
        obligation.obligationKey: obligation.code
        for obligation in coverage.obligations
        if obligation.obligationKey in {"g1.framework_structure", "g1.benchmark_index_table"}
    }
    assert structural == {
        "g1.framework_structure": "satisfied",
        "g1.benchmark_index_table": "satisfied",
    }


def test_missing_period_declaration_raises_attention(full_report):
    report = full_report.model_copy(deep=True)
    for block in report.iter_blocks():
        if block.id == "about.timeframe":
            block.state = "omitted"

    coverage = evaluate_disclosure_coverage(report)
    attention = {obligation.obligationKey for obligation in coverage.attention_obligations}
    assert "g1.reporting_period_declaration" in attention


def test_finding_codes_are_stable_and_sorted(full_report):
    codes = evaluate_disclosure_coverage(full_report).finding_codes()
    assert list(codes) == sorted(codes)
    assert all(isinstance(code, str) and code for code in codes)


def test_coverage_table_and_obligations_load_as_typed_objects():
    coverage = load_requirement_coverage(SSE_PACKAGE)
    obligations = load_report_level_obligations(SSE_PACKAGE)
    assert coverage and obligations
    assert all(item.userFacingNote for item in obligations)
