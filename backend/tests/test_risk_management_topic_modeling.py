# ABOUTME: 风险管理单议题建模测试，验证组织职责、制度遵循、风险流程和指标与目标。
# ABOUTME: 取证依据为参考模板“风险管理”章节结构与定量目录风险管理五项指标。
from pathlib import Path

from sustainability_desk.contract.models import Field, Report, Section
from sustainability_desk.llm.generation_guardrails import check_paragraph_output
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import load_topic_intake
from topic_intake_assertions import empty_guardrail_context, expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]

TEMPLATE_PLACEHOLDER_REDLINES = {
    "《》、《》",
    "代入制度名称",
    "若企业没有对应组织架构内容资料",
    "拟议段符合所有企业",
    "注意该段内容中的部门名称无需具化",
    "根据风险管理制度内容",
    "如果没有制度",
    "适用于任何企业",
    "不宜太过具象",
    "需适合所有企业情况",
    "资料：",
}


def _load_risk_management_section_only() -> Section:
    path = SSE_PACKAGE.topic_sections_dir / "risk_management.yaml"
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


def test_risk_management_section_reflects_reference_template_structure():
    section = _load_risk_management_section_only()
    blocks = {block.id: block for block in _walk_blocks(section)}

    assert section.title == "风险管理"
    assert {
        "risk_management.gov_structure_responsibilities",
        "risk_management.gov_policy_documents",
        "risk_management.strategy_integrated_risk_management",
        "risk_management.iro_process",
    }.issubset(blocks)
    assert "risk_management.metrics_targets" not in blocks
    assert "risk_management.metrics_narrative_body" in blocks


def test_risk_management_intake_collects_template_specific_facts():
    items = [item for item in load_topic_intake(SSE_PACKAGE) if item.contentScopeId == "risk_management"]
    keys = {item.key for item in items}

    assert keys == expected_sme_topic_intake_keys("risk_management")
    assert any("风险识别" in item.prompt for item in items)
    assert any("风险评估" in item.prompt for item in items)


def test_risk_management_reference_template_is_not_standard_disclosure_requirement():
    """风险管理目前只有参考模板内容，不作为准则披露要求默认资产。"""
    requirements = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "risk_management",
        [
            "risk_management.gov.policy_documents_required",
            "risk_management.gov.policy_documents_encouraged",
            "risk_management.iro.process_required",
            "risk_management.iro.process_encouraged",
        ],
    )

    assert requirements == []


def test_risk_management_metrics_pillar_is_backed_by_catalog_metrics():
    """指标与目标由定量目录风险管理五项承载，不设独立叙述块。"""
    section = _load_risk_management_section_only()
    blocks_by_id = {block.id: block for block in _walk_blocks(section)}
    assert "risk_management.metrics_targets" not in blocks_by_id
    metrics = next(child for child in section.children or [] if child.key.endswith(".metrics"))
    assert metrics.appears_when is None
    assert metrics.blocks[0].id == "risk_management.metrics_summary"
    narrative = blocks_by_id["risk_management.metrics_narrative_body"]
    assert set(narrative.generation.inputs.evidence.quantitativeMetrics or []) == {
        f"governance_r{i}" for i in range(19, 24)
    }
    assert "risk_management.metrics_no_data_note" not in blocks_by_id

    requirements = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "risk_management",
        ["risk_management.metrics.targets_required"],
    )
    assert requirements == []


def test_risk_management_blocks_enforce_reference_template_placeholder_redlines():
    section = _load_risk_management_section_only()
    blocks = [block for block in _walk_blocks(section) if block.generation]

    for block in blocks:
        # 指标叙述块只复述定量指标，红线属正文合同。
        if block.generation.task.mode == "metric_narrative":
            continue
        assert TEMPLATE_PLACEHOLDER_REDLINES <= set(block.generation.templateResidueBans or [])


def test_risk_management_l1_blocks_reference_template_placeholders():
    section = _load_risk_management_section_only()
    blocks_by_id = {block.id: block for block in _walk_blocks(section)}
    ctx = empty_guardrail_context()

    policy = blocks_by_id["risk_management.gov_policy_documents"]
    policy_issues = check_paragraph_output(
        policy,
        _minimal_report(),
        ctx,
        "企业结合自身经营与业务特征制定《》、《》（代入制度名称），按制度流程常态化开展风险识别与评估工作。",
    )
    assert "template_residue" in {issue.key for issue in policy_issues}

    process = blocks_by_id["risk_management.iro_process"]
    process_issues = check_paragraph_output(
        process,
        _minimal_report(),
        ctx,
        "如果没有制度，则按照风险识别、风险评估、风险应对、持续跟踪的风险管理框架形成适用于任何企业的内容。",
    )
    assert "template_residue" in {issue.key for issue in process_issues}
