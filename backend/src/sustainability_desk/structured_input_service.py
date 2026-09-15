# ABOUTME: Report-bound 重要性与定量输入服务，在同一 V4 行锁事务内完成解析、校验、整批替换和 CAS。
# ABOUTME: 适用性、单位、报告期间及 scoped freshness 均从权威 Report 状态与合同派生，客户端不得复制拥有。
# ABOUTME: put_assessment 走 require_complete=False 允许在线草稿子集提交（仍拒重复/越界，逐项校验分值）；导入路径保持完整覆盖。
# ABOUTME(en): Report-bound materiality and quantitative input service: parse, validate, whole-batch replace and CAS
# ABOUTME(en): in one V4 row-locked transaction. Applicability, units, period and freshness derive from Report state.
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from uuid import UUID

import asyncpg
import asyncio
import hashlib

from sustainability_desk.assets.quantitative_parser import parse_quantitative_workbook
from sustainability_desk.assets.quantitative_template import create_quantitative_template
from sustainability_desk.assets.report_basics_parser import (
    ReportBasicsImport,
    parse_report_basics_workbook,
)
from sustainability_desk.assets.report_basics_template import (
    create_report_basics_template,
    report_basics_context_fingerprint,
)
from sustainability_desk.assets.scoring import parse_scoring
from sustainability_desk.assets.scoring_template import create_scoring_template
from sustainability_desk.assets.topic_questions_parser import parse_topic_questions_workbook
from sustainability_desk.assets.topic_questions_template import (
    create_topic_questions_template,
)
from sustainability_desk.assets.unified_workbook import (
    BLANK_UNIFIED_WORKBOOK_REPORT_ID,
    create_unified_workbook,
    split_unified_workbook,
    unified_workbook_context_fingerprint,
)
from sustainability_desk.accounts.report_execution_scope import EffectiveReportScope
from sustainability_desk.contract.compiled_definition import COMPILED_SEMANTICS_VERSION
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.models import (
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
    QuantitativeMetricsMeta,
    Report,
    ReportMeta,
)
from sustainability_desk.contract.assessment_classify import (
    DEFAULT_THRESHOLD,
    assessment_counts,
    resolve_materiality_assessment,
)
from sustainability_desk.contract.report_api import (
    AssessmentCatalogTopicResponse,
    AssessmentInputResponse,
    AssessmentScoreWrite,
    PutAssessmentInputRequest,
    PutQuantitativeMetricsRequest,
    QuantitativeMetricsResponse,
    ResolvedAssessmentResponse,
    ResolvedAssessmentTopicResponse,
    StructuredInputConflictResponse,
    StructuredInputMutationResponse,
)
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import (
    StoredIntakeAnswer,
    StoredReportMetaV4,
    StoredReportStateV4,
)
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    StructuredInputStatus,
    assessment_context_fingerprint,
    canonical_json_sha256,
    context_metadata_values,
    quantitative_metrics_context_fingerprint,
    topic_question_items,
    topic_questions_context_fingerprint,
)
from sustainability_desk.contract.topic_registry import (
    applicable_materiality_topics,
    applicable_scoring_topics,
    load_topic_contract,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.quantitative_metrics import (
    greenhouse_gas_accounting_standard_options,
    quantitative_no_value_reasons,
    all_quantitative_metrics,
    validate_complete_quantitative_metrics,
)
from sustainability_desk.lightweight_report_readiness import (
    LightweightReportReadiness,
    parse_lightweight_report_readiness,
)

_ONLINE_PARSER_CONTRACT = "sustainability_desk.structured_input.online.v1"
_ASSESSMENT_WORKBOOK_PARSER_CONTRACT = (
    "sustainability_desk.structured_input.assessment_workbook.v1"
)
_QUANTITATIVE_WORKBOOK_PARSER_CONTRACT = (
    "sustainability_desk.structured_input.quantitative_workbook.v1"
)
_TOPIC_QUESTIONS_WORKBOOK_PARSER_CONTRACT = (
    "sustainability_desk.structured_input.topic_questions_workbook.v1"
)
_REPORT_BASICS_WORKBOOK_PARSER_CONTRACT = (
    "sustainability_desk.structured_input.report_basics_workbook.v1"
)
_UNIFIED_WORKBOOK_PARSER_CONTRACT = (
    "sustainability_desk.structured_input.unified_workbook.v1"
)


class StructuredInputRequestError(ValueError):
    """可稳定投影到 HTTP 的结构化输入业务校验错误。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class StructuredInputService:
    """一份轻量版 Report 的结构化输入边界。"""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        account_id: UUID,
        report_id: UUID,
        execution_scope: EffectiveReportScope | None = None,
        knowledge_package: KnowledgePackage | None = None,
    ) -> None:
        self._pool = pool
        self._account_id = account_id
        self._report_id = report_id
        self._execution_scope = execution_scope
        if execution_scope is None and knowledge_package is None:
            raise ValueError("StructuredInputService requires an execution scope or a knowledge package")
        self._knowledge_package = knowledge_package

    @property
    def _package(self) -> KnowledgePackage:
        """The report's knowledge package: from the execution scope, else the explicit one (internal paths)."""

        if self._execution_scope is not None:
            return self._execution_scope.knowledge_package
        assert self._knowledge_package is not None
        return self._knowledge_package

    @property
    def _collects_materiality_assessment(self) -> bool:
        """评分收集入口（评分页、模板、导入）是否开放。

        与 _includes_materiality_assessment 分开：收集与进入交付物是两个口径，
        两者共用一个开关会让"能填"和"进报告"无法独立配置。
        无执行范围（内部/测试路径）时按完整语义放行。
        """

        return (
            self._execution_scope is None
            or self._execution_scope.collects_materiality_assessment
        )

    @property
    def _includes_materiality_assessment(self) -> bool:
        """评分是否进入报告内容与生成门槛。无执行范围时按完整轻量版语义放行。"""

        return (
            self._execution_scope is None
            or self._execution_scope.includes_materiality_assessment
        )

    @property
    def _allowed_metric_keys(self) -> frozenset[str] | None:
        return (
            self._execution_scope.allowed_quantitative_metric_keys()
            if self._execution_scope is not None
            else None
        )

    async def assessment(self) -> AssessmentInputResponse:
        if not self._collects_materiality_assessment:
            raise StructuredInputRequestError(
                "assessment_not_available",
                "当前报告范围不收集重要性评分。",
            )
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        return self._assessment_response(snapshot)

    async def quantitative_metrics(self) -> QuantitativeMetricsResponse:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        return self._quantitative_response(snapshot)

    async def assessment_template(self) -> bytes:
        if not self._collects_materiality_assessment:
            raise StructuredInputRequestError(
                "assessment_not_available",
                "当前报告范围不提供重要性评分模板。",
            )
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        report, context = _report_and_context(snapshot, package=self._package)
        return create_scoring_template(report, context=context)

    async def quantitative_template(self) -> bytes:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        report, context = _report_and_context(snapshot, package=self._package)
        return create_quantitative_template(
            report,
            context=context,
            allowed_metric_keys=self._allowed_metric_keys,
        )

    @property
    def _allowed_report_section_ids(self) -> frozenset[str] | None:
        return (
            self._execution_scope.allowed_report_section_ids
            if self._execution_scope is not None
            else None
        )

    async def topic_questions_template(self) -> bytes:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        report, context = _revision_and_context(snapshot, package=self._package)
        return create_topic_questions_template(
            report,
            context=context,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )

    async def import_topic_questions(
        self,
        *,
        content: bytes,
        expected_state_seq: int,
    ) -> StructuredInputMutationResponse:
        snapshot = await self._snapshot_at(expected_state_seq)
        report, context = _revision_and_context(snapshot, package=self._package)
        expected_context_fingerprint = topic_questions_context_fingerprint(
            report,
            context,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )
        answers = await asyncio.to_thread(
            parse_topic_questions_workbook,
            content,
            report=report,
            context=context,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )
        catalog_keys = frozenset(
            item.key
            for item in topic_question_items(
                report,
                allowed_report_section_ids=self._allowed_report_section_ids,
            )
        )
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                expected_state_seq,
            )
            locked_report, locked_context = _revision_and_context(locked, package=self._package)
            _require_same_context(
                expected_context_fingerprint,
                topic_questions_context_fingerprint(
                    locked_report,
                    locked_context,
                    allowed_report_section_ids=self._allowed_report_section_ids,
                ),
            )
            next_state = _state_with_topic_questions(
                locked.state,
                answers=answers,
                catalog_keys=catalog_keys,
            )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="topic_questions_workbook_imported",
                event_payload=_audit_payload(
                    value={
                        key: answer.model_dump(mode="json")
                        for key, answer in sorted(answers.items())
                    },
                    context_fingerprint=expected_context_fingerprint,
                    parser_contract_version=(
                        _TOPIC_QUESTIONS_WORKBOOK_PARSER_CONTRACT
                    ),
                    accepted_count=len(answers),
                    workbook=content,
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def report_basics_template(self) -> bytes:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        report, context = _report_and_context(snapshot, package=self._package)
        return create_report_basics_template(report, context=context)

    async def import_report_basics(
        self,
        *,
        content: bytes,
        expected_state_seq: int,
    ) -> StructuredInputMutationResponse:
        snapshot = await self._snapshot_at(expected_state_seq)
        report, context = _report_and_context(snapshot, package=self._package)
        expected_context_fingerprint = report_basics_context_fingerprint(
            report, context
        )
        parsed = await asyncio.to_thread(
            parse_report_basics_workbook,
            content,
            report=report,
            context=context,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                expected_state_seq,
            )
            locked_report, locked_context = _report_and_context(locked, package=self._package)
            _require_same_context(
                expected_context_fingerprint,
                report_basics_context_fingerprint(locked_report, locked_context),
            )
            next_state = _state_with_report_basics(locked.state, parsed=parsed)
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="report_basics_workbook_imported",
                event_payload=_audit_payload(
                    value={
                        "fields": parsed.fields,
                        "intakeItems": {
                            key: answer.model_dump(mode="json")
                            for key, answer in sorted(
                                parsed.intake_answers.items()
                            )
                        },
                        "disclosureProfile": (
                            parsed.disclosure_profile.model_dump(mode="json")
                            if parsed.disclosure_profile is not None
                            else None
                        ),
                        "appendixPackage": (
                            parsed.appendix_package.model_dump(mode="json")
                            if parsed.appendix_package is not None
                            else None
                        ),
                    },
                    context_fingerprint=expected_context_fingerprint,
                    parser_contract_version=(
                        _REPORT_BASICS_WORKBOOK_PARSER_CONTRACT
                    ),
                    accepted_count=len(parsed.fields)
                    + len(parsed.intake_answers),
                    workbook=content,
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def unified_workbook_template(self) -> bytes:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        basics_report, context = _report_and_context(snapshot, package=self._package)
        revision_report, _ = _revision_and_context(snapshot, package=self._package)
        return create_unified_workbook(
            basics_report,
            revision_report,
            context=context,
            allowed_metric_keys=self._allowed_metric_keys,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )

    async def import_unified_workbook(
        self,
        *,
        content: bytes,
        expected_state_seq: int,
        threshold: MaterialityThreshold | None = None,
    ) -> StructuredInputMutationResponse:
        """整册导入：基础资料与议题问题整批替换；评分/定量留空即跳过、保持现状。

        评分与定量的适用范围按下载时上下文校验（统一指纹保证一致）；若本次导入的
        基础资料改变了议题适用性，freshness 指纹随之漂移，由 readiness 引导用户
        重新确认，不在本边界内做二次推演。
        """

        snapshot = await self._snapshot_at(expected_state_seq)
        basics_report, context = _report_and_context(snapshot, package=self._package)
        revision_report, _ = _revision_and_context(snapshot, package=self._package)
        expected_fingerprint = unified_workbook_context_fingerprint(
            basics_report,
            revision_report,
            context,
            allowed_metric_keys=self._allowed_metric_keys,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )
        parts = await asyncio.to_thread(
            split_unified_workbook,
            content,
            basics_report=basics_report,
            revision_report=revision_report,
            context=context,
            allowed_metric_keys=self._allowed_metric_keys,
            allowed_report_section_ids=self._allowed_report_section_ids,
            # 空白母版血统（元数据声明全零 report_id）按账户级模板期望校验。
            blank_expected_metadata=blank_unified_workbook_expected_metadata(),
        )
        basics_parsed = await asyncio.to_thread(
            parse_report_basics_workbook,
            parts.report_basics,
            report=basics_report,
            context=context,
        )
        topic_answers = await asyncio.to_thread(
            parse_topic_questions_workbook,
            parts.topic_questions,
            report=revision_report,
            context=context,
            allowed_report_section_ids=self._allowed_report_section_ids,
        )
        topic_catalog_keys = frozenset(
            item.key
            for item in topic_question_items(
                revision_report,
                allowed_report_section_ids=self._allowed_report_section_ids,
            )
        )
        assessment: MaterialityAssessmentInput | None = None
        if parts.scoring is not None:
            if not self._collects_materiality_assessment:
                raise StructuredInputRequestError(
                    "assessment_not_available",
                    "当前报告范围不收集重要性评分，请将评分表留空后重新导入。",
                )
            parsed_scoring = await asyncio.to_thread(
                parse_scoring,
                parts.scoring,
                report=basics_report,
                context=context,
            )
            effective_threshold = (
                threshold
                or (
                    snapshot.state.assessmentInput.threshold
                    if snapshot.state.assessmentInput is not None
                    else None
                )
                or DEFAULT_THRESHOLD
            )
            assessment = _validated_assessment(
                basics_report,
                threshold=effective_threshold,
                scores=[
                    AssessmentScoreWrite.model_validate(asdict(score))
                    for score in parsed_scoring.scored
                ],
            )
        metrics: QuantitativeMetricsMeta | None = None
        if parts.quantitative is not None:
            metrics = await asyncio.to_thread(
                parse_quantitative_workbook,
                parts.quantitative,
                report=basics_report,
                context=context,
                allowed_metric_keys=self._allowed_metric_keys,
            )
            _validate_complete_quantitative_metrics(
                metrics,
                package=self._package,
                allowed_metric_keys=self._allowed_metric_keys,
            )

        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                expected_state_seq,
            )
            locked_basics, locked_context = _report_and_context(locked, package=self._package)
            locked_revision, _ = _revision_and_context(locked, package=self._package)
            _require_same_context(
                expected_fingerprint,
                unified_workbook_context_fingerprint(
                    locked_basics,
                    locked_revision,
                    locked_context,
                    allowed_metric_keys=self._allowed_metric_keys,
                    allowed_report_section_ids=self._allowed_report_section_ids,
                ),
            )
            next_state = _state_with_report_basics(
                locked.state, parsed=basics_parsed
            )
            next_state = _state_with_topic_questions(
                next_state,
                answers=topic_answers,
                catalog_keys=topic_catalog_keys,
            )
            if assessment is not None:
                next_state = _state_with_assessment(
                    next_state,
                    assessment=assessment,
                    fingerprint=assessment_context_fingerprint(
                        locked_basics, locked_context
                    ),
                )
            if metrics is not None:
                next_state = _state_with_quantitative_metrics(
                    next_state,
                    metrics=metrics,
                    fingerprint=quantitative_metrics_context_fingerprint(
                        locked_basics, locked_context
                    ),
                )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="unified_workbook_imported",
                event_payload=_audit_payload(
                    value={
                        "fieldCount": len(basics_parsed.fields),
                        "topicAnswerCount": len(topic_answers),
                        "assessmentImported": assessment is not None,
                        "assessmentScoreCount": (
                            len(assessment.scores) if assessment is not None else 0
                        ),
                        "quantitativeImported": metrics is not None,
                        "quantitativeMetricCount": (
                            len(metrics.metrics) if metrics is not None else 0
                        ),
                    },
                    context_fingerprint=expected_fingerprint,
                    parser_contract_version=_UNIFIED_WORKBOOK_PARSER_CONTRACT,
                    accepted_count=(
                        len(basics_parsed.fields)
                        + len(topic_answers)
                        + (len(assessment.scores) if assessment is not None else 0)
                        + (len(metrics.metrics) if metrics is not None else 0)
                    ),
                    workbook=content,
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def conflict_response(
        self,
        error: reports_dal.StateConflictError,
    ) -> StructuredInputConflictResponse:
        snapshot = error.current
        if snapshot is None:
            snapshot = await reports_dal.get_lightweight_v4_snapshot(
                self._pool,
                self._account_id,
                self._report_id,
            )
        return StructuredInputConflictResponse(
            message="报告已在其他入口更新，请使用当前权威状态重新确认。",
            current=self._mutation_response(
                locked=snapshot,
                state=snapshot.state,
                state_seq=snapshot.state_seq,
            ),
        )

    async def put_assessment(
        self,
        request: PutAssessmentInputRequest,
    ) -> StructuredInputMutationResponse:
        if not self._collects_materiality_assessment:
            raise StructuredInputRequestError(
                "assessment_not_available",
                "当前报告范围不收集重要性评分。",
            )
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                request.expected_state_seq,
            )
            report, context = _report_and_context(locked, package=self._package)
            # 在线草稿保存允许子集：自动保存频率高于完成一次性提交，逐项校验分值但不强制齐套。
            assessment = _validated_assessment(
                report,
                threshold=request.threshold,
                scores=request.scores,
                require_complete=False,
            )
            fingerprint = assessment_context_fingerprint(report, context)
            next_state = _state_with_assessment(
                locked.state,
                assessment=assessment,
                fingerprint=fingerprint,
            )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="assessment_input_replaced",
                event_payload=_audit_payload(
                    value=assessment.model_dump(mode="json"),
                    context_fingerprint=fingerprint,
                    parser_contract_version=_ONLINE_PARSER_CONTRACT,
                    accepted_count=len(assessment.scores),
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def import_assessment(
        self,
        *,
        content: bytes,
        expected_state_seq: int,
        threshold: MaterialityThreshold,
    ) -> StructuredInputMutationResponse:
        if not self._collects_materiality_assessment:
            raise StructuredInputRequestError(
                "assessment_not_available",
                "当前报告范围不收集重要性评分。",
            )
        snapshot = await self._snapshot_at(expected_state_seq)
        report, context = _report_and_context(snapshot, package=self._package)
        parsed = await asyncio.to_thread(
            parse_scoring,
            content,
            report=report,
            context=context,
        )
        assessment = _validated_assessment(
            report,
            threshold=threshold,
            scores=[
                AssessmentScoreWrite.model_validate(asdict(score))
                for score in parsed.scored
            ],
        )
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                expected_state_seq,
            )
            locked_report, locked_context = _report_and_context(locked, package=self._package)
            _require_same_context(
                parsed.context_fingerprint,
                assessment_context_fingerprint(
                    locked_report,
                    locked_context,
                ),
            )
            next_state = _state_with_assessment(
                locked.state,
                assessment=assessment,
                fingerprint=parsed.context_fingerprint,
            )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="assessment_workbook_imported",
                event_payload=_audit_payload(
                    value=assessment.model_dump(mode="json"),
                    context_fingerprint=parsed.context_fingerprint,
                    parser_contract_version=(
                        _ASSESSMENT_WORKBOOK_PARSER_CONTRACT
                    ),
                    accepted_count=len(assessment.scores),
                    workbook=content,
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def put_quantitative_metrics(
        self,
        request: PutQuantitativeMetricsRequest,
    ) -> StructuredInputMutationResponse:
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                request.expected_state_seq,
            )
            report, context = _report_and_context(locked, package=self._package)
            metrics = QuantitativeMetricsMeta(
                metrics=request.metrics,
                greenhouseGasAccountingStandard=(
                    request.greenhouseGasAccountingStandard
                ),
                greenhouseGasAccountingStandardOther=(
                    request.greenhouseGasAccountingStandardOther
                ),
            )
            _validate_complete_quantitative_metrics(
                metrics,
                package=self._package,
                allowed_metric_keys=self._allowed_metric_keys,
            )
            fingerprint = quantitative_metrics_context_fingerprint(
                report,
                context,
            )
            next_state = _state_with_quantitative_metrics(
                locked.state,
                metrics=metrics,
                fingerprint=fingerprint,
            )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="quantitative_metrics_replaced",
                event_payload=_audit_payload(
                    value=metrics.model_dump(mode="json"),
                    context_fingerprint=fingerprint,
                    parser_contract_version=_ONLINE_PARSER_CONTRACT,
                    accepted_count=len(metrics.metrics),
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def import_quantitative_metrics(
        self,
        *,
        content: bytes,
        expected_state_seq: int,
    ) -> StructuredInputMutationResponse:
        snapshot = await self._snapshot_at(expected_state_seq)
        report, context = _report_and_context(snapshot, package=self._package)
        expected_context_fingerprint = (
            quantitative_metrics_context_fingerprint(report, context)
        )
        metrics = await asyncio.to_thread(
            parse_quantitative_workbook,
            content,
            report=report,
            context=context,
            allowed_metric_keys=self._allowed_metric_keys,
        )
        _validate_complete_quantitative_metrics(
            metrics,
            package=self._package,
            allowed_metric_keys=self._allowed_metric_keys,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            locked = await reports_dal.lock_lightweight_v4_state(
                conn,
                self._account_id,
                self._report_id,
                expected_state_seq,
            )
            locked_report, locked_context = _report_and_context(locked, package=self._package)
            fingerprint = quantitative_metrics_context_fingerprint(
                locked_report,
                locked_context,
            )
            _require_same_context(
                expected_context_fingerprint,
                fingerprint,
            )
            next_state = _state_with_quantitative_metrics(
                locked.state,
                metrics=metrics,
                fingerprint=fingerprint,
            )
            new_seq = await reports_dal.save_locked_lightweight_v4_state(
                conn,
                account_id=self._account_id,
                locked=locked,
                state=next_state,
                event_type="quantitative_workbook_imported",
                event_payload=_audit_payload(
                    value=metrics.model_dump(mode="json"),
                    context_fingerprint=fingerprint,
                    parser_contract_version=(
                        _QUANTITATIVE_WORKBOOK_PARSER_CONTRACT
                    ),
                    accepted_count=len(metrics.metrics),
                    workbook=content,
                ),
            )
        return self._mutation_response(
            locked=locked,
            state=next_state,
            state_seq=new_seq,
        )

    async def _snapshot_at(
        self,
        expected_state_seq: int,
    ) -> reports_dal.LockedLightweightReportState:
        snapshot = await reports_dal.get_lightweight_v4_snapshot(
            self._pool,
            self._account_id,
            self._report_id,
        )
        if snapshot.state_seq != expected_state_seq:
            raise reports_dal.StateConflictError(
                str(self._report_id),
                current=snapshot,
            )
        return snapshot

    def _assessment_response(
        self,
        snapshot: reports_dal.LockedLightweightReportState,
    ) -> AssessmentInputResponse:
        report, context = _report_and_context(snapshot, package=self._package)
        fingerprint = assessment_context_fingerprint(report, context)
        status = _assessment_status(
            report,
            stored_fingerprint=(
                snapshot.state.structuredInputFreshness.assessmentContextFingerprint
            ),
            current_fingerprint=fingerprint,
        )
        return AssessmentInputResponse(
            status=status,
            state_seq=snapshot.state_seq,
            contract_version=snapshot.contract_version,
            context_fingerprint=fingerprint,
            score_scale=_score_scale(report),
            topics=_assessment_topics(report),
            current=snapshot.state.assessmentInput,
            resolved=_resolved_assessment(report),
            readiness=_readiness(
                report,
                assessment_status=status,
                quantitative_status=_quantitative_status_for(
                    report,
                    snapshot,
                    context,
                    allowed_metric_keys=self._allowed_metric_keys,
                ),
                include_assessment=self._includes_materiality_assessment,
                allowed_metric_keys=self._allowed_metric_keys,
            ),
        )

    def _quantitative_response(
        self,
        snapshot: reports_dal.LockedLightweightReportState,
    ) -> QuantitativeMetricsResponse:
        report, context = _report_and_context(snapshot, package=self._package)
        fingerprint = quantitative_metrics_context_fingerprint(report, context)
        status = _quantitative_status(
            report.meta.quantitativeMetrics,
            package=self._package,
            stored_fingerprint=(
                snapshot.state.structuredInputFreshness.quantitativeMetricsContextFingerprint
            ),
            current_fingerprint=fingerprint,
            allowed_metric_keys=self._allowed_metric_keys,
        )
        return QuantitativeMetricsResponse(
            status=status,
            state_seq=snapshot.state_seq,
            contract_version=snapshot.contract_version,
            context_fingerprint=fingerprint,
            catalog=[
                metric
                for metric in all_quantitative_metrics(self._package)
                if self._allowed_metric_keys is None
                or metric.key in self._allowed_metric_keys
            ],
            greenhouse_gas_accounting_standard_options=list(
                greenhouse_gas_accounting_standard_options(self._package)
            ),
            no_value_reasons=list(quantitative_no_value_reasons()),
            current=report.meta.quantitativeMetrics.model_copy(
                update={
                    "metrics": {
                        key: value
                        for key, value in report.meta.quantitativeMetrics.metrics.items()
                        if self._allowed_metric_keys is None
                        or key in self._allowed_metric_keys
                    }
                }
            ),
            readiness=_readiness(
                report,
                assessment_status=_assessment_status_for(
                    report,
                    snapshot,
                    context,
                ),
                quantitative_status=status,
                include_assessment=self._includes_materiality_assessment,
                allowed_metric_keys=self._allowed_metric_keys,
            ),
        )

    def _mutation_response(
        self,
        *,
        locked: reports_dal.LockedLightweightReportState,
        state,
        state_seq: int,
    ) -> StructuredInputMutationResponse:
        current = reports_dal.LockedLightweightReportState(
            report_id=locked.report_id,
            title=locked.title,
            report_profile_id=locked.report_profile_id,
            state=state,
            state_seq=state_seq,
            contract_version=locked.contract_version,
        )
        report, context = _report_and_context(current, package=self._package)
        return StructuredInputMutationResponse(
            state=state,
            state_seq=state_seq,
            contract_version=locked.contract_version,
            readiness=_readiness(
                report,
                assessment_status=_assessment_status_for(
                    report,
                    current,
                    context,
                ),
                quantitative_status=_quantitative_status_for(
                    report,
                    current,
                    context,
                    allowed_metric_keys=self._allowed_metric_keys,
                ),
                include_assessment=self._includes_materiality_assessment,
                allowed_metric_keys=self._allowed_metric_keys,
            ),
        )


def _report_and_context(
    snapshot: reports_dal.LockedLightweightReportState,
    *,
    package: KnowledgePackage,
) -> tuple[Report, StructuredInputContext]:
    """从同一权威快照投影工作簿所需 Report；不消费客户端上下文副本。"""

    if snapshot.contract_version != contract_version(package):
        raise StructuredInputRequestError(
            "contract_upgrade_required",
            "报告使用的契约版本已过期，请重建报告。",
        )
    state = snapshot.state
    values: dict[str, object] = {
        "fields": state.fields,
        "intake": {
            key: item.model_dump(mode="json")
            for key, item in state.intakeItems.items()
        },
    }
    if state.disclosureProfile is not None:
        values["disclosureProfile"] = state.disclosureProfile.model_dump(
            mode="json"
        )
    if state.appendixPackage is not None:
        values["appendixPackage"] = state.appendixPackage.model_dump(mode="json")
    report = fill_report(load_package_contract(package), values)
    # Report.meta 是报告内容契约，只投影内容字段：编排状态（如 primaryInputMode）
    # 存在于 StoredReportMetaV4 但不属于报告内容，整体透传会被 extra_forbidden 拒收。
    meta = (
        ReportMeta(
            quantitativeMetrics=state.meta.quantitativeMetrics,
            materialityStrategy=state.meta.materialityStrategy,
        )
        if state.meta is not None
        else ReportMeta()
    )
    report = report.model_copy(
        update={
            "title": snapshot.title,
            "assessmentInput": state.assessmentInput,
            "meta": meta,
            "stakeholderEngagement": state.stakeholderEngagement,
        }
    )
    context = StructuredInputContext(
        reportId=snapshot.report_id,
        contractVersion=snapshot.contract_version,
        compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
    )
    return report, context


def _score_scale(report: Report):
    if report.assessmentScoreScale is None:
        raise StructuredInputRequestError(
            "assessment_score_scale_missing",
            "当前报告合同未声明重要性评分尺度。",
        )
    return report.assessmentScoreScale


def _reporting_year(report: Report) -> int:
    field = report.fields.get("reporting_year")
    value = field.value if field is not None else None
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise StructuredInputRequestError(
            "reporting_year_missing",
            "请先填写报告年份，再提交重要性评分。",
        ) from None
    if not 1900 <= year <= 9999:
        raise StructuredInputRequestError(
            "reporting_year_invalid",
            "报告年份不符合当前报告合同。",
        )
    return year


def _assessment_topics(report: Report) -> list[AssessmentCatalogTopicResponse]:
    dimension_label = load_topic_contract(knowledge_package_of(report)).dimension_label
    return [
        AssessmentCatalogTopicResponse(
            assessmentTopicId=topic.id,
            name=topic.name,
            dimension=dimension_label(topic.dimension),
            order=topic.order,
            reportSectionId=topic.reportSectionId,
        )
        for topic in applicable_scoring_topics(report)
    ]


def _resolved_assessment(
    report: Report,
) -> ResolvedAssessmentResponse | None:
    """复用唯一 resolver 投影展示结果；stale/不完整输入不猜测补齐。"""

    if report.assessmentInput is None:
        return None
    try:
        resolved = resolve_materiality_assessment(
            report.assessmentInput,
            report,
        )
    except ValueError:
        return None
    registry = {
        topic.id: topic for topic in applicable_materiality_topics(report)
    }
    dimension_label = load_topic_contract(knowledge_package_of(report)).dimension_label
    topics: list[ResolvedAssessmentTopicResponse] = []
    for result in resolved.topics:
        topic = registry[result.assessmentTopicId]
        topics.append(
            ResolvedAssessmentTopicResponse(
                assessmentTopicId=result.assessmentTopicId,
                name=topic.name,
                dimension=dimension_label(topic.dimension),
                order=topic.order,
                reportSectionId=topic.reportSectionId,
                determination=result.determination,
                materiality=result.materiality,
                financialScore=getattr(result, "financialScore", None),
                impactScore=getattr(result, "impactScore", None),
            )
        )
    return ResolvedAssessmentResponse(
        reportingYear=resolved.reportingYear,
        threshold=resolved.threshold,
        counts=assessment_counts(resolved),
        topics=topics,
    )


def _validated_assessment(
    report: Report,
    *,
    threshold: MaterialityThreshold,
    scores: list[AssessmentScoreWrite],
    require_complete: bool = True,
) -> MaterialityAssessmentInput:
    """校验并排序评分输入；require_complete=False 时允许子集草稿，但仍拒绝重复与非适用议题。"""

    topics = applicable_scoring_topics(report)
    required_ids = [topic.id for topic in topics]
    required_id_set = set(required_ids)
    supplied_ids = [score.assessmentTopicId for score in scores]
    if len(set(supplied_ids)) != len(supplied_ids):
        raise StructuredInputRequestError(
            "assessment_topic_duplicate",
            "重要性评分包含重复议题。",
        )
    unexpected = [
        topic_id for topic_id in supplied_ids if topic_id not in required_id_set
    ]
    if require_complete:
        missing = [
            topic_id for topic_id in required_ids if topic_id not in supplied_ids
        ]
        if missing or unexpected:
            raise StructuredInputRequestError(
                "assessment_scope_mismatch",
                (
                    f"重要性评分必须完整覆盖当前 {len(required_ids)} 个适用议题；"
                    f"缺少 {len(missing)} 项，多出 {len(unexpected)} 项。"
                ),
            )
    elif unexpected:
        raise StructuredInputRequestError(
            "assessment_scope_mismatch",
            f"重要性评分包含 {len(unexpected)} 项当前不适用的议题。",
        )
    scale = _score_scale(report)
    from sustainability_desk.contract.materiality_scoring import (
        validate_materiality_score,
    )

    try:
        validate_materiality_score(threshold.financial, scale)
        validate_materiality_score(threshold.impact, scale)
    except ValueError as error:
        raise StructuredInputRequestError(
            "assessment_score_invalid",
            str(error),
        ) from error
    by_id = {score.assessmentTopicId: score for score in scores}
    ordered: list[MaterialityScoreInput] = []
    for topic_id in required_ids:
        score = by_id.get(topic_id)
        if score is None:
            continue
        try:
            ordered.append(
                MaterialityScoreInput(
                    assessmentTopicId=topic_id,
                    financialScore=validate_materiality_score(
                        score.financialScore,
                        scale,
                    ),
                    impactScore=validate_materiality_score(
                        score.impactScore,
                        scale,
                    ),
                )
            )
        except ValueError as error:
            raise StructuredInputRequestError(
                "assessment_score_invalid",
                f"议题 {topic_id}：{error}",
            ) from error
    return MaterialityAssessmentInput(
        reportingYear=_reporting_year(report),
        threshold=threshold,
        scores=ordered,
    )


def _validate_complete_quantitative_metrics(
    metrics: QuantitativeMetricsMeta,
    *,
    package: KnowledgePackage,
    allowed_metric_keys: frozenset[str] | None = None,
) -> None:
    issues = validate_complete_quantitative_metrics(
        metrics,
        package=package,
        allowed_metric_keys=allowed_metric_keys,
    )
    if issues:
        raise StructuredInputRequestError(
            "quantitative_metrics_incomplete",
            "；".join(issue.message for issue in issues[:10]),
        )


def _revision_and_context(
    snapshot: reports_dal.LockedLightweightReportState,
    *,
    package: KnowledgePackage,
) -> tuple[Report, StructuredInputContext]:
    """投影装配后 Report revision（含按范围展开的议题引导问题）。

    与 _report_and_context 的差异：fill_report 只含合同静态题（4 道报告级题），
    议题题在装配阶段由 planner 展开；议题问题模板/解析必须消费装配投影，
    否则题目集合恒为空。评分不完整时按完整覆盖容忍（与准备投影同一语义）。
    """

    if snapshot.contract_version != contract_version(package):
        raise StructuredInputRequestError(
            "contract_upgrade_required",
            "报告使用的契约版本已过期，请重建报告。",
        )
    report = build_report_revision(
        snapshot.state,
        package=package,
        tolerate_incomplete_assessment=True,
    )
    context = StructuredInputContext(
        reportId=snapshot.report_id,
        contractVersion=snapshot.contract_version,
        compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
    )
    return report, context


@lru_cache(maxsize=1)
def _blank_unified_workbook_inputs(package: KnowledgePackage) -> (
    tuple[Report, Report, StructuredInputContext]
):
    """空白母版的规范输入：合同模板 + 空状态装配修订，身份为全零 UUID 哨兵。

    完全由当前合同确定性派生（不含任何报告数据），因此下载与导入两侧可各自
    重算出同一份元数据期望；合同变更即指纹漂移，旧空白母版按版本不一致拒绝。
    """

    blank_state = StoredReportStateV4(version=4)
    basics = fill_report(
        load_package_contract(package),
        {"fields": {}, "intake": {}},
    )
    revision = build_report_revision(
        blank_state,
        package=package,
        tolerate_incomplete_assessment=True,
    )
    context = StructuredInputContext(
        reportId=BLANK_UNIFIED_WORKBOOK_REPORT_ID,
        contractVersion=contract_version(package),
        compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
    )
    return basics, revision, context


def blank_unified_workbook_template(package: KnowledgePackage) -> bytes:
    """账户级空白统一填报工作簿：不绑定报告、全量适用面。

    导入时用户任选目标报告，整册按覆盖语义写入（评分/定量留空仍为跳过）。
    """

    basics, revision, context = _blank_unified_workbook_inputs(package)
    return create_unified_workbook(
        basics,
        revision,
        context=context,
        allowed_metric_keys=None,
        allowed_report_section_ids=None,
        climate_core_required=False,
    )


def blank_unified_workbook_expected_metadata(package: KnowledgePackage) -> dict[str, str]:
    """空白母版血统的元数据期望；导入侧对声明全零 report_id 的工作簿据此全等校验。"""

    basics, revision, context = _blank_unified_workbook_inputs(package)
    fingerprint = unified_workbook_context_fingerprint(
        basics,
        revision,
        context,
        allowed_metric_keys=None,
        allowed_report_section_ids=None,
    )
    return context_metadata_values(
        input_kind="unified_workbook",
        context=context,
        context_fingerprint=fingerprint,
    )


def _state_with_topic_questions(
    state,
    *,
    answers: dict[str, StoredIntakeAnswer],
    catalog_keys: frozenset[str],
):
    """整批替换模板范围内的议题题答案；范围外键（报告级题等）原样保留。"""

    next_items = {
        key: value
        for key, value in state.intakeItems.items()
        if key not in catalog_keys
    }
    next_items.update(answers)
    return state.model_copy(update={"intakeItems": next_items})


def _state_with_report_basics(state, *, parsed: ReportBasicsImport):
    """整批替换基础资料面：模板范围内的字段与报告级题；议题题答案原样保留。"""

    next_fields = dict(state.fields)
    next_fields.update(parsed.fields)
    next_items = {
        key: value
        for key, value in state.intakeItems.items()
        if key not in parsed.intake_keys
    }
    next_items.update(parsed.intake_answers)
    return state.model_copy(
        update={
            "fields": next_fields,
            "intakeItems": next_items,
            "disclosureProfile": parsed.disclosure_profile,
            "appendixPackage": parsed.appendix_package,
        }
    )


def _state_with_assessment(
    state,
    *,
    assessment: MaterialityAssessmentInput,
    fingerprint: str,
):
    """写入评分即退出 complete_coverage；两种互斥语义不得同时存在。"""

    meta = state.meta or StoredReportMetaV4()
    return state.model_copy(
        update={
            "assessmentInput": assessment,
            "meta": meta.model_copy(update={"materialityStrategy": None}),
            "structuredInputFreshness": (
                state.structuredInputFreshness.model_copy(
                    update={"assessmentContextFingerprint": fingerprint}
                )
            ),
        }
    )


def _state_with_quantitative_metrics(
    state,
    *,
    metrics: QuantitativeMetricsMeta,
    fingerprint: str,
):
    meta = state.meta or StoredReportMetaV4()
    next_meta = meta.model_copy(update={"quantitativeMetrics": metrics})
    return state.model_copy(
        update={
            "meta": next_meta,
            "structuredInputFreshness": (
                state.structuredInputFreshness.model_copy(
                    update={
                        "quantitativeMetricsContextFingerprint": fingerprint,
                    }
                )
            ),
        }
    )


def _require_same_context(
    parsed_fingerprint: str,
    locked_fingerprint: str,
) -> None:
    if parsed_fingerprint != locked_fingerprint:
        raise reports_dal.StateConflictError("结构化输入上下文已变化")


def _audit_payload(
    *,
    value: object,
    context_fingerprint: str,
    parser_contract_version: str,
    accepted_count: int,
    workbook: bytes | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contextFingerprint": context_fingerprint,
        "inputSemanticFingerprint": canonical_json_sha256(value),
        "parserContractVersion": parser_contract_version,
        "acceptedCount": accepted_count,
    }
    if workbook is not None:
        payload["workbookSha256"] = hashlib.sha256(workbook).hexdigest()
        payload["workbookSizeBytes"] = len(workbook)
    return payload


def _assessment_status(
    report: Report,
    *,
    stored_fingerprint: str | None,
    current_fingerprint: str,
) -> StructuredInputStatus:
    if (
        report.meta.materialityStrategy == "complete_coverage"
        and report.assessmentInput is None
    ):
        return "current"
    assessment = report.assessmentInput
    required_ids = {topic.id for topic in applicable_scoring_topics(report)}
    actual_ids = (
        [score.assessmentTopicId for score in assessment.scores]
        if assessment is not None
        else []
    )
    if (
        assessment is None
        or set(actual_ids) != required_ids
        or len(actual_ids) != len(set(actual_ids))
    ):
        return "missing"
    if stored_fingerprint is None:
        return "unverified"
    if stored_fingerprint != current_fingerprint:
        return "stale"
    return "current"


def _quantitative_status(
    metrics: QuantitativeMetricsMeta,
    *,
    stored_fingerprint: str | None,
    current_fingerprint: str,
    package: KnowledgePackage,
    allowed_metric_keys: frozenset[str] | None = None,
) -> StructuredInputStatus:
    try:
        _validate_complete_quantitative_metrics(
            metrics,
            package=package,
            allowed_metric_keys=allowed_metric_keys,
        )
    except StructuredInputRequestError:
        return "missing"
    if stored_fingerprint is None:
        return "unverified"
    if stored_fingerprint != current_fingerprint:
        return "stale"
    return "current"


def _assessment_status_for(
    report: Report,
    snapshot: reports_dal.LockedLightweightReportState,
    context: StructuredInputContext,
) -> StructuredInputStatus:
    return _assessment_status(
        report,
        stored_fingerprint=(
            snapshot.state.structuredInputFreshness.assessmentContextFingerprint
        ),
        current_fingerprint=assessment_context_fingerprint(report, context),
    )


def _quantitative_status_for(
    report: Report,
    snapshot: reports_dal.LockedLightweightReportState,
    context: StructuredInputContext,
    *,
    allowed_metric_keys: frozenset[str] | None = None,
) -> StructuredInputStatus:
    return _quantitative_status(
        report.meta.quantitativeMetrics,
        package=knowledge_package_of(report),
        stored_fingerprint=(
            snapshot.state.structuredInputFreshness.quantitativeMetricsContextFingerprint
        ),
        current_fingerprint=quantitative_metrics_context_fingerprint(
            report,
            context,
        ),
        allowed_metric_keys=allowed_metric_keys,
    )


def _readiness(
    report: Report,
    *,
    assessment_status: StructuredInputStatus,
    quantitative_status: StructuredInputStatus,
    include_assessment: bool = True,
    allowed_metric_keys: frozenset[str] | None = None,
) -> LightweightReportReadiness:
    return parse_lightweight_report_readiness(
        report,
        assessment_input_status=assessment_status,
        quantitative_metrics_status=quantitative_status,
        include_assessment=include_assessment,
        allowed_metric_keys=allowed_metric_keys,
    )
