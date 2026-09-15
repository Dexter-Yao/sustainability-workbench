# ABOUTME: 持久化单文件 Agent、资料快照和章节 Mapping 的可恢复运行与不可变 lineage。
# ABOUTME: 本模块不解释资料语义，也不承载人工确认事实。
# ABOUTME(en): Persists resumable runs and immutable lineage for per-file Agents, material snapshots and Mapping.
# ABOUTME(en): This module does not interpret material semantics, nor does it carry human confirmation facts.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4, uuid5

import asyncpg
from pydantic import BaseModel, ConfigDict

from sustainability_desk.material.intake.file_agent_contract import (
    FileDossier,
    FileAgentContext,
    FileAgentRunCheckpoint,
    FileAgentRunReceipt,
    FileAgentRunResult,
)
from sustainability_desk.material.intake.image_agent_contract import (
    ImageAgentContext,
    ImageAgentRunReceipt,
)
from sustainability_desk.material.intake.models import UserFileDeclarationRevision
from sustainability_desk.material.mapping.agent import MappingDossierEntry
from sustainability_desk.material.mapping.decisions import ValidatedMappingResult
from sustainability_desk.material.mapping.scope import MappingScopeDefinition
from sustainability_desk.material.mapping.snapshot import MaterialSetSnapshot

type ImageAgentRunStatus = Literal[
    "queued", "running", "succeeded", "failed", "superseded",
]

type PipelineRunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "needs_attention",
    "failed",
    "superseded",
]


class MaterialAgentPipelinePersistenceError(RuntimeError):
    """新资料 Agent 链路的持久化状态与调用合同不一致。"""


class MaterialAgentPipelineLeaseError(MaterialAgentPipelinePersistenceError):
    """运行租约不存在、已过期或已被其他 worker 接管。"""


class MappingRunInput(BaseModel):
    """章节 Mapping 的冻结输入，仅标识 File Agent 终态 Dossier 与已编译 scope。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: MappingScopeDefinition
    dossier_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class FileAgentRunRecord:
    """排队或终结后的 File Agent 运行记录。"""

    run_id: UUID
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    binding_id: UUID
    source_id: UUID
    declaration_revision_id: UUID
    input_fingerprint: str
    idempotency_key: str
    harness_version: str
    status: PipelineRunStatus
    attempt: int
    max_attempts: int
    context: FileAgentContext
    checkpoint: FileAgentRunCheckpoint | None
    dossier_id: UUID | None


@dataclass(frozen=True)
class FileAgentRunLease:
    """worker 对一次 File Agent 尝试的短期执行权。"""

    run_id: UUID
    lease_token: UUID
    attempt: int
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    binding_id: UUID
    input_fingerprint: str
    context: FileAgentContext
    checkpoint: FileAgentRunCheckpoint | None


@dataclass(frozen=True)
class ImageAgentRunRecord:
    """排队或终结后的 Image Agent 运行记录；表结构无 checkpoint/dossier_id。"""

    run_id: UUID
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    binding_id: UUID
    source_id: UUID
    declaration_revision_id: UUID
    input_fingerprint: str
    idempotency_key: str
    harness_version: str
    status: ImageAgentRunStatus
    attempt: int
    max_attempts: int
    context: ImageAgentContext
    updated_at: datetime


@dataclass(frozen=True)
class ImageAgentRunLease:
    """worker 对一次 Image Agent 尝试的短期执行权。"""

    run_id: UUID
    lease_token: UUID
    attempt: int
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    binding_id: UUID
    source_id: UUID
    input_fingerprint: str
    context: ImageAgentContext


@dataclass(frozen=True)
class MaterialSetSnapshotRecord:
    """数据库中的不可变资料集合快照。"""

    account_id: UUID
    workspace_id: UUID
    snapshot: MaterialSetSnapshot


@dataclass(frozen=True)
class CurrentDossierRecord:
    """当前 active Binding 对应的最新有效 Dossier 与用户声明。"""

    binding_id: UUID
    source_id: UUID
    object_path: str
    filename: str
    declaration: UserFileDeclarationRevision
    dossier: FileDossier

    def mapping_entry(self) -> MappingDossierEntry:
        """投影 Mapping Agent 的高信号 dossier 入口。"""

        return MappingDossierEntry(
            dossier=self.dossier,
            filename=self.filename,
            user_description=self.declaration.description,
        )


@dataclass(frozen=True)
class MaterialPipelineStatus:
    """准备中心所需的资料处理与资料映射运行摘要。"""

    file_queued_or_running: int
    mapping_queued_or_running: int
    file_needs_attention: int
    mapping_needs_attention: int
    file_failed: int
    mapping_failed: int
    # 排版素材的图片识别运行；与 File Agent 同属"文件仍在处理"，但不进 Mapping。
    image_queued_or_running: int = 0

    @property
    def queued_or_running(self) -> int:
        """保留聚合值给不区分阶段的内部诊断使用。"""

        return self.file_queued_or_running + self.mapping_queued_or_running

    @property
    def needs_attention(self) -> int:
        """保留聚合值给不区分阶段的内部诊断使用。"""

        return self.file_needs_attention + self.mapping_needs_attention

    @property
    def failed(self) -> int:
        """保留聚合值给不区分阶段的内部诊断使用。"""

        return self.file_failed + self.mapping_failed


@dataclass(frozen=True)
class CurrentFileAgentRun:
    """一个当前文件 binding 最近一次 File Agent 运行的受限投影。"""

    binding_id: UUID
    status: PipelineRunStatus
    dossier: FileDossier | None
    updated_at: datetime


@dataclass(frozen=True)
class MappingRunRecord:
    """章节 Mapping 的排队或终结记录。"""

    run_id: UUID
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    scope_id: str
    input_fingerprint: str
    idempotency_key: str
    mapping_policy_id: str
    harness_version: str
    status: PipelineRunStatus
    attempt: int
    max_attempts: int
    input: MappingRunInput


@dataclass(frozen=True)
class MappingRunLease:
    """worker 对一次章节 Mapping 尝试的短期执行权。"""

    run_id: UUID
    lease_token: UUID
    attempt: int
    account_id: UUID
    report_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    input_fingerprint: str
    input: MappingRunInput


@dataclass(frozen=True)
class MappingTraceRecord:
    """冻结资料快照中一次成功 Mapping 的观测定位，不复制模型正文。"""

    run_id: UUID
    scope_id: str
    input_fingerprint: str
    observation_run_id: str


def _file_run(row: asyncpg.Record) -> FileAgentRunRecord:
    checkpoint_payload = row["checkpoint"]
    return FileAgentRunRecord(
        run_id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        binding_id=row["binding_id"],
        source_id=row["source_id"],
        declaration_revision_id=row["declaration_revision_id"],
        input_fingerprint=row["input_fingerprint"],
        idempotency_key=row["idempotency_key"],
        harness_version=row["harness_version"],
        status=row["status"],
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        context=FileAgentContext.model_validate(row["input_payload"]),
        checkpoint=(
            FileAgentRunCheckpoint.model_validate(checkpoint_payload)
            if checkpoint_payload is not None
            else None
        ),
        dossier_id=row["dossier_id"],
    )


def _image_run(row: asyncpg.Record) -> ImageAgentRunRecord:
    return ImageAgentRunRecord(
        run_id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        binding_id=row["binding_id"],
        source_id=row["source_id"],
        declaration_revision_id=row["declaration_revision_id"],
        input_fingerprint=row["input_fingerprint"],
        idempotency_key=row["idempotency_key"],
        harness_version=row["harness_version"],
        status=row["status"],
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        context=ImageAgentContext.model_validate(row["input_payload"]),
        updated_at=row["updated_at"],
    )


def _mapping_run(row: asyncpg.Record) -> MappingRunRecord:
    return MappingRunRecord(
        run_id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        snapshot_id=row["snapshot_id"],
        scope_id=row["scope_id"],
        input_fingerprint=row["input_fingerprint"],
        idempotency_key=row["idempotency_key"],
        mapping_policy_id=row["mapping_policy_id"],
        harness_version=row["harness_version"],
        status=row["status"],
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        input=MappingRunInput.model_validate(row["input_payload"]),
    )


async def enqueue_file_agent_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    declaration_revision_id: UUID,
    context: FileAgentContext,
    input_fingerprint: str,
    idempotency_key: str,
    harness_version: str,
    max_attempts: int = 3,
) -> FileAgentRunRecord:
    """幂等创建一项 File Agent 运行；相同业务输入返回原运行。"""

    if max_attempts < 1:
        raise ValueError("max_attempts 必须大于等于 1")
    row = await pool.fetchrow(
        """
        insert into file_agent_runs (
          id, account_id, report_id, workspace_id, binding_id, source_id,
          declaration_revision_id, input_fingerprint, idempotency_key,
          harness_version, input_payload, max_attempts, status
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'queued')
        on conflict (report_id, idempotency_key) do update
        set id = file_agent_runs.id
        returning *
        """,
        run_id,
        account_id,
        report_id,
        workspace_id,
        binding_id,
        context.source_revision.source_id,
        declaration_revision_id,
        input_fingerprint,
        idempotency_key,
        harness_version,
        context.model_dump(mode="json"),
        max_attempts,
    )
    if row is None:
        raise MaterialAgentPipelinePersistenceError("File Agent 运行写入后无法读取")
    return _file_run(row)


async def claim_file_agent_run(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    lease_seconds: int = 300,
    report_id: UUID | None = None,
) -> FileAgentRunLease | None:
    """有界 worker 以 skip locked 领取一个可执行 File Agent 节点。"""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须为正数")
    lease_token = uuid4()
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """
            with candidate as (
              select id
              from file_agent_runs
              where status = 'queued' and attempt < max_attempts
                and ($4::uuid is null or report_id = $4)
              order by created_at, id
              for update skip locked
              limit 1
            )
            update file_agent_runs run
            set status = 'running',
                attempt = run.attempt + 1,
                leased_by = $1,
                lease_token = $2,
                lease_expires_at = now() + $3::interval,
                started_at = coalesce(run.started_at, now()),
                updated_at = now()
            from candidate
            where run.id = candidate.id
            returning run.id, run.lease_token, run.attempt,
                      run.account_id, run.report_id, run.workspace_id,
                      run.binding_id, run.input_fingerprint,
                      run.input_payload, run.checkpoint
            """,
            worker_id,
            lease_token,
            timedelta(seconds=lease_seconds),
            report_id,
        )
    if row is None:
        return None
    checkpoint_payload = row["checkpoint"]
    return FileAgentRunLease(
        run_id=row["id"],
        lease_token=row["lease_token"],
        attempt=int(row["attempt"]),
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        binding_id=row["binding_id"],
        input_fingerprint=row["input_fingerprint"],
        context=FileAgentContext.model_validate(row["input_payload"]),
        checkpoint=(
            FileAgentRunCheckpoint.model_validate(checkpoint_payload)
            if checkpoint_payload is not None
            else None
        ),
    )


async def finish_file_agent_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    lease_token: UUID,
    result: FileAgentRunResult,
    retryable_failure: bool = False,
) -> None:
    """持有效租约原子写入 FileDossier、恢复点和运行终态。

    retryable_failure 只对 failed 结果生效：attempt 仍有余量时回置 queued 等待
    重新 claim，并保留本次 failure_code 与 receipt 作为失败痕迹（下次终结覆盖）；
    attempt 用尽或不可重试错误才落终态 failed。
    """

    if result.receipt.run_id != run_id:
        raise ValueError("File Agent receipt 与待完成运行身份不一致")
    if retryable_failure and result.status != "failed":
        raise ValueError("retryable_failure 只能用于 failed 结果")
    terminal_status: PipelineRunStatus = {
        "completed": "succeeded",
        "suspended": "needs_attention",
        "failed": "failed",
    }[result.status]
    async with pool.acquire() as connection, connection.transaction():
        run = await connection.fetchrow(
            """
            select id, account_id, report_id, workspace_id, binding_id,
                   source_id, attempt, max_attempts, input_payload
            from file_agent_runs
            where id = $1 and status = 'running' and lease_token = $2
              and lease_expires_at > now()
            for update
            """,
            run_id,
            lease_token,
        )
        if run is None:
            raise MaterialAgentPipelineLeaseError(str(run_id))
        if int(run["attempt"]) != result.receipt.attempt:
            raise MaterialAgentPipelinePersistenceError(
                "File Agent receipt attempt 与数据库运行不一致"
            )
        frozen_context = FileAgentContext.model_validate(run["input_payload"])

        dossier_id: UUID | None = None
        if result.dossier is not None:
            dossier = result.dossier
            if (
                dossier.source_revision != frozen_context.source_revision
                or dossier.source_revision
                != result.receipt.source_revision
            ):
                raise MaterialAgentPipelinePersistenceError(
                    "FileDossier 来源版本与运行输入不一致"
                )
            await connection.execute(
                """
                update file_dossiers
                set superseded_at = now()
                where binding_id = $1 and superseded_at is null
                """,
                run["binding_id"],
            )
            await connection.execute(
                """
                insert into file_dossiers (
                  id, run_id, account_id, report_id, workspace_id, binding_id,
                  source_id, source_sha256, declaration_revision,
                  dossier_fingerprint, dossier_payload
                ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                dossier.dossier_id,
                run_id,
                run["account_id"],
                run["report_id"],
                run["workspace_id"],
                run["binding_id"],
                dossier.source_revision.source_id,
                dossier.source_revision.source_sha256,
                dossier.source_revision.declaration_revision,
                dossier.dossier_fingerprint,
                dossier.model_dump(mode="json"),
            )
            dossier_id = dossier.dossier_id

        requeue_for_retry = (
            retryable_failure
            and terminal_status == "failed"
            and int(run["attempt"]) < int(run["max_attempts"])
        )
        if requeue_for_retry:
            update_sql = """
            update file_agent_runs
            set status = 'queued', leased_by = null,
                lease_token = null, lease_expires_at = null,
                output_payload = $3, checkpoint = coalesce($4, checkpoint),
                receipt = $5, dossier_id = $6, failure_code = $7,
                finished_at = null, updated_at = now()
            where id = $1 and lease_token = $2 and status = 'running'
            """
        else:
            update_sql = f"""
            update file_agent_runs
            set status = '{terminal_status}', leased_by = null,
                lease_token = null, lease_expires_at = null,
                output_payload = $3, checkpoint = $4, receipt = $5,
                dossier_id = $6, failure_code = $7,
                finished_at = now(), updated_at = now()
            where id = $1 and lease_token = $2 and status = 'running'
            """
        update_result = await connection.execute(
            update_sql,
            run_id,
            lease_token,
            result.model_dump(mode="json"),
            (
                result.checkpoint.model_dump(mode="json")
                if result.checkpoint is not None
                else None
            ),
            result.receipt.model_dump(mode="json"),
            dossier_id,
            result.receipt.failure_code,
        )
        if update_result != "UPDATE 1":
            raise MaterialAgentPipelineLeaseError(str(run_id))


async def requeue_file_agent_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    expected_input_fingerprint: str,
) -> None:
    """在外部条件已补齐后恢复 needs_attention 节点，保留原 checkpoint。"""

    result = await pool.execute(
        """
        update file_agent_runs
        set status = 'queued', finished_at = null, failure_code = null,
            updated_at = now()
        where id = $1 and status = 'needs_attention'
          and input_fingerprint = $2 and attempt < max_attempts
        """,
        run_id,
        expected_input_fingerprint,
    )
    if result != "UPDATE 1":
        raise MaterialAgentPipelinePersistenceError(
            "File Agent 运行不可恢复或输入已变化"
        )


async def supersede_file_agent_runs(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    binding_id: UUID,
    except_input_fingerprint: str,
) -> None:
    """声明或来源变化时使旧运行失效；旧 dossier 与收据继续保留。"""

    await pool.execute(
        """
        update file_agent_runs
        set status = 'superseded', leased_by = null, lease_token = null,
            lease_expires_at = null, superseded_at = now(),
            finished_at = coalesce(finished_at, now()), updated_at = now()
        where report_id = $1 and binding_id = $2
          and input_fingerprint <> $3
          and status in ('queued', 'running', 'succeeded', 'needs_attention')
        """,
        report_id,
        binding_id,
        except_input_fingerprint,
    )


async def enqueue_image_agent_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    declaration_revision_id: UUID,
    context: ImageAgentContext,
    input_fingerprint: str,
    idempotency_key: str,
    harness_version: str,
    max_attempts: int = 3,
) -> ImageAgentRunRecord:
    """幂等创建一项 Image Agent 运行；相同业务输入返回原运行。"""

    if max_attempts < 1:
        raise ValueError("max_attempts 必须大于等于 1")
    row = await pool.fetchrow(
        """
        insert into image_agent_runs (
          id, account_id, report_id, workspace_id, binding_id, source_id,
          declaration_revision_id, input_fingerprint, idempotency_key,
          harness_version, input_payload, max_attempts, status
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'queued')
        on conflict (report_id, idempotency_key) do update
        set id = image_agent_runs.id
        returning *
        """,
        run_id,
        account_id,
        report_id,
        workspace_id,
        binding_id,
        context.source_revision.source_id,
        declaration_revision_id,
        input_fingerprint,
        idempotency_key,
        harness_version,
        context.model_dump(mode="json"),
        max_attempts,
    )
    if row is None:
        raise MaterialAgentPipelinePersistenceError("Image Agent 运行写入后无法读取")
    return _image_run(row)


async def claim_image_agent_run(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    lease_seconds: int = 300,
    report_id: UUID | None = None,
) -> ImageAgentRunLease | None:
    """有界 worker 以 skip locked 领取一个可执行 Image Agent 节点。"""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须为正数")
    lease_token = uuid4()
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """
            with candidate as (
              select id
              from image_agent_runs
              where status = 'queued' and attempt < max_attempts
                and ($4::uuid is null or report_id = $4)
              order by created_at, id
              for update skip locked
              limit 1
            )
            update image_agent_runs run
            set status = 'running',
                attempt = run.attempt + 1,
                leased_by = $1,
                lease_token = $2,
                lease_expires_at = now() + $3::interval,
                started_at = coalesce(run.started_at, now()),
                updated_at = now()
            from candidate
            where run.id = candidate.id
            returning run.id, run.lease_token, run.attempt,
                      run.account_id, run.report_id, run.workspace_id,
                      run.binding_id, run.source_id, run.input_fingerprint,
                      run.input_payload
            """,
            worker_id,
            lease_token,
            timedelta(seconds=lease_seconds),
            report_id,
        )
    if row is None:
        return None
    return ImageAgentRunLease(
        run_id=row["id"],
        lease_token=row["lease_token"],
        attempt=int(row["attempt"]),
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        binding_id=row["binding_id"],
        source_id=row["source_id"],
        input_fingerprint=row["input_fingerprint"],
        context=ImageAgentContext.model_validate(row["input_payload"]),
    )


async def finish_image_agent_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    lease_token: UUID,
    status: Literal["succeeded", "failed"],
    output_payload: dict | None,
    receipt: ImageAgentRunReceipt,
    retryable_failure: bool = False,
) -> None:
    """持有效租约终结一次 Image Agent 尝试；成功须携带 output_payload。

    retryable_failure 只对 failed 生效：attempt 仍有余量时回置 queued 等待重新
    claim，并保留本次 failure_code 与 receipt 作为失败痕迹（下次终结覆盖）。
    """

    if status == "succeeded" and output_payload is None:
        raise ValueError("成功运行必须携带 output_payload")
    if status == "succeeded" and retryable_failure:
        raise ValueError("retryable_failure 只能用于 failed 结果")
    result = await pool.execute(
        f"""
        update image_agent_runs
        set status = case when $6::boolean and attempt < max_attempts
                          then 'queued' else '{status}' end,
            leased_by = null, lease_token = null, lease_expires_at = null,
            output_payload = $3, receipt = $4, failure_code = $5,
            finished_at = case when $6::boolean and attempt < max_attempts
                               then null else now() end,
            updated_at = now()
        where id = $1 and lease_token = $2 and status = 'running'
        """,
        run_id,
        lease_token,
        output_payload,
        receipt.model_dump(mode="json"),
        receipt.failure_code,
        retryable_failure,
    )
    if result != "UPDATE 1":
        raise MaterialAgentPipelineLeaseError(str(run_id))


async def supersede_image_agent_runs(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    binding_id: UUID,
    except_input_fingerprint: str,
) -> None:
    """声明或来源变化时使旧 Image Agent 运行失效；已提升的 evidence_assets 继续保留。"""

    await pool.execute(
        """
        update image_agent_runs
        set status = 'superseded', leased_by = null, lease_token = null,
            lease_expires_at = null, superseded_at = now(),
            finished_at = coalesce(finished_at, now()), updated_at = now()
        where report_id = $1 and binding_id = $2
          and input_fingerprint <> $3
          and status in ('queued', 'running', 'succeeded')
        """,
        report_id,
        binding_id,
        except_input_fingerprint,
    )


async def unfinished_image_agent_run_count(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> int:
    """统计当前活跃排版素材 binding 中尚未完成的 Image Agent 运行；只计 queued/running。"""

    count = await pool.fetchval(
        """
        select count(*)
        from (
          select binding.id, current_run.status
          from report_material_bindings binding
          join material_workspaces workspace on workspace.id = binding.workspace_id
          join material_sources source
            on source.id = binding.source_id and source.workspace_id = binding.workspace_id
          join lateral (
            select revision.role
            from user_file_declaration_revisions revision
            where revision.binding_id = binding.id
            order by revision.revision desc, revision.id desc
            limit 1
          ) declaration on true
          left join lateral (
            select run.status
            from image_agent_runs run
            where run.binding_id = binding.id
              and run.report_id = $1 and run.account_id = $2
            order by run.created_at desc, run.id desc
            limit 1
          ) current_run on true
          where workspace.report_id = $1 and workspace.account_id = $2
            and binding.status = 'active'
            and source.status not in ('failed', 'deleted')
            and declaration.role = 'layout_asset'
        ) current
        where current.status in ('queued', 'running')
        """,
        report_id,
        account_id,
    )
    return int(count or 0)


async def never_enqueued_image_agent_binding_ids(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> tuple[UUID, ...]:
    """找出说明已填却没有有效 Image Agent 运行的当前活跃排版素材 binding。

    说明为空的素材尚不具备入队条件，不算遗漏；superseded 表示当前没有有效 run，
    与从未入队同处境——都靠补入队恢复。
    """

    rows = await pool.fetch(
        """
        select current.id as binding_id
        from (
          select binding.id, current_run.status
          from report_material_bindings binding
          join material_workspaces workspace on workspace.id = binding.workspace_id
          join material_sources source
            on source.id = binding.source_id and source.workspace_id = binding.workspace_id
          join lateral (
            select revision.role, revision.description
            from user_file_declaration_revisions revision
            where revision.binding_id = binding.id
            order by revision.revision desc, revision.id desc
            limit 1
          ) declaration on true
          left join lateral (
            select run.status
            from image_agent_runs run
            where run.binding_id = binding.id
              and run.report_id = $1 and run.account_id = $2
            order by run.created_at desc, run.id desc
            limit 1
          ) current_run on true
          where workspace.report_id = $1 and workspace.account_id = $2
            and binding.status = 'active'
            and source.status not in ('failed', 'deleted')
            and declaration.role = 'layout_asset'
            and btrim(declaration.description) <> ''
        ) current
        where current.status is null or current.status = 'superseded'
        """,
        report_id,
        account_id,
    )
    return tuple(row["binding_id"] for row in rows)


async def list_current_image_agent_runs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> tuple[ImageAgentRunRecord, ...]:
    """读取每个当前活跃排版素材 binding 的最新非 superseded Image Agent 运行，供准备中心投影。"""

    rows = await pool.fetch(
        """
        select distinct on (run.binding_id) run.*
        from image_agent_runs run
        join report_material_bindings binding on binding.id = run.binding_id
        join material_workspaces workspace on workspace.id = run.workspace_id
        where run.account_id = $1 and run.report_id = $2
          and workspace.account_id = $1 and workspace.report_id = $2
          and binding.status = 'active'
          and run.status <> 'superseded'
        order by run.binding_id, run.created_at desc, run.id desc
        """,
        account_id,
        report_id,
    )
    return tuple(_image_run(row) for row in rows)


async def load_image_agent_receipts(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> tuple[ImageAgentRunReceipt, ...]:
    """读取每个当前活跃排版素材 binding 最新成功运行的收据，供内部审计包复盘。"""

    rows = await pool.fetch(
        """
        select distinct on (run.binding_id) run.receipt
        from image_agent_runs run
        join report_material_bindings binding on binding.id = run.binding_id
        join material_workspaces workspace on workspace.id = run.workspace_id
        where run.account_id = $1 and run.report_id = $2
          and workspace.account_id = $1 and workspace.report_id = $2
          and binding.status = 'active'
          and run.status = 'succeeded'
        order by run.binding_id, run.created_at desc, run.id desc
        """,
        account_id,
        report_id,
    )
    if any(row["receipt"] is None for row in rows):
        raise MaterialAgentPipelinePersistenceError(
            "成功的 Image Agent 运行缺少收据"
        )
    return tuple(
        ImageAgentRunReceipt.model_validate(row["receipt"]) for row in rows
    )


async def store_material_set_snapshot(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    snapshot: MaterialSetSnapshot,
) -> MaterialSetSnapshotRecord:
    """按输入指纹幂等保存不可变资料集合。

    同指纹重建时快照身份与 payload 不变，但刷新 created_at 列——该列的语义是
    「最近一次由同步流程确认/重建的时间」，latest_material_set_snapshot 据此定位
    当前资料集；否则用户改回旧资料组合后，「最新快照」会错误指向已被替换的集合。
    """

    row = await pool.fetchrow(
        """
        insert into material_set_snapshots (
          id, account_id, report_id, workspace_id, input_fingerprint,
          snapshot_payload, created_at
        ) values ($1, $2, $3, $4, $5, $6, $7)
        on conflict (report_id, input_fingerprint) do update
        set created_at = excluded.created_at
        returning *
        """,
        snapshot.snapshot_id,
        account_id,
        snapshot.report_id,
        workspace_id,
        snapshot.input_fingerprint,
        snapshot.model_dump(mode="json"),
        snapshot.created_at,
    )
    if row is None:
        raise MaterialAgentPipelinePersistenceError("资料集合快照写入后无法读取")
    return MaterialSetSnapshotRecord(
        account_id=row["account_id"],
        workspace_id=row["workspace_id"],
        snapshot=MaterialSetSnapshot.model_validate(row["snapshot_payload"]),
    )


async def enqueue_mapping_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    snapshot_id: UUID,
    scope: MappingScopeDefinition,
    dossier_ids: tuple[UUID, ...],
    input_fingerprint: str,
    idempotency_key: str,
    mapping_policy_id: str,
    harness_version: str,
    max_attempts: int = 3,
) -> MappingRunRecord:
    """幂等创建一个章节 Mapping 运行，不把 dossier 正文复制进输入。"""

    if max_attempts < 1:
        raise ValueError("max_attempts 必须大于等于 1")
    mapping_input = MappingRunInput(
        scope=scope,
        dossier_ids=dossier_ids,
    )
    row = await pool.fetchrow(
        """
        insert into material_mapping_runs (
          id, account_id, report_id, workspace_id, snapshot_id, scope_id,
          input_fingerprint, idempotency_key, mapping_policy_id,
          harness_version, input_payload, max_attempts, status
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'queued')
        on conflict (report_id, idempotency_key) do update
        set status = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then 'queued'
              else material_mapping_runs.status
            end,
            leased_by = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then null
              else material_mapping_runs.leased_by
            end,
            lease_token = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then null
              else material_mapping_runs.lease_token
            end,
            lease_expires_at = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then null
              else material_mapping_runs.lease_expires_at
            end,
            finished_at = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then null
              else material_mapping_runs.finished_at
            end,
            receipt = case
              when material_mapping_runs.status = 'failed'
                and material_mapping_runs.attempt < material_mapping_runs.max_attempts
              then null
              else material_mapping_runs.receipt
            end
        returning *
        """,
        run_id,
        account_id,
        report_id,
        workspace_id,
        snapshot_id,
        scope.scope_id,
        input_fingerprint,
        idempotency_key,
        mapping_policy_id,
        harness_version,
        mapping_input.model_dump(mode="json"),
        max_attempts,
    )
    if row is None:
        raise MaterialAgentPipelinePersistenceError("Mapping 运行写入后无法读取")
    return _mapping_run(row)


async def claim_mapping_run(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    lease_seconds: int = 960,
    report_id: UUID | None = None,
    scope_id: str | None = None,
) -> MappingRunLease | None:
    """有界 worker 以 skip locked 领取一个章节 Mapping 节点。"""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须为正数")
    lease_token = uuid4()
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """
            with candidate as (
              select id
              from material_mapping_runs
              where status = 'queued' and attempt < max_attempts
                and ($4::uuid is null or report_id = $4)
                and ($5::text is null or scope_id = $5)
              order by created_at, id
              for update skip locked
              limit 1
            )
            update material_mapping_runs run
            set status = 'running',
                attempt = run.attempt + 1,
                leased_by = $1,
                lease_token = $2,
                lease_expires_at = now() + $3::interval,
                started_at = coalesce(run.started_at, now()),
                updated_at = now()
            from candidate
            where run.id = candidate.id
            returning run.id, run.lease_token, run.attempt,
                      run.account_id, run.report_id, run.workspace_id,
                      run.snapshot_id, run.input_fingerprint, run.input_payload
            """,
            worker_id,
            lease_token,
            timedelta(seconds=lease_seconds),
            report_id,
            scope_id,
        )
    if row is None:
        return None
    return MappingRunLease(
        run_id=row["id"],
        lease_token=row["lease_token"],
        attempt=int(row["attempt"]),
        account_id=row["account_id"],
        report_id=row["report_id"],
        workspace_id=row["workspace_id"],
        snapshot_id=row["snapshot_id"],
        input_fingerprint=row["input_fingerprint"],
        input=MappingRunInput.model_validate(row["input_payload"]),
    )


async def finish_mapping_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    lease_token: UUID,
    result: ValidatedMappingResult,
    receipt: dict[str, object],
) -> None:
    """持有效租约写入 Block 对 FileMaterial 的采用决定。"""

    async with pool.acquire() as connection, connection.transaction():
        run = await connection.fetchrow(
            """
            select run.id, run.account_id, run.report_id, run.workspace_id,
                   run.snapshot_id, run.scope_id, run.attempt,
                   snapshot.snapshot_payload
            from material_mapping_runs run
            join material_set_snapshots snapshot on snapshot.id = run.snapshot_id
            where run.id = $1 and run.status = 'running'
              and run.lease_token = $2 and run.lease_expires_at > now()
            for update of run
            """,
            run_id,
            lease_token,
        )
        if run is None:
            raise MaterialAgentPipelineLeaseError(str(run_id))
        if result.scope_id != run["scope_id"]:
            raise MaterialAgentPipelinePersistenceError(
                "Mapping 结果不属于当前章节 scope"
            )
        snapshot = MaterialSetSnapshot.model_validate(run["snapshot_payload"])
        snapshot_dossier_ids = {member.dossier_id for member in snapshot.members}

        await connection.execute(
            """
            update material_mapping_runs
            set status = 'superseded', superseded_at = now(),
                finished_at = coalesce(finished_at, now()), updated_at = now()
            where report_id = $1 and scope_id = $2 and id <> $3
              and status = 'succeeded'
            """,
            run["report_id"],
            run["scope_id"],
            run_id,
        )

        planned_dossier_ids = set(snapshot.mapping_plan.candidate_dossier_ids)
        if not planned_dossier_ids.issubset(snapshot_dossier_ids):
            raise MaterialAgentPipelinePersistenceError("冻结 Mapping plan 引用了快照外资料")
        decision_material_rows: list[tuple[object, ...]] = []
        for decision in result.block_decisions:
            decision_id = uuid5(run_id, f"block-decision:{decision.block_id}")
            await connection.execute(
                """
                insert into block_material_decisions (
                  id, mapping_run_id, account_id, report_id, snapshot_id,
                  scope_id, block_id, disposition, material_ids,
                  reason, decision_payload
                ) values (
                  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                )
                """,
                decision_id,
                run_id,
                run["account_id"],
                run["report_id"],
                run["snapshot_id"],
                run["scope_id"],
                decision.block_id,
                decision.disposition,
                list(decision.material_ids),
                decision.reason,
                decision.model_dump(mode="json"),
            )
            decision_material_rows.extend(
                (
                    decision_id,
                    material_id,
                    ordinal,
                )
                for ordinal, material_id in enumerate(
                    decision.material_ids,
                    start=1,
                )
            )
        if decision_material_rows:
            await connection.executemany(
                """
                insert into block_material_decision_materials (
                  decision_id, material_id, ordinal
                ) values ($1, $2, $3)
                """,
                decision_material_rows,
            )
        updated = await connection.execute(
            """
            update material_mapping_runs
            set status = 'succeeded', leased_by = null, lease_token = null,
                lease_expires_at = null, result_payload = $3, receipt = $4,
                finished_at = now(), updated_at = now()
            where id = $1 and lease_token = $2 and status = 'running'
            """,
            run_id,
            lease_token,
            result.model_dump(mode="json"),
            receipt,
        )
        if updated != "UPDATE 1":
            raise MaterialAgentPipelineLeaseError(str(run_id))


async def fail_mapping_run(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    lease_token: UUID,
    failure_code: str,
    receipt: dict[str, object],
    needs_attention: bool = False,
    retryable_failure: bool = False,
) -> None:
    """终结 Mapping 尝试，保留失败收据供恢复和审计。

    retryable_failure 只对 failed 生效：attempt 仍有余量时回置 queued 等待重新
    claim，并保留本次 failure_code 与 receipt 作为失败痕迹（下次终结覆盖）。
    """

    if needs_attention and retryable_failure:
        raise ValueError("retryable_failure 不能用于 needs_attention 终态")
    status = "needs_attention" if needs_attention else "failed"
    result = await pool.execute(
        f"""
        update material_mapping_runs
        set status = case when $5::boolean and attempt < max_attempts
                          then 'queued' else '{status}' end,
            leased_by = null, lease_token = null, lease_expires_at = null,
            failure_code = $3, receipt = $4,
            finished_at = case when $5::boolean and attempt < max_attempts
                               then null else now() end,
            updated_at = now()
        where id = $1 and lease_token = $2 and status = 'running'
          and lease_expires_at > now()
        """,
        run_id,
        lease_token,
        failure_code,
        receipt,
        retryable_failure,
    )
    if result != "UPDATE 1":
        raise MaterialAgentPipelineLeaseError(str(run_id))


async def recover_expired_pipeline_runs(pool: asyncpg.Pool) -> None:
    """回收三个运行队列的过期租约；未达上限继续排队，达上限则失败。"""

    for table in ("file_agent_runs", "material_mapping_runs", "image_agent_runs"):
        await pool.execute(
            f"""
            update {table}
            set status = case when attempt < max_attempts then 'queued'
                              else 'failed' end,
                leased_by = null, lease_token = null, lease_expires_at = null,
                failure_code = case when attempt < max_attempts then null
                                    else 'lease_expired_after_max_attempts' end,
                finished_at = case when attempt < max_attempts then null
                                   else now() end,
                updated_at = now()
            where status = 'running' and lease_expires_at <= now()
            """
        )


async def list_current_dossiers(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> tuple[CurrentDossierRecord, ...]:
    """读取当前 active 语义资料的最新 dossier；排版素材和旧 lineage 不进入 snapshot。"""

    rows = await pool.fetch(
        """
        select binding.id as binding_id, source.id as source_id,
               source.object_path, source.original_filename as filename,
               revision.id as declaration_revision_id, revision.revision,
               revision.description, revision.role, revision.topic_tags,
               revision.asset_title, revision.created_at as declared_at,
               dossier.dossier_payload
        from report_material_bindings binding
        join material_workspaces workspace on workspace.id = binding.workspace_id
        join material_sources source on source.id = binding.source_id
        join lateral (
          select *
          from user_file_declaration_revisions candidate
          where candidate.binding_id = binding.id
          order by candidate.revision desc
          limit 1
        ) revision on true
        join file_dossiers dossier
          on dossier.binding_id = binding.id and dossier.superseded_at is null
        where workspace.report_id = $1 and workspace.account_id = $2
          and binding.status = 'active'
          and source.status <> 'failed'
          and revision.role = 'semantic_material'
        order by binding.created_at, binding.id
        """,
        report_id,
        account_id,
    )
    return tuple(
        CurrentDossierRecord(
            binding_id=row["binding_id"],
            source_id=row["source_id"],
            object_path=row["object_path"],
            filename=row["filename"],
            declaration=UserFileDeclarationRevision(
                revision_id=row["declaration_revision_id"],
                binding_id=row["binding_id"],
                revision=row["revision"],
                description=row["description"],
                role=row["role"],
                topic_tags=list(row["topic_tags"]),
                asset_title=row["asset_title"],
                declared_at=row["declared_at"],
            ),
            dossier=FileDossier.model_validate(row["dossier_payload"]),
        )
        for row in rows
    )


async def list_current_file_agent_runs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> tuple[CurrentFileAgentRun, ...]:
    """读取每个当前文件 binding 的最近 File Agent 状态，不泄漏运行收据。"""

    rows = await pool.fetch(
        """
        select distinct on (run.binding_id)
               run.binding_id, run.status, run.updated_at, dossier.dossier_payload
        from file_agent_runs run
        join report_material_bindings binding on binding.id = run.binding_id
        join material_workspaces workspace on workspace.id = run.workspace_id
        left join file_dossiers dossier
          on dossier.id = run.dossier_id and dossier.superseded_at is null
        where run.account_id = $1 and run.report_id = $2
          and workspace.account_id = $1 and workspace.report_id = $2
        order by run.binding_id, run.created_at desc, run.id desc
        """,
        account_id,
        report_id,
    )
    return tuple(
        CurrentFileAgentRun(
            binding_id=row["binding_id"],
            status=row["status"],
            dossier=(
                FileDossier.model_validate(row["dossier_payload"])
                if row["dossier_payload"] is not None
                else None
            ),
            updated_at=row["updated_at"],
        )
        for row in rows
    )


async def load_dossiers(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    dossier_ids: tuple[UUID, ...],
) -> tuple[CurrentDossierRecord, ...]:
    """按冻结身份读取 dossier 及其当时声明；允许来源后来被移出报告。"""

    if not dossier_ids:
        return ()
    rows = await pool.fetch(
        """
        select dossier.id as dossier_id, dossier.binding_id, dossier.source_id,
               source.object_path, source.original_filename as filename,
               revision.id as declaration_revision_id, revision.revision,
               revision.description, revision.role, revision.topic_tags,
               revision.asset_title, revision.created_at as declared_at,
               dossier.dossier_payload
        from file_dossiers dossier
        join material_sources source on source.id = dossier.source_id
        join material_workspaces workspace on workspace.id = dossier.workspace_id
        join user_file_declaration_revisions revision
          on revision.binding_id = dossier.binding_id
         and revision.revision = dossier.declaration_revision
        where dossier.id = any($1::uuid[])
          and dossier.report_id = $2 and dossier.account_id = $3
          and workspace.report_id = $2
        order by array_position($1::uuid[], dossier.id)
        """,
        list(dossier_ids),
        report_id,
        account_id,
    )
    if len(rows) != len(dossier_ids):
        raise MaterialAgentPipelinePersistenceError(
            "Mapping 冻结输入引用的 dossier 不完整"
        )
    return tuple(
        CurrentDossierRecord(
            binding_id=row["binding_id"],
            source_id=row["source_id"],
            object_path=row["object_path"],
            filename=row["filename"],
            declaration=UserFileDeclarationRevision(
                revision_id=row["declaration_revision_id"],
                binding_id=row["binding_id"],
                revision=row["revision"],
                description=row["description"],
                role=row["role"],
                topic_tags=list(row["topic_tags"]),
                asset_title=row["asset_title"],
                declared_at=row["declared_at"],
            ),
            dossier=FileDossier.model_validate(row["dossier_payload"]),
        )
        for row in rows
    )


class UnfinishedFileAgentWork(BaseModel):
    """尚未形成 Mapping 输入的语义资料，按处境分类。

    三者需要完全不同的处置：never_enqueued 是产品自身遗漏（可补入队自愈）；
    in_flight 只需等待；failed 需要用户重传或移出。合并成一个计数会让用户
    面对"请处理失败或仍在处理的资料"却无从判断该做什么。
    """

    model_config = ConfigDict(frozen=True)

    never_enqueued_binding_ids: tuple[UUID, ...] = ()
    in_flight_count: int = 0
    failed_count: int = 0

    @property
    def total(self) -> int:
        return (
            len(self.never_enqueued_binding_ids)
            + self.in_flight_count
            + self.failed_count
        )


async def unfinished_file_agent_work(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> UnfinishedFileAgentWork:
    """读取尚未形成可进入 Mapping 的当前活跃语义文件分析，并区分其处境。"""

    rows = await pool.fetch(
        """
        select current.id as binding_id, current.status
        from (
          select binding.id, current_run.status
          from report_material_bindings binding
          join material_workspaces workspace on workspace.id = binding.workspace_id
          join material_sources source
            on source.id = binding.source_id and source.workspace_id = binding.workspace_id
          join lateral (
            select revision.role
            from user_file_declaration_revisions revision
            where revision.binding_id = binding.id
            order by revision.revision desc, revision.id desc
            limit 1
          ) declaration on true
          left join lateral (
            select run.status
            from file_agent_runs run
            where run.binding_id = binding.id
              and run.report_id = $1 and run.account_id = $2
            order by run.created_at desc, run.id desc
            limit 1
          ) current_run on true
          where workspace.report_id = $1 and workspace.account_id = $2
            and binding.status = 'active'
            and source.status not in ('failed', 'deleted')
            and declaration.role = 'semantic_material'
        ) current
        where current.status is null
           or current.status not in ('succeeded', 'needs_attention')
        """,
        report_id,
        account_id,
    )
    never_enqueued: list[UUID] = []
    in_flight = 0
    failed = 0
    for row in rows:
        status = row["status"]
        # superseded 表示当前没有有效 run，与从未入队同处境——都靠补入队恢复，
        # 不能计入 in_flight，否则用户会一直等一个不存在的运行。
        if status is None or status == "superseded":
            never_enqueued.append(row["binding_id"])
        elif status == "failed":
            failed += 1
        else:
            in_flight += 1
    return UnfinishedFileAgentWork(
        never_enqueued_binding_ids=tuple(never_enqueued),
        in_flight_count=in_flight,
        failed_count=failed,
    )


async def latest_material_set_snapshot(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> MaterialSetSnapshotRecord | None:
    """读取报告当前资料快照——created_at 表示最近一次同步确认时间，非首次创建时间。"""

    row = await pool.fetchrow(
        """
        select account_id, workspace_id, snapshot_payload
        from material_set_snapshots
        where report_id = $1 and account_id = $2
        order by created_at desc, id desc
        limit 1
        """,
        report_id,
        account_id,
    )
    if row is None:
        return None
    return MaterialSetSnapshotRecord(
        account_id=row["account_id"],
        workspace_id=row["workspace_id"],
        snapshot=MaterialSetSnapshot.model_validate(row["snapshot_payload"]),
    )


async def get_material_set_snapshot(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    snapshot_id: UUID,
) -> MaterialSetSnapshotRecord:
    """按冻结身份读取资料集合，禁止报告生成误用后续快照。"""

    row = await pool.fetchrow(
        """
        select account_id, workspace_id, snapshot_payload
        from material_set_snapshots
        where id = $1 and report_id = $2 and account_id = $3
        """,
        snapshot_id,
        report_id,
        account_id,
    )
    if row is None:
        raise MaterialAgentPipelinePersistenceError("资料集合快照不存在")
    return MaterialSetSnapshotRecord(
        account_id=row["account_id"],
        workspace_id=row["workspace_id"],
        snapshot=MaterialSetSnapshot.model_validate(row["snapshot_payload"]),
    )


async def load_file_agent_receipts(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    dossier_ids: tuple[UUID, ...],
) -> tuple[FileAgentRunReceipt, ...]:
    """读取冻结 dossier 对应的运行收据，供内部审计包复盘。"""

    if not dossier_ids:
        return ()
    rows = await pool.fetch(
        """
        select run.receipt
        from file_dossiers dossier
        join file_agent_runs run on run.id = dossier.run_id
        where dossier.id = any($1::uuid[])
          and dossier.report_id = $2 and dossier.account_id = $3
        order by array_position($1::uuid[], dossier.id)
        """,
        list(dossier_ids),
        report_id,
        account_id,
    )
    if len(rows) != len(dossier_ids) or any(row["receipt"] is None for row in rows):
        raise MaterialAgentPipelinePersistenceError(
            "资料快照对应的 File Agent 收据不完整"
        )
    return tuple(
        FileAgentRunReceipt.model_validate(row["receipt"])
        for row in rows
    )


async def current_mapping_results(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    snapshot_id: UUID | None = None,
) -> tuple[ValidatedMappingResult, ...]:
    """读取当前成功 Mapping 结果；指定 snapshot 时拒绝混入旧资料集合。"""

    rows = await pool.fetch(
        """
        select result_payload
        from material_mapping_runs
        where report_id = $1 and account_id = $2 and status = 'succeeded'
          and ($3::uuid is null or snapshot_id = $3)
        order by scope_id
        """,
        report_id,
        account_id,
        snapshot_id,
    )
    return tuple(
        ValidatedMappingResult.model_validate(row["result_payload"])
        for row in rows
    )


async def load_mapping_trace_records(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    snapshot_id: UUID,
    scope_ids: tuple[str, ...],
) -> tuple[MappingTraceRecord, ...]:
    """读取 frozen mapping plan 对应的完整 trace 身份；不接受非计划 scope。"""

    if not scope_ids:
        return ()
    rows = await pool.fetch(
        """
        select id, scope_id, input_fingerprint, receipt
        from material_mapping_runs
        where account_id = $1 and report_id = $2 and snapshot_id = $3
          and status = 'succeeded' and scope_id = any($4::text[])
        order by scope_id
        """,
        account_id,
        report_id,
        snapshot_id,
        list(scope_ids),
    )
    if len(rows) != len(scope_ids):
        raise MaterialAgentPipelinePersistenceError("冻结 Mapping plan 的 trace 运行不完整")
    records: list[MappingTraceRecord] = []
    for row in rows:
        receipt = row["receipt"]
        observation_run_id = receipt.get("observationRunId") if isinstance(receipt, dict) else None
        if not isinstance(observation_run_id, str) or not observation_run_id:
            raise MaterialAgentPipelinePersistenceError("Mapping 运行缺少 observation trace 身份")
        records.append(
            MappingTraceRecord(
                run_id=row["id"],
                scope_id=row["scope_id"],
                input_fingerprint=row["input_fingerprint"],
                observation_run_id=observation_run_id,
            )
        )
    if {record.scope_id for record in records} != set(scope_ids):
        raise MaterialAgentPipelinePersistenceError("Mapping trace scope 与冻结计划不一致")
    return tuple(records)


async def material_pipeline_status(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> MaterialPipelineStatus:
    """按当前报告汇总 File Agent、Image Agent 与 Mapping 的非终态和注意事项。"""

    row = await pool.fetchrow(
        """
        select
          (select count(*) from file_agent_runs
            where report_id = $1 and account_id = $2
              and status in ('queued', 'running')) as file_queued_or_running,
          (select count(*) from image_agent_runs
            where report_id = $1 and account_id = $2
              and status in ('queued', 'running')) as image_queued_or_running,
          (select count(*) from material_mapping_runs
            where report_id = $1 and account_id = $2
              and status in ('queued', 'running')) as mapping_queued_or_running,
          (select count(*) from file_agent_runs
            where report_id = $1 and account_id = $2
              and status = 'needs_attention') as file_needs_attention,
          (select count(*) from material_mapping_runs
            where report_id = $1 and account_id = $2
              and status = 'needs_attention') as mapping_needs_attention,
          (select count(*) from file_agent_runs
            where report_id = $1 and account_id = $2 and status = 'failed') as file_failed,
          (select count(*) from material_mapping_runs
            where report_id = $1 and account_id = $2 and status = 'failed') as mapping_failed
        """,
        report_id,
        account_id,
    )
    return MaterialPipelineStatus(
        file_queued_or_running=int(row["file_queued_or_running"] or 0),
        mapping_queued_or_running=int(row["mapping_queued_or_running"] or 0),
        file_needs_attention=int(row["file_needs_attention"] or 0),
        mapping_needs_attention=int(row["mapping_needs_attention"] or 0),
        file_failed=int(row["file_failed"] or 0),
        mapping_failed=int(row["mapping_failed"] or 0),
        image_queued_or_running=int(row["image_queued_or_running"] or 0),
    )
