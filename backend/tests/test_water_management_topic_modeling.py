# ABOUTME: 水资源管理单议题严谨建模测试，验证其不再是通用四题脚手架。
# ABOUTME: 取证依据为附录索引表第三十四至三十六条及参考模板“水资源管理”章节结构。
from collections import Counter
from pathlib import Path

from sustainability_desk.contract.models import Field, Report, Section
from sustainability_desk.llm.generation_guardrails import check_paragraph_output
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake
from topic_intake_assertions import empty_guardrail_context, expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]


def _load_water_section_only() -> Section:
    path = SSE_PACKAGE.topic_sections_dir / "water_resource_management.yaml"
    return load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def test_water_management_section_reflects_reference_template_structure():
    section = _load_water_section_only()
    block_ids = {block.id for block in _walk_blocks(section)}

    assert block_ids == {
            "water_resource_management.gov_management_framework",
            "water_resource_management.strategy_water_strategy",
            "water_resource_management.iro_water_saving_actions",
            "water_resource_management.metrics_summary",
            "water_resource_management.metrics_narrative_body",
            "water_resource_management.layout_assets",
        }


def test_water_management_intake_collects_water_specific_facts():
    items = [item for item in load_topic_intake(SSE_PACKAGE) if item.contentScopeId == "water_resource_management"]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("water_resource_management")
    assert all("ESG 定量数据表" not in item.prompt for item in items)
    assert any("水资源" in item.prompt and "战略方向" in item.prompt for item in items)
    assert any("节水" in item.prompt for item in items)
    assert any("循环用水" in item.prompt for item in items)


def test_water_management_does_not_read_appendix_quantitative_data():
    section = _load_water_section_only()
    blocks_by_id = {block.id: block for block in _walk_blocks(section)}

    for block in _walk_blocks(section):
        generation = block.generation
        if not generation or not generation.inputs:
            continue
        assert getattr(generation.inputs, "materials", None) in (None, [])
        assert set(generation.inputs.fields or []) <= {"company_short_name", "industry"}
        assert all(
            key.startswith("water_resource_management.")
            for key in (generation.inputs.evidence.intakeItems or [])
        )

    assert "water_resource_management.metrics_no_data_note" not in blocks_by_id


def test_water_management_does_not_reuse_same_intake_within_pillar():
    section = _load_water_section_only()

    for child in section.children or []:
        intake_keys: list[str] = []
        for block in _walk_blocks(child):
            generation = block.generation
            if not generation or not generation.inputs:
                continue
            intake_keys.extend(generation.inputs.evidence.intakeItems or [])
        repeated = [key for key, count in Counter(intake_keys).items() if count > 1]
        assert repeated == []


def test_water_management_metrics_block_rejects_reference_template_placeholder_year():
    section = _load_water_section_only()
    blocks = {block.id: block for block in _walk_blocks(section)}
    block = blocks["water_resource_management.metrics_narrative_body"]
    assert block.generation.task.mode == "metric_narrative"
    assert block.content is None
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_short_name": Field(
                key="company_short_name",
                label="公司简称",
                type="string",
                source="user_input",
                value="公司",
            ),
            "industry": Field(
                key="industry",
                label="行业",
                type="string",
                source="user_input",
                value="制造业",
            ),
        },
        sections=[],
    )
    ctx = empty_guardrail_context()
    issues = check_paragraph_output(
        block,
        report,
        ctx,
        "202X 年，公司启动水资源管理量化指标体系搭建工作。",
    )

    assert "unsupported_numeric_claim" in {issue.key for issue in issues}


WATER_REQUIREMENT_KEYS = [
    "water_resource_management.gov.responsibility_structure",
    "water_resource_management.gov.management_system",
    "water_resource_management.gov.policy_documents",
    "water_resource_management.strategy.saving_strategy",
    "water_resource_management.strategy.water_risk",
    "water_resource_management.iro.site_water_assessment",
    "water_resource_management.metrics.total_water_consumption",
    "water_resource_management.metrics.water_use_intensity",
    "water_resource_management.metrics.water_difficulty",
]


def test_water_management_prompt_requirements_are_clause_specific():
    """required_only 过滤只留应披露项；条件适用项（如涉及、如有）仅在全量投影出现。"""
    required_only = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "water_resource_management", WATER_REQUIREMENT_KEYS, required_only=True
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "water_resource_management", WATER_REQUIREMENT_KEYS
    )

    required_text = "\n".join(item.standardDisclosureRequirementText for item in required_only)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "组织架构" in required_text
    assert "用水管理统计核算制度" in required_text
    assert "总耗水量" in required_text
    assert "水资源使用强度" in required_text
    # conditional 项（制度文件、风险评估、场所评估、使用困难）不进 required_only 投影
    assert "水资源使用存在的具体困难" not in required_text
    assert "水资源使用存在的具体困难" in comprehensive_text
    assert "评估目标" in comprehensive_text


