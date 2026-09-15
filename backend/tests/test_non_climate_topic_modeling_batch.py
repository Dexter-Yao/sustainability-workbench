# ABOUTME: 非气候议题基础建模批次测试，锁定纳入/排除边界与 SSOT 链路。
# ABOUTME: 本测试验证章节、内容清单、准则披露要求与用户可见批注相互独立，不把待确认议题误纳入。
from pathlib import Path

import yaml

from sustainability_desk.api.app import plan_report
from sustainability_desk.contract.models import (
    DisclosureProfile,
    Field,
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
    Report,
)
from sustainability_desk.contract.topic_registry import (
    all_report_sections,
    applicable_scoring_topics,


    resolve_topic,
    section_prefix_of,
)
from sustainability_desk.contract.user_visible_disclosure_clause_annotations import (
    find_user_visible_disclosure_clause_annotation_entry,
)
from sustainability_desk.contract.visibility import visible
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.planner import assemble_report, load_topic_intake, load_topic_templates
from assessment_fixtures import complete_assessment
from knowledge_package_fixtures import SSE_DATA, SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract

BACKEND = Path(__file__).resolve().parents[1]

INCLUDED_TOPICS = {
    "energy_management": "能源管理",
    "water_resource_management": "水资源管理",
    "waste_management": "废弃物管理",
    "pollutant_emissions_management": "污染物排放管理",
    "ecosystem_biodiversity_protection": "生态系统与生物多样性保护",
    "environmental_compliance_management": "环境合规管理",
    "circular_economy_promotion": "促进循环经济",
    "human_capital_development": "人力资本发展",
    "occupational_health_safety": "职业健康与安全",
    "rural_revitalization_social_contribution": "乡村振兴与社会贡献",
    "customer_service_quality_management": "客户服务质量管理",
    "sustainable_supply_chain_management": "可持续供应链管理",
    "sme_fair_treatment": "平等对待中小企业",
    "innovation_driven": "创新驱动",
    "product_quality_safety": "产品质量与安全",
    "data_security_customer_privacy_protection": "数据安全与客户隐私保护",
    "anti_bribery_anti_corruption": "反商业贿赂与反贪污",
    "anti_unfair_competition": "反不正当竞争",
    "due_diligence": "尽职调查",
}

COMBINED_SECTION_ASSESSMENT_TITLES = {
    "rural_revitalization_social_contribution": ("乡村振兴", "社会贡献"),
}

GENERIC_SCAFFOLD_TOPICS = {}

# 风险管理恒为适用评分议题并进入正文；
# 与 INCLUDED_TOPICS 唯一的差别是其用户可见准则批注尚未收录
# （data/user_visible_disclosure_clause_annotations/ 无 risk_management 条目），
# 故批注断言暂不覆盖它。
INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS = {
    "risk_management": "风险管理",
}

CONDITIONAL_TOPICS = {
    "technology_ethics": "科技伦理",
}

EMBEDDED_ASSESSMENT_TOPICS = {
    "stakeholder_communication": "利益相关方沟通",
}

EXCLUDED_PENDING_TOPICS = set()

CONDITIONAL_NARRATIVE_METRICS_TOPICS = {
    "circular_economy_promotion",
    "due_diligence",
    "ecosystem_biodiversity_protection",
    "environmental_compliance_management",
    "sme_fair_treatment",
    "technology_ethics",
}

SPECIALIZED_DISCLOSURE_REFS = {
    # 能源与水资源按指南第四、五号重锚定后，披露要点只有「应当」与「如有」两级，无 encouraged 条目。
    "energy_management": [
        "energy_management.gov.energy_management_system",
        "energy_management.gov.certifications",
    ],
    "water_resource_management": [
        "water_resource_management.gov.management_system",
        "water_resource_management.gov.policy_documents",
    ],
    "waste_management": [
        "waste_management.gov.waste_management_required",
        "waste_management.gov.waste_management_encouraged",
    ],
    "pollutant_emissions_management": [
        "pollutant_emissions_management.gov.pollution_control_system",
        "pollutant_emissions_management.metrics.discharge_intensity_and_classification",
    ],
    "ecosystem_biodiversity_protection": [
        "ecosystem_biodiversity_protection.gov.ecological_governance_required",
        "ecosystem_biodiversity_protection.gov.ecological_governance_encouraged",
    ],
    "environmental_compliance_management": [
        "environmental_compliance_management.gov.management_system_required",
        "environmental_compliance_management.gov.management_system_encouraged",
    ],
    "circular_economy_promotion": [
        "circular_economy_promotion.gov.framework_required",
        "circular_economy_promotion.gov.framework_encouraged",
    ],
    "human_capital_development": [
        "human_capital_development.gov.labor_rights_required",
        "human_capital_development.gov.labor_rights_encouraged",
    ],
    "occupational_health_safety": [
        "occupational_health_safety.gov.organization_responsibilities_required",
        "occupational_health_safety.gov.iso45001_encouraged",
    ],
    "rural_revitalization_social_contribution": [
        "rural_revitalization_social_contribution.gov.responsibility_department_required",
        "rural_revitalization_social_contribution.strategy.national_strategy_encouraged",
    ],
    "customer_service_quality_management": [
        "customer_service_quality_management.gov.service_management_required",
        "customer_service_quality_management.gov.service_management_encouraged",
    ],
    "sustainable_supply_chain_management": [
        "sustainable_supply_chain_management.gov.governance_structure_required",
        "sustainable_supply_chain_management.iro.supplier_training_encouraged",
    ],
    "sme_fair_treatment": [
        "sme_fair_treatment.gov.fair_cooperation_required",
        "sme_fair_treatment.gov.fair_cooperation_encouraged",
    ],
    "innovation_driven": [
        "innovation_driven.strategy.rd_strategy_required",
        "innovation_driven.strategy.science_ethics_encouraged",
    ],
    "product_quality_safety": [
        "product_quality_safety.gov.quality_system_required",
        "product_quality_safety.strategy.quality_strategy_encouraged",
    ],
    "data_security_customer_privacy_protection": [
        "data_security_customer_privacy_protection.gov.security_management_system_required",
        "data_security_customer_privacy_protection.gov.security_certification_encouraged",
    ],
    "anti_bribery_anti_corruption": [
        "anti_bribery_anti_corruption.gov.policy_system_required",
        "anti_bribery_anti_corruption.gov.certification_encouraged",
    ],
    "anti_unfair_competition": [
        "anti_unfair_competition.gov.policy_system_required",
        "anti_unfair_competition.gov.policy_system_encouraged",
    ],
    "risk_management": [
        "risk_management.gov.policy_documents_required",
        "risk_management.gov.policy_documents_encouraged",
    ],
    "due_diligence": [
        "due_diligence.strategy.materiality_risk_classification_required",
        "due_diligence.strategy.materiality_risk_classification_encouraged",
    ],
}

METRIC_TOPIC_IDS = {
    "energy_management",
    "water_resource_management",
    "waste_management",
    "pollutant_emissions_management",
    "ecosystem_biodiversity_protection",
    "environmental_compliance_management",
    "circular_economy_promotion",
    "human_capital_development",
    "occupational_health_safety",
    "rural_revitalization_social_contribution",
    "customer_service_quality_management",
    "sustainable_supply_chain_management",
    "sme_fair_treatment",
    "innovation_driven",
    "product_quality_safety",
    "data_security_customer_privacy_protection",
    "anti_bribery_anti_corruption",
    "anti_unfair_competition",
    "risk_management",
    "due_diligence",
}

SIMPLIFIED_QUANTITATIVE_METRIC_KEYS = {
    "energy_management": {
        "economic_environment_r11",
        "economic_environment_r17",
        "economic_environment_r19",
        "economic_environment_r22",
    },
    "water_resource_management": {
        "economic_environment_r42",
        "economic_environment_r43",
        "economic_environment_r44",
        "economic_environment_r45",
        "economic_environment_r46",
    },
    "waste_management": {
        "economic_environment_r38",
        "economic_environment_r39",
        "economic_environment_r40",
        "economic_environment_r41",
    },
    "pollutant_emissions_management": {f"economic_environment_r{i}" for i in range(25, 38)},
    "human_capital_development": {
        "social_r02",
        "social_r03",
        "social_r04",
        "social_r10",
        "social_r11",
        "social_r12",
        "social_r13",
        "social_r17",
        "social_r25",
        "social_r26",
    },
    "occupational_health_safety": {"social_r41", "social_r43", "social_r44", "social_r45", "social_r46", "social_r48"},
    "rural_revitalization_social_contribution": {"social_r81", "social_r83"},
    "customer_service_quality_management": {"social_r55", "social_r56"},
    "sustainable_supply_chain_management": {"social_r64", "social_r65", "social_r66", "social_r67", "social_r69"},
    "innovation_driven": {"social_r74", "social_r76", "social_r77", "social_r79"},
    "product_quality_safety": {"social_r53", "social_r54"},
    "data_security_customer_privacy_protection": {"social_r59", "social_r60", "social_r63"},
    "anti_bribery_anti_corruption": {"governance_r06", "governance_r07"},
    "anti_unfair_competition": {"governance_r17", "governance_r18"},
    "risk_management": {f"governance_r{i}" for i in range(19, 24)},
}

INTERNAL_PROMPT_TEXT_SENTINELS = {
    "本轮",
    "TODO",
    "后续需",
    "链路承载",
}


def _has_topic_section(sections, topic_id: str) -> bool:
    for section in sections:
        if section.reportSectionId == topic_id:
            return True
        if _has_topic_section(section.children or [], topic_id):
            return True
    return False


def _walk_blocks(section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def _condition_ops_for_path(section, path: str) -> set[str]:
    ops: set[str] = set()
    for block in _walk_blocks(section):
        cond = block.appears_when
        if cond is None:
            continue
        for rule in list(cond.all or []) + list(cond.any or []):
            if rule.path == path:
                ops.add(rule.op)
    return ops


def _topic_modeling_text(topic_id: str) -> str:
    parts = []
    for folder in ("topic_intake", "topic_sections", "standard_disclosure_requirements"):
        path = SSE_DATA / folder / f"{topic_id}.yaml"
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _report_for_topic(topic_id: str, title: str) -> Report:
    resolve_title = COMBINED_SECTION_ASSESSMENT_TITLES.get(topic_id, (title,))[0]
    ref = resolve_topic(SSE_PACKAGE, resolve_title)
    assert ref is not None
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "has_technology_ethics_sensitive_activity": Field(
                key="has_technology_ethics_sensitive_activity",
                label="科技伦理适用性",
                type="enum",
                source="user_input",
                value="否",
                options=["是", "否"],
            )
        },
        disclosureProfile=DisclosureProfile(),
        sections=[],
    )
    report.assessmentInput = MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=[
            MaterialityScoreInput(
                assessmentTopicId=topic_ref.id,
                financialScore=5.0,
                impactScore=5.0,
            )
            for topic_ref in applicable_scoring_topics(report, package=SSE_PACKAGE)
        ],
    )
    assessment = complete_assessment(report)
    topic_ids = {topic.assessmentTopicId for topic in assessment.topics}
    if topic_id in COMBINED_SECTION_ASSESSMENT_TITLES:
        assert all(
            resolve_topic(SSE_PACKAGE, title).id in topic_ids
            for title in COMBINED_SECTION_ASSESSMENT_TITLES[topic_id]
        )
    else:
        assert topic_id in topic_ids
    report.assessment = assessment
    return report


def _assemble_report_for_topic(topic_id: str, title: str):
    contract = load_package_contract(SSE_PACKAGE)
    report = _report_for_topic(topic_id, title)
    contract.fields["has_technology_ethics_sensitive_activity"] = report.fields[
        "has_technology_ethics_sensitive_activity"
    ].model_copy(deep=True)
    contract.assessment = report.assessment
    return assemble_report(
        contract,
        load_topic_templates(SSE_PACKAGE),
        assessment=report.assessment,
        intake_items=load_topic_intake(SSE_PACKAGE),
    )


def _expected_intake_keys(topic_id: str) -> set[str]:
    prefix = section_prefix_of(SSE_PACKAGE, topic_id)
    fixed = {
        f"{prefix}.q_governance_roles",
        f"{prefix}.q_governance_policies",
        f"{prefix}.q_governance_certifications",
        f"{prefix}.q_strategy_content",
    }
    raw = yaml.safe_load((SSE_PACKAGE.topic_intake_dir / f"{topic_id}.yaml").read_text(encoding="utf-8"))
    return fixed | {item["key"] for item in raw.get("items", []) or []}


def _disclosure_refs_for_filter_test(topic_id: str) -> list[str]:
    if topic_id in SPECIALIZED_DISCLOSURE_REFS:
        return SPECIALIZED_DISCLOSURE_REFS[topic_id]
    return [f"{topic_id}.gov.management_required", f"{topic_id}.gov.management_encouraged"]


def test_included_topic_names_follow_appendix_index():
    for topic_id, title in INCLUDED_TOPICS.items():
        if topic_id in COMBINED_SECTION_ASSESSMENT_TITLES:
            for assessment_title in COMBINED_SECTION_ASSESSMENT_TITLES[topic_id]:
                ref = resolve_topic(SSE_PACKAGE, assessment_title)
                assert ref is not None
                assert ref.reportSectionId == topic_id
                assert ref.name == assessment_title
                assert ref.name == assessment_title
            continue

        ref = resolve_topic(SSE_PACKAGE, title)
        assert ref is not None
        assert ref.id == topic_id
        assert ref.name == title
        assert ref.name == title


def test_included_topics_have_section_intake_and_prompt_requirements():
    templates = load_topic_templates(SSE_PACKAGE)
    intake_items = load_topic_intake(SSE_PACKAGE)
    intake_by_topic = {}
    for item in intake_items:
        intake_by_topic.setdefault(item.contentScopeId, set()).add(item.key)

    for topic_id, title in INCLUDED_TOPICS.items():
        assert topic_id in templates
        assert templates[topic_id].title == title
        assert templates[topic_id].children
        assert intake_by_topic.get(topic_id) == _expected_intake_keys(topic_id)
        assert (SSE_PACKAGE.standard_disclosure_requirements_dir / f"{topic_id}.yaml").exists()


def test_modeled_topic_templates_define_only_contractual_metrics_pillars():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in INCLUDED_TOPICS | INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS | CONDITIONAL_TOPICS:
        section = templates[topic_id]
        expected_keys = [
            f"{topic_id}.gov",
            f"{topic_id}.strategy",
            f"{topic_id}.iro",
        ]
        expected_titles = [
            "治理",
            "战略",
            "影响、风险与机遇管理",
        ]
        if topic_id in SIMPLIFIED_QUANTITATIVE_METRIC_KEYS or topic_id in CONDITIONAL_NARRATIVE_METRICS_TOPICS:
            expected_keys.append(f"{topic_id}.metrics")
            expected_titles.append("指标与目标")
        assert [child.key for child in section.children or []] == expected_keys
        assert [child.title for child in section.children or []] == expected_titles


def test_topics_without_catalog_metrics_compile_one_dynamic_metric_narrative():
    templates = load_topic_templates(SSE_PACKAGE)

    assert (METRIC_TOPIC_IDS - set(SIMPLIFIED_QUANTITATIVE_METRIC_KEYS)) | {
        "technology_ethics"
    } == CONDITIONAL_NARRATIVE_METRICS_TOPICS
    for topic_id in CONDITIONAL_NARRATIVE_METRICS_TOPICS:
        section = templates[topic_id]
        metrics = next(child for child in section.children or [] if child.key == f"{topic_id}.metrics")
        assert metrics.appears_when is None
        assert metrics.children in (None, [])
        assert len(metrics.blocks) == 2
        assert metrics.blocks[1].id == f"{topic_id}.layout_assets"
        block = metrics.blocks[0]
        assert block.id == f"{topic_id}.metrics_narrative_body"
        assert block.appears_when is None
        assert block.generation is not None
        assert block.generation.task.mode == "metric_narrative"
        assert block.generation.inputs.evidence.quantitativeMetrics in (None, [])
        requirement_text = (SSE_PACKAGE.standard_disclosure_requirements_dir / f"{topic_id}.yaml").read_text(encoding="utf-8")
        assert f"topicSectionKey: {topic_id}.metrics" not in requirement_text


def test_metric_h3_materiality_is_owned_by_planner_not_source_visibility():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in CONDITIONAL_NARRATIVE_METRICS_TOPICS:
        metrics = next(
            child
            for child in templates[topic_id].children or []
            if child.key == f"{topic_id}.metrics"
        )
        assert metrics.appears_when is None
        assert visible(metrics, Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[templates[topic_id]]))


def test_config_excluded_topics_do_not_have_intake_or_prompt_requirements():
    intake_topics = {item.contentScopeId for item in load_topic_intake(SSE_PACKAGE)}
    for topic_id in EXCLUDED_PENDING_TOPICS:
        assert topic_id not in intake_topics
        assert not (SSE_PACKAGE.standard_disclosure_requirements_dir / f"{topic_id}.yaml").exists()


def test_risk_management_is_always_planned_into_report_body():
    """双档移除后风险管理恒为适用评分议题：建模齐备，且任何完整评分的
    报告（含非以它为主角的规划）都装配其章节、内容清单与纳入诊断。"""
    templates = load_topic_templates(SSE_PACKAGE)
    intake_items = load_topic_intake(SSE_PACKAGE)
    intake_by_topic = {}
    for item in intake_items:
        intake_by_topic.setdefault(item.contentScopeId, set()).add(item.key)

    for topic_id, title in INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS.items():
        assert topic_id in templates
        assert templates[topic_id].title == title
        assert templates[topic_id].children
        assert intake_by_topic.get(topic_id) == _expected_intake_keys(topic_id)
        assert (SSE_PACKAGE.standard_disclosure_requirements_dir / f"{topic_id}.yaml").exists()

        planned = plan_report(_report_for_topic("climate_change", "应对气候变化"), package=SSE_PACKAGE)
        planned_report = planned["report"]
        assert _has_topic_section(planned_report.sections, topic_id)
        assert {item.key for item in planned_report.intakeItems if item.contentScopeId == topic_id} == _expected_intake_keys(topic_id)
        assert any(
            d["reportSectionId"] == topic_id and d["status"] == "report_section_included"
            for d in planned["diagnostics"]
        )

        assembled = _assemble_report_for_topic(topic_id, title)
        assembled_report = assembled.report
        assert _has_topic_section(assembled_report.sections, topic_id)
        assert {item.key for item in assembled_report.intakeItems if item.contentScopeId == topic_id} == _expected_intake_keys(topic_id)
        assert any(
            item.reportSectionId == topic_id
            and item.status == "report_section_included"
            for item in assembled.diagnostics
        )


def test_embedded_assessment_topics_do_not_have_topic_workpaper_modeling():
    templates = load_topic_templates(SSE_PACKAGE)
    intake_topics = {item.contentScopeId for item in load_topic_intake(SSE_PACKAGE)}
    for topic_id, title in EMBEDDED_ASSESSMENT_TOPICS.items():
        ref = resolve_topic(SSE_PACKAGE, title)
        assert ref is not None
        assert ref.id == topic_id
        assert ref.reportSectionId is None
        assert topic_id not in templates
        assert topic_id not in intake_topics
        assert not (SSE_PACKAGE.standard_disclosure_requirements_dir / f"{topic_id}.yaml").exists()


def test_config_excluded_topics_are_not_planned_even_if_section_stub_exists():
    result = plan_report(_report_for_topic("climate_change", "应对气候变化"), package=SSE_PACKAGE)
    report = result["report"]
    for topic_id in EXCLUDED_PENDING_TOPICS:
        assert not _has_topic_section(report.sections, topic_id)
        assert all(item.contentScopeId != topic_id for item in report.intakeItems)
        assert {"reportSectionId": topic_id, "status": "omitted_by_config"} in result["diagnostics"]


def test_generic_scaffold_topics_are_planned_as_applicable_topics():
    intake_items = load_topic_intake(SSE_PACKAGE)
    intake_by_topic = {}
    for item in intake_items:
        intake_by_topic.setdefault(item.contentScopeId, set()).add(item.key)

    for topic_id, title in GENERIC_SCAFFOLD_TOPICS.items():
        assert intake_by_topic.get(topic_id) == {
            f"{topic_id}.q_management",
            f"{topic_id}.q_strategy",
            f"{topic_id}.q_practices",
            f"{topic_id}.q_metrics",
        }

        result = plan_report(_report_for_topic(topic_id, title), package=SSE_PACKAGE)
        report = result["report"]

        assert _has_topic_section(report.sections, topic_id)
        assert {item.key for item in report.intakeItems if item.contentScopeId == topic_id} == _expected_intake_keys(topic_id)
        assert {"reportSectionId": topic_id, "status": "report_section_included"} in result["diagnostics"]


def test_common_topic_intake_template_expands_for_applicable_report_sections():
    items = load_topic_intake(SSE_PACKAGE)
    by_topic = {}
    for item in items:
        by_topic.setdefault(item.contentScopeId, {})[item.key] = item

    for section in all_report_sections(SSE_PACKAGE):
        prefix = section_prefix_of(SSE_PACKAGE, section.id)
        topic_items = by_topic[section.id]
        assert topic_items[f"{prefix}.q_governance_roles"].prompt == (
            f"贵公司“{section.title}”相关工作的组织设置情况如何？"
        )
        assert f"{prefix}.q_metrics_supplement" not in topic_items

    assert "stakeholder_communication" not in by_topic
    assert (
        by_topic["rural_revitalization_social_contribution"][
            "rural_revitalization_social_contribution.q_governance_roles"
        ].prompt
        == "贵公司“乡村振兴与社会贡献”相关工作的组织设置情况如何？"
    )


def test_plan_assembles_each_included_topic_and_attaches_intake_items():
    for topic_id, title in INCLUDED_TOPICS.items():
        result = plan_report(_report_for_topic(topic_id, title), package=SSE_PACKAGE)
        report = result["report"]
        assert _has_topic_section(report.sections, topic_id)
        assert {item.key for item in report.intakeItems if item.contentScopeId == topic_id} == _expected_intake_keys(topic_id)


def test_standard_disclosure_requirement_required_only_filters_each_included_topic():
    for topic_id in INCLUDED_TOPICS | INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS:
        if topic_id in {"due_diligence", "risk_management"}:
            assert resolve_standard_disclosure_requirements(SSE_PACKAGE, topic_id, _disclosure_refs_for_filter_test(topic_id)) == []
            continue
        refs = _disclosure_refs_for_filter_test(topic_id)
        voluntary = resolve_standard_disclosure_requirements(SSE_PACKAGE, topic_id, refs, required_only=True)
        strict = resolve_standard_disclosure_requirements(SSE_PACKAGE, topic_id, refs)
        # voluntary 只留应披露项；strict 保留样本中的全部义务等级（含鼓励或条件适用项）。
        assert [item.disclosureRequirementObligationLevel for item in voluntary] == ["required"]
        strict_levels = {item.disclosureRequirementObligationLevel for item in strict}
        assert "required" in strict_levels
        assert len(strict) == len(refs), f"{topic_id} 的 strict 投影应保留样本全部条目"


def test_metric_blocks_use_quantitative_data_without_common_intake_question():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in METRIC_TOPIC_IDS:
        prefix = section_prefix_of(SSE_PACKAGE, topic_id)
        metric_key = f"{prefix}.q_metrics_supplement"
        for block in _walk_blocks(templates[topic_id]):
            gen = block.generation
            if gen and gen.inputs:
                assert metric_key not in (gen.inputs.evidence.intakeItems or []), block.id
        assert _condition_ops_for_path(templates[topic_id], f"intakeItems.{metric_key}") == set()
        for metric in SIMPLIFIED_QUANTITATIVE_METRIC_KEYS.get(topic_id, set()):
            assert _condition_ops_for_path(templates[topic_id], f"quantitativeMetrics.{metric}") == {
                "not_exists"
            }


def test_metric_blocks_do_not_expose_internal_fill_state_in_model_visible_text():
    templates = load_topic_templates(SSE_PACKAGE)
    internal_state_terms = ("填写状态", "填写值", "未填写值", "未填写数值")

    for topic_id in METRIC_TOPIC_IDS:
        for block in _walk_blocks(templates[topic_id]):
            gen = block.generation
            if not (gen and gen.inputs and getattr(gen.inputs.evidence, "quantitativeMetrics", None)):
                continue
            parts: list[str] = []
            parts.extend([gen.task.focus, gen.task.noFactGuidance or ""])
            parts.extend(gen.simplifiedWritingGuidance or [])
            parts.extend(inline.text for inline in (block.content or []) if inline.kind == "text")
            model_visible_text = "\n".join(parts)

            assert not any(term in model_visible_text for term in internal_state_terms), block.id


def test_topic_generation_blocks_have_complete_generation_contract():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in INCLUDED_TOPICS | INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS | CONDITIONAL_TOPICS:
        for block in _walk_blocks(templates[topic_id]):
            if block.blockType not in {"constrained", "generative"}:
                continue

            assert block.generation is not None, block.id
            assert block.generation.task.focus, block.id
            assert block.generation.inputs is not None, block.id
            if block.generation.task.mode == "metric_narrative":
                assert not block.generation.standardDisclosureRequirementKeys, block.id
            elif (
                getattr(block.generation.inputs.evidence, "kind", None) == "material_gated"
                and not block.generation.standardDisclosureRequirementKeys
            ):
                # 显式豁免清单：仅这两个块暂无可挂准则资产（留待准则要求库工作流）。
                # 其余材料门控块均已挂 key，缺失即视为回归。
                assert block.id in {
                    "sustainable_supply_chain_management.iro_supplier_traceability_commitments",
                    "sustainable_supply_chain_management.iro_responsible_minerals",
                }, block.id
            elif topic_id not in {"due_diligence", "risk_management"}:
                assert block.generation.standardDisclosureRequirementKeys, block.id
            else:
                assert not block.generation.standardDisclosureRequirementKeys, block.id
            if block.type == "table":
                assert block.generation.rowCount is not None, block.id
                assert block.table is not None, block.id
                assert block.table.colDefs, block.id
            else:
                assert block.generation.targetChars is not None, block.id


def test_topic_generation_blocks_reference_fixed_common_questions():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in INCLUDED_TOPICS | INCLUDED_TOPICS_WITHOUT_CLAUSE_ANNOTATIONS | CONDITIONAL_TOPICS:
        prefix = section_prefix_of(SSE_PACKAGE, topic_id)
        expected_by_pillar = {
            f"{prefix}.gov": {
                f"{prefix}.q_governance_roles",
                f"{prefix}.q_governance_policies",
                f"{prefix}.q_governance_certifications",
            },
            f"{prefix}.strategy": {f"{prefix}.q_strategy_content"},
        }
        for pillar in templates[topic_id].children or []:
            expected = expected_by_pillar.get(pillar.key)
            if expected is None:
                continue
            for block in pillar.blocks:
                if block.blockType not in {"constrained", "generative"}:
                    continue
                if block.id == "anti_bribery_anti_corruption.strategy_risk_response_table":
                    continue
                inputs = block.generation.inputs if block.generation else None
                assert inputs is not None, block.id
                assert expected <= set(inputs.evidence.intakeItems or []), block.id


def test_metric_topics_record_quantitative_data_boundary():
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id in METRIC_TOPIC_IDS:
        if topic_id in SIMPLIFIED_QUANTITATIVE_METRIC_KEYS:
            declared = set()
            for block in _walk_blocks(templates[topic_id]):
                gen = block.generation
                if gen and gen.inputs and getattr(gen.inputs.evidence, "quantitativeMetrics", None):
                    declared.update(gen.inputs.evidence.quantitativeMetrics)
            for metric in SIMPLIFIED_QUANTITATIVE_METRIC_KEYS[topic_id]:
                assert metric in declared


def test_prompt_requirements_do_not_contain_internal_workflow_terms():
    for topic_id in METRIC_TOPIC_IDS:
        refs = [f"{topic_id}.*"] if topic_id != "climate_change" else []
        requirements = resolve_standard_disclosure_requirements(SSE_PACKAGE, topic_id, refs)
        text = "\n".join(req.standardDisclosureRequirementText for req in requirements)
        for sentinel in INTERNAL_PROMPT_TEXT_SENTINELS:
            assert sentinel not in text


def test_user_visible_annotations_are_available_for_each_included_topic():
    for topic_id in INCLUDED_TOPICS:
        for mainland_standard in ("sse", "szse", "bse"):
            entry = find_user_visible_disclosure_clause_annotation_entry(SSE_PACKAGE, 
                mainland_standard=mainland_standard,
                report_section_key=topic_id,
            )
            assert entry is not None
            assert entry.reportSectionKey == topic_id
            assert entry.clauseOriginalTexts


def test_user_visible_annotation_for_stakeholder_communication_is_front_chapter_section():
    for mainland_standard in ("sse", "szse", "bse"):
        entry = find_user_visible_disclosure_clause_annotation_entry(SSE_PACKAGE, 
            mainland_standard=mainland_standard,
            report_section_key="sm.stakeholder",
        )
        assert entry is not None
        assert entry.reportContentTopicName == "利益相关方沟通"
        assert entry.reportSectionKey == "sm.stakeholder"
        assert entry.clauseOriginalTexts


def test_every_topic_pillar_section_has_an_unconditional_content_unit():
    """四支柱结构不变量：议题被纳入报告后，每个支柱节必须至少有一个不依赖
    可选资料的无条件内容单元，否则资料不齐时支柱整节消失、违反准则四支柱结构
    （曾发生：反商业贿赂/气候/生态/污染物的“影响、风险与机遇管理”全条件化）。"""
    templates = load_topic_templates(SSE_PACKAGE)

    def has_unconditional_block(section) -> bool:
        for block in section.blocks or []:
            if getattr(block, "appears_when", None) is None:
                return True
        for child in section.children or []:
            if getattr(child, "appears_when", None) is None and has_unconditional_block(child):
                return True
        return False

    for topic_id, template in templates.items():
        for pillar in template.children or []:
            if getattr(pillar, "appears_when", None) is not None:
                continue
            assert has_unconditional_block(pillar), (
                f"{topic_id} 支柱「{pillar.title}」全部内容都挂在可选资料条件上，"
                "资料不齐时该支柱整节消失；须补一个无条件基础内容单元。"
            )
