# ABOUTME: 跨议题段落任务合同测试，确保 source 只声明任务，不预置可见占位正文。
# ABOUTME: 事实范围由输入与证据姿态决定，专项事实段继续由既有显隐条件控制。
import re
from pathlib import Path


from sustainability_desk.contract.models import Block, Section
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
OPTIONAL_FACT_BLOCKS = {
    "anti_bribery_anti_corruption.iro_management_measures",
    "anti_bribery_anti_corruption.iro_integrity_training",
    "anti_unfair_competition.iro_litigation_penalties",
    "circular_economy_promotion.iro_end_of_life_product_recovery",
    "ecosystem_biodiversity_protection.iro_protection_measures_and_activities",
    "human_capital_development.iro_training_development",
    "occupational_health_safety.iro_training_drills",
    "pollutant_emissions_management.iro_annual_discharge_treatment",
    "pollutant_emissions_management.iro_reduction_measures_results",
    "sustainable_supply_chain_management.iro_supplier_training_and_capacity_building",
    "technology_ethics.iro_violation_incident_management",
}


def _topic_sections() -> list[Section]:
    return [
        load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]
        for path in sorted((SSE_PACKAGE.topic_sections_dir).glob("*.yaml"))
    ]


def _condition_reads_intake(condition) -> bool:
    if condition is None:
        return False
    return any(
        rule.path.startswith("intakeItems.")
        for rule in [*(condition.all or []), *(condition.any or [])]
    )


def _walk(
    section: Section,
    *,
    ancestor_conditioned: bool = False,
    ancestor_intake_conditioned: bool = False,
):
    conditioned = ancestor_conditioned or section.appears_when is not None
    intake_conditioned = ancestor_intake_conditioned or _condition_reads_intake(
        section.appears_when
    )
    for block in section.blocks:
        yield (
            block,
            conditioned or block.appears_when is not None,
            intake_conditioned or _condition_reads_intake(block.appears_when),
        )
    for child in section.children or []:
        yield from _walk(
            child,
            ancestor_conditioned=conditioned,
            ancestor_intake_conditioned=intake_conditioned,
        )


def _is_intake_backed_paragraph(block: Block) -> bool:
    generation = block.generation
    inputs = generation.inputs if generation else None
    return (
        block.type == "paragraph"
        and block.blockType in {"generative", "constrained"}
        and bool(inputs and inputs.evidence.intakeItems)
    )


def test_all_paragraph_tasks_are_semantic_instructions_not_heading_wrappers() -> None:
    blocks = [
        block
        for section in _topic_sections()
        for block, _conditioned, _intake_conditioned in _walk(section)
        if block.type == "paragraph"
        and block.blockType in {"generative", "constrained"}
        and block.generation is not None
    ]

    for block in blocks:
        assert block.generation.task.focus.strip(), block.id
        assert not re.fullmatch(
            r"围绕[「“].+[」”]形成本块报告正文。",
            block.generation.task.focus,
        ), block.id
        assert "本块报告正文" not in block.generation.task.focus, block.id
        assert "管理关注" not in block.generation.task.focus, block.id
        assert "中的定位" not in block.generation.task.focus, block.id


def test_generic_no_input_tasks_are_owned_by_evidence_posture() -> None:
    """通用缺料口径不再复制到 61 个块；块级 noFact 只保留特殊边界。"""

    generic_targets = []
    for section in _topic_sections():
        for block, _conditioned, _intake_conditioned in _walk(section):
            no_fact = block.generation.task.noFactGuidance if block.generation else None
            if no_fact and re.fullmatch(
                r"简要说明「[^」]+」的管理目的和基本关注方向。",
                no_fact,
            ):
                generic_targets.append(no_fact)

    assert generic_targets == []


def test_context_only_governance_tasks_do_not_require_unsupported_responsibility_assignment() -> None:
    risky = {
        block.id: block.generation.task.focus
        for section in _topic_sections()
        for block, _conditioned, _intake_conditioned in _walk(section)
        if block.generation
        and block.id
        in {
            "rural_revitalization_social_contribution.gov_responsibility_department",
            "technology_ethics.gov_management_framework",
            "ecosystem_biodiversity_protection.gov_ecological_governance",
        }
        and "责任分工" in block.generation.task.focus
    }

    assert risky == {}


def test_intake_backed_lightweight_guidance_covers_expected_blocks() -> None:
    guided_blocks = {
        block.id
        for section in _topic_sections()
        for block, _, _ in _walk(section)
        if _is_intake_backed_paragraph(block)
        and block.generation.simplifiedWritingGuidance
    }
    assert guided_blocks == {
        "anti_bribery_anti_corruption.gov_structure_responsibilities",
        "anti_bribery_anti_corruption.iro_management_framework",
        "anti_bribery_anti_corruption.iro_management_measures",
        "anti_bribery_anti_corruption.iro_integrity_training",
        "anti_bribery_anti_corruption.iro_whistleblowing_mechanism",
        "anti_unfair_competition.iro_fair_competition_controls",
        "circular_economy_promotion.iro_end_of_life_product_recovery",
        "climate.gov_structure",
        "climate.strategy_direction",
        "climate.iro_management_framework",
        "climate.iro_reduction_practice",
        "climate.iro_training",
        "ecosystem_biodiversity_protection.iro_management_framework",
        "customer_service_quality_management.strategy_customer_centric_service",
        "customer_service_quality_management.iro_service_feedback_improvement",
        "data_security_customer_privacy_protection.gov_security_management_system",
        "data_security_customer_privacy_protection.iro_customer_information_protection_controls",
        "due_diligence.iro_due_diligence_practices",
        "energy_management.gov_system_framework",
        "energy_management.iro_efficiency_projects",
        "human_capital_development.gov_workforce_governance",
        "human_capital_development.strategy_talent_development",
        "human_capital_development.iro_employee_rights_and_inclusion",
        "pollutant_emissions_management.gov_responsibility_structure",
        "pollutant_emissions_management.iro_policy_practice",
        "occupational_health_safety.iro_safety_protection_measures",
        "product_quality_safety.gov_quality_system_policies_certifications",
        "product_quality_safety.iro_lifecycle_quality_safety_controls",
        "sustainable_supply_chain_management.gov_governance_structure_responsibilities",
        "sustainable_supply_chain_management.strategy_targets",
        "sustainable_supply_chain_management.iro_resilience_risk_management",
        "sustainable_supply_chain_management.iro_supplier_training_and_capacity_building",
        "technology_ethics.gov_management_framework",
        "waste_management.strategy_control_framework",
        "waste_management.iro_classification_and_disposal",
        "water_resource_management.iro_water_saving_actions",
    }


def test_concise_summary_task_owns_summary_shape_without_parallel_guidance() -> None:
    concise_blocks = [
        section.conciseDisclosure
        for section in _topic_sections()
        if section.conciseDisclosure is not None
    ]

    assert len(concise_blocks) == 22
    for block in concise_blocks:
        assert block.generation is not None
        assert block.generation.simplifiedWritingGuidance is None
        assert (
            block.generation.task.focus
            == "根据本议题当前可见证据形成一段连贯摘要，覆盖相关管理关注、方向与实践，不使用四要素小标题。"
        )


def test_optional_fact_paragraphs_are_hidden_by_existing_conditions() -> None:
    conditioned = {
        block.id
        for section in _topic_sections()
        for block, is_conditioned, _intake_conditioned in _walk(section)
        if is_conditioned
    }

    assert OPTIONAL_FACT_BLOCKS <= conditioned


def test_intake_visibility_owns_absent_fact_behavior() -> None:
    """输入条件已决定块是否存在时，不再向模型重复声明“无事实不生成”。"""

    redundant = {
        block.id
        for section in _topic_sections()
        for block, _conditioned, intake_conditioned in _walk(section)
        if intake_conditioned
        and block.generation is not None
        and block.generation.task.noFactGuidance
    }

    assert redundant == set()
