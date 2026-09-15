# ABOUTME: 轻量版显式报告级生成的幂等队列、事件、不可变 revision 与交付物 lineage。
# ABOUTME: 只有完整 Block 结果和已验证交付物可以在同一事务内替换当前 Report state。
# ABOUTME(en): Idempotent queue, events, immutable revisions and deliverable lineage for lightweight report runs.
# ABOUTME(en): Only a complete Block result and verified deliverable may replace Report state, in one transaction.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Literal
from uuid import UUID, uuid4

import asyncpg

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.report_generation import (
    ReportGenerationStatus,
)
from sustainability_desk.contract.stored_report_state import StoredReportStateV4


class ReportGenerationPersistenceError(RuntimeError):
    """报告级生成运行或 Report revision 不满足持久化边界。"""


class ReportGenerationConflictError(ReportGenerationPersistenceError):
    """同一报告已有运行，或客户端基于的 Report state 已变化。"""


class ReportGenerationLeaseError(ReportGenerationPersistenceError):
    """worker 不再持有有效报告生成租约。"""


@dataclass(frozen=True)
class ReportGenerationRunRecord:
    run_id: UUID
    account_id: UUID
    report_id: UUID
    material_set_snapshot_id: UUID
    base_report_state_seq: int
    input_fingerprint: str
    idempotency_key: UUID
    #: 本次运行实际使用的生成模型；由入队边界定值，worker 不再各自读环境。
    model_id: str
    status: ReportGenerationStatus
    expected_block_ids: tuple[str, ...]
    block_results: tuple[dict, ...]
    result_report_state_seq: int | None
    result_revision_id: UUID | None
    failure_code: str | None
    started_at: datetime | None


@dataclass(frozen=True)
class ReportGenerationLease:
    run_id: UUID
    lease_token: UUID
    account_id: UUID
    report_id: UUID
    material_set_snapshot_id: UUID
    base_report_state_seq: int
    input_fingerprint: str
    #: 入队时定值的生成模型；worker 按租约执行，不在自己进程里重新解析环境变量，
    #: 否则同一运行可能被不同环境的 worker 用不同模型执行。
    model_id: str
    expected_block_ids: tuple[str, ...]
    attempt: int


@dataclass(frozen=True)
class PlannedReportRevision:
    revision_id: UUID
    revision: int


@dataclass(frozen=True)
class ReportRevisionRecord:
    """One immutable report revision as committed by a successful generation run."""

    revision_id: UUID
    revision: int
    report_state_seq: int
    generation_run_id: UUID
    content_fingerprint: str
    state: StoredReportStateV4
    created_at: datetime


@dataclass(frozen=True)
class ReportArtifactWrite:
    artifact_id: UUID
    kind: Literal["word", "review", "internal_audit"]
    filename: str
    media_type: str
    content_fingerprint: str
    storage_ref: str


@dataclass(frozen=True)
class ReportArtifactRecord:
    artifact_id: UUID
    report_revision_id: UUID
    generation_run_id: UUID
    kind: Literal["word", "review", "internal_audit"]
    filename: str
    media_type: str
    content_fingerprint: str
    storage_ref: str


@dataclass(frozen=True)
class InternalAuditArtifactRecord:
    """受限内部审计包的最小定位信息；不包含正文、trace 或客户资料。"""

    artifact: ReportArtifactRecord
    account_id: UUID
    report_id: UUID
    report_title: str
    account_email: str
    created_at: datetime


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ARTIFACT_KINDS = frozenset(
    {"word", "review", "internal_audit"}
)


def _run(row: asyncpg.Record) -> ReportGenerationRunRecord:
    return ReportGenerationRunRecord(
        run_id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        material_set_snapshot_id=row["material_set_snapshot_id"],
        base_report_state_seq=int(row["base_report_state_seq"]),
        input_fingerprint=row["input_fingerprint"],
        idempotency_key=row["idempotency_key"],
        model_id=row["model_id"],
        status=row["status"],
        expected_block_ids=tuple(row["expected_block_ids"]),
        block_results=tuple(row["block_results"] or ()),
        result_report_state_seq=(
            int(row["result_report_state_seq"])
            if row["result_report_state_seq"] is not None
            else None
        ),
        result_revision_id=row["result_revision_id"],
        failure_code=row["failure_code"],
        started_at=row["started_at"],
    )


def _validate_expected_blocks(expected_block_ids: tuple[str, ...]) -> None:
    if not expected_block_ids:
        raise ValueError("报告级生成必须至少包含一个 Block")
    if (
        any(not block_id.strip() for block_id in expected_block_ids)
        or len(expected_block_ids) != len(set(expected_block_ids))
    ):
        raise ValueError("报告级生成 Block 清单包含空值或重复身份")


def _validate_completion(
    *,
    expected_block_ids: tuple[str, ...],
    content_fingerprint: str,
    block_results: tuple[dict, ...],
    artifacts: tuple[ReportArtifactWrite, ...],
    package: KnowledgePackage,
    export_blocked: bool = False,
) -> None:
    if _SHA256_PATTERN.fullmatch(content_fingerprint) is None:
        raise ValueError("报告正文指纹无效")
    result_ids = [item.get("blockId") for item in block_results]
    if (
        set(result_ids) != set(expected_block_ids)
        or len(result_ids) != len(set(result_ids))
        or len(result_ids) != len(expected_block_ids)
    ):
        raise ValueError("生成结果必须完整覆盖全部适用 Block")

    # 受控省略对两类块成立：无可披露资料的表格，以及合同声明 omit_if_unsupported 的
    # 证据门控块（段落亦可）；其余段落必须 ready。资格以编译合同为准，不信任结果自述。
    material_gated_ids = frozenset(
        contract.block_id
        for contract in load_compiled_report_definition(package).generation_contracts.values()
        if contract.absence_behavior == "omit_if_unsupported"
    )

    def _accepted_result(item: dict) -> bool:
        if item.get("status") == "ready":
            return True
        if item.get("status") != "omitted":
            return False
        if not (isinstance(item.get("reason"), str) and item["reason"].strip()):
            return False
        return item.get("kind") == "table" or item.get("blockId") in material_gated_ids

    if any(not _accepted_result(item) for item in block_results):
        raise ValueError("适用 Block 必须成功生成或形成受控表格省略")

    artifact_kinds = [artifact.kind for artifact in artifacts]
    if export_blocked:
        # 导出闸阻断时正文照常保存，但不得产出任何客户可见交付物。
        if artifacts:
            raise ValueError("导出闸阻断的报告不得携带交付物")
        return
    if (
        set(artifact_kinds) != _REQUIRED_ARTIFACT_KINDS
        or len(artifact_kinds) != len(set(artifact_kinds))
    ):
        raise ValueError("成功报告必须同时具有三类交付物")
    artifact_ids = [artifact.artifact_id for artifact in artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("报告交付物身份不得重复")
    for artifact in artifacts:
        if (
            not artifact.filename.strip()
            or not artifact.media_type.strip()
            or not artifact.storage_ref.strip()
            or _SHA256_PATTERN.fullmatch(artifact.content_fingerprint) is None
        ):
            raise ValueError("报告交付物元数据或内容指纹无效")


async def _append_event(
    connection: asyncpg.Connection,
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    event_type: str,
    user_message: str,
    current_object: str | None = None,
    action_required: bool = False,
    payload: dict[str, object] | None = None,
) -> None:
    await connection.execute(
        """
        insert into lightweight_report_generation_events (
          run_id, account_id, report_id, event_type, user_message,
          current_object, action_required, payload
        ) values ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        run_id,
        account_id,
        report_id,
        event_type,
        user_message,
        current_object,
        action_required,
        payload or {},
    )


async def enqueue_generation(
    pool: asyncpg.Pool,
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    material_set_snapshot_id: UUID,
    base_report_state_seq: int,
    input_fingerprint: str,
    idempotency_key: UUID,
    model_id: str,
    expected_block_ids: tuple[str, ...],
) -> ReportGenerationRunRecord:
    """校验当前 Report state 并幂等建立报告级运行。"""

    _validate_expected_blocks(expected_block_ids)
    async with pool.acquire() as connection, connection.transaction():
        known = await connection.fetchrow(
            """
            select * from lightweight_report_generation_runs
            where report_id = $1 and idempotency_key = $2
            for update
            """,
            report_id,
            idempotency_key,
        )
        if known is not None:
            if (
                known["account_id"] != account_id
                or known["material_set_snapshot_id"]
                != material_set_snapshot_id
                or int(known["base_report_state_seq"])
                != base_report_state_seq
                or known["input_fingerprint"] != input_fingerprint
                # 模型是生成输入：同一幂等键换模型必须判冲突，否则界面选了新模型
                # 却静默拿回旧模型写的运行。
                or known["model_id"] != model_id
                or tuple(known["expected_block_ids"]) != expected_block_ids
            ):
                raise ReportGenerationConflictError(
                    "幂等键已经用于其他报告生成输入"
                )
            return _run(known)
        snapshot = await connection.fetchrow(
            """
            select id from material_set_snapshots
            where id = $1 and report_id = $2 and account_id = $3
            """,
            material_set_snapshot_id,
            report_id,
            account_id,
        )
        if snapshot is None:
            raise ReportGenerationConflictError(
                "资料集合快照不存在或不属于当前报告"
            )
        current_seq = await connection.fetchval(
            """
            select state.state_seq
            from report_states state
            join reports report on report.id = state.report_id
            where state.report_id = $1 and report.account_id = $2
              and report.status = 'active'
            for update of state, report
            """,
            report_id,
            account_id,
        )
        if current_seq != base_report_state_seq:
            raise ReportGenerationConflictError("报告输入已变化，请刷新后重新生成")
        try:
            row = await connection.fetchrow(
                """
                insert into lightweight_report_generation_runs (
                  id, account_id, report_id, material_set_snapshot_id,
                  base_report_state_seq, input_fingerprint, idempotency_key,
                  model_id, expected_block_ids
                ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                returning *
                """,
                run_id,
                account_id,
                report_id,
                material_set_snapshot_id,
                base_report_state_seq,
                input_fingerprint,
                idempotency_key,
                model_id,
                list(expected_block_ids),
            )
        except asyncpg.UniqueViolationError as error:
            raise ReportGenerationConflictError(
                "当前报告已有生成或更新任务"
            ) from error
        if row is None:
            raise ReportGenerationPersistenceError(
                "报告生成运行写入后无法读取"
            )
        await _append_event(
            connection,
            run_id=run_id,
            account_id=account_id,
            report_id=report_id,
            event_type="queued",
            user_message="报告生成请求已接收，系统将基于当前输入和资料版本开始处理。",
        )
    return _run(row)


async def claim_generation(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    lease_seconds: int = 900,
    report_id: UUID | None = None,
) -> ReportGenerationLease | None:
    """在 File/Mapping 队列排空后领取一个可执行报告生成节点。"""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds 必须为正数")
    token = uuid4()
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """
            with candidate as (
              select run.id
              from lightweight_report_generation_runs run
              join material_set_snapshots snapshot
                on snapshot.id = run.material_set_snapshot_id
               and snapshot.report_id = run.report_id
               and snapshot.account_id = run.account_id
              where run.status = 'queued' and run.attempt < run.max_attempts
                and ($4::uuid is null or run.report_id = $4)
                and not exists (
                  select 1 from material_set_snapshots newer
                  where newer.report_id = run.report_id
                    and newer.account_id = run.account_id
                    and (newer.created_at, newer.id)
                      > (snapshot.created_at, snapshot.id)
                )
                and not exists (
                  select 1
                  from jsonb_array_elements(
                    snapshot.snapshot_payload -> 'members'
                  ) member
                  where not exists (
                    select 1
                    from file_dossiers dossier
                    join file_agent_runs file_run
                      on file_run.id = dossier.run_id
                     and file_run.status = 'succeeded'
                    where dossier.id = (member ->> 'dossier_id')::uuid
                      and dossier.report_id = run.report_id
                      and dossier.account_id = run.account_id
                      and dossier.source_id
                        = (member ->> 'source_id')::uuid
                      and dossier.source_sha256
                        = member ->> 'source_sha256'
                      and dossier.declaration_revision
                        = (member ->> 'declaration_revision')::integer
                      and dossier.dossier_fingerprint
                        = member ->> 'dossier_fingerprint'
                  )
                )
                and not exists (
                  select 1 from file_agent_runs file_run
                  where file_run.report_id = run.report_id
                    and file_run.status in ('queued', 'running')
                )
                and not exists (
                  select 1 from material_mapping_runs mapping_run
                  where mapping_run.report_id = run.report_id
                    and mapping_run.snapshot_id = run.material_set_snapshot_id
                    and mapping_run.status in ('queued', 'running')
                )
                and not exists (
                  select 1
                  from jsonb_array_elements(
                    coalesce(
                      snapshot.snapshot_payload -> 'mapping_plan' -> 'scopes',
                      '[]'::jsonb
                    )
                  ) plan_scope
                  where not exists (
                    select 1
                    from material_mapping_runs mapping_run
                    where mapping_run.report_id = run.report_id
                      and mapping_run.account_id = run.account_id
                      and mapping_run.snapshot_id = run.material_set_snapshot_id
                      and mapping_run.scope_id = plan_scope ->> 'scope_id'
                      and mapping_run.status = 'succeeded'
                  )
                )
              order by run.created_at, run.id
              for update skip locked
              limit 1
            )
            update lightweight_report_generation_runs run
            set status = 'running', attempt = run.attempt + 1,
                leased_by = $1, lease_token = $2,
                lease_expires_at = now() + $3::interval,
                started_at = coalesce(run.started_at, now()),
                updated_at = now()
            from candidate
            where run.id = candidate.id
            returning run.*
            """,
            worker_id,
            token,
            timedelta(seconds=lease_seconds),
            report_id,
        )
        if row is None:
            return None
        await _append_event(
            connection,
            run_id=row["id"],
            account_id=row["account_id"],
            report_id=row["report_id"],
            event_type="started",
            user_message="系统已开始生成完整报告，已完成内容会持续记录。",
        )
    return ReportGenerationLease(
        run_id=row["id"],
        lease_token=row["lease_token"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        material_set_snapshot_id=row["material_set_snapshot_id"],
        base_report_state_seq=int(row["base_report_state_seq"]),
        input_fingerprint=row["input_fingerprint"],
        model_id=row["model_id"],
        expected_block_ids=tuple(row["expected_block_ids"]),
        attempt=int(row["attempt"]),
    )


async def append_block_event(
    pool: asyncpg.Pool,
    *,
    lease: ReportGenerationLease,
    block_id: str,
    completed: bool,
    result: dict | None = None,
    display_label: str | None = None,
) -> None:
    """追加一项用户友好 Block 进度；内部结果仅存 payload。

    display_label 是面向用户的内容名称(章节/小节中文标题);内部 block key 不进
    用户可见字段,仅保留在 payload 供审计。
    """

    async with pool.acquire() as connection, connection.transaction():
        valid = await connection.fetchval(
            """
            select 1 from lightweight_report_generation_runs
            where id = $1 and lease_token = $2 and status = 'running'
              and lease_expires_at > now()
            """,
            lease.run_id,
            lease.lease_token,
        )
        if valid is None:
            raise ReportGenerationLeaseError(str(lease.run_id))
        await _append_event(
            connection,
            run_id=lease.run_id,
            account_id=lease.account_id,
            report_id=lease.report_id,
            event_type="block_completed" if completed else "block_started",
            user_message=(
                f"已完成：{display_label or '一项报告内容'}"
                if completed
                else f"正在生成：{display_label or '一项报告内容'}"
            ),
            current_object=display_label or "报告内容",
            payload=(
                {"blockId": block_id, "resultStatus": (result or {}).get("status")}
                if completed
                else {"blockId": block_id}
            ),
        )


async def plan_next_revision(
    pool: asyncpg.Pool,
    *,
    lease: ReportGenerationLease,
) -> PlannedReportRevision:
    """在交付物构建前预分配本运行唯一 revision 身份。"""

    row = await pool.fetchrow(
        """
        select coalesce(max(revision), 0) + 1 as revision
        from lightweight_report_revisions
        where report_id = $1 and account_id = $2
        """,
        lease.report_id,
        lease.account_id,
    )
    return PlannedReportRevision(
        revision_id=uuid4(),
        revision=int(row["revision"]),
    )


async def complete_generation(
    pool: asyncpg.Pool,
    *,
    lease: ReportGenerationLease,
    planned_revision: PlannedReportRevision,
    state: StoredReportStateV4,
    content_fingerprint: str,
    block_results: tuple[dict, ...],
    artifacts: tuple[ReportArtifactWrite, ...],
    package: KnowledgePackage,
    export_blocking_issues: tuple[str, ...] = (),
) -> int:
    """验证所有交付物后原子写入 Report、revision、artifact lineage 和运行终态。

    export_blocking_issues 非空表示生成后的报告未通过导出闸：正文照常保存，
    不写入任何交付物，并以 action_required 事件引导用户在工作台补齐后导出。
    """

    _validate_completion(
        expected_block_ids=lease.expected_block_ids,
        content_fingerprint=content_fingerprint,
        block_results=block_results,
        artifacts=artifacts,
        package=package,
        export_blocked=bool(export_blocking_issues),
    )
    async with pool.acquire() as connection, connection.transaction():
        run = await connection.fetchrow(
            """
            select * from lightweight_report_generation_runs
            where id = $1 and lease_token = $2 and status = 'running'
              and lease_expires_at > now()
            for update
            """,
            lease.run_id,
            lease.lease_token,
        )
        if run is None:
            raise ReportGenerationLeaseError(str(lease.run_id))
        if (
            run["account_id"] != lease.account_id
            or run["report_id"] != lease.report_id
            or run["material_set_snapshot_id"]
            != lease.material_set_snapshot_id
            or int(run["base_report_state_seq"])
            != lease.base_report_state_seq
            or run["input_fingerprint"] != lease.input_fingerprint
            or tuple(run["expected_block_ids"])
            != lease.expected_block_ids
            or int(run["attempt"]) != lease.attempt
        ):
            raise ReportGenerationLeaseError(
                "报告生成运行与冻结租约输入不一致"
            )
        state_row = await connection.fetchrow(
            """
            select state_seq from report_states
            where report_id = $1
            for update
            """,
            lease.report_id,
        )
        if state_row is None or int(state_row["state_seq"]) != lease.base_report_state_seq:
            raise ReportGenerationConflictError(
                "报告输入在生成期间发生变化，未覆盖当前版本"
            )
        expected_revision = await connection.fetchval(
            """
            select coalesce(max(revision), 0) + 1
            from lightweight_report_revisions
            where report_id = $1
            """,
            lease.report_id,
        )
        if int(expected_revision) != planned_revision.revision:
            raise ReportGenerationConflictError("报告 revision 序号已变化")
        payload = state.model_dump(mode="json", by_alias=True)
        new_seq = await connection.fetchval(
            """
            update report_states
            set state = $1, state_seq = state_seq + 1, updated_at = now()
            where report_id = $2 and state_seq = $3
            returning state_seq
            """,
            payload,
            lease.report_id,
            lease.base_report_state_seq,
        )
        if new_seq is None:
            raise ReportGenerationConflictError("报告状态写入冲突")
        await connection.execute(
            """
            insert into lightweight_report_revisions (
              id, account_id, report_id, generation_run_id, revision,
              report_state_seq, content_fingerprint, state_payload
            ) values ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            planned_revision.revision_id,
            lease.account_id,
            lease.report_id,
            lease.run_id,
            planned_revision.revision,
            new_seq,
            content_fingerprint,
            payload,
        )
        for artifact in artifacts:
            await connection.execute(
                """
                insert into lightweight_report_artifacts (
                  id, account_id, report_id, report_revision_id,
                  generation_run_id, kind, filename, media_type,
                  content_fingerprint, storage_ref
                ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                artifact.artifact_id,
                lease.account_id,
                lease.report_id,
                planned_revision.revision_id,
                lease.run_id,
                artifact.kind,
                artifact.filename,
                artifact.media_type,
                artifact.content_fingerprint,
                artifact.storage_ref,
            )
        updated = await connection.execute(
            """
            update lightweight_report_generation_runs
            set status = 'succeeded', leased_by = null, lease_token = null,
                lease_expires_at = null, block_results = $3,
                result_report_state_seq = $4, result_revision_id = $5,
                finished_at = now(), updated_at = now()
            where id = $1 and lease_token = $2 and status = 'running'
            """,
            lease.run_id,
            lease.lease_token,
            list(block_results),
            new_seq,
            planned_revision.revision_id,
        )
        if updated != "UPDATE 1":
            raise ReportGenerationLeaseError(str(lease.run_id))
        await _append_event(
            connection,
            run_id=lease.run_id,
            account_id=lease.account_id,
            report_id=lease.report_id,
            event_type="report_saved",
            user_message="完整报告版本已保存，旧版本的来源关系仍可追溯。",
        )
        if export_blocking_issues:
            await _append_event(
                connection,
                run_id=lease.run_id,
                account_id=lease.account_id,
                report_id=lease.report_id,
                event_type="export_blocked",
                user_message=(
                    f"报告内容已生成并保存，但存在 {len(export_blocking_issues)} 项待完善事项，"
                    "本次未生成可下载的 Word 交付物。请补齐相应信息后重新生成。"
                ),
                action_required=True,
                payload={"blocking_issues": list(export_blocking_issues)},
            )
        else:
            await _append_event(
                connection,
                run_id=lease.run_id,
                account_id=lease.account_id,
                report_id=lease.report_id,
                event_type="artifacts_ready",
                user_message="Word 报告和审阅说明已准备完成。",
            )
    return int(new_seq)


async def fail_generation(
    pool: asyncpg.Pool,
    *,
    lease: ReportGenerationLease,
    failure_code: str,
    user_message: str,
    action_required: bool = False,
) -> None:
    """终结失败运行，不修改 Report state 或既有交付物。"""

    async with pool.acquire() as connection, connection.transaction():
        updated = await connection.execute(
            """
            update lightweight_report_generation_runs
            set status = 'failed', leased_by = null, lease_token = null,
                lease_expires_at = null, failure_code = $3,
                finished_at = now(), updated_at = now()
            where id = $1 and lease_token = $2 and status = 'running'
              and lease_expires_at > now()
            """,
            lease.run_id,
            lease.lease_token,
            failure_code[:100],
        )
        if updated != "UPDATE 1":
            raise ReportGenerationLeaseError(str(lease.run_id))
        await _append_event(
            connection,
            run_id=lease.run_id,
            account_id=lease.account_id,
            report_id=lease.report_id,
            event_type="failed",
            user_message=user_message,
            action_required=action_required,
            payload={"failureCode": failure_code[:100]},
        )


async def recover_expired_generation_runs(pool: asyncpg.Pool) -> None:
    """恢复过期报告租约；达到尝试上限时形成明确失败事件。"""

    async with pool.acquire() as connection, connection.transaction():
        failed = await connection.fetch(
            """
            update lightweight_report_generation_runs
            set status = case when attempt < max_attempts
                              then 'queued' else 'failed' end,
                leased_by = null, lease_token = null, lease_expires_at = null,
                failure_code = case when attempt < max_attempts then null
                                    else 'lease_expired_after_max_attempts' end,
                finished_at = case when attempt < max_attempts then null
                                   else now() end,
                updated_at = now()
            where status = 'running' and lease_expires_at <= now()
            returning id, account_id, report_id, status
            """
        )
        for row in failed:
            if row["status"] != "failed":
                continue
            await _append_event(
                connection,
                run_id=row["id"],
                account_id=row["account_id"],
                report_id=row["report_id"],
                event_type="failed",
                user_message=(
                    "报告生成运行多次中断，既有报告未被覆盖，请重新发起生成。"
                ),
                action_required=True,
                payload={"failureCode": "lease_expired_after_max_attempts"},
            )


async def get_generation(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    run_id: UUID,
) -> tuple[ReportGenerationRunRecord, tuple[asyncpg.Record, ...], tuple[asyncpg.Record, ...]]:
    """读取一个运行、公开事件与交付物元数据。"""

    row = await pool.fetchrow(
        """
        select * from lightweight_report_generation_runs
        where id = $1 and report_id = $2 and account_id = $3
        """,
        run_id,
        report_id,
        account_id,
    )
    if row is None:
        raise ReportGenerationPersistenceError("报告生成运行不存在")
    events = tuple(
        await pool.fetch(
            """
            select * from lightweight_report_generation_events
            where run_id = $1 and account_id = $2
            order by id
            """,
            run_id,
            account_id,
        )
    )
    artifacts = tuple(
        await pool.fetch(
            """
            select * from lightweight_report_artifacts
            where generation_run_id = $1 and account_id = $2
              and kind <> 'internal_audit'
            order by kind
            """,
            run_id,
            account_id,
        )
    )
    return _run(row), events, artifacts


async def latest_generation(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> ReportGenerationRunRecord | None:
    row = await pool.fetchrow(
        """
        select * from lightweight_report_generation_runs
        where report_id = $1 and account_id = $2
        order by created_at desc, id desc
        limit 1
        """,
        report_id,
        account_id,
    )
    return _run(row) if row is not None else None


async def latest_successful_generation(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> ReportGenerationRunRecord | None:
    """读取最近成功交付的报告版本，用于判断当前输入是否需要更新报告。"""

    row = await pool.fetchrow(
        """
        select * from lightweight_report_generation_runs
        where report_id = $1 and account_id = $2 and status = 'succeeded'
        order by finished_at desc, id desc
        limit 1
        """,
        report_id,
        account_id,
    )
    return _run(row) if row is not None else None


async def revision_state(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    revision_id: UUID,
) -> ReportRevisionRecord:
    """Read the frozen state a generation run committed; the generated baseline for edits."""

    row = await pool.fetchrow(
        """
        select id, revision, report_state_seq, generation_run_id,
               content_fingerprint, state_payload, created_at
        from lightweight_report_revisions
        where id = $1 and report_id = $2 and account_id = $3
        """,
        revision_id,
        report_id,
        account_id,
    )
    if row is None:
        raise ReportGenerationPersistenceError("报告修订不存在")
    return ReportRevisionRecord(
        revision_id=row["id"],
        revision=int(row["revision"]),
        report_state_seq=int(row["report_state_seq"]),
        generation_run_id=row["generation_run_id"],
        content_fingerprint=row["content_fingerprint"],
        state=StoredReportStateV4.model_validate(row["state_payload"]),
        created_at=row["created_at"],
    )


async def artifact_download_target(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    artifact_id: UUID,
    include_internal: bool = False,
) -> ReportArtifactRecord:
    row = await pool.fetchrow(
        """
        select artifact.id, artifact.kind, artifact.filename,
               artifact.media_type, artifact.content_fingerprint,
               artifact.storage_ref, artifact.report_revision_id,
               artifact.generation_run_id
        from lightweight_report_artifacts artifact
        join lightweight_report_generation_runs run
          on run.id = artifact.generation_run_id
         and run.report_id = artifact.report_id
         and run.account_id = artifact.account_id
        join lightweight_report_revisions revision
          on revision.id = artifact.report_revision_id
         and revision.report_id = artifact.report_id
         and revision.account_id = artifact.account_id
         and revision.generation_run_id = artifact.generation_run_id
        where artifact.id = $1 and artifact.report_id = $2
          and artifact.account_id = $3
          and run.status = 'succeeded'
          and run.result_revision_id = artifact.report_revision_id
          and ($4::boolean or artifact.kind <> 'internal_audit')
        """,
        artifact_id,
        report_id,
        account_id,
        include_internal,
    )
    if row is None:
        raise ReportGenerationPersistenceError("报告交付物不存在")
    return ReportArtifactRecord(
        artifact_id=row["id"],
        report_revision_id=row["report_revision_id"],
        generation_run_id=row["generation_run_id"],
        kind=row["kind"],
        filename=row["filename"],
        media_type=row["media_type"],
        content_fingerprint=row["content_fingerprint"],
        storage_ref=row["storage_ref"],
    )


async def list_internal_audit_artifacts(
    pool: asyncpg.Pool,
) -> tuple[InternalAuditArtifactRecord, ...]:
    """为受权运营者列出成功 revision 的内部审计包，不复用客户所有权查询。"""

    rows = await pool.fetch(
        """
        select artifact.id, artifact.kind, artifact.filename, artifact.media_type,
               artifact.content_fingerprint, artifact.storage_ref, artifact.report_revision_id,
               artifact.generation_run_id, artifact.account_id, artifact.report_id,
               artifact.created_at, report.title as report_title, account.email as account_email
        from lightweight_report_artifacts artifact
        join lightweight_report_generation_runs run
          on run.id = artifact.generation_run_id
         and run.result_revision_id = artifact.report_revision_id
         and run.status = 'succeeded'
        join reports report on report.id = artifact.report_id and report.account_id = artifact.account_id
        join accounts account on account.id = artifact.account_id
        where artifact.kind = 'internal_audit'
        order by artifact.created_at desc, artifact.id desc
        """
    )
    return tuple(
        InternalAuditArtifactRecord(
            artifact=ReportArtifactRecord(
                artifact_id=row["id"],
                report_revision_id=row["report_revision_id"],
                generation_run_id=row["generation_run_id"],
                kind=row["kind"],
                filename=row["filename"],
                media_type=row["media_type"],
                content_fingerprint=row["content_fingerprint"],
                storage_ref=row["storage_ref"],
            ),
            account_id=row["account_id"],
            report_id=row["report_id"],
            report_title=row["report_title"],
            account_email=row["account_email"],
            created_at=row["created_at"],
        )
        for row in rows
    )


async def internal_audit_artifact_download_target(
    pool: asyncpg.Pool, *, artifact_id: UUID
) -> InternalAuditArtifactRecord:
    """按审计包 ID 读取跨账户下载目标，仅由更高层运营权限调用。"""

    rows = await list_internal_audit_artifacts(pool)
    item = next((candidate for candidate in rows if candidate.artifact.artifact_id == artifact_id), None)
    if item is None:
        raise ReportGenerationPersistenceError("内部审计包不存在")
    return item
