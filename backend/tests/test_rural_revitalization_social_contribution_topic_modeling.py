# ABOUTME: 乡村振兴与社会贡献合章严谨建模测试，验证两项评分议题共同映射为一个正文章节。
# ABOUTME: 取证依据为附录索引表第三十八至第四十条及参考模板“乡村振兴与社会贡献”章节结构。
from pathlib import Path
from collections import Counter

from sustainability_desk.contract.models import Field, Report, Section
from sustainability_desk.llm.generation_guardrails import check_paragraph_output
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake
from topic_intake_assertions import empty_guardrail_context, expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]

TEMPLATE_PLACEHOLDER_REDLINES = {
    "XX部门",
    "代入用户填写部门",
    # 「设立专职部门」是通用管理表述，不是模板残留物——「公司暂未设立专职部门」是合法正文。
    # 模板批注形态由「XX部门」「代入用户填写部门」拦住，无需再拦这半句。
    "根据资料生成",
    "资料：",
    "若无资料",
    "引用数据表",
    "对应议题指标",
    "数据表对应议题",
    "202X",
    "202X年",
    "XXX",
    "XXXX",
}


def _load_rural_social_section_only() -> Section:
    path = SSE_PACKAGE.topic_sections_dir / "rural_revitalization_social_contribution.yaml"
    return load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


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


def test_rural_social_section_uses_combined_appendix_title_and_reference_structure():
    section = _load_rural_social_section_only()
    block_ids = {block.id for block in _walk_blocks(section)}

    assert section.title == "乡村振兴与社会贡献"
    assert block_ids == {
            "rural_revitalization_social_contribution.gov_responsibility_department",
            "rural_revitalization_social_contribution.strategy_social_responsibility_strategy",
            "rural_revitalization_social_contribution.iro_rural_and_social_contribution_practices",
            "rural_revitalization_social_contribution.metrics_summary",
            "rural_revitalization_social_contribution.metrics_narrative_body",
            "rural_revitalization_social_contribution.layout_assets",
        }


def test_rural_social_intake_collects_two_assessment_topic_facts_without_splitting_section():
    items = [
        item
        for item in load_topic_intake(SSE_PACKAGE)
        if item.contentScopeId == "rural_revitalization_social_contribution"
    ]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("rural_revitalization_social_contribution")
    assert any("乡村地区" in item.prompt for item in items)
    assert any("公益慈善" in item.prompt for item in items)
    assert any("社会贡献行动" in item.prompt for item in items)


def test_rural_social_prompt_requirements_are_clause_specific():
    lightweight = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "rural_revitalization_social_contribution",
        [
            "rural_revitalization_social_contribution.gov.responsibility_department_required",
            "rural_revitalization_social_contribution.strategy.national_strategy_encouraged",
            "rural_revitalization_social_contribution.iro.rural_actions_required",
            "rural_revitalization_social_contribution.iro.social_contribution_required",
            "rural_revitalization_social_contribution.metrics.results_required",
        ],
        required_only=True,
    )
    comprehensive = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "rural_revitalization_social_contribution",
        [
            "rural_revitalization_social_contribution.gov.responsibility_department_required",
            "rural_revitalization_social_contribution.strategy.national_strategy_encouraged",
            "rural_revitalization_social_contribution.iro.rural_actions_required",
            "rural_revitalization_social_contribution.iro.social_contribution_required",
            "rural_revitalization_social_contribution.metrics.results_required",
        ],
    )

    lightweight_text = "\n".join(item.standardDisclosureRequirementText for item in lightweight)
    comprehensive_text = "\n".join(item.standardDisclosureRequirementText for item in comprehensive)
    assert "归口部门" in lightweight_text
    assert "乡村地区设施建设" in lightweight_text
    assert "社会捐赠" in lightweight_text
    assert "ESG 定量数据表" not in lightweight_text
    assert "五大振兴" not in lightweight_text
    assert "五大振兴" in comprehensive_text


def test_rural_social_generation_only_reads_topic_intake():
    section = _load_rural_social_section_only()
    for block in _walk_blocks(section):
        generation = block.generation
        if generation is None:
            continue

        assert set(generation.inputs.fields or []) <= {"company_short_name", "industry"}
        assert all(
            item.startswith("rural_revitalization_social_contribution.")
            for item in (generation.inputs.evidence.intakeItems or [])
        )

    metrics_block = next(block for block in _walk_blocks(section) if block.id == "rural_revitalization_social_contribution.metrics_narrative_body")
    metrics_posture = "\n".join(metrics_block.generation.simplifiedWritingGuidance or [])
    assert metrics_block.generation.inputs.evidence.quantitativeMetrics
    assert metrics_posture == ""


def test_rural_social_does_not_reuse_same_intake_within_pillar():
    section = _load_rural_social_section_only()

    for pillar in section.children or []:
        consumed: list[str] = []
        for block in _walk_blocks(pillar):
            generation = block.generation
            if generation and generation.inputs:
                consumed.extend(generation.inputs.evidence.intakeItems or [])
        repeated = [key for key, count in Counter(consumed).items() if count > 1]

        assert repeated == [], f"{pillar.key} repeats intake inputs: {repeated}"


def test_rural_social_lightweight_guidance_matches_block_scope():
    section = _load_rural_social_section_only()
    blocks = {block.id: block for block in _walk_blocks(section)}

    for block_id in {
        "rural_revitalization_social_contribution.gov_responsibility_department",
        "rural_revitalization_social_contribution.strategy_social_responsibility_strategy",
        "rural_revitalization_social_contribution.iro_rural_and_social_contribution_practices",
    }:
        guidance = "\n".join(blocks[block_id].generation.simplifiedWritingGuidance or [])
        assert "指标段" not in guidance
        assert "报告期数值" not in guidance

    metrics_guidance = "\n".join(
        blocks["rural_revitalization_social_contribution.metrics_narrative_body"].generation.simplifiedWritingGuidance or []
    )
    assert metrics_guidance == ""
    assert blocks[
        "rural_revitalization_social_contribution.metrics_narrative_body"
    ].generation.inputs.evidence.quantitativeMetrics


def test_rural_social_blocks_enforce_reference_template_placeholder_redlines():
    section = _load_rural_social_section_only()
    blocks = [block for block in _walk_blocks(section) if block.generation]

    for block in blocks:
        if block.generation.task.mode == "metric_narrative":
            continue
        assert TEMPLATE_PLACEHOLDER_REDLINES <= set(block.generation.templateResidueBans or [])


def test_rural_social_l1_blocks_reference_template_placeholders():
    section = _load_rural_social_section_only()
    blocks = {block.id: block for block in _walk_blocks(section)}
    ctx = empty_guardrail_context()

    governance = blocks["rural_revitalization_social_contribution.gov_responsibility_department"]
    governance_issues = check_paragraph_output(
        governance,
        _minimal_report(),
        ctx,
        "公司由XX部门（代入用户填写部门，如未填写部门，则默认显示“设立专职部门”）统一归口负责相关工作。",
    )
    assert "template_residue" in {issue.key for issue in governance_issues}

    metrics = blocks["rural_revitalization_social_contribution.metrics_narrative_body"]
    metrics_issues = check_paragraph_output(
        metrics,
        _minimal_report(),
        ctx,
        "202X年，公司引用数据表对应议题指标，披露乡村振兴与社会贡献工作成效。",
    )
    assert "unsupported_numeric_claim" in {issue.key for issue in metrics_issues}
