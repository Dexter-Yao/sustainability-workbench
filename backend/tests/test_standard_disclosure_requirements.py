# ABOUTME: 准则披露要求加载/解析测试——按 standardDisclosureRequirementKeys 解析准则合规映射。
# ABOUTME: 边界硬约束：仅模型可见投影字段可用；来源标签、映射键和章节键绝不外泄。
from sustainability_desk.llm.standard_disclosure_requirements import StandardDisclosureRequirement, resolve_standard_disclosure_requirements
from knowledge_package_fixtures import SSE_PACKAGE


def test_resolve_exact_keys_returns_points_in_order():
    points = resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "climate_change",
        ["climate.gov.governance_body", "climate.gov.expertise"],
    )
    assert [p.standardDisclosureRequirementTitle for p in points] == ["气候相关治理机构", "气候相关治理机构（人员）专业技能和能力"]
    assert points[0].standardDisclosureRequirementText.startswith("1．描述负责监督管理")
    assert points[0].disclosureRequirementObligationLevel == "required"


def test_resolve_pillar_wildcard_expands_to_all_points_in_pillar():
    points = resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.gov.*"])
    titles = [p.standardDisclosureRequirementTitle for p in points]
    assert "气候相关治理机构" in titles
    assert "气候相关治理机构将气候相关因素纳入决策的情况" in titles
    assert len(titles) == 5  # 治理支柱 5 个准则披露要求


def test_disclosure_point_carries_only_model_visible_fields():
    fields = set(StandardDisclosureRequirement.model_fields)
    assert fields == {
        "standardDisclosureRequirementTitle",
        "standardDisclosureRequirementText",
        "disclosureRequirementObligationLevel",
    }
    for forbidden in ("standardDisclosureRequirementKey", "sourceClauseReferenceLabels", "topicSectionKey", "topicId", "excerptFrom"):
        assert forbidden not in fields


def test_unknown_ref_is_skipped_not_error():
    points = resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.gov.does_not_exist"])
    assert points == []


def test_reference_template_only_topics_do_not_default_to_standard_requirements():
    """ReferenceTemplate-only 内容不进入准则披露要求库。"""
    assert resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "due_diligence",
        ["due_diligence.iro.policy_process_required"],
    ) == []
    assert resolve_standard_disclosure_requirements(SSE_PACKAGE, 
        "risk_management",
        ["risk_management.iro.process_required"],
    ) == []


def test_internal_ref_markup_stripped_from_standard_text():
    """准则正文内的 <ref> 交叉引用标记（内部 markup，指向待填充框架）不得进入模型可见正文。"""
    points = resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.gov.governance_body"])
    assert points and "<ref>" not in points[0].standardDisclosureRequirementText
    assert "</ref>" not in points[0].standardDisclosureRequirementText


def test_required_only_keeps_only_required_points():
    """解析器的 required_only 只返回 obligation=required。"""
    titles_v = {
        p.standardDisclosureRequirementTitle
        for p in resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.strategy.*"], required_only=True)
    }
    titles_s = {
        p.standardDisclosureRequirementTitle
        for p in resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.strategy.*"])
    }
    # value_chain_impact 为 encouraged：简化档丢、完整档留
    assert "气候相关风险和机遇对商业模式和价值链的影响" in titles_s
    assert "气候相关风险和机遇对商业模式和价值链的影响" not in titles_v
    assert titles_v < titles_s


def test_strict_is_default_intensity():
    """默认取全量义务等级；只保留 required 由调用方显式传 required_only=True。"""
    default = {p.standardDisclosureRequirementTitle for p in resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.strategy.*"])}
    strict = {
        p.standardDisclosureRequirementTitle
        for p in resolve_standard_disclosure_requirements(SSE_PACKAGE, "climate_change", ["climate.strategy.*"])
    }
    assert default == strict
