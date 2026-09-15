# ABOUTME: Report-bound 结构化输入服务合同测试，锁定 scoped freshness、完整批量和服务端权威上下文。
# ABOUTME: 客户端不得提交适用性、单位或期间副本；未验证与过期输入必须在 readiness 中可区分。
from __future__ import annotations

from uuid import UUID
from types import SimpleNamespace

import pytest
import httpx
from pydantic import ValidationError

from sustainability_desk.contract.models import (
    DisclosureProfile,
    MaterialityThreshold,
    QuantitativeMetricDraft,
    QuantitativeMetricsMeta,
    ReportMeta,
)
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.assets.scoring import ScoredTopic
from sustainability_desk.api.app import app
from sustainability_desk.api.auth import AuthenticatedUser, current_user
from sustainability_desk.persistence.db import get_pool
from sustainability_desk.contract.report_api import (
    AssessmentScoreWrite,
    PutAssessmentInputRequest,
    PutQuantitativeMetricsRequest,
)
from sustainability_desk.contract.stored_report_state import (
    StoredReportMetaV4,
    StoredReportStateV4,
)
from sustainability_desk.persistence.reports import LockedLightweightReportState
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.quantitative_metrics import (
    quantitative_no_value_reasons,
    all_quantitative_metrics,
    validate_complete_quantitative_metrics,
)
from sustainability_desk.structured_input_service import (
    StructuredInputService,
    StructuredInputRequestError,
    _audit_payload,
    _assessment_status,
    _quantitative_status,
    _report_and_context,
    _resolved_assessment,
    _state_with_assessment,
    _validated_assessment,
    _validate_complete_quantitative_metrics,
)
from sustainability_desk.contract.structured_inputs import (
    assessment_context_fingerprint,
    quantitative_metrics_context_fingerprint,
)
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from sustainability_desk.lightweight_report_readiness import (
    parse_lightweight_report_readiness,
    structured_input_statuses,
)
from knowledge_package_fixtures import SSE_PACKAGE, SSE_REPORT_PROFILE_ID

REPORT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _snapshot() -> LockedLightweightReportState:
    return LockedLightweightReportState(
        report_id=REPORT_ID,
        title="结构化输入测试",
        report_profile_id="sse_zh_hans@1",
        state=StoredReportStateV4(
            version=4,
            fields={
                "company_registered_name": "测试股份有限公司",
                "reporting_year": 2025,
                "report_period_start": "2025-01-01",
                "report_period_end": "2025-12-31",
                "consolidation_scope": "本公司及纳入合并范围的子公司",
                "has_technology_ethics_sensitive_activity": "否",
            },
            disclosureProfile=DisclosureProfile(mainlandStandard="sse"),
        ),
        state_seq=3,
        contract_version=contract_version(SSE_PACKAGE),
    )


def test_report_context_comes_from_authoritative_state() -> None:
    report, context = _report_and_context(_snapshot(), package=SSE_PACKAGE)

    assert report.fields["reporting_year"].value == 2025
    assert report.fields["consolidation_scope"].value == (
        "本公司及纳入合并范围的子公司"
    )
    assert context.reportId == REPORT_ID
    assert context.contractVersion == contract_version(SSE_PACKAGE)
    assert context.compiledSemanticsVersion


def test_assessment_batch_derives_period_and_exact_applicability() -> None:
    report, _ = _report_and_context(_snapshot(), package=SSE_PACKAGE)
    scores = [
        AssessmentScoreWrite(
            assessmentTopicId=topic.id,
            financialScore=4,
            impactScore=4,
        )
        for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
    ]

    assessment = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=scores,
    )

    assert assessment.reportingYear == 2025
    assert [score.assessmentTopicId for score in assessment.scores] == [
        topic.id for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
    ]
    resolved = _resolved_assessment(
        report.model_copy(update={"assessmentInput": assessment})
    )
    assert resolved is not None
    assert resolved.counts.total == len(resolved.topics)
    assert any(
        topic.determination == "fixed"
        and topic.financialScore is None
        and topic.impactScore is None
        for topic in resolved.topics
    )
    with pytest.raises(
        StructuredInputRequestError,
        match="必须完整覆盖",
    ):
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=scores[:-1],
        )
    invalid = list(scores)
    invalid[0] = invalid[0].model_copy(
        update={"financialScore": float("nan")}
    )
    with pytest.raises(StructuredInputRequestError) as captured:
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=invalid,
        )
    assert captured.value.code == "assessment_score_invalid"


def test_partial_scores_allowed_when_require_complete_is_false() -> None:
    """在线草稿保存（require_complete=False）允许子集，仍拒绝重复与非适用议题；resolved 与 status 保持缺项语义。"""

    report, _ = _report_and_context(_snapshot(), package=SSE_PACKAGE)
    topics = applicable_scoring_topics(report, package=SSE_PACKAGE)
    assert len(topics) > 1, "测试需要至少两个适用评分议题才能验证子集覆盖"
    scores = [
        AssessmentScoreWrite(
            assessmentTopicId=topic.id,
            financialScore=4,
            impactScore=4,
        )
        for topic in topics
    ]

    partial = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=scores[:-1],
        require_complete=False,
    )
    assert len(partial.scores) == len(scores) - 1

    # resolved 投影对不完整评分不猜测补齐；直接返回 None（缺项 ≠ 故障）。
    resolved = _resolved_assessment(
        report.model_copy(update={"assessmentInput": partial})
    )
    assert resolved is None

    # status 必须仍判定为 missing：覆盖集合与适用议题集合不相等。
    fingerprint = assessment_context_fingerprint(
        report.model_copy(update={"assessmentInput": partial}),
        _report_and_context(_snapshot(), package=SSE_PACKAGE)[1],
    )
    status = _assessment_status(
        report.model_copy(update={"assessmentInput": partial}),
        stored_fingerprint=fingerprint,
        current_fingerprint=fingerprint,
    )
    assert status == "missing"

    # 空草稿（0 项）也允许——前端约定空草稿不 PUT，但服务端本身不强加下限。
    empty = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=[],
        require_complete=False,
    )
    assert empty.scores == []

    # 重复议题仍必须拒绝，不因子集放宽而放开。
    duplicated = list(scores[:-1]) + [scores[0]]
    with pytest.raises(StructuredInputRequestError) as duplicate_captured:
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=duplicated,
            require_complete=False,
        )
    assert duplicate_captured.value.code == "assessment_topic_duplicate"

    # 非适用议题仍必须拒绝，子集放宽只影响“缺项”，不影响“越界”。
    unexpected = list(scores[:-1]) + [
        AssessmentScoreWrite(
            assessmentTopicId="not_an_applicable_topic",
            financialScore=4,
            impactScore=4,
        )
    ]
    with pytest.raises(StructuredInputRequestError) as unexpected_captured:
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=unexpected,
            require_complete=False,
        )
    assert unexpected_captured.value.code == "assessment_scope_mismatch"

    # 分值仍逐项校验：子集放宽不豁免非法分值。
    invalid_partial = list(scores[:-1])
    invalid_partial[0] = invalid_partial[0].model_copy(
        update={"financialScore": float("nan")}
    )
    with pytest.raises(StructuredInputRequestError) as invalid_captured:
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=invalid_partial,
            require_complete=False,
        )
    assert invalid_captured.value.code == "assessment_score_invalid"


def test_import_assessment_still_requires_complete_coverage() -> None:
    """xlsx 导入路径必须保持 require_complete=True 默认值；子集放宽只适用于在线草稿保存。"""

    report, _ = _report_and_context(_snapshot(), package=SSE_PACKAGE)
    topics = applicable_scoring_topics(report, package=SSE_PACKAGE)
    assert len(topics) > 1, "测试需要至少两个适用评分议题才能验证缺项被拒"
    scores = [
        AssessmentScoreWrite(
            assessmentTopicId=topic.id,
            financialScore=4,
            impactScore=4,
        )
        for topic in topics
    ]

    with pytest.raises(
        StructuredInputRequestError,
        match="必须完整覆盖",
    ) as captured:
        _validated_assessment(
            report,
            threshold=MaterialityThreshold(financial=4, impact=4),
            scores=scores[:-1],
        )
    assert captured.value.code == "assessment_scope_mismatch"


def test_unbound_readiness_is_unverified_and_old_contract_is_rejected() -> None:
    snapshot = _snapshot()
    report, _ = _report_and_context(snapshot, package=SSE_PACKAGE)
    assessment_status, quantitative_status = structured_input_statuses(
        report,
        state=None,
        context=None,
    )
    assert assessment_status == "missing"
    # 定量是选填页：一项未作答不构成 missing，只是尚未被当前上下文验证。
    assert quantitative_status == "unverified"

    old = LockedLightweightReportState(
        **{**snapshot.__dict__, "contract_version": "cv-retired"}
    )
    with pytest.raises(StructuredInputRequestError) as captured:
        _report_and_context(old, package=SSE_PACKAGE)
    assert captured.value.code == "contract_upgrade_required"


def test_unanswered_metrics_are_allowed_because_the_page_is_optional() -> None:
    """未作答的指标不是错误——定量信息是选填页（design.md）。

    若 key 不在字典里与 key 在但两字段皆空走同一条拒绝路径，选填页
    实际就是必填页：用户必须对全部 149 项逐个显式声明「不填」。目录一扩容，全部
    存量报告立即不可导出，且用户要回去对从没见过的指标逐个点选才能恢复。
    """
    partial = QuantitativeMetricsMeta(
        metrics={
            next(iter(all_quantitative_metrics(SSE_PACKAGE))).key: QuantitativeMetricDraft(
                value="12.5"
            )
        }
    )
    assert validate_complete_quantitative_metrics(partial, package=SSE_PACKAGE) == ()

    empty = QuantitativeMetricsMeta(metrics={})
    assert validate_complete_quantitative_metrics(empty, package=SSE_PACKAGE) == ()


def test_answered_metric_must_still_choose_value_or_reason() -> None:
    """一旦作答，必须二选一：空壳草稿是半完成状态，不是「不填」的声明。"""
    hollow = QuantitativeMetricsMeta(
        metrics={
            next(iter(all_quantitative_metrics(SSE_PACKAGE))).key: QuantitativeMetricDraft()
        }
    )
    codes = [issue.code for issue in validate_complete_quantitative_metrics(hollow, package=SSE_PACKAGE)]
    assert codes == ["quantitative_value_choice_invalid"]


def test_quantitative_batch_accepts_every_metric_declared_no_value() -> None:
    complete = {
        metric.key: QuantitativeMetricDraft(noValueReason="not_collected")
        for metric in all_quantitative_metrics(SSE_PACKAGE)
    }
    request = PutQuantitativeMetricsRequest(
        expected_state_seq=3,
        metrics=complete,
    )
    assert quantitative_no_value_reasons() == (
        "not_collected",
        "not_available",
        "not_applicable",
        "will_supplement",
    )
    _validate_complete_quantitative_metrics(
        QuantitativeMetricsMeta(
            metrics=request.metrics,
            greenhouseGasAccountingStandard=(
                request.greenhouseGasAccountingStandard
            ),
            greenhouseGasAccountingStandardOther=(
                request.greenhouseGasAccountingStandardOther
            ),
        ), package=SSE_PACKAGE
    )


def test_online_contract_rejects_client_owned_copies() -> None:
    with pytest.raises(ValidationError):
        PutAssessmentInputRequest.model_validate(
            {
                "expected_state_seq": 3,
                "threshold": {"financial": 4, "impact": 4},
                "scores": [],
                "reportingYear": 2025,
                "applicableTopicIds": [],
            }
        )
    with pytest.raises(ValidationError):
        PutQuantitativeMetricsRequest.model_validate(
            {
                "expected_state_seq": 3,
                "metrics": {},
                "reportPeriod": "2025",
                "units": {},
            }
        )


def test_scoped_freshness_distinguishes_unverified_stale_and_current() -> None:
    snapshot = _snapshot()
    report, context = _report_and_context(snapshot, package=SSE_PACKAGE)
    assessment = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=[
            AssessmentScoreWrite(
                assessmentTopicId=topic.id,
                financialScore=4,
                impactScore=4,
            )
            for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
        ],
    )
    metrics = {
        metric.key: QuantitativeMetricDraft(noValueReason="not_collected")
        for metric in all_quantitative_metrics(SSE_PACKAGE)
    }
    report = report.model_copy(
        update={
            "assessmentInput": assessment,
            "meta": report.meta.model_copy(
                update={
                    "quantitativeMetrics": report.meta.quantitativeMetrics.model_copy(
                        update={"metrics": metrics}
                    )
                }
            ),
        }
    )
    assessment_fingerprint = assessment_context_fingerprint(report, context)
    quantitative_fingerprint = quantitative_metrics_context_fingerprint(
        report,
        context,
    )

    assert _assessment_status(
        report,
        stored_fingerprint=None,
        current_fingerprint=assessment_fingerprint,
    ) == "unverified"
    assert _assessment_status(
        report,
        stored_fingerprint="0" * 64,
        current_fingerprint=assessment_fingerprint,
    ) == "stale"
    assert _assessment_status(
        report,
        stored_fingerprint=assessment_fingerprint,
        current_fingerprint=assessment_fingerprint,
    ) == "current"
    assert _quantitative_status(
        report.meta.quantitativeMetrics,
        stored_fingerprint=quantitative_fingerprint,
        current_fingerprint=quantitative_fingerprint, package=SSE_PACKAGE,
    ) == "current"

    readiness = parse_lightweight_report_readiness(
        report,
        assessment_input_status="stale",
        quantitative_metrics_status="current",
    )
    assessment_stage = next(
        stage
        for stage in readiness.stages
        if stage.id == "assessment_scoring"
    )
    assert assessment_stage.inputStatus == "stale"


class _LockConnection:
    def __init__(self, row: dict) -> None:
        self.row = row
        self.query = ""

    async def fetchrow(self, query: str, *_args):
        self.query = query
        return self.row


async def test_lock_uses_for_update_of_state_and_checks_expected_seq() -> None:
    snapshot = _snapshot()
    row = {
        "report_id": snapshot.report_id,
        "state": snapshot.state.model_dump(mode="json"),
        "state_seq": snapshot.state_seq,
        "title": snapshot.title,
        "report_type": "lightweight",
        "report_profile_id": snapshot.report_profile_id,
        "contract_version": snapshot.contract_version,
    }
    connection = _LockConnection(row)

    locked = await reports_dal.lock_lightweight_v4_state(
        connection,  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000002"),
        REPORT_ID,
        3,
    )

    assert locked.state_seq == 3
    assert "for update of s" in " ".join(connection.query.lower().split())
    with pytest.raises(reports_dal.StateConflictError):
        await reports_dal.lock_lightweight_v4_state(
            connection,  # type: ignore[arg-type]
            UUID("00000000-0000-0000-0000-000000000002"),
            REPORT_ID,
            2,
        )


class _SaveConnection:
    def __init__(self) -> None:
        self.fetchval_query = ""
        self.executed: list[tuple[str, tuple]] = []

    async def fetchval(self, query: str, *_args):
        self.fetchval_query = query
        return 4

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        return "UPDATE 1"


async def test_save_keeps_cas_in_same_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    connection = _SaveConnection()

    new_seq = await reports_dal.save_locked_lightweight_v4_state(
        connection,  # type: ignore[arg-type]
        account_id=UUID("00000000-0000-0000-0000-000000000002"),
        locked=snapshot,
        state=snapshot.state,
        event_type="assessment_input_replaced",
        event_payload={"contextFingerprint": "a" * 64},
    )

    assert new_seq == 4
    normalized = " ".join(connection.fetchval_query.lower().split())
    assert "where report_id = $2 and state_seq = $3" in normalized
    assert any(
        "insert into report_events" in " ".join(query.lower().split())
        for query, _ in connection.executed
    )


class _AsyncContext:
    def __init__(self, value) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args) -> None:
        return None


class _PutConnection:
    def transaction(self):
        return _AsyncContext(self)


class _PutPool:
    def __init__(self) -> None:
        self.connection = _PutConnection()

    def acquire(self):
        return _AsyncContext(self.connection)


async def test_generic_put_preserves_locked_freshness_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    authoritative = snapshot.state.structuredInputFreshness.model_copy(
        update={"assessmentContextFingerprint": "a" * 64}
    )
    report, _ = _report_and_context(snapshot, package=SSE_PACKAGE)
    assessment = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=[
            AssessmentScoreWrite(
                assessmentTopicId=topic.id,
                financialScore=4,
                impactScore=4,
            )
            for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
        ],
    )
    authoritative_metrics = QuantitativeMetricsMeta(
        metrics={
            "economic_environment_r02": QuantitativeMetricDraft(value="1")
        }
    )
    locked = LockedLightweightReportState(
        **{
            **snapshot.__dict__,
            "state": snapshot.state.model_copy(
                update={
                    "assessmentInput": assessment,
                    "meta": StoredReportMetaV4(
                        quantitativeMetrics=authoritative_metrics,
                        materialityStrategy="complete_coverage",
                    ),
                    "structuredInputFreshness": authoritative,
                }
            ),
        }
    )
    captured = {}

    async def fake_lock(*_args, **_kwargs):
        return locked

    async def fake_save(*_args, state, **_kwargs):
        captured["state"] = state
        return 4

    monkeypatch.setattr(reports_dal, "lock_lightweight_v4_state", fake_lock)
    monkeypatch.setattr(
        reports_dal,
        "save_locked_lightweight_v4_state",
        fake_save,
    )
    malicious = snapshot.state.model_copy(
        update={
            "structuredInputFreshness": (
                snapshot.state.structuredInputFreshness.model_copy(
                    update={"assessmentContextFingerprint": "b" * 64}
                )
            ),
            "assessmentInput": None,
            "meta": StoredReportMetaV4(),
        }
    )

    new_seq = await reports_dal.put_state(
        _PutPool(),  # type: ignore[arg-type]
        UUID("00000000-0000-0000-0000-000000000002"),
        REPORT_ID,
        malicious.model_dump(mode="json"),
        3,
    )

    assert new_seq == 4
    assert (
        captured["state"].structuredInputFreshness
        == authoritative
    )
    assert captured["state"].assessmentInput == assessment
    assert captured["state"].meta.materialityStrategy == "complete_coverage"
    assert (
        captured["state"].meta.quantitativeMetrics
        == authoritative_metrics
    )


def test_assessment_write_clears_complete_coverage() -> None:
    snapshot = _snapshot()
    report, context = _report_and_context(snapshot, package=SSE_PACKAGE)
    assessment = _validated_assessment(
        report,
        threshold=MaterialityThreshold(financial=4, impact=4),
        scores=[
            AssessmentScoreWrite(
                assessmentTopicId=topic.id,
                financialScore=4,
                impactScore=4,
            )
            for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
        ],
    )
    state = snapshot.state.model_copy(
        update={
            "meta": StoredReportMetaV4(
                materialityStrategy="complete_coverage"
            )
        }
    )

    updated = _state_with_assessment(
        state,
        assessment=assessment,
        fingerprint=assessment_context_fingerprint(report, context),
    )

    assert updated.assessmentInput == assessment
    assert updated.meta is not None
    assert updated.meta.materialityStrategy is None


def test_audit_payload_records_fingerprints_without_raw_values() -> None:
    payload = _audit_payload(
        value={"metrics": {"metric": {"value": "sensitive"}}},
        context_fingerprint="c" * 64,
        parser_contract_version="parser.v1",
        accepted_count=69,
        workbook=b"xlsx-bytes",
    )

    assert payload["contextFingerprint"] == "c" * 64
    assert len(str(payload["inputSemanticFingerprint"])) == 64
    assert len(str(payload["workbookSha256"])) == 64
    assert payload["workbookSizeBytes"] == len(b"xlsx-bytes")
    assert payload["parserContractVersion"] == "parser.v1"
    assert payload["acceptedCount"] == 69
    assert "sensitive" not in str(payload)


async def test_conflict_response_contains_current_authoritative_snapshot() -> None:
    snapshot = _snapshot()
    service = StructuredInputService(knowledge_package=SSE_PACKAGE, 
        pool=None,  # type: ignore[arg-type]
        account_id=UUID("00000000-0000-0000-0000-000000000002"),
        report_id=REPORT_ID,
    )

    conflict = await service.conflict_response(
        reports_dal.StateConflictError(
            str(REPORT_ID),
            current=snapshot,
        )
    )

    assert conflict.code == "report_state_conflict"
    assert conflict.current.state_seq == snapshot.state_seq
    assert conflict.current.state == snapshot.state
    assert conflict.current.contract_version == snapshot.contract_version


async def test_workbook_parse_happens_before_lock_and_audit_is_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    report, context = _report_and_context(snapshot, package=SSE_PACKAGE)
    fingerprint = assessment_context_fingerprint(report, context)
    order: list[str] = []
    captured_payload: dict[str, object] = {}

    async def fake_snapshot(*_args, **_kwargs):
        order.append("snapshot")
        return snapshot

    async def fake_to_thread(_function, *_args, **_kwargs):
        order.append("parse")
        return SimpleNamespace(
            scored=[
                ScoredTopic(
                    assessmentTopicId=topic.id,
                    financialScore=4.0,
                    impactScore=4.0,
                )
                for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
            ],
            context_fingerprint=fingerprint,
        )

    async def fake_lock(*_args, **_kwargs):
        order.append("lock")
        return snapshot

    async def fake_save(*_args, event_payload, **_kwargs):
        order.append("save")
        captured_payload.update(event_payload)
        return 4

    class _RecordingPool(_PutPool):
        def acquire(self):
            order.append("acquire")
            return super().acquire()

    monkeypatch.setattr(
        reports_dal,
        "get_lightweight_v4_snapshot",
        fake_snapshot,
    )
    monkeypatch.setattr(
        "sustainability_desk.structured_input_service.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(reports_dal, "lock_lightweight_v4_state", fake_lock)
    monkeypatch.setattr(
        reports_dal,
        "save_locked_lightweight_v4_state",
        fake_save,
    )
    service = StructuredInputService(knowledge_package=SSE_PACKAGE, 
        pool=_RecordingPool(),  # type: ignore[arg-type]
        account_id=UUID("00000000-0000-0000-0000-000000000002"),
        report_id=REPORT_ID,
    )

    await service.import_assessment(
        content=b"workbook",
        expected_state_seq=3,
        threshold=MaterialityThreshold(financial=4, impact=4),
    )

    assert order == ["snapshot", "parse", "acquire", "lock", "save"]
    assert captured_payload["workbookSizeBytes"] == len(b"workbook")
    assert captured_payload["acceptedCount"] == len(
        applicable_scoring_topics(report, package=SSE_PACKAGE)
    )
    assert "workbook" not in captured_payload


async def test_conflict_is_top_level_wire_json_and_openapi_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()

    async def fake_account_context(*_args, **_kwargs):
        return SimpleNamespace(
            account_id=UUID("00000000-0000-0000-0000-000000000002"),
            capabilities=lambda: {"can_edit_existing": True},
        )

    async def conflict(*_args, **_kwargs):
        raise reports_dal.StateConflictError(
            str(REPORT_ID),
            current=snapshot,
        )

    async def fake_summary(*_args, **_kwargs):
        return SimpleNamespace(report_profile_id=SSE_REPORT_PROFILE_ID, 
            created_under_profile_id="local_single_user@1",
        )

    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.get_account_context",
        fake_account_context,
    )
    monkeypatch.setattr(StructuredInputService, "put_assessment", conflict)
    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.reports_dal.get_report_summary",
        fake_summary,
    )
    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.effective_report_scope",
        lambda *_args, **_kwargs: None,
    )
    app.dependency_overrides[get_pool] = lambda: object()
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=UUID("00000000-0000-0000-0000-000000000003"),
        email=None,
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.put(
                f"/api/reports/{REPORT_ID}/structured-inputs/assessment",
                json={
                    "expected_state_seq": 1,
                    "threshold": {"financial": 4, "impact": 4},
                    "scores": [],
                },
            )
            schema = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["code"] == "report_state_conflict"
    assert response.json()["current"]["state_seq"] == snapshot.state_seq
    operation = schema["paths"][
        "/api/reports/{report_id}/structured-inputs/assessment"
    ]["put"]
    assert "409" in operation["responses"]


async def test_contract_upgrade_is_top_level_for_get_and_put_and_openapi_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_account_context(*_args, **_kwargs):
        return SimpleNamespace(
            account_id=UUID("00000000-0000-0000-0000-000000000002"),
            capabilities=lambda: {"can_edit_existing": True},
        )

    async def contract_upgrade_required(*_args, **_kwargs):
        raise StructuredInputRequestError(
            "contract_upgrade_required",
            "报告使用的契约版本已过期，请重建报告。",
        )

    async def fake_summary(*_args, **_kwargs):
        return SimpleNamespace(report_profile_id=SSE_REPORT_PROFILE_ID, 
            created_under_profile_id="local_single_user@1",
        )

    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.get_account_context",
        fake_account_context,
    )
    monkeypatch.setattr(
        StructuredInputService,
        "assessment",
        contract_upgrade_required,
    )
    monkeypatch.setattr(
        StructuredInputService,
        "put_assessment",
        contract_upgrade_required,
    )
    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.reports_dal.get_report_summary",
        fake_summary,
    )
    monkeypatch.setattr(
        "sustainability_desk.api.structured_input_router.effective_report_scope",
        lambda *_args, **_kwargs: None,
    )
    app.dependency_overrides[get_pool] = lambda: object()
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        subject=UUID("00000000-0000-0000-0000-000000000003"),
        email=None,
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            get_response = await client.get(
                f"/api/reports/{REPORT_ID}/structured-inputs/assessment",
            )
            put_response = await client.put(
                f"/api/reports/{REPORT_ID}/structured-inputs/assessment",
                json={
                    "expected_state_seq": 1,
                    "threshold": {"financial": 4, "impact": 4},
                    "scores": [],
                },
            )
            schema = (await client.get("/openapi.json")).json()
    finally:
        app.dependency_overrides.clear()

    expected_error = {
        "code": "contract_upgrade_required",
        "message": "报告使用的契约版本已过期，请重建报告。",
    }
    assert get_response.status_code == 409
    assert get_response.json() == expected_error
    assert put_response.status_code == 409
    assert put_response.json() == expected_error

    paths = schema["paths"]
    structured_input_operations = (
        (
            "/api/reports/{report_id}/structured-inputs/assessment",
            "get",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/assessment/template",
            "get",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/quantitative-metrics",
            "get",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/"
            "quantitative-metrics/template",
            "get",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/assessment",
            "put",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/assessment/import",
            "post",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/quantitative-metrics",
            "put",
        ),
        (
            "/api/reports/{report_id}/structured-inputs/"
            "quantitative-metrics/import",
            "post",
        ),
    )
    for path, method in structured_input_operations:
        response_schema = paths[path][method]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]
        assert {
            item["$ref"] for item in response_schema["anyOf"]
        } == {
            "#/components/schemas/StructuredInputConflictResponse",
            "#/components/schemas/StructuredInputPreconditionResponse",
        }

    write_operations = structured_input_operations[4:]
    for path, method in write_operations:
        success_schema = paths[path][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert success_schema == {
            "$ref": "#/components/schemas/StructuredInputMutationResponse"
        }


def test_quantitative_status_honors_allowed_metric_scope() -> None:
    """完整性按调用方声明的指标范围判定——受限范围只要求白名单指标。

    回归：导出闸若未传白名单，会按全量指标集把已填齐白名单的报告误判为
    missing，与入队门判定分叉。

    未作答不是 missing（选填页），故用「范围外指标」区分两种范围：
    范围内的目录外指标是真错误，白名单收窄后同一指标即合法。
    """
    snapshot = _snapshot()
    report, _ = _report_and_context(snapshot, package=SSE_PACKAGE)
    first, second = (metric.key for metric in all_quantitative_metrics(SSE_PACKAGE)[:2])
    report.meta = ReportMeta(
        quantitativeMetrics=QuantitativeMetricsMeta(
            metrics={
                first: QuantitativeMetricDraft(noValueReason="not_collected"),
                second: QuantitativeMetricDraft(value="12.5"),
            }
        )
    )
    _, scoped = structured_input_statuses(
        report,
        state=None,
        context=None,
        allowed_metric_keys=frozenset({first}),
    )
    assert scoped == "missing", "second 落在白名单外，属目录外指标"
    _, wider = structured_input_statuses(
        report,
        state=None,
        context=None,
        allowed_metric_keys=frozenset({first, second}),
    )
    assert wider == "unverified", "两项都在白名单内，已作答部分合法"
