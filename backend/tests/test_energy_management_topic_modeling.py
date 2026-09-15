# ABOUTME: 能源管理单议题严谨建模测试，验证其不再是通用四题脚手架。
# ABOUTME: 取证依据为附录索引表第三十四至三十五条及参考模板“能源管理”章节结构。
from collections import Counter
from pathlib import Path

from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake, load_topic_templates
from topic_intake_assertions import expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def test_energy_management_section_reflects_reference_template_structure():
    section = load_topic_templates(SSE_PACKAGE)["energy_management"]
    blocks = {block.id: block for block in _walk_blocks(section)}

    assert set(blocks) == {
        "energy_management.gov_system_framework",
        "energy_management.strategy_risk_opportunity_preface",
        "energy_management.strategy_risk_opportunity_table",
        "energy_management.iro_efficiency_projects",
        "energy_management.metrics_summary",
        "energy_management.metrics_narrative_body",
        "energy_management.layout_assets",
    }
    assert blocks["energy_management.gov_system_framework"].content is None
    assert blocks["energy_management.iro_efficiency_projects"].content is None
    preface = blocks["energy_management.strategy_risk_opportunity_preface"]
    assert preface.blockType == "fixed"
    assert preface.source == "template"
    assert preface.generation is None
    assert "能源管理相关风险与机遇" in preface.content[0].text
    table = blocks["energy_management.strategy_risk_opportunity_table"]
    assert table.table is not None
    assert [col.header for col in table.table.colDefs] == [
        "风险与机遇类型",
        "风险与机遇名称",
        "潜在影响",
        "财务影响",
        "影响的时间范围",
        "应对措施",
    ]
    catalog_text = " ".join(item.reference for item in (table.generation.referenceCatalog or []))
    assert "客户" not in catalog_text
    assert "订单" not in catalog_text
    assert "供应商评价" not in catalog_text


def test_energy_management_does_not_reuse_same_intake_within_pillar():
    section = load_topic_templates(SSE_PACKAGE)["energy_management"]
    for pillar in section.children or []:
        intake_keys = []
        for block in pillar.blocks or []:
            if block.blockType not in {"generative", "constrained"} or block.generation is None:
                continue
            intake_keys.extend(block.generation.inputs.evidence.intakeItems or [])
        duplicates = {key for key, count in Counter(intake_keys).items() if count > 1}
        assert duplicates == set(), pillar.key


def test_energy_management_intake_collects_energy_specific_facts():
    items = [item for item in load_topic_intake(SSE_PACKAGE) if item.contentScopeId == "energy_management"]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("energy_management")
    assert any("制度名称" in (item.hint or "") for item in items)
    assert all("ESG 定量数据表" not in item.prompt for item in items)
    assert any("节能降耗" in item.prompt for item in items)
    assert any("清洁能源" in item.prompt for item in items)


ENERGY_REQUIREMENT_KEYS = [
    "energy_management.gov.responsibility_structure",
    "energy_management.gov.energy_management_system",
    "energy_management.gov.certifications",
    "energy_management.strategy.risk_opportunity",
    "energy_management.iro.product_service_efficiency",
    "energy_management.metrics.targets_progress",
    "energy_management.metrics.energy_use_basics",
    "energy_management.metrics.clean_energy_usage",
    "energy_management.metrics.energy_difficulty",
]


def test_energy_management_prompt_requirements_are_clause_specific():
    """required_only 过滤只留应披露项；条件适用项（如有、如涉及）仅在全量投影出现。"""
    required_only = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "energy_management", ENERGY_REQUIREMENT_KEYS, required_only=True
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "energy_management", ENERGY_REQUIREMENT_KEYS
    )

    required_text = "\n".join(item.standardDisclosureRequirementText for item in required_only)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "组织架构" in required_text
    assert "总能耗量" in required_text
    assert "清洁能源" in required_text
    assert "能源管理目标" in required_text
    # conditional 项（体系认证、产品服务案例、使用困难）不进 required_only 投影
    assert "ISO 50001" not in required_text
    assert "能源使用存在的具体困难" not in required_text
    assert "ISO 50001" in comprehensive_text
    assert "能源使用存在的具体困难" in comprehensive_text


def test_energy_management_strategy_table_remains_in_current_lightweight_schema():
    section = load_topic_templates(SSE_PACKAGE)["energy_management"]
    block_ids = {block.id for block in _walk_blocks(section)}

    assert "energy_management.strategy_risk_opportunity_table" in block_ids


def test_energy_management_does_not_auto_read_appendix_quantitative_data():
    section = load_topic_templates(SSE_PACKAGE)["energy_management"]
    blocks_by_id = {block.id: block for block in _walk_blocks(section)}
    energy_use = blocks_by_id["energy_management.metrics_narrative_body"]

    guidance = "\n".join(energy_use.generation.simplifiedWritingGuidance or [])
    assert energy_use.generation.inputs.evidence.quantitativeMetrics
    assert guidance == ""
    assert energy_use.generation.inputs.evidence.intakeItems == []
    assert set(energy_use.generation.inputs.evidence.quantitativeMetrics or []) == {
        "economic_environment_r11",
        "economic_environment_r17",
        "economic_environment_r19",
        "economic_environment_r22",
    }
    assert energy_use.content is None
    assert energy_use.generation.task.mode == "metric_narrative"
    assert "energy_management.metrics_no_data_note" not in blocks_by_id
    assert "energy_management.metrics_targets_progress" not in blocks_by_id

    requirements = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "energy_management",
        [
            "energy_management.metrics.energy_use_required",
            "energy_management.metrics.energy_use_encouraged",
        ],
    )
    requirement_text = "\n".join(item.standardDisclosureRequirementText for item in requirements)
    assert "ESG 定量数据表" not in requirement_text
