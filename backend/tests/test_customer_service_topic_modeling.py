# ABOUTME: 客户服务质量管理单议题严谨建模测试，验证其不再是通用四题脚手架。
# ABOUTME: 取证依据为附录索引表第四十四、第四十七条及参考模板“客户服务质量管理”章节结构。
from collections import Counter
from pathlib import Path

from sustainability_desk.contract.models import Field, Report
from sustainability_desk.llm.generation_guardrails import check_paragraph_output
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake, load_topic_templates
from topic_intake_assertions import empty_guardrail_context, expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def test_customer_service_quality_management_section_uses_appendix_title_and_reference_structure():
    section = load_topic_templates(SSE_PACKAGE)["customer_service_quality_management"]
    blocks = {block.id: block for block in _walk_blocks(section)}

    assert section.title == "客户服务质量管理"
    assert {
            "customer_service_quality_management.gov_service_responsibility",
            "customer_service_quality_management.strategy_customer_centric_service",
            "customer_service_quality_management.iro_service_feedback_improvement",
            "customer_service_quality_management.metrics_summary",
            "customer_service_quality_management.metrics_narrative_body",
            "customer_service_quality_management.layout_assets",
        } == set(blocks)
    metric_block = blocks["customer_service_quality_management.metrics_narrative_body"]
    assert metric_block.type == "paragraph"
    assert metric_block.table is None
    assert set(metric_block.generation.inputs.evidence.quantitativeMetrics or []) == {"social_r55", "social_r56"}
    assert metric_block.content is None
    assert metric_block.generation.task.mode == "metric_narrative"


def test_customer_service_quality_management_intake_collects_service_specific_facts():
    items = [item for item in load_topic_intake(SSE_PACKAGE) if item.contentScopeId == "customer_service_quality_management"]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("customer_service_quality_management")
    assert any("客户服务" in item.prompt and "客诉处理平台" in item.prompt for item in items)
    assert any("客户服务承诺" in item.prompt for item in items)
    assert any("售后支持" in (item.hint or "") for item in items)


def test_customer_service_quality_management_prompt_requirements_are_clause_specific():
    lightweight = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "customer_service_quality_management",
        [
            "customer_service_quality_management.gov.service_management_required",
            "customer_service_quality_management.strategy.customer_centric_encouraged",
            "customer_service_quality_management.iro.complaint_process_required",
            "customer_service_quality_management.iro.product_safety_feedback_linkage_required",
            "customer_service_quality_management.metrics.service_metrics_required",
        ],
        required_only=True,
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "customer_service_quality_management",
        [
            "customer_service_quality_management.gov.service_management_required",
            "customer_service_quality_management.strategy.customer_centric_encouraged",
            "customer_service_quality_management.iro.complaint_process_required",
            "customer_service_quality_management.iro.product_safety_feedback_linkage_required",
            "customer_service_quality_management.metrics.service_metrics_required",
        ],
    )

    lightweight_text = "\n".join(item.standardDisclosureRequirementText for item in lightweight)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "客户投诉" in lightweight_text
    assert "售后服务" in lightweight_text
    assert "产品健康与安全" in lightweight_text
    assert "ESG 定量数据表" not in lightweight_text
    assert "以客户为中心" not in lightweight_text
    assert "以客户为中心" in comprehensive_text
    assert "品牌价值" in comprehensive_text


def test_customer_service_quality_management_generation_only_reads_topic_intake():
    section = load_topic_templates(SSE_PACKAGE)["customer_service_quality_management"]
    for block in _walk_blocks(section):
        generation = block.generation
        if generation is None:
            continue

        assert set(generation.inputs.fields or []) <= {"company_short_name", "industry"}
        assert all(
            item.startswith("customer_service_quality_management.")
            for item in (generation.inputs.evidence.intakeItems or [])
        )

    metric_table = next(block for block in _walk_blocks(section) if block.id == "customer_service_quality_management.metrics_narrative_body")
    metrics_posture = "\n".join(metric_table.generation.simplifiedWritingGuidance or [])
    assert metric_table.generation.inputs.evidence.quantitativeMetrics
    assert (metric_table.generation.inputs.evidence.intakeItems or []) == []
    assert metric_table.type == "paragraph"
    assert metric_table.table is None
    assert metrics_posture == ""


def test_customer_service_quality_management_does_not_reuse_same_intake_within_pillar():
    section = load_topic_templates(SSE_PACKAGE)["customer_service_quality_management"]

    for child in section.children or []:
        intake_keys: list[str] = []
        for block in _walk_blocks(child):
            generation = block.generation
            if not generation or not generation.inputs:
                continue
            intake_keys.extend(generation.inputs.evidence.intakeItems or [])
        repeated = [key for key, count in Counter(intake_keys).items() if count > 1]
        assert repeated == []


def test_customer_service_satisfaction_block_blocks_template_negative_shortfall_language():
    section = load_topic_templates(SSE_PACKAGE)["customer_service_quality_management"]
    blocks = {block.id: block for block in _walk_blocks(section)}
    block = blocks["customer_service_quality_management.iro_service_feedback_improvement"]

    banned = block.generation.templateResidueBans or []
    # 模板原句整体是残留物；「仍存在一定改进空间」单独作为禁止串会误伤合法正文，
    # 故只登记整句（模板出处：客户服务质量管理指南「但在退换货政策和品牌宣传推广力度方面仍存在一定改进空间」）。
    assert "退换货政策和品牌宣传推广力度方面仍存在一定改进空间" in banned
    assert "仍存在一定改进空间" not in banned
    task_text = "\n".join(
        [block.generation.task.focus, *(block.generation.simplifiedWritingGuidance or [])]
    )
    assert "改进短板" not in task_text

    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_short_name": Field(key="company_short_name", label="公司简称", type="string", source="user_input", value="公司"),
            "industry": Field(key="industry", label="行业", type="string", source="user_input", value="制造业"),
        },
        sections=[],
    )
    ctx = empty_guardrail_context()
    issues = check_paragraph_output(
        block,
        report,
        ctx,
        "调研显示，公司在退换货政策和品牌宣传推广力度方面仍存在一定改进空间。",
    )

    assert "template_residue" in {issue.key for issue in issues}
