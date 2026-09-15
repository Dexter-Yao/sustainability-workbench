# ABOUTME: 结构化输入上下文指纹测试，锁定最小依赖面和 canonical sha256 结果。
# ABOUTME: 无关报告正文不得制造 stale，企业边界、适用性或目录合同变化必须改变对应指纹。
from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from sustainability_desk.contract.models import (
    DisclosureProfile,
    Field,
    QuantitativeMetricDraft,
    Report,
)
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    assessment_context_fingerprint,
    quantitative_metrics_context_fingerprint,
)
from knowledge_package_fixtures import SSE_PACKAGE

CONTEXT = StructuredInputContext(
    reportId=UUID("00000000-0000-0000-0000-000000000001"),
    contractVersion="cv-test",
    compiledSemanticsVersion="semantics-test",
)


def _report() -> Report:
    values: dict[str, tuple[str, str | int]] = {
        "company_registered_name": ("string", "测试股份有限公司"),
        "company_short_name": ("string", "测试公司"),
        "reporting_year": ("year", 2025),
        "report_period_start": ("date", "2025-01-01"),
        "report_period_end": ("date", "2025-12-31"),
        "consolidation_scope": ("string", "本公司及纳入合并范围的子公司"),
        "has_technology_ethics_sensitive_activity": ("enum", "否"),
    }
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="结构化输入",
        sections=[],
        fields={
            key: Field(
                key=key,
                label=key,
                type=field_type,
                source="user_input",
                value=value,
                options=["是", "否"] if field_type == "enum" else None,
            )
            for key, (field_type, value) in values.items()
        },
        disclosureProfile=DisclosureProfile(),
    )


def test_context_fingerprints_are_stable_and_ignore_unconsumed_title() -> None:
    report = _report()
    renamed = report.model_copy(update={"title": "另一报告标题"})

    assert assessment_context_fingerprint(
        report,
        CONTEXT,
    ) == assessment_context_fingerprint(renamed, CONTEXT)
    assert quantitative_metrics_context_fingerprint(
        report,
        CONTEXT,
    ) == quantitative_metrics_context_fingerprint(renamed, CONTEXT)


def test_context_fingerprints_change_only_for_owned_relevant_facts() -> None:
    report = _report()
    changed_scope_fields = dict(report.fields)
    changed_scope_fields["consolidation_scope"] = changed_scope_fields[
        "consolidation_scope"
    ].model_copy(update={"value": "仅母公司"})
    changed_scope = report.model_copy(update={"fields": changed_scope_fields})
    changed_ethics_fields = dict(report.fields)
    changed_ethics_fields["has_technology_ethics_sensitive_activity"] = (
        changed_ethics_fields[
            "has_technology_ethics_sensitive_activity"
        ].model_copy(update={"value": "是"})
    )
    changed_ethics = report.model_copy(update={"fields": changed_ethics_fields})

    assert assessment_context_fingerprint(
        report,
        CONTEXT,
    ) == assessment_context_fingerprint(changed_scope, CONTEXT)
    assert quantitative_metrics_context_fingerprint(
        report,
        CONTEXT,
    ) != quantitative_metrics_context_fingerprint(changed_scope, CONTEXT)
    assert assessment_context_fingerprint(
        report,
        CONTEXT,
    ) != assessment_context_fingerprint(changed_ethics, CONTEXT)


def test_quantitative_draft_value_and_reason_are_mutually_exclusive() -> None:
    assert QuantitativeMetricDraft(noValueReason="not_collected").value is None
    with pytest.raises(ValidationError, match="不得同时填写"):
        QuantitativeMetricDraft(
            value="12.5",
            noValueReason="not_collected",
        )


def test_catalog_growth_does_not_invalidate_stored_answers() -> None:
    """目录新增指标不得使存量报告失效——选填页填过的答案仍然有效。

    若指纹含目录清单，定量目录一扩容，全部存量报告的指纹立即失配，
    导出闸按 quantitative_metrics_stale 一律拦下，而用户无法自助修复——他要回去对
    从没见过的指标逐个声明「不填」。指纹的职责是「用户答过的这些答案还成不成立」，
    不是「目录有没有变过」。
    """
    report = _report()
    grown = CONTEXT.model_copy(update={"contractVersion": "cv-grown"})

    assert quantitative_metrics_context_fingerprint(
        report, CONTEXT
    ) == quantitative_metrics_context_fingerprint(report, grown)


def test_reporting_boundary_change_still_invalidates_answers() -> None:
    """企业边界或报告期间变了，已填数值的口径随之失效，必须重新确认。"""
    report = _report()
    changed = dict(report.fields)
    changed["report_period_end"] = changed["report_period_end"].model_copy(
        update={"value": "2026-12-31"}
    )
    moved = report.model_copy(update={"fields": changed})

    assert quantitative_metrics_context_fingerprint(
        report, CONTEXT
    ) != quantitative_metrics_context_fingerprint(moved, CONTEXT)
