# ABOUTME: 污染物排放管理单议题严谨建模测试，验证其不再是通用四题脚手架。
# ABOUTME: 取证依据为附录索引表第二十九、第三十、第三十三条及参考模板“污染物排放管理”章节结构。
from pathlib import Path

from sustainability_desk.contract.models import Field, IntakeItem, Report, Section
from sustainability_desk.contract.visibility import visible_block_in_report
from sustainability_desk.llm.generation_guardrails import check_paragraph_output
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake
from topic_intake_assertions import empty_guardrail_context, expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]



def _guidance(item) -> str:
    """说明文本按 design.md §2.2.1 分两段承载；断言口径覆盖两段，不锁定它落在哪一段。"""

    return f"{item.hint or ''}{item.termExplanation or ''}"

def _load_pollutant_section_only() -> Section:
    path = SSE_PACKAGE.topic_sections_dir / "pollutant_emissions_management.yaml"
    return load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def _blocks_by_id(section):
    return {block.id: block for block in _walk_blocks(section)}


def _minimal_report() -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
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


def test_pollutant_emissions_management_section_reflects_reference_template_structure():
    section = _load_pollutant_section_only()
    block_ids = {block.id for block in _walk_blocks(section)}

    assert block_ids == {
        "pollutant_emissions_management.gov_responsibility_structure",
            "pollutant_emissions_management.strategy_risk_opportunity_preface",
            "pollutant_emissions_management.strategy_risk_opportunity_table",
            "pollutant_emissions_management.iro_annual_discharge_treatment",
            "pollutant_emissions_management.iro_policy_practice",
            "pollutant_emissions_management.iro_reduction_measures_results",
            "pollutant_emissions_management.metrics_summary",
            "pollutant_emissions_management.metrics_narrative_body",
            "pollutant_emissions_management.layout_assets",
        }
    preface = next(
        block
        for block in _walk_blocks(section)
        if block.id == "pollutant_emissions_management.strategy_risk_opportunity_preface"
    )
    assert preface.blockType == "fixed"
    assert preface.source == "template"
    assert preface.generation is None
    assert "污染物排放相关风险与机遇" in preface.content[0].text
    table = next(block for block in _walk_blocks(section) if block.id == "pollutant_emissions_management.strategy_risk_opportunity_table")
    assert table.table is not None
    assert [col.header for col in table.table.colDefs] == [
        "风险与机遇类型",
        "风险与机遇名称",
        "潜在影响",
        "财务影响",
        "影响的时间范围",
        "应对措施",
    ]


def test_pollutant_emissions_management_pillar_inputs_are_not_repeated_within_pillar():
    section = _load_pollutant_section_only()

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


def test_pollutant_emissions_management_intake_collects_pollution_specific_facts():
    items = [
        item
        for item in load_topic_intake(SSE_PACKAGE)
        if item.contentScopeId == "pollutant_emissions_management"
    ]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("pollutant_emissions_management")
    assert any("排污许可" in _guidance(item) for item in items)
    assert any("大气污染物" in _guidance(item) for item in items)
    assert any("污染物减排" in item.prompt for item in items)


POLLUTANT_REQUIREMENT_KEYS = [
    "pollutant_emissions_management.gov.responsibility_structure",
    "pollutant_emissions_management.gov.pollution_control_system",
    "pollutant_emissions_management.gov.accounting_scope",
    "pollutant_emissions_management.gov.disclosure_permit_compliance",
    "pollutant_emissions_management.strategy.risk_opportunity",
    "pollutant_emissions_management.strategy.reduction_target",
    "pollutant_emissions_management.iro.treatment_and_facilities",
    "pollutant_emissions_management.iro.reduction_measures_and_effect",
    "pollutant_emissions_management.metrics.discharge_information",
    "pollutant_emissions_management.metrics.discharge_intensity_and_classification",
    "pollutant_emissions_management.metrics.environmental_compliance",
]


def test_pollutant_emissions_management_prompt_requirements_are_clause_specific():
    """required_only 过滤只留应披露项；条件适用与鼓励项仅在全量投影出现。"""
    required_only = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "pollutant_emissions_management", POLLUTANT_REQUIREMENT_KEYS, required_only=True
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "pollutant_emissions_management", POLLUTANT_REQUIREMENT_KEYS
    )

    required_text = "\n".join(item.standardDisclosureRequirementText for item in required_only)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "组织架构" in required_text
    assert "排放总量" in required_text
    assert "超标排放" in required_text
    assert "噪声" in required_text
    assert "减排类型" in required_text
    assert "重大行政处罚" in required_text
    # conditional（依法披露环境信息企业口径）与 encouraged（排放强度、分类披露）不进 required_only 投影
    assert "纳入重点排污单位管理" not in required_text
    assert "鼓励按照业务单位" not in required_text
    assert "纳入重点排污单位管理" in comprehensive_text
    assert "鼓励按照业务单位" in comprehensive_text
    assert "重大行政处罚" in comprehensive_text


def test_pollutant_emissions_management_generation_only_reads_topic_intake():
    section = _load_pollutant_section_only()
    for block in _walk_blocks(section):
        generation = block.generation
        if generation is None:
            continue

        assert set(generation.inputs.fields or []) <= {"company_short_name", "industry"}
        assert all(
            item.startswith("pollutant_emissions_management.")
            for item in (generation.inputs.evidence.intakeItems or [])
        )

    metrics_block = _blocks_by_id(section)["pollutant_emissions_management.metrics_narrative_body"]
    metrics_posture = "\n".join(metrics_block.generation.simplifiedWritingGuidance or [])
    assert metrics_block.generation.inputs.evidence.quantitativeMetrics
    assert metrics_posture == ""


def test_pollutant_disclosure_permit_block_requires_applicability_and_details():
    section = _load_pollutant_section_only()

    not_applicable_report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[section],
        intakeItems=[
            IntakeItem(
                key="pollutant_emissions_management.q_emission_management_requirements",
                contentScopeId="pollutant_emissions_management",
                prompt="p",
                kind="single_select",
                options=["是", "否", "不确定"],
                answer="否",
            )
        ],
    )
    applicable_report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[section],
        intakeItems=[
            IntakeItem(
                key="pollutant_emissions_management.q_emission_management_requirements",
                contentScopeId="pollutant_emissions_management",
                prompt="p",
                kind="single_select",
                options=["是", "否", "不确定"],
                answer="是",
                supplement="公司持有排污许可证，主要污染物为废水 COD、氨氮及废气 VOC，报告期内未发生超标排放处罚。",
            ),
        ],
    )

    block_id = "pollutant_emissions_management.iro_annual_discharge_treatment"
    assert not visible_block_in_report(not_applicable_report, block_id)
    assert visible_block_in_report(applicable_report, block_id)


def test_pollutant_reduction_block_requires_confirmed_reduction_measures():
    section = _load_pollutant_section_only()
    block = _blocks_by_id(section)["pollutant_emissions_management.iro_reduction_measures_results"]

    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[section],
        intakeItems=[
            IntakeItem(
                key="pollutant_emissions_management.q_reduction_measures",
                contentScopeId="pollutant_emissions_management",
                prompt="p",
                kind="single_select",
                options=["是", "否", "不确定"],
                answer="否",
            )
        ],
    )

    assert not visible_block_in_report(report, block.id)
    report.intakeItems[0].answer = "是"
    assert visible_block_in_report(report, block.id)


def test_pollutant_emissions_blocks_reject_reference_template_placeholders():
    section = _load_pollutant_section_only()
    blocks = _blocks_by_id(section)
    ctx = empty_guardrail_context()

    policy_block = blocks["pollutant_emissions_management.gov_responsibility_structure"]
    assert "XXXX" in (policy_block.generation.templateResidueBans or [])
    policy_issues = check_paragraph_output(
        policy_block,
        _minimal_report(),
        ctx,
        "公司制定《》、《》（代入上传制度名称），为实现XXXX提供保障。",
    )
    assert "template_residue" in {issue.key for issue in policy_issues}

    metrics_block = blocks["pollutant_emissions_management.metrics_narrative_body"]
    assert metrics_block.generation.task.mode == "metric_narrative"
    assert metrics_block.content is None
    metrics_issues = check_paragraph_output(
        metrics_block,
        _minimal_report(),
        ctx,
        "202X 年，公司启动污染物排放管理与污染物减排指标体系建设工作。",
    )
    assert "unsupported_numeric_claim" in {issue.key for issue in metrics_issues}
