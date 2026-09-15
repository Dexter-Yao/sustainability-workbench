# ABOUTME: 轻量版报告级生成的公共投影、命令端口与客户交付物读取边界。
# ABOUTME: 内部审计产物在服务层被结构性排除，Storage 引用和失败代码不会进入客户合同。
# ABOUTME(en): Public projection, command port and customer deliverable read boundary of lightweight report generation.
# ABOUTME(en): Internal audit artifacts are structurally excluded in the service; no Storage refs or failure codes leak.
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

import asyncpg

from sustainability_desk.block_provenance import load_report_block_provenance
from sustainability_desk.contract.block_provenance import ReportBlockProvenanceProjection
from sustainability_desk.contract.report_generation import (
    CreateReportGenerationRequest,
    ReportArtifactKind,
    ReportArtifactProjection,
    ReportGenerationEvent,
    ReportGenerationProjection,
)
from sustainability_desk.persistence import lightweight_report_generations as generations_dal

PUBLIC_ARTIFACT_KINDS: frozenset[str] = frozenset(
    {"word", "review"}
)


class ReportGenerationDomainError(RuntimeError):
    """报告级生成公共服务无法完成请求。"""


class ReportGenerationNotFoundError(ReportGenerationDomainError):
    """指定运行不存在，或不属于当前 Account/Report。"""


class ReportGenerationConflictError(ReportGenerationDomainError):
    """请求与当前报告版本或已有幂等命令冲突。"""


class ReportGenerationArtifactNotFoundError(ReportGenerationDomainError):
    """指定客户交付物不存在或不允许通过客户接口访问。"""


class ReportGenerationArtifactIntegrityError(ReportGenerationDomainError):
    """私有 Storage 内容与持久化指纹不一致。"""


class ReportGenerationEnqueuePort(Protocol):
    """将 API 命令交给唯一生成准备服务，避免路由复制快照和指纹语义。"""

    async def enqueue(
        self,
        *,
        account_id: UUID,
        report_id: UUID,
        request: CreateReportGenerationRequest,
    ) -> UUID: ...


class ReportGenerationArtifactReader(Protocol):
    """按服务端私有引用读取交付物；浏览器永远不会获得该引用。"""

    async def read(self, storage_ref: str) -> bytes: ...


@dataclass(frozen=True)
class ReportArtifactDownload:
    """已完成授权和内容指纹校验的客户交付物。"""

    kind: ReportArtifactKind
    filename: str
    media_type: str
    content: bytes


def _summary(
    run: generations_dal.ReportGenerationRunRecord,
    *,
    completed_block_count: int,
) -> str:
    total = len(run.expected_block_ids)
    if run.status == "queued":
        return "报告生成请求已接收，正在等待处理。"
    if run.status == "running":
        return (
            f"报告正在生成，已完成 {completed_block_count}/{total} 项内容。"
        )
    if run.status == "succeeded":
        return "报告正式稿与审阅版报告已准备完成。"
    if run.status == "superseded":
        return "报告输入已变化，本次运行未覆盖当前报告。"
    return "报告生成未完成，请根据进度说明处理后重试。"


def _projection(
    *,
    run: generations_dal.ReportGenerationRunRecord,
    events: tuple[asyncpg.Record, ...],
    artifacts: tuple[asyncpg.Record, ...],
    workbench_enabled: bool,
    allowed_artifact_kinds: frozenset[str],
) -> ReportGenerationProjection:
    # 完成计数按块身份（payload.blockId）去重：display 标题经祖先回退会让多块同名，
    # 按标题去重曾使进度系统性偏低、进度条卡住。
    completed_block_count = len(
        {
            (row["payload"] or {}).get("blockId") or row["current_object"]
            for row in events
            if row["event_type"] == "block_completed"
            and ((row["payload"] or {}).get("blockId") or row["current_object"])
            is not None
        }
    )
    public_artifacts = tuple(
        ReportArtifactProjection(
            artifact_id=row["id"],
            kind=row["kind"],
            filename=row["filename"],
            media_type=row["media_type"],
            download_href=(
                f"/api/reports/{run.report_id}/generations/{run.run_id}"
                f"/artifacts/{row['id']}/download"
            ),
        )
        for row in artifacts
        if row["kind"] in PUBLIC_ARTIFACT_KINDS
        and row["kind"] in allowed_artifact_kinds
    )
    return ReportGenerationProjection(
        run_id=run.run_id,
        report_id=run.report_id,
        status=run.status,
        base_report_state_seq=run.base_report_state_seq,
        result_report_state_seq=run.result_report_state_seq,
        completed_block_count=completed_block_count,
        total_block_count=len(run.expected_block_ids),
        summary=_summary(
            run,
            completed_block_count=completed_block_count,
        ),
        started_at=run.started_at,
        events=tuple(
            ReportGenerationEvent(
                sequence=sequence,
                event_type=row["event_type"],
                message=row["user_message"],
                # 写入端已存用户可读章节标题，直接透传；曾误当 block_id 查表致全部置空。
                current_object=row["current_object"],
                action_required=bool(row["action_required"]),
                occurred_at=row["created_at"],
            )
            for sequence, row in enumerate(events, start=1)
        ),
        artifacts=public_artifacts,
        workbench_enabled=workbench_enabled,
    )


class LightweightReportGenerationService:
    """报告级 API 用例服务；Account/Report 授权由路由依赖先行裁决。"""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        account_id: UUID,
        report_id: UUID,
        workbench_enabled: bool,
        enqueue_port: ReportGenerationEnqueuePort,
        artifact_reader: ReportGenerationArtifactReader,
        allowed_artifact_kinds: frozenset[str] = PUBLIC_ARTIFACT_KINDS,
    ) -> None:
        self._pool = pool
        self._account_id = account_id
        self._report_id = report_id
        self._workbench_enabled = workbench_enabled
        self._enqueue_port = enqueue_port
        self._artifact_reader = artifact_reader
        self._allowed_artifact_kinds = allowed_artifact_kinds

    async def create_generation(
        self,
        request: CreateReportGenerationRequest,
    ) -> ReportGenerationProjection:
        try:
            run_id = await self._enqueue_port.enqueue(
                account_id=self._account_id,
                report_id=self._report_id,
                request=request,
            )
        except generations_dal.ReportGenerationConflictError as error:
            raise ReportGenerationConflictError(str(error)) from error
        return await self.get_generation(run_id)

    async def get_generation(
        self,
        run_id: UUID,
    ) -> ReportGenerationProjection:
        try:
            run, events, artifacts = await generations_dal.get_generation(
                self._pool,
                account_id=self._account_id,
                report_id=self._report_id,
                run_id=run_id,
            )
        except generations_dal.ReportGenerationPersistenceError as error:
            raise ReportGenerationNotFoundError(
                "报告生成运行不存在"
            ) from error
        return _projection(
            run=run,
            events=events,
            artifacts=artifacts,
            workbench_enabled=self._workbench_enabled,
            allowed_artifact_kinds=self._allowed_artifact_kinds,
        )

    async def get_latest_generation(self) -> ReportGenerationProjection:
        run = await generations_dal.latest_generation(
            self._pool,
            account_id=self._account_id,
            report_id=self._report_id,
        )
        if run is None:
            raise ReportGenerationNotFoundError("报告尚未发起生成")
        return await self.get_generation(run.run_id)

    async def get_block_provenance(self) -> ReportBlockProvenanceProjection:
        """Per-block provenance of the latest successful revision; 404 semantics when none exists."""

        run = await generations_dal.latest_successful_generation(
            self._pool,
            account_id=self._account_id,
            report_id=self._report_id,
        )
        if run is None or run.result_revision_id is None:
            raise ReportGenerationNotFoundError("报告尚未成功生成")
        return await load_report_block_provenance(
            self._pool,
            account_id=self._account_id,
            report_id=self._report_id,
            run=run,
        )

    async def download_artifact(
        self,
        *,
        run_id: UUID,
        artifact_id: UUID,
    ) -> ReportArtifactDownload:
        try:
            run, _events, artifacts = await generations_dal.get_generation(
                self._pool,
                account_id=self._account_id,
                report_id=self._report_id,
                run_id=run_id,
            )
        except generations_dal.ReportGenerationPersistenceError as error:
            raise ReportGenerationArtifactNotFoundError(
                "报告交付物不存在"
            ) from error
        if run.status != "succeeded":
            raise ReportGenerationArtifactNotFoundError(
                "报告交付物不存在"
            )
        row = next(
            (
                item
                for item in artifacts
                if item["id"] == artifact_id
                and item["kind"] in PUBLIC_ARTIFACT_KINDS
                and item["kind"] in self._allowed_artifact_kinds
            ),
            None,
        )
        if row is None:
            raise ReportGenerationArtifactNotFoundError(
                "报告交付物不存在"
            )
        content = await self._artifact_reader.read(row["storage_ref"])
        if sha256(content).hexdigest() != row["content_fingerprint"]:
            raise ReportGenerationArtifactIntegrityError(
                "报告交付物完整性验证失败"
            )
        return ReportArtifactDownload(
            kind=row["kind"],
            filename=row["filename"],
            media_type=row["media_type"],
            content=content,
        )
