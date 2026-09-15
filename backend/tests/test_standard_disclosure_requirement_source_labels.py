# ABOUTME: 准则出处标签受控格式校验——excerptFrom 与 SSE clauseRef 必须锚定准则原文，不得以参考模板充当合规锚点。
# ABOUTME: TEMPLATE_ANCHORED_TOPICS 是尚未按指南披露要点重锚定的议题台账，重锚定一个即从清单移除。
from pathlib import Path

import pytest
import yaml
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]
REQUIREMENTS_DIR = SSE_PACKAGE.standard_disclosure_requirements_dir

# 指南只覆盖气候、污染物、能源、水资源四个议题；其余议题的合规原子单元是《指引第14号》条款，
# 当前仍沿用参考模板梳理结果，待逐个按条款重锚定后从本清单移除。
TEMPLATE_ANCHORED_TOPICS = {
    "anti_bribery_anti_corruption",
    "anti_unfair_competition",
    "circular_economy_promotion",
    "customer_service_quality_management",
    "data_security_customer_privacy_protection",
    "ecosystem_biodiversity_protection",
    "environmental_compliance_management",
    "human_capital_development",
    "innovation_driven",
    "occupational_health_safety",
    "product_quality_safety",
    "rural_revitalization_social_contribution",
    "sme_fair_treatment",
    "sustainable_supply_chain_management",
    "technology_ethics",
    "waste_management",
}

TOPICS = sorted(path.stem for path in REQUIREMENTS_DIR.glob("*.yaml"))
STANDARD_ANCHORED_TOPICS = sorted(set(TOPICS) - TEMPLATE_ANCHORED_TOPICS)


def _requirements(topic: str) -> list[dict]:
    raw = yaml.safe_load((REQUIREMENTS_DIR / f"{topic}.yaml").read_text()) or {}
    return [
        requirement
        for group in raw.get("topicStandardDisclosureRequirementGroups") or []
        for requirement in group["standardDisclosureRequirements"]
    ]


def _sse_clause_refs(requirement: dict) -> list[str]:
    return [
        label["clauseRef"]
        for label in requirement.get("sourceClauseReferenceLabels") or []
        if label["standard"] == "SSE"
    ]


def test_template_anchored_topic_list_is_current():
    """清单只登记真实仍用模板锚点的议题，重锚定后必须同步移除。"""
    stale = {
        topic
        for topic in TEMPLATE_ANCHORED_TOPICS
        if not any("参考模板" in item["excerptFrom"] or "附录索引表" in item["excerptFrom"] for item in _requirements(topic))
    }
    assert stale == set(), f"以下议题已完成重锚定，应从 TEMPLATE_ANCHORED_TOPICS 移除：{sorted(stale)}"


@pytest.mark.parametrize("topic", STANDARD_ANCHORED_TOPICS)
def test_excerpt_from_anchors_standard_text(topic: str):
    for requirement in _requirements(topic):
        excerpt = requirement["excerptFrom"]
        assert excerpt.startswith("上交所·"), f"{requirement['standardDisclosureRequirementKey']} 的 excerptFrom 未锚定准则原文：{excerpt}"
        assert "参考模板" not in excerpt, f"{requirement['standardDisclosureRequirementKey']} 以参考模板充当合规锚点"


@pytest.mark.parametrize("topic", STANDARD_ANCHORED_TOPICS)
def test_sse_clause_ref_cites_guideline(topic: str):
    """SSE 出处须引指南；指引条款括注仅在该要点确有对应条款时出现（如碳信用类要点在指引中无对应条款）。"""
    for requirement in _requirements(topic):
        for clause_ref in _sse_clause_refs(requirement):
            assert clause_ref.startswith("指南第"), f"{requirement['standardDisclosureRequirementKey']} 的 SSE 出处未引指南：{clause_ref}"


@pytest.mark.parametrize("topic", TOPICS)
def test_requirement_text_is_not_truncated(topic: str):
    """要求正文须为完整句，防止「不得将。」这类截断。"""
    for requirement in _requirements(topic):
        text = requirement["standardDisclosureRequirementText"]
        assert not text.rstrip().endswith(("不得将。", "不得。", "应当。", "包括。")), (
            f"{requirement['standardDisclosureRequirementKey']} 的要求正文疑似截断：{text[-30:]}"
        )
