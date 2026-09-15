# ABOUTME: 议题内容清单测试断言，锁定 common 固定题与议题专属题合同。
# ABOUTME: 本模块只表达测试侧领域合同，不参与生产加载逻辑。
from types import SimpleNamespace


def empty_guardrail_context(*, substantive_input_present: bool = False) -> SimpleNamespace:
    """构造与当前 Evidence 边界一致的空 Guardrail 测试上下文。"""

    from knowledge_package_fixtures import SSE_PACKAGE

    return SimpleNamespace(
        knowledge_package_id=SSE_PACKAGE.id,
        output_language=SSE_PACKAGE.language,
        evidence=SimpleNamespace(
            intake_facts=(),
            mapped_materials=(),
            metric_evidence=(),
            substantive_input_present=substantive_input_present,
        ),
        metric_narrative_policy=None,
        report_subject=(),
    )


COMMON_FIXED_SUFFIXES = {
    "q_governance_roles",
    "q_governance_policies",
    "q_governance_certifications",
    "q_strategy_content",
}

TOPIC_SPECIFIC_KEYS_BY_PREFIX = {
    "anti_bribery_anti_corruption": {
        "q_sunshine_procurement_integrity",
        "q_integrity_training",
        "q_whistleblowing_channels",
    },
    "anti_unfair_competition": {
        "q_advertising_review_requirements",
        "q_litigation_reports",
        "q_trade_secret_protection",
    },
    "circular_economy_promotion": {
        "q_product_recycling_mechanism",
        "q_circular_economy_practices",
    },
    "climate": {
        "q_climate_risk_choices",
        "q_climate_opportunity_choices",
        "q_climate_target_status",
        "q_training_activities",
        "q_reduction_practices",
    },
    "customer_service_quality_management": {
        "q_service_complaint_platforms",
        "q_customer_service_commitments",
    },
    "data_security_customer_privacy_protection": {
        "q_customer_info_confidentiality",
        "q_customer_info_access_permissions",
    },
    "due_diligence": {
        "q_internal_external_due_diligence",
    },
    "ecosystem_biodiversity_protection": {
        "q_sensitive_area_impact",
        "q_ecological_protection_measures",
        "q_ecological_protection_activities",
    },
    "energy_management": {
        "q_energy_saving_measures",
    },
    "environmental_compliance_management": {
        "q_pollutants_waste_names",
        "q_compliance_training_activities",
        "q_violation_penalties",
    },
    "human_capital_development": {
        "q_employee_benefits",
        "q_employee_training",
        "q_vulnerable_employee_support",
    },
    "innovation_driven": {
        "q_rd_team_incentives",
        "q_innovation_work_measures",
    },
    "occupational_health_safety": {
        "q_safety_training_publicity",
        "q_safety_drills",
        "q_safety_investments_measures",
        "q_hazardous_chemicals_categories",
    },
    "pollutant_emissions_management": {
        "q_emission_management_requirements",
        "q_reduction_measures",
    },
    "product_quality_safety": {
        "q_quality_system_name",
        "q_quality_management_requirements",
        "q_quality_training_activities",
    },
    "risk_management": {
        "q_iro_impacts_risks_opportunities",
        "q_iro_management_actions",
    },
    "rural_revitalization_social_contribution": {
        "q_rural_products_services",
        "q_social_contribution_actions",
    },
    "sme_fair_treatment": {
        "q_supplier_payment_arrears",
        "q_sme_supplier_training_support",
    },
    "sustainable_supply_chain_management": {
        "q_supplier_evaluation_dimensions",
        "q_supplier_training_support",
        "q_conflict_minerals_involvement",
    },
    "technology_ethics": {
        "q_ethics_violation_penalties",
        "q_ethics_training",
    },
    "waste_management": {
        "q_solid_waste_requirements",
        "q_waste_reduction_measures",
        "q_third_party_disposal",
    },
    "water_resource_management": {
        "q_water_stressed_area",
        "q_water_management_measures",
    },
}


def expected_sme_topic_intake_keys(prefix: str) -> set[str]:
    return {
        *(f"{prefix}.{suffix}" for suffix in COMMON_FIXED_SUFFIXES),
        *(f"{prefix}.{suffix}" for suffix in TOPIC_SPECIFIC_KEYS_BY_PREFIX[prefix]),
    }
