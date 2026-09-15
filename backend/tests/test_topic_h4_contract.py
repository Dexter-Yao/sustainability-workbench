# ABOUTME: 议题 H4 子主题合同测试，确保稳定标题、块归属和条件均由 Section Schema 决定。
# ABOUTME: H4 只拆分语义独立内容，不拆开场段与表格或指标图片与互斥正文。
from pathlib import Path

from sustainability_desk.planner import load_topic_templates
from knowledge_package_fixtures import SSE_PACKAGE


BACKEND = Path(__file__).resolve().parents[1]

EXPECTED_H4_BLOCKS = {
    "anti_bribery_anti_corruption": {
        "反贪污管理规范": ["anti_bribery_anti_corruption.iro_management_framework"],
        "廉洁管理实践": ["anti_bribery_anti_corruption.iro_management_measures"],
        "廉洁培训": ["anti_bribery_anti_corruption.iro_integrity_training"],
        "举报机制与举报人保护": ["anti_bribery_anti_corruption.iro_whistleblowing_mechanism"],
    },
    "waste_management": {
        "危险废弃物委托处置": ["waste_management.iro_hazardous_disposal_evidence"],
    },
    "environmental_compliance_management": {
        "环境合规检查与审计记录": ["environmental_compliance_management.iro_compliance_audit_evidence"],
    },
    "data_security_customer_privacy_protection": {
        "应急演练与业务连续性": ["data_security_customer_privacy_protection.iro_drills_continuity_evidence"],
    },
    "product_quality_safety": {
        "产品召回与客户反馈处理": ["product_quality_safety.iro_recall_feedback_evidence"],
    },
    "anti_unfair_competition": {
        "公平竞争与宣传合规": ["anti_unfair_competition.iro_fair_competition_controls"],
        "诉讼与处罚": ["anti_unfair_competition.iro_litigation_penalties"],
        "合作伙伴公平竞争约定": ["anti_unfair_competition.iro_partner_fair_competition_terms"],
    },
    "circular_economy_promotion": {
        "循环经济实践": ["circular_economy_promotion.iro_circular_practices"],
        "废旧产品回收": ["circular_economy_promotion.iro_end_of_life_product_recovery"],
    },
    "climate_change": {
        "气候变化管理机制": ["climate.iro_management_framework"],
        "节能减排与资源效率": ["climate.iro_reduction_practice"],
        "气候培训与能力建设": ["climate.iro_training"],
    },
    "ecosystem_biodiversity_protection": {
        "生态保护管理机制": ["ecosystem_biodiversity_protection.iro_management_framework"],
        "生态影响识别": ["ecosystem_biodiversity_protection.iro_sensitive_area_and_impact"],
        "生态保护措施": ["ecosystem_biodiversity_protection.iro_protection_measures_and_activities"],
    },
    "human_capital_development": {
        "员工权益与包容": ["human_capital_development.iro_employee_rights_and_inclusion"],
        "员工福利保障": [
            "human_capital_development.iro_welfare_benefits_preface",
            "human_capital_development.iro_welfare_benefits_table",
        ],
        "员工培训与发展": ["human_capital_development.iro_training_development"],
    },
    "innovation_driven": {
        "研发团队管理与激励": ["innovation_driven.iro_rd_team_management_incentives"],
        "创新举措与成果": ["innovation_driven.iro_innovation_work_measures"],
    },
    "occupational_health_safety": {
        "安全风险与劳动保护": ["occupational_health_safety.iro_safety_protection_measures"],
        "安全培训与应急演练": ["occupational_health_safety.iro_training_drills"],
    },
    "pollutant_emissions_management": {
        "排放管理与处理": ["pollutant_emissions_management.iro_annual_discharge_treatment"],
        "污染物管理机制": ["pollutant_emissions_management.iro_policy_practice"],
        "减排措施与成效": ["pollutant_emissions_management.iro_reduction_measures_results"],
    },
    "risk_management": {
        "风险管理职责": ["risk_management.gov_structure_responsibilities"],
        "风险管理制度": ["risk_management.gov_policy_documents"],
    },
    "sustainable_supply_chain_management": {
        "供应链韧性与风险管理": ["sustainable_supply_chain_management.iro_resilience_risk_management"],
        "供应商追溯与承诺管理": ["sustainable_supply_chain_management.iro_supplier_traceability_commitments"],
        "负责任矿产供应链管理": ["sustainable_supply_chain_management.iro_responsible_minerals"],
        "供应商赋能与培训": [
            "sustainable_supply_chain_management.iro_supplier_training_and_capacity_building"
        ],
    },
    "technology_ethics": {
        "违规事件与整改": ["technology_ethics.iro_violation_incident_management"],
        "培训与科普": ["technology_ethics.iro_training_public_education"],
    },
}

CONDITIONAL_H4 = {
    "anti_bribery_anti_corruption.iro.management_practices",
    "anti_bribery_anti_corruption.iro.integrity_training",
    "anti_unfair_competition.iro.litigation_penalties",
    "circular_economy_promotion.iro.end_of_life_product_recovery",
    "climate.iro.reduction_practice",
    "climate.iro.training",
    "ecosystem_biodiversity_protection.iro.sensitive_area_and_impact",
    "ecosystem_biodiversity_protection.iro.protection_measures_and_activities",
    "human_capital_development.iro.training_development",
    "occupational_health_safety.iro.training_drills",
    "pollutant_emissions_management.iro.annual_discharge_treatment",
    "pollutant_emissions_management.iro.reduction_measures_results",
    "sustainable_supply_chain_management.iro.supplier_training_and_capacity_building",
    "sustainable_supply_chain_management.iro.responsible_minerals",
    "technology_ethics.iro.violation_incident_management",
}


def test_topic_h4_titles_and_block_groups_are_schema_owned() -> None:
    templates = load_topic_templates(SSE_PACKAGE)

    for topic_id, expected in EXPECTED_H4_BLOCKS.items():
        topic = templates[topic_id]
        actual = {
            child.title: [block.id for block in child.blocks]
            for pillar in topic.children or []
            if pillar.title != "指标与目标"
            for child in pillar.children or []
        }
        assert actual == expected, topic_id
        assert all(
            child.headingLevel == 4
            for pillar in topic.children or []
            if pillar.title != "指标与目标"
            for child in pillar.children or []
        )


def test_single_block_conditional_h4_owns_visibility_without_empty_heading() -> None:
    templates = load_topic_templates(SSE_PACKAGE)
    h4_sections = {
        child.key: child
        for topic_id in EXPECTED_H4_BLOCKS
        for pillar in templates[topic_id].children or []
        if pillar.title != "指标与目标"
        for child in pillar.children or []
    }

    for key in CONDITIONAL_H4:
        section = h4_sections[key]
        assert section.appears_when is not None, key
        # 显隐归 H4 所有：正文块恰一个，块本身不再自带条件。
        assert len(section.blocks) == 1, key
        assert all(block.appears_when is None for block in section.blocks), key

    welfare = h4_sections["human_capital_development.iro.welfare_benefits"]
    assert welfare.appears_when is None
    assert welfare.blocks[0].appears_when is None
    assert welfare.blocks[1].appears_when is not None
