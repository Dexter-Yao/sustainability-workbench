# ABOUTME: 验证 authoring sources 只编译为一份稳定关系索引，并由确定性审计守住跨文件引用。
# ABOUTME: 测试不调用模型；输入消费者、缺失分支和已裁决合同修复均从编译结果证明。
from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.audit import audit_contract
from sustainability_desk.contract.audit import ContractAuditFinding
from sustainability_desk.contract import compiled_definition
from sustainability_desk.contract.compiled_definition import (
    COMPILED_SEMANTICS_VERSION,
    CompiledReportDefinition,
    ContractCompileError,
    ContractValidationError,
    load_compiled_report_definition,
)
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.knowledge_packages import KnowledgePackage


def test_compiled_definition_is_versioned_deterministic_and_read_only() -> None:
    first = load_compiled_report_definition(SSE_PACKAGE)
    second = load_compiled_report_definition(SSE_PACKAGE)

    assert first is second
    assert first.schema_version == "sustainability_desk.compiled_report_definition.v1"
    assert first.contract_version.startswith("cv-")
    assert first.compiled_semantics_version == COMPILED_SEMANTICS_VERSION
    assert tuple(first.nodes_by_id) == tuple(second.nodes_by_id)
    with pytest.raises(TypeError):
        first.nodes_by_id["block/forbidden"] = first.nodes_by_id["block/company_intro.body"]
    with pytest.raises(AttributeError):
        getattr(first.nodes_by_id, "_data")
    with pytest.raises(AttributeError):
        setattr(first.nodes_by_id, "_data", {})


def test_production_loader_rejects_contract_audit_errors(monkeypatch) -> None:
    import sustainability_desk.contract.audit as audit_module

    compiled_definition._load_validated_compiled_report_definition.cache_clear()
    monkeypatch.setattr(
        audit_module,
        "audit_contract",
        lambda _definition: (
            ContractAuditFinding(
                code="test_error",
                severity="error",
                owner_kind="test",
                owner_id="test",
                message="测试审计错误",
            ),
        ),
    )
    with pytest.raises(ContractValidationError, match="报告合同审计未通过"):
        load_compiled_report_definition(SSE_PACKAGE)
    compiled_definition._load_validated_compiled_report_definition.cache_clear()


def test_compiled_definition_is_deeply_immutable() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    condition = next(iter(definition.visibility_contracts.values()))
    intake_item = next(iter(definition.input_definitions_by_id.values()))
    metric = next(iter(definition.metric_definitions_by_id.values()))

    with pytest.raises(ValidationError, match="Instance is frozen"):
        definition.fixed_report_definition.title = "污染缓存"
    with pytest.raises(TypeError, match="compiled list is immutable"):
        definition.fixed_report_definition.sections.append(
            definition.fixed_report_definition.sections[0]
        )
    with pytest.raises(ValidationError, match="Instance is frozen"):
        intake_item.prompt = "污染缓存"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        (condition.all or condition.any)[0].path = "fields.forbidden.value"
    with pytest.raises(TypeError, match="compiled list is immutable"):
        metric.groupPath.append("污染缓存")


def test_compiled_definition_remains_serializable_and_yields_mutable_report_copy() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = definition.model_dump(mode="json")
        report = definition.fixed_report_definition.model_copy(deep=True)
        report_dump = report.model_dump(mode="json")

    report.title = "独立运行态报告"
    report.sections.append(report.sections[0].model_copy(deep=True))

    assert not caught
    assert dumped["contract_version"] == definition.contract_version
    assert report_dump["title"] == definition.fixed_report_definition.title
    assert definition.fixed_report_definition.title != report.title
    assert CompiledReportDefinition.model_json_schema()["title"] == (
        "CompiledReportDefinition"
    )


def test_compiled_standard_requirements_remove_internal_reference_markup() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    assert definition.standard_requirements_by_id
    assert all(
        "<ref>" not in requirement.text and "</ref>" not in requirement.text
        for requirement in definition.standard_requirements_by_id.values()
    )


@pytest.mark.parametrize(
    ("invalid_item", "invalid_location"),
    [
        (
            """standardDisclosureRequirementKey: sample.gov.requirement
    standardDisclosureRequirementTitle: 示例要求
    standardDisclosureRequirementText: 应披露示例内容。
    disclosureRequirementObligationLevel: required
    excerptFrom: 示例来源
    sourceClauseReferenceLabels:
    - standard: SSE
      clauseRef: 第一条
    unexpectedField: forbidden
""",
            "unexpectedField",
        ),
        (
            """standardDisclosureRequirementKey: sample.gov.requirement
    standardDisclosureRequirementText: 应披露示例内容。
    disclosureRequirementObligationLevel: required
    excerptFrom: 示例来源
    sourceClauseReferenceLabels:
    - standard: SSE
      clauseRef: 第一条
""",
            "standardDisclosureRequirementTitle",
        ),
    ],
)
def test_standard_requirement_authoring_yaml_fails_closed_with_source_location(
    tmp_path, monkeypatch, invalid_item: str, invalid_location: str
) -> None:
    requirements_dir = tmp_path / "standard_disclosure_requirements"
    requirements_dir.mkdir()
    (requirements_dir / "sample.yaml").write_text(
        """topicStandardDisclosureRequirementGroups:
- topicSectionKey: sample.gov
  pillar: governance
  standardDisclosureRequirements:
  - """
        + invalid_item,
        encoding="utf-8",
    )
    temp_package = KnowledgePackage(id=SSE_PACKAGE.id, root=tmp_path, manifest=SSE_PACKAGE.manifest)

    with pytest.raises(ContractCompileError) as exc_info:
        compiled_definition._standard_requirements(temp_package)

    message = str(exc_info.value)
    assert "sample.yaml" in message
    assert "topicStandardDisclosureRequirementGroups.0.standardDisclosureRequirements.0" in message
    assert invalid_location in message


def test_all_intake_items_have_authoritative_consumers() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    assert definition.input_definitions_by_id
    assert all(definition.input_consumers[key] for key in definition.input_definitions_by_id)


def test_paragraph_absence_behavior_is_context_only_regardless_of_block_type() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    assert (
        definition.generation_for_block("company_intro.body").absence_behavior
        == "generate_context_only"
    )
    assert (
        definition.generation_for_block("risk_management.strategy_integrated_risk_management").absence_behavior
        == "generate_context_only"
    )
    assert (
        definition.generation_for_block("climate_change.metrics_narrative_body").absence_behavior
        == "generate_context_only"
    )


def test_input_obligations_compile_from_existing_authoring_owners() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    obligations = definition.input_obligations_by_target_handle

    # 门禁阶段由字段显式声明，不再从 required 合成：正文无条件引用的字段才标 export。
    registered_name = obligations["field.company_registered_name"]
    assert registered_name.owner_kind == "field"
    assert registered_name.required_before == "export"
    assert registered_name.path == "fields.company_registered_name.value"

    assert obligations["field.consolidation_scope"].label == "合并范围"

    # 发布与审批类字段为可选：既不阻断交付，也不进引导必填清单。
    # 正文引用它们的块均自带 appears_when，缺失时整块隐藏。
    for key in (
        "field.consolidation_scope",
        "field.report_publication_channel",
        "field.report_publication_website_url",
        "field.report_approval_year",
        "field.report_approval_month",
        "field.report_approval_body",
    ):
        assert obligations[key].required_before is None, key
        assert obligations[key].obligation == "optional", key

    # 仍须填但不阻断交付：正文不引用，或承载块缺失时自行隐藏。
    for key in ("field.company_short_name", "field.has_technology_ethics_sensitive_activity"):
        assert obligations[key].required_before is None, key
        assert obligations[key].obligation == "required_for_readiness", key

    company_profile = obligations["company_profile"]
    assert company_profile.owner_kind == "intake_item"
    # 公司简介不设门禁阶段：轻量版以 profile.generation_required_field_ids 为唯一生成门槛，
    # 缺失时由生成侧按缺资料分支处理。
    assert company_profile.required_before is None

    articles = obligations["articles"]
    assert articles.obligation == "optional"
    assert articles.required_before is None

    reader_email = obligations["appendix.reader_feedback.email"]
    assert reader_email.owner_kind == "appendix_value"
    # 读者反馈联系为纯选填：缺值时附录与段落自动省略，无门禁阶段。
    assert reader_email.required_before is None
    assert reader_email.obligation == "optional"
    assert (
        reader_email.path
        == "appendixPackage.readerFeedbackContactInformation.email"
    )
    assert "field.industry" not in obligations


def test_known_contract_conflicts_are_resolved_in_owner_sources() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)

    assert "block/sm.materiality_counts" not in definition.nodes_by_id
    assert definition.generation_for_block("climate.iro_reduction_practice").intake_item_ids == (
        "climate.q_reduction_practices",
    )
    assert definition.generation_for_block(
        "risk_management.gov_structure_responsibilities"
    ).intake_item_ids == ("risk_management.q_governance_roles",)
    assert definition.generation_for_block("risk_management.gov_policy_documents").intake_item_ids == (
        "risk_management.q_governance_policies",
        "risk_management.q_governance_certifications",
    )
    assert definition.nodes_by_id["report_section/climate_change"].ordered_child_ids == (
        "section/climate_change",
    )
    assert "appendix_projection/report_appendix" in definition.nodes_by_id[
        "section/report_appendix"
    ].ordered_child_ids


def test_contract_audit_has_no_unresolved_findings() -> None:
    assert audit_contract(load_compiled_report_definition(SSE_PACKAGE)) == ()
