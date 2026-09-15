# ABOUTME: 创新驱动单议题严谨建模测试，验证其按参考模板拆分研发战略、体系投入、技术产品和知识产权。
# ABOUTME: 取证依据为附录索引表第四十一条及参考模板“创新驱动”章节结构。
from sustainability_desk.planner import load_topic_templates
from pathlib import Path

from sustainability_desk.contract.models import Section
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake
from topic_intake_assertions import expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]



def _load_innovation_section_only() -> Section:
    path = SSE_PACKAGE.topic_sections_dir / "innovation_driven.yaml"
    return load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def _blocks_by_id(section):
    return {block.id: block for block in _walk_blocks(section)}


def test_innovation_driven_section_reflects_reference_template_structure():
    section = load_topic_templates(SSE_PACKAGE)["innovation_driven"]
    block_ids = {block.id for block in _walk_blocks(section)}

    assert section.title == "创新驱动"
    assert block_ids == {
        "innovation_driven.gov_rd_governance",
            "innovation_driven.strategy_rd_strategy_innovation_philosophy",
            "innovation_driven.iro_rd_team_management_incentives",
            "innovation_driven.iro_innovation_work_measures",
            "innovation_driven.metrics_summary",
            "innovation_driven.metrics_narrative_body",
            "innovation_driven.layout_assets",
        }
    assert "innovation_driven.metrics_no_data_note" not in block_ids
    assert "innovation_driven.iro_rd_system_resource_investment" not in block_ids
    assert "innovation_driven.iro_innovative_products_core_technologies" not in block_ids
    assert "innovation_driven.iro_smart_manufacturing_digital_transformation" not in block_ids
    assert "innovation_driven.iro_external_innovation_ecosystem" not in block_ids
    assert "innovation_driven.iro_ip_management_industry_recognition" not in block_ids


def test_innovation_driven_pillar_inputs_are_not_repeated_within_pillar():
    section = _load_innovation_section_only()

    for child in section.children or []:
        seen: dict[str, str] = {}
        for block in child.blocks:
            generation = block.generation
            if not generation or not generation.inputs:
                continue
            for intake_key in generation.inputs.evidence.intakeItems or []:
                assert intake_key not in seen, (
                    f"{child.key} repeats {intake_key} in {seen.get(intake_key)} and {block.id}"
                )
                seen[intake_key] = block.id


def test_innovation_driven_intake_collects_innovation_specific_facts():
    items = [item for item in load_topic_intake(SSE_PACKAGE) if item.contentScopeId == "innovation_driven"]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("innovation_driven")
    assert any("研发团队考核指标和激励方式" in item.prompt for item in items)
    assert any("研发投入" in item.prompt for item in items)
    assert any("数字化转型" in item.prompt for item in items)
    assert any("知识产权管理" in item.prompt for item in items)


def test_innovation_driven_prompt_requirements_are_clause_and_template_specific():
    lightweight = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "innovation_driven",
        [
            "innovation_driven.strategy.rd_strategy_required",
            "innovation_driven.strategy.science_ethics_encouraged",
            "innovation_driven.iro.products_technologies_required",
            "innovation_driven.iro.ip_recognition_required",
        ],
        required_only=True,
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "innovation_driven",
        [
            "innovation_driven.strategy.rd_strategy_required",
            "innovation_driven.strategy.science_ethics_encouraged",
            "innovation_driven.iro.products_technologies_required",
            "innovation_driven.iro.ip_recognition_required",
        ],
    )

    lightweight_text = "\n".join(item.standardDisclosureRequirementText for item in lightweight)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "创新驱动发展战略" in lightweight_text
    assert "创新产品" in lightweight_text
    assert "专利" in lightweight_text
    assert "科学伦理" not in lightweight_text
    assert "科学伦理" in comprehensive_text


def test_innovation_driven_iro_blocks_follow_lightweight_input_boundaries():
    section = _load_innovation_section_only()
    blocks = _blocks_by_id(section)
    team = blocks["innovation_driven.iro_rd_team_management_incentives"]
    measures = blocks["innovation_driven.iro_innovation_work_measures"]

    assert team.generation.inputs.evidence.intakeItems == ["innovation_driven.q_rd_team_incentives"]
    assert measures.generation.inputs.evidence.intakeItems == ["innovation_driven.q_innovation_work_measures"]
    assert team.generation.task.focus
    assert measures.generation.task.focus
    assert team.generation.simplifiedWritingGuidance is None
    assert measures.generation.simplifiedWritingGuidance is None
    assert measures.generation.task.noFactGuidance is None


def test_innovation_governance_without_content_uses_explicit_task_without_placeholder():
    section = _load_innovation_section_only()
    block = _blocks_by_id(section)["innovation_driven.gov_rd_governance"]
    content = "\n".join(item.text for item in block.content or [] if item.kind == "text")

    assert block.generation.task.noFactGuidance is None
    assert "成熟研发治理体系" not in block.generation.task.focus
    assert content == ""
    assert block.content is None


def test_innovation_driven_does_not_auto_read_appendix_quantitative_data():
    section = load_topic_templates(SSE_PACKAGE)["innovation_driven"]
    blocks_by_id = {block.id: block for block in _walk_blocks(section)}
    metrics = blocks_by_id["innovation_driven.metrics_narrative_body"]

    guidance = "\n".join(metrics.generation.simplifiedWritingGuidance or [])
    assert metrics.generation.inputs.evidence.quantitativeMetrics
    assert guidance == ""
    assert "innovation_driven.metrics_no_data_note" not in blocks_by_id

    requirements = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "innovation_driven",
        ["innovation_driven.metrics.innovation_metrics_required"],
    )
    requirement_text = "\n".join(item.standardDisclosureRequirementText for item in requirements)
    assert "ESG 定量数据表" not in requirement_text
