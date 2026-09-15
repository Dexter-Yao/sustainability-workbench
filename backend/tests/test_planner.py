# ABOUTME: 验证五模块 Planner 只按严格 Registry 和完整重要性结果选择报告章节内容分支。
# ABOUTME: 合并 H2 采用成员重要性聚合；impact/non 直属摘要，financial/dual 使用固定四要素。
from pathlib import Path

import pytest

from sustainability_desk.contract.assessment_classify import resolve_materiality_assessment
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import (
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
)
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from sustainability_desk.planner import TopicGuardError, assemble_report
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from
from sustainability_desk.planner import load_topic_intake_from

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
TOPICS = SSE_PACKAGE.topic_sections_dir
INTAKE = SSE_PACKAGE.topic_intake_dir


def _fixed(*, technology_ethics: str = "否"):
    report = load_contract(CONTRACT)
    fields = dict(report.fields)
    fields["has_technology_ethics_sensitive_activity"] = fields[
        "has_technology_ethics_sensitive_activity"
    ].model_copy(update={"value": technology_ethics})
    return report.model_copy(update={"fields": fields})


def _assessment(report, *, financial_ids: set[str] | None = None):
    financial_ids = financial_ids or set()
    scores = [
        MaterialityScoreInput(
            assessmentTopicId=topic.id,
            financialScore=5 if topic.id in financial_ids else 3,
            impactScore=3,
        )
        for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
    ]
    assessment_input = MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=scores,
    )
    return resolve_materiality_assessment(assessment_input, report)


def _assemble(report, assessment):
    return assemble_report(
        report,
        load_topic_templates_from(TOPICS, package=SSE_PACKAGE),
        assessment=assessment,
        intake_items=load_topic_intake_from(INTAKE, package=SSE_PACKAGE),
    ).report


def _section(report, key):
    stack = list(report.sections)
    while stack:
        section = stack.pop(0)
        if section.key == key:
            return section
        stack[0:0] = section.children or []
    raise AssertionError(key)


def test_no_assessment_does_not_create_report_modules():
    report = _assemble(_fixed(), None)
    assert not any(section.reportModuleId for section in report.sections)


def test_non_and_impact_sections_use_direct_summary_without_h3():
    report = _assemble(_fixed(), _assessment(_fixed()))
    modules = [section for section in report.sections if section.reportModuleId]
    assert [section.key for section in modules] == [
        "environmental_sustainability",
        "people_and_communities",
        "innovation_and_product_responsibility",
        "sustainable_value_chain",
        "responsible_governance",
    ]
    for module in modules:
        for section in module.children or []:
            assert section.children is None
            assert len(section.blocks) == 1
            assert section.blocks[0].id.endswith(".concise_summary")


def test_merged_report_section_uses_four_pillars_if_any_member_is_financial():
    fixed = _fixed()
    report = _assemble(fixed, _assessment(fixed, financial_ids={"social_contribution"}))
    section = _section(report, "rural_revitalization_social_contribution")
    assert [child.title for child in section.children or []] == [
        "治理",
        "战略",
        "影响、风险与机遇管理",
        "指标与目标",
    ]
    assert section.blocks == []


def test_technology_ethics_switch_changes_scoring_and_report_section_scope():
    without = _fixed(technology_ethics="否")
    with_topic = _fixed(technology_ethics="是")
    without_report = _assemble(without, _assessment(without))
    with_report = _assemble(with_topic, _assessment(with_topic))
    assert len(applicable_scoring_topics(without, package=SSE_PACKAGE)) == 22
    assert len(applicable_scoring_topics(with_topic, package=SSE_PACKAGE)) == 23
    without_ids = {
        child.reportSectionId for module in without_report.sections for child in (module.children or [])
    }
    with_ids = {
        child.reportSectionId for module in with_report.sections for child in (module.children or [])
    }
    assert "technology_ethics" not in without_ids
    assert "technology_ethics" in with_ids


def test_partial_assessment_is_rejected():
    fixed = _fixed()
    assessment = _assessment(fixed)
    partial = assessment.model_copy(update={"topics": assessment.topics[:-1]})
    with pytest.raises(TopicGuardError, match="缺少适用议题"):
        _assemble(fixed, partial)


def test_missing_applicable_template_is_rejected():
    fixed = _fixed()
    templates = load_topic_templates_from(TOPICS, package=SSE_PACKAGE)
    templates.pop("climate_change")
    with pytest.raises(TopicGuardError, match="缺少章节模板"):
        assemble_report(fixed, templates, assessment=_assessment(fixed))
