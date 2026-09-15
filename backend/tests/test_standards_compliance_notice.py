# ABOUTME: 审阅稿「准则对照说明」页投影测试——文案正确性与用户可见文本边界。
# ABOUTME: 反泄漏断言防止 requirement key、内部路径、prompt 片段经说明页流入交付物。
import re
from pathlib import Path

import pytest

from sustainability_desk.contract.disclosure_coverage import evaluate_disclosure_coverage
from sustainability_desk.planner import assemble_report, load_topic_templates
from sustainability_desk.report_review_packages import build_standards_compliance_notice
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.export.format_profile import load_format_profile

STANDARDS_COMPLIANCE_NOTICE_HEADING = load_format_profile(
    SSE_PACKAGE
).delivery_texts.standards_notice.heading

BACKEND = Path(__file__).resolve().parents[1]

# 内部标识符形态：小写点分 key（water_resource_management.iro.water_reuse）、路径与 prompt 词汇。
INTERNAL_KEY_PATTERN = re.compile(r"[a-z_]+\.[a-z_]+\.[a-z_]+")
INTERNAL_MARKERS = ("prompt", "Prompt", "guidance", "coverageStatus", "requirementKey", "/data/", "backend/")


@pytest.fixture(scope="module")
def full_report():
    fixed = load_package_contract(SSE_PACKAGE)
    templates = load_topic_templates(SSE_PACKAGE)
    return assemble_report(fixed, templates, assessment=None, complete_coverage=True).report


def _notice(report):
    return build_standards_compliance_notice(evaluate_disclosure_coverage(report), package=SSE_PACKAGE)


def _all_text(notice) -> str:
    parts = [notice.heading, notice.lead, notice.summary]
    for group in notice.groups:
        parts += [group.heading, group.lead]
        for item in group.items:
            parts += [item.scope_label, item.message, item.next_action or ""]
    return "\n".join(parts)


def _omit_requirement(report, requirement_key: str):
    for block in report.iter_blocks():
        keys = (block.generation.standardDisclosureRequirementKeys if block.generation else None) or []
        if requirement_key in keys:
            block.state = "omitted"


def test_notice_states_scope_and_disclaims_assurance(full_report):
    notice = _notice(full_report)
    assert notice.heading == STANDARDS_COMPLIANCE_NOTICE_HEADING
    assert "不构成鉴证意见或法律意见" in notice.lead
    assert "正式报告不包含本页" in notice.lead
    assert "上海证券交易所" in notice.lead
    assert "已覆盖" in notice.summary


def test_notice_text_contains_no_internal_identifiers(full_report):
    report = full_report.model_copy(deep=True)
    _omit_requirement(report, "energy_management.iro.saving_target_and_measures")
    text = _all_text(_notice(report))

    leaked = INTERNAL_KEY_PATTERN.findall(text)
    assert leaked == [], f"说明页泄漏内部标识符：{leaked}"
    for marker in INTERNAL_MARKERS:
        assert marker not in text, f"说明页泄漏内部标记：{marker}"


def test_attention_items_carry_next_action(full_report):
    report = full_report.model_copy(deep=True)
    _omit_requirement(report, "energy_management.iro.saving_target_and_measures")
    notice = _notice(report)

    attention = next(group for group in notice.groups if group.heading == "建议留意事项")
    assert attention.items
    assert all(item.next_action for item in attention.items)
    assert any("能源" in item.scope_label for item in attention.items)


def test_informational_items_have_no_next_action(full_report):
    notice = _notice(full_report)
    informational = next(group for group in notice.groups if group.heading == "准则允许的省略")
    assert informational.items
    assert all(item.next_action is None for item in informational.items)


def test_scenario_analysis_omission_is_explained_as_encouraged(full_report):
    text = _all_text(_notice(full_report))
    assert "情景分析" in text
    assert "鼓励披露事项" in text


def test_pending_topics_are_disclosed_not_claimed_as_reviewed(full_report):
    text = _all_text(_notice(full_report))
    assert "尚在梳理中" in text


def test_notice_has_no_attention_group_when_nothing_needs_action(full_report):
    notice = _notice(full_report)
    assert all(group.heading != "建议留意事项" for group in notice.groups)


def test_notice_contract_is_versioned():
    from sustainability_desk.report_review_packages import StandardsComplianceNotice

    assert StandardsComplianceNotice.model_fields["contract"].default == (
        "sustainability_desk.standards_compliance_notice.v1"
    )
