# ABOUTME: 锁定评分议题→报告 H2→五个报告模块的单向 Registry 与适用范围。
# ABOUTME: 合并 H2 的维度和适用性必须在 parse-first 边界 fail-loud。
import pytest

from sustainability_desk.contract.models import DisclosureProfile, Field, Report
from sustainability_desk.contract.topic_registry import (
    AssessmentTopicRef,
    DimensionRef,
    MaterialityDetermination,
    ReportModuleRef,
    ReportSectionRef,
    TopicRegistrySource,
    _resolve,
    applicable_materiality_topics,
    applicable_report_modules,
    applicable_report_sections,
    applicable_scoring_topics,
    load_topic_contract,
    resolve_topic,
    section_prefix_of,
)
from knowledge_package_fixtures import SSE_PACKAGE

_EXPECTED_SIMPLE_REPORT_SECTION_IDS_BY_MODULE = {
    "environmental_sustainability": (
        "climate_change",
        "environmental_compliance_management",
        "pollutant_emissions_management",
        "waste_management",
        "circular_economy_promotion",
        "energy_management",
        "water_resource_management",
        "ecosystem_biodiversity_protection",
    ),
    "people_and_communities": (
        "human_capital_development",
        "occupational_health_safety",
        "rural_revitalization_social_contribution",
    ),
    "innovation_and_product_responsibility": (
        "innovation_driven",
        "product_quality_safety",
        "customer_service_quality_management",
    ),
    "sustainable_value_chain": (
        "sustainable_supply_chain_management",
        "sme_fair_treatment",
        "technology_ethics",
        "data_security_customer_privacy_protection",
    ),
    "responsible_governance": (
        "anti_bribery_anti_corruption",
        "anti_unfair_competition",
        "risk_management",
        "due_diligence",
    ),
}


def _report(*, technology_ethics: str = "否") -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        fields={
            "has_technology_ethics_sensitive_activity": Field(
                key="has_technology_ethics_sensitive_activity",
                label="科技伦理适用性",
                type="enum",
                source="user_input",
                value=technology_ethics,
                options=["是", "否"],
            )
        },
        disclosureProfile=DisclosureProfile(),
    )


def test_contract_has_single_direction_and_five_modules():
    contract = load_topic_contract(SSE_PACKAGE)
    assert len(contract.reportModulesById) == 5
    assert contract.assessmentTopicsByReportSectionId[
        "rural_revitalization_social_contribution"
    ] == (
        contract.assessmentTopicsById["rural_revitalization"],
        contract.assessmentTopicsById["social_contribution"],
    )
    assert contract.resolvedReportSectionsById[
        "rural_revitalization_social_contribution"
    ].dimension == "social"
    assert contract.dimension_label("social") == "社会"


def test_simple_report_module_membership_is_locked_by_test_snapshot():
    contract = load_topic_contract(SSE_PACKAGE)
    actual = {
        module_id: tuple(section.id for section in sections)
        for module_id, sections in contract.reportSectionsByReportModuleId.items()
    }

    assert actual == _EXPECTED_SIMPLE_REPORT_SECTION_IDS_BY_MODULE


def test_resolve_topic_requires_official_name():
    assert resolve_topic(SSE_PACKAGE, "应对气候变化").id == "climate_change"
    assert resolve_topic(SSE_PACKAGE, "产品质量与安全").id == "product_quality_safety"
    assert resolve_topic(SSE_PACKAGE, "产品安全与质量") is None


def test_fixed_stakeholder_is_materiality_topic_but_not_scoring_or_h2():
    report = _report()
    materiality_ids = {topic.id for topic in applicable_materiality_topics(report, package=SSE_PACKAGE)}
    scoring_ids = {topic.id for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)}
    section_ids = {section.definition.id for section in applicable_report_sections(report, package=SSE_PACKAGE)}
    assert "stakeholder_communication" in materiality_ids
    assert "stakeholder_communication" not in scoring_ids
    assert "stakeholder_communication" not in section_ids
    determination = load_topic_contract(SSE_PACKAGE).assessmentTopicsById[
        "stakeholder_communication"
    ].materialityDetermination
    assert determination.kind == "fixed" and determination.materiality == "impact"


def test_scope_counts_and_modules():
    report = _report(technology_ethics="否")
    assert len(applicable_scoring_topics(report, package=SSE_PACKAGE)) == 22
    assert len(applicable_materiality_topics(report, package=SSE_PACKAGE)) == 23
    assert [module.id for module in applicable_report_modules(report, package=SSE_PACKAGE)] == [
        "environmental_sustainability",
        "people_and_communities",
        "innovation_and_product_responsibility",
        "sustainable_value_chain",
        "responsible_governance",
    ]
    enabled = _report(technology_ethics="是")
    assert len(applicable_scoring_topics(enabled, package=SSE_PACKAGE)) == 23
    assert len(applicable_materiality_topics(enabled, package=SSE_PACKAGE)) == 24


def test_section_prefix_climate_is_climate():
    assert section_prefix_of(SSE_PACKAGE, "climate_change") == "climate"
    assert section_prefix_of(SSE_PACKAGE, "energy_management") == "energy_management"


def test_mixed_applicability_in_merged_section_fails_at_parse_boundary():
    modules = (
        ReportModuleRef(id="environmental_sustainability", navigationTitle="E", order=1, titleGenerationGuidance="E"),
        ReportModuleRef(id="people_and_communities", navigationTitle="S1", order=2, titleGenerationGuidance="S1"),
        ReportModuleRef(id="innovation_and_product_responsibility", navigationTitle="S2", order=3, titleGenerationGuidance="S2"),
        ReportModuleRef(id="sustainable_value_chain", navigationTitle="S3", order=4, titleGenerationGuidance="S3"),
        ReportModuleRef(id="responsible_governance", navigationTitle="G", order=5, titleGenerationGuidance="G"),
    )
    section = ReportSectionRef(id="merged", title="合并", reportModuleId="people_and_communities", order=1)
    topics = (
        AssessmentTopicRef(id="a", name="A", dimension="social", order=1, reportSectionId="merged", materialityDetermination=MaterialityDetermination(kind="scored")),
        AssessmentTopicRef(id="b", name="B", dimension="social", order=2, reportSectionId="merged", applicability="technology_ethics_sensitive_activity", materialityDetermination=MaterialityDetermination(kind="scored")),
    )
    dimensions = (DimensionRef(id="social", label="社会", order=1),)
    with pytest.raises(ValueError, match="适用性规则不一致"):
        _resolve(
            TopicRegistrySource(
                dimensions=dimensions,
                reportModules=modules,
                reportSections=(section,),
                assessmentTopics=topics,
            )
        )
