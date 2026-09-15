# ABOUTME: 轻量版报告上游准备状态解析器，把 Report 解析成可供诊断、导出和前端门禁共用的 typed readiness。
# ABOUTME: 本模块只表达轻量版链路前置条件；不处理工作台正文质量或导出格式问题。
# ABOUTME(en): Parses a Report into typed lightweight upstream readiness, shared by diagnostics, export and UI gates.
# ABOUTME(en): Expresses only lightweight pipeline preconditions; not prose quality or export formatting problems.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from sustainability_desk.contract.input_obligations import (
    missing_required_report_configuration_obligations,
)
from sustainability_desk.contract.models import QuantitativeMetricsMeta, Report
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    StructuredInputStatus,
    assessment_context_fingerprint,
    quantitative_metrics_context_fingerprint,
)
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.loader import quantitative_metrics_vocabulary
from sustainability_desk.contract.topic_registry import all_assessment_topics, applicable_scoring_topics
from sustainability_desk.quantitative_metrics import (
    all_quantitative_metrics,
    validate_complete_quantitative_metrics,
)

ReadinessStageId = Literal[
    "report_configuration",
    "assessment_scoring",
    "quantitative_metrics",
    "workbench_entry",
]
class LightweightReadinessIssue(BaseModel):
    code: str
    message: str
    stageId: ReadinessStageId
    actionHref: str
    fieldKey: str | None = None
    path: str | None = None
    assessmentTopicId: str | None = None
    metricKey: str | None = None


class LightweightReadinessStage(BaseModel):
    id: ReadinessStageId
    label: str
    actionHref: str
    complete: bool
    issueCount: int
    inputStatus: StructuredInputStatus


class LightweightReportReadiness(BaseModel):
    stages: list[LightweightReadinessStage]
    issues: list[LightweightReadinessIssue]
    readyForWorkbench: bool
    firstIncompleteStageId: ReadinessStageId | None = None
    firstIncompleteHref: str | None = None


def _filled(value: object | None) -> bool:
    return value is not None and str(value).strip() != ""


def _quantitative_metrics_meta(report: Report) -> dict:
    meta = report.meta
    quant = meta.get("quantitativeMetrics") if isinstance(meta, dict) else getattr(meta, "quantitativeMetrics", None)
    if quant is not None and hasattr(quant, "model_dump"):
        return quant.model_dump()
    return quant if isinstance(quant, dict) else {}


def _metric_value(report: Report, key: str) -> object | None:
    meta = _quantitative_metrics_meta(report)
    metrics = meta.get("metrics")
    if not isinstance(metrics, dict):
        return None
    draft = metrics.get(key)
    if not isinstance(draft, dict):
        return None
    return draft.get("value")


def _ghg_standard_ready(report: Report) -> bool:
    meta = _quantitative_metrics_meta(report)
    standard = str(meta.get("greenhouseGasAccountingStandard") or "").strip()
    if not standard:
        return False
    if standard == quantitative_metrics_vocabulary(knowledge_package_of(report)).otherStandardLabel:
        return _filled(meta.get("greenhouseGasAccountingStandardOther"))
    return True


def _add_config_issues(report: Report, out: list[LightweightReadinessIssue]) -> None:
    profile = report.disclosureProfile
    basis = knowledge_package_of(report).manifest.disclosure_basis
    if basis.mainland_standard_selectable and (
        profile is None or not _filled(profile.mainlandStandard)
    ):
        out.append(
            LightweightReadinessIssue(
                code="required_mainland_standard",
                message="大陆披露准则未选择。",
                stageId="report_configuration",
                actionHref="/intake/info",
                path="disclosureProfile.mainlandStandard",
            )
        )
    # readiness 引导按「用户须填」取义务，不按门禁阶段：字段可以须填但不阻断交付，
    # 引导清单仍应完整，否则用户界面会漏掉该补的信息。
    for obligation in missing_required_report_configuration_obligations(report):
        field_key = (
            obligation.owner_id if obligation.owner_kind == "field" else None
        )
        out.append(
            LightweightReadinessIssue(
                code="required_report_configuration",
                message=f"{obligation.label}未填写。",
                stageId="report_configuration",
                actionHref="/intake/info",
                fieldKey=field_key,
                path=obligation.path,
            )
        )


def _add_assessment_issues(
    report: Report,
    out: list[LightweightReadinessIssue],
    input_status: StructuredInputStatus | None,
) -> None:
    if getattr(report.meta, "materialityStrategy", None) == "complete_coverage":
        return
    applicable = applicable_scoring_topics(report)
    required_ids = {topic.id for topic in applicable}
    actual = {
        score.assessmentTopicId: score
        for score in (report.assessmentInput.scores if report.assessmentInput else [])
    }
    if not actual:
        out.append(
            LightweightReadinessIssue(
                code="required_assessment_scoring",
                message="重要性评分尚未完成。",
                stageId="assessment_scoring",
                actionHref="/intake/scoring",
            )
        )
        return
    for topic in applicable:
        assessed = actual.get(topic.id)
        if assessed is None:
            out.append(
                LightweightReadinessIssue(
                    code="assessment_topic_missing",
                    message=f"适用议题「{topic.name}」缺少评分。",
                    stageId="assessment_scoring",
                    actionHref="/intake/scoring",
                    assessmentTopicId=topic.id,
                )
            )
            continue
        if not all(
            [
                isinstance(assessed.financialScore, (int, float)),
                isinstance(assessed.impactScore, (int, float)),
            ]
        ):
            out.append(
                LightweightReadinessIssue(
                    code="assessment_topic_incomplete",
                    message=f"适用议题「{topic.name}」评分不完整。",
                    stageId="assessment_scoring",
                    actionHref="/intake/scoring",
                    assessmentTopicId=topic.id,
                )
            )
    registry_names = {
        topic.id: topic.name for topic in all_assessment_topics(knowledge_package_of(report))
    }
    for topic_id, topic in actual.items():
        if topic_id not in required_ids:
            out.append(
                LightweightReadinessIssue(
                    code="assessment_topic_not_applicable",
                    message=(
                        "评分输入包含当前轻量版无需评分或不适用议题"
                        f"「{registry_names.get(topic_id, topic_id)}」。"
                    ),
                    stageId="assessment_scoring",
                    actionHref="/intake/scoring",
                    assessmentTopicId=topic_id,
                )
            )
    if not any(issue.stageId == "assessment_scoring" for issue in out):
        if input_status == "unverified":
            out.append(
                LightweightReadinessIssue(
                    code="assessment_input_unverified",
                    message="重要性评分存在，但尚未由当前报告上下文验证。",
                    stageId="assessment_scoring",
                    actionHref="/intake/scoring",
                )
            )
        elif input_status == "stale":
            out.append(
                LightweightReadinessIssue(
                    code="assessment_input_stale",
                    message="报告配置已变化，请按当前适用议题重新确认重要性评分。",
                    stageId="assessment_scoring",
                    actionHref="/intake/scoring",
                )
            )


def _add_metric_issues(
    report: Report,
    out: list[LightweightReadinessIssue],
    input_status: StructuredInputStatus | None,
    *,
    allowed_metric_keys: frozenset[str] | None = None,
) -> None:
    if input_status == "missing":
        out.append(
            LightweightReadinessIssue(
                code="required_quantitative_metrics",
                message="定量信息尚未逐项填写数值或无值原因。",
                stageId="quantitative_metrics",
                actionHref="/intake/metrics",
            )
        )
        return
    if input_status == "unverified":
        out.append(
            LightweightReadinessIssue(
                code="quantitative_metrics_unverified",
                message="定量信息存在，但尚未由当前报告上下文验证。",
                stageId="quantitative_metrics",
                actionHref="/intake/metrics",
            )
        )
        return
    if input_status == "stale":
        out.append(
            LightweightReadinessIssue(
                code="quantitative_metrics_stale",
                message="企业边界或报告期间已变化，请重新确认定量信息。",
                stageId="quantitative_metrics",
                actionHref="/intake/metrics",
            )
        )
        return
    metrics = tuple(
        metric
        for metric in all_quantitative_metrics(knowledge_package_of(report))
        if allowed_metric_keys is None or metric.key in allowed_metric_keys
    )
    requires_ghg_standard = any(
        metric.requiresGreenhouseGasAccountingStandard
        and _filled(_metric_value(report, metric.key))
        for metric in metrics
    )
    if requires_ghg_standard and not _ghg_standard_ready(report):
        out.append(
            LightweightReadinessIssue(
                code="required_greenhouse_gas_accounting_standard",
                message="温室气体排放核算标准未填写。",
                stageId="quantitative_metrics",
                actionHref="/intake/metrics",
                path="meta.quantitativeMetrics.greenhouseGasAccountingStandard",
            )
        )


def parse_lightweight_report_readiness(
    report: Report,
    *,
    assessment_input_status: StructuredInputStatus | None = None,
    quantitative_metrics_status: StructuredInputStatus | None = None,
    include_assessment: bool = True,
    allowed_metric_keys: frozenset[str] | None = None,
) -> LightweightReportReadiness:
    issues: list[LightweightReadinessIssue] = []
    _add_config_issues(report, issues)
    if include_assessment and not any(
        issue.stageId == "report_configuration" for issue in issues
    ):
        _add_assessment_issues(report, issues, assessment_input_status)
    if not any(issue.stageId in {"report_configuration", "assessment_scoring"} for issue in issues):
        _add_metric_issues(
            report,
            issues,
            quantitative_metrics_status,
            allowed_metric_keys=allowed_metric_keys,
        )

    issue_counts = {stage: 0 for stage in ("report_configuration", "assessment_scoring", "quantitative_metrics", "workbench_entry")}
    for issue in issues:
        issue_counts[issue.stageId] += 1
    assessment_complete = not include_assessment or (
        issue_counts["assessment_scoring"] == 0
        and assessment_input_status in {None, "current"}
    )
    quantitative_complete = (
        issue_counts["quantitative_metrics"] == 0
        and quantitative_metrics_status in {None, "current"}
    )
    stages = [
        LightweightReadinessStage(
            id="report_configuration",
            label="报告配置",
            actionHref="/intake/info",
            complete=issue_counts["report_configuration"] == 0,
            issueCount=issue_counts["report_configuration"],
            inputStatus=(
                "current"
                if issue_counts["report_configuration"] == 0
                else "missing"
            ),
        ),
        *(
            [
                LightweightReadinessStage(
                    id="assessment_scoring",
                    label="重要性评分",
                    actionHref="/intake/scoring",
                    complete=assessment_complete,
                    issueCount=issue_counts["assessment_scoring"],
                    inputStatus=(
                        assessment_input_status
                        or ("current" if assessment_complete else "missing")
                    ),
                )
            ]
            if include_assessment
            else []
        ),
        LightweightReadinessStage(
            id="quantitative_metrics",
            label="定量信息收集",
            actionHref="/intake/metrics",
            complete=quantitative_complete,
            issueCount=issue_counts["quantitative_metrics"],
            inputStatus=(
                quantitative_metrics_status
                or (
                    "current"
                    if quantitative_complete
                    else "missing"
                )
            ),
        ),
        LightweightReadinessStage(
            id="workbench_entry",
            label="报告正文入口",
            actionHref="/reports/document",
            complete=not issues,
            issueCount=0,
            inputStatus="current" if not issues else "missing",
        ),
    ]
    first = next((stage for stage in stages if not stage.complete), None)
    return LightweightReportReadiness(
        stages=stages,
        issues=issues,
        readyForWorkbench=not issues,
        firstIncompleteStageId=first.id if first else None,
        firstIncompleteHref=first.actionHref if first else None,
    )


def structured_input_statuses(
    report: Report,
    *,
    state: StoredReportStateV4 | None,
    context: StructuredInputContext | None,
    allowed_metric_keys: frozenset[str] | None = None,
) -> tuple[StructuredInputStatus, StructuredInputStatus]:
    """从同一 V4 状态计算两类 freshness；缺少 state/context 只能是 missing/unverified。

    完整性必须按调用方声明的指标范围判定：受限范围只要求白名单
    指标，不传范围会把范围内完整的报告误判为 missing，入队门与导出闸会因此分叉。
    """

    assessment_present = report.assessmentInput is not None
    quantitative = (
        report.meta.quantitativeMetrics
        if report.meta is not None
        else QuantitativeMetricsMeta()
    )
    quantitative_complete = not validate_complete_quantitative_metrics(
        quantitative,
        package=knowledge_package_of(report),
        allowed_metric_keys=allowed_metric_keys,
    )
    if state is None or context is None:
        return (
            "unverified" if assessment_present else "missing",
            "unverified" if quantitative_complete else "missing",
        )
    assessment_fingerprint = assessment_context_fingerprint(report, context)
    quantitative_fingerprint = quantitative_metrics_context_fingerprint(
        report,
        context,
    )
    stored_assessment = (
        state.structuredInputFreshness.assessmentContextFingerprint
    )
    stored_quantitative = (
        state.structuredInputFreshness.quantitativeMetricsContextFingerprint
    )
    assessment_status: StructuredInputStatus
    if not assessment_present:
        assessment_status = "missing"
    elif stored_assessment is None:
        assessment_status = "unverified"
    elif stored_assessment != assessment_fingerprint:
        assessment_status = "stale"
    else:
        assessment_status = "current"
    quantitative_status: StructuredInputStatus
    if not quantitative_complete:
        quantitative_status = "missing"
    elif stored_quantitative is None:
        quantitative_status = "unverified"
    elif stored_quantitative != quantitative_fingerprint:
        quantitative_status = "stale"
    else:
        quantitative_status = "current"
    return assessment_status, quantitative_status


def parse_stored_lightweight_report_readiness(
    report: Report,
    *,
    state: StoredReportStateV4 | None,
    context: StructuredInputContext | None,
    include_assessment: bool = True,
    allowed_metric_keys: frozenset[str] | None = None,
) -> LightweightReportReadiness:
    assessment_status, quantitative_status = structured_input_statuses(
        report,
        state=state,
        context=context,
        allowed_metric_keys=allowed_metric_keys,
    )
    return parse_lightweight_report_readiness(
        report,
        assessment_input_status=assessment_status,
        quantitative_metrics_status=quantitative_status,
        include_assessment=include_assessment,
        allowed_metric_keys=allowed_metric_keys,
    )
