# ABOUTME: 轻量版报告 readiness parser 单测，确保配置、评分、定量与工作台入口共用同一后端合同。
# ABOUTME: 测试只验证上游准备状态，不覆盖正文质量诊断。

from sustainability_desk.contract.input_obligations import missing_input_obligations
from sustainability_desk.contract.models import (
    AppendixPackage,
    DisclosureProfile,
    Field,
    IntakeItem,
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
    ReaderFeedbackContactInformation,
    Report,
    ReportMeta,
)
from sustainability_desk.contract.topic_registry import all_assessment_topics, applicable_scoring_topics
from sustainability_desk.quantitative_metrics import all_quantitative_metrics
from sustainability_desk.lightweight_report_readiness import parse_lightweight_report_readiness
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_intake_from


def _base_report() -> Report:
    fields = {
        key: Field(key=key, label=key, type="string", source="user_input", value=value)
        for key, value in {
            "company_registered_name": "示例有限公司",
            "company_short_name": "示例公司",
            "industry_major_category": "制造业",
            "business_description": "主营业务描述",
            "reporting_year": "2025",
            "report_period_start": "2025-01-01",
            "report_period_end": "2025-12-31",
            "report_publication_channel": "线下发布",
            "report_approval_year": "2026",
            "report_approval_month": "2026-07",
            "report_approval_body": "董事会",
            "has_technology_ethics_sensitive_activity": "否",
            "consolidation_scope": "示例公司及合并报表范围内主体",
        }.items()
    }
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields=fields,
        intakeItems=[
            IntakeItem(
                key="company_profile",
                contentScopeId="front_company_intro",
                prompt="公司简介",
                kind="text",
                collectionPriority="core",
                requiredBefore="generation",
                answer="示例公司从事电气设备研发、制造与销售，本段为 readiness 测试输入。",
            ),
        ],
        disclosureProfile=DisclosureProfile(mainlandStandard="sse"),
        appendixPackage=AppendixPackage(
            readerFeedbackContactInformation=ReaderFeedbackContactInformation(
                address="addr",
                email="esg@example.com",
                phone="0577",
            )
        ),
        sections=[],
    )


def _with_complete_assessment(report: Report) -> Report:
    scores = [
        MaterialityScoreInput(
            assessmentTopicId=topic.id,
            financialScore=4.0,
            impactScore=4.0,
        )
        for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
    ]
    return report.model_copy(update={"assessmentInput": MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=scores,
    )})


def _with_complete_metrics(report: Report) -> Report:
    metrics = {metric.key: {"value": "1"} for metric in all_quantitative_metrics(SSE_PACKAGE)}
    meta = {
        **(report.meta or {}),
        "quantitativeMetrics": {
            "metrics": metrics,
            "greenhouseGasAccountingStandard": "GHG Protocol",
        },
    }
    return report.model_copy(update={"meta": meta})


def test_missing_configuration_blocks_at_configuration_stage() -> None:
    report = _base_report()
    report.fields["company_registered_name"] = report.fields["company_registered_name"].model_copy(update={"value": ""})
    readiness = parse_lightweight_report_readiness(report)
    assert readiness.firstIncompleteStageId == "report_configuration"
    assert any(issue.fieldKey == "company_registered_name" for issue in readiness.issues)


def test_future_and_optional_intake_do_not_block_workbench() -> None:
    report = _base_report()
    report.intakeItems = [
        report.intakeItems[0].model_copy(update={"answer": None}),
        IntakeItem(
            key="articles",
            contentScopeId="front_governance",
            prompt="公司章程",
            kind="text",
            collectionPriority="core",
            answer=None,
        ),
    ]

    readiness = parse_lightweight_report_readiness(report)

    assert all(
        issue.path != "intakeItems.company_profile" for issue in readiness.issues
    )
    assert all(issue.path != "intakeItems.articles" for issue in readiness.issues)


def test_generation_gate_does_not_require_company_profile_or_optional_core_intake() -> None:
    """轻量版生成门槛只由 profile.generation_required_field_ids 决定。

    公司简介与公司章程同为 core 采集项，都不得阻断生成：缺失时由生成侧按缺资料
    分支处理。
    """

    report = _base_report()
    report.intakeItems = [
        report.intakeItems[0].model_copy(update={"answer": None}),
        IntakeItem(
            key="articles",
            contentScopeId="front_governance",
            prompt="公司章程",
            kind="text",
            collectionPriority="core",
            answer=None,
        ),
    ]

    paths = {
        obligation.path
        for obligation in missing_input_obligations(report, "generation")
    }

    assert "intakeItems.company_profile" not in paths
    assert "intakeItems.articles" not in paths


def test_generation_gate_enforces_climate_risk_opportunity_and_target_contracts() -> None:
    """气候试用必须覆盖物理风险、转型风险、机遇及目标状态，不能只填任意一项。"""
    climate_items = {
        item.key: item
        for item in load_topic_intake_from(
            SSE_PACKAGE.topic_intake_dir
        , package=SSE_PACKAGE)
        if item.key
        in {
            "climate.q_climate_risk_choices",
            "climate.q_climate_opportunity_choices",
            "climate.q_climate_target_status",
        }
    }
    report = _base_report().model_copy(
        update={
            "intakeItems": [
                *(_base_report().intakeItems),
                climate_items["climate.q_climate_risk_choices"].model_copy(
                    update={"answer": ["极端高温"]}
                ),
                climate_items["climate.q_climate_opportunity_choices"].model_copy(
                    update={"answer": ["能源绿色转型"]}
                ),
                climate_items["climate.q_climate_target_status"],
            ]
        }
    )

    missing = {
        obligation.target_handle
        for obligation in missing_input_obligations(report, "generation")
    }

    assert "climate.q_climate_risk_choices" in missing
    assert "climate.q_climate_target_status" in missing
    assert "climate.q_climate_opportunity_choices" not in missing


def test_export_gate_no_longer_requires_reader_feedback_contacts() -> None:
    """读者反馈联系为纯选填：缺值时附录与段落自动省略，导出闸不索要。"""
    report = _base_report().model_copy(
        update={
            "appendixPackage": AppendixPackage(
                readerFeedbackContactInformation=(
                    ReaderFeedbackContactInformation()
                )
            )
        }
    )

    paths = {
        obligation.path
        for obligation in missing_input_obligations(report, "export")
    }

    assert not paths & {
        "appendixPackage.readerFeedbackContactInformation.address",
        "appendixPackage.readerFeedbackContactInformation.email",
        "appendixPackage.readerFeedbackContactInformation.phone",
    }


def test_online_publication_website_field_is_optional_and_never_blocks() -> None:
    """选择官网发布后官网地址仍是可选：正文承载块自带 appears_when，缺失即整段隐藏。

    发布与审批类字段为可选，不进引导必填清单。
    """

    report = _base_report()
    report.fields["report_publication_channel"] = report.fields[
        "report_publication_channel"
    ].model_copy(update={"value": "公司官网发布"})
    report.fields["report_publication_website_url"] = Field(
        key="report_publication_website_url",
        label="公司官网地址",
        type="url",
        source="user_input",
        required=False,
        value=None,
    )

    readiness = parse_lightweight_report_readiness(report)

    assert all(
        issue.path != "fields.report_publication_website_url.value"
        for issue in readiness.issues
    )


def test_complete_coverage_skips_only_assessment_not_required_configuration() -> None:
    complete = _base_report().model_copy(
        update={"meta": ReportMeta(materialityStrategy="complete_coverage")}
    )
    assert parse_lightweight_report_readiness(complete).readyForWorkbench

    # 用仍属「用户须填」的配置字段验证：审批类字段已改为纯可选，不再进引导清单。
    complete.fields["company_short_name"] = complete.fields[
        "company_short_name"
    ].model_copy(update={"value": None})
    readiness = parse_lightweight_report_readiness(complete)

    assert not readiness.readyForWorkbench
    assert any(issue.fieldKey == "company_short_name" for issue in readiness.issues)


def test_missing_assessment_blocks_after_configuration() -> None:
    readiness = parse_lightweight_report_readiness(_base_report())
    assert readiness.firstIncompleteStageId == "assessment_scoring"
    assert any(issue.code == "required_assessment_scoring" for issue in readiness.issues)


def test_partial_assessment_reports_missing_topic() -> None:
    report = _base_report()
    applicable = list(applicable_scoring_topics(report, package=SSE_PACKAGE))
    report = report.model_copy(update={"assessmentInput": MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=[MaterialityScoreInput(
            assessmentTopicId=applicable[0].id,
            financialScore=4.0,
            impactScore=4.0,
        )],
    )})
    readiness = parse_lightweight_report_readiness(report)
    assert any(issue.code == "assessment_topic_missing" for issue in readiness.issues)


def test_not_applicable_assessment_topic_message_uses_registry_name() -> None:
    """不适用议题的提示必须用官方议题名称，不外泄内部 topic id。"""
    report = _with_complete_assessment(_base_report())
    applicable_ids = {topic.id for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)}
    extra = next(
        topic for topic in all_assessment_topics(SSE_PACKAGE) if topic.id not in applicable_ids
    )
    report = report.model_copy(update={"assessmentInput": report.assessmentInput.model_copy(update={
        "scores": [*report.assessmentInput.scores, MaterialityScoreInput(
            assessmentTopicId=extra.id,
            financialScore=4.0,
            impactScore=4.0,
        )],
    })})
    readiness = parse_lightweight_report_readiness(report)
    issue = next(
        issue for issue in readiness.issues if issue.code == "assessment_topic_not_applicable"
    )
    assert f"「{extra.name}」" in issue.message
    assert extra.id not in issue.message


def test_zero_quantitative_metrics_allows_workbench() -> None:
    report = _with_complete_assessment(_base_report())
    readiness = parse_lightweight_report_readiness(report)
    assert readiness.readyForWorkbench
    assert readiness.issues == []


def test_filled_ghg_metric_requires_accounting_standard_and_zero_is_valid() -> None:
    report = _with_complete_assessment(_base_report())
    ghg_metric = next(
        metric for metric in all_quantitative_metrics(SSE_PACKAGE)
        if metric.requiresGreenhouseGasAccountingStandard
    )
    report = report.model_copy(
        update={"meta": {"quantitativeMetrics": {"metrics": {ghg_metric.key: {"value": 0}}}}}
    )
    readiness = parse_lightweight_report_readiness(report)
    assert not readiness.readyForWorkbench
    assert [issue.code for issue in readiness.issues] == [
        "required_greenhouse_gas_accounting_standard"
    ]


def test_complete_lightweight_readiness_allows_workbench() -> None:
    report = _with_complete_metrics(_with_complete_assessment(_base_report()))
    readiness = parse_lightweight_report_readiness(report)
    assert readiness.readyForWorkbench
    assert readiness.issues == []
    assert all(stage.complete for stage in readiness.stages)
