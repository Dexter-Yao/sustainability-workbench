# ABOUTME: 资料工作区与来源生命周期的 Account 所有权感知 DAL。
# ABOUTME: workspace.state 是可变状态 SSOT；material_events 只追加，写路径全部要求所有权与 CAS。
# ABOUTME(en): Account-ownership-aware DAL for the material workspace and source lifecycle.
# ABOUTME(en): workspace.state is the mutable-state SSOT; material_events is append-only; writes need ownership.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import asyncpg

from sustainability_desk.material.intake.facts import stale_source_dependencies
from sustainability_desk.material.intake.models import (
    MaterialIngressDecision,
    MaterialProcessingError,
    MaterialSnapshot,
    MaterialSource,
    MaterialSourceDeletionTarget,
    MaterialWorkspace,
    NormalizedMaterial,
    ProcessingStep,
    MaterialSourceReviewDecision,
    ReportMaterialBinding,
    UserFileDeclaration,
    UserFileDeclarationRevision,
    ValidatedMaterialFile,
    WorkspaceState,
    WorkspaceMutationResult,
)
from sustainability_desk.persistence.report_lineage import mark_source_stale


class MaterialPersistenceError(Exception):
    """资料持久化业务错误基类。"""


class MaterialOwnershipError(MaterialPersistenceError):
    """Account 不拥有目标 Report 或 workspace。"""


class MaterialStateConflictError(MaterialPersistenceError):
    """workspace state_seq 已变化。"""


class MaterialDuplicateSourceError(MaterialPersistenceError):
    """同一工作区已有相同内容的未删除来源。"""


class ReportFileCapacityError(MaterialPersistenceError):
    """报告已达到当前文件准入上限。"""


class ReportFileSourceConflictError(MaterialPersistenceError):
    """同一内容已属于旧资料路径，不能被静默并入报告文件入口。"""


class ReportFileDeclarationConflictError(MaterialPersistenceError):
    """重复内容携带了不同声明，必须由用户显式编辑既有 Binding。"""


class ReportMaterialBindingStateError(MaterialPersistenceError):
    """报告资料 Binding 的当前状态不允许所请求操作。"""


REPORT_FILE_CAPACITY_COUNT_SQL = """
    select count(*)
    from report_material_bindings binding
    join material_sources source on source.id = binding.source_id
    where binding.workspace_id = $1 and binding.status = 'active'
      and source.status not in ('failed', 'deleted')
"""


async def active_report_file_count(
    connection: asyncpg.Connection,
    workspace_id: UUID,
) -> int:
    """统一计算占用当前报告文件额度的 active 且准入成功文件。"""

    return int(
        await connection.fetchval(REPORT_FILE_CAPACITY_COUNT_SQL, workspace_id)
    )


async def get_active_source_by_sha256(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    sha256: str,
) -> MaterialSource | None:
    """返回同工作区内容身份相同的现有 Source；不复制或改写其元数据。"""

    row = await pool.fetchrow(
        """
        select *
        from material_sources
        where workspace_id = $1 and account_id = $2 and sha256 = $3
          and status <> 'deleted'
        """,
        workspace_id,
        account_id,
        sha256,
    )
    return _source(row) if row is not None else None


async def reuse_source_and_record_ingress(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    sha256: str,
    decision: MaterialIngressDecision,
) -> MaterialSource:
    """锁定既有 Source 并在同一事务记录复用决定。"""

    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            select *
            from material_sources
            where workspace_id = $1 and account_id = $2 and sha256 = $3
              and status <> 'deleted'
            for update
            """,
            workspace_id,
            account_id,
            sha256,
        )
        if row is None or row["id"] != decision.source_id:
            raise MaterialOwnershipError(sha256)
        await conn.execute(
            """
            insert into material_events
              (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'system', 'source_ingress_decided', $3)
            """,
            workspace_id,
            row["id"],
            decision.model_dump(mode="json"),
        )
    return _source(row)


async def record_ingress_decisions(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    decisions: tuple[MaterialIngressDecision, ...],
) -> None:
    """把准入决定追加到 workspace 审计流；不在事件中复制文件正文。"""

    if not decisions:
        return
    async with pool.acquire() as conn, conn.transaction():
        owned = await conn.fetchval(
            """
            select 1 from material_workspaces
            where id = $1 and account_id = $2 and status = 'active'
            for update
            """,
            workspace_id,
            account_id,
        )
        if owned is None:
            raise MaterialOwnershipError(str(workspace_id))
        for decision in decisions:
            await conn.execute(
                """
                insert into material_events
                  (workspace_id, source_id, actor, event_type, payload)
                values ($1, $2, 'system', 'source_ingress_decided', $3)
                """,
                workspace_id,
                decision.source_id,
                decision.model_dump(mode="json"),
            )


async def record_source_review_decision(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    decision: MaterialSourceReviewDecision,
) -> None:
    """追加一项绑定当前解析指纹的人类裁决。"""

    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            select *
            from material_sources
            where id = $1 and workspace_id = $2 and account_id = $3
              and status = 'needs_attention'
            for update
            """,
            decision.source_id,
            workspace_id,
            account_id,
        )
        if row is None:
            raise MaterialOwnershipError(str(decision.source_id))
        source = _source(row)
        if (
            source.normalized_material_fingerprint
            != decision.normalized_material_fingerprint
        ):
            raise MaterialStateConflictError("资料解析结果已变化")
        await conn.execute(
            """
            insert into material_events
              (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, $3, 'source_review_decided', $4)
            """,
            workspace_id,
            decision.source_id,
            decision.actor,
            decision.model_dump(mode="json", exclude={"actor"}),
        )


async def get_latest_source_review_decisions(
    pool: asyncpg.Pool | asyncpg.Connection,
    *,
    workspace_id: UUID,
) -> dict[UUID, MaterialSourceReviewDecision]:
    """按 Source 返回最近裁决；消费者仍须校验当前解析指纹。"""

    rows = await pool.fetch(
        """
        select distinct on (source_id) source_id, actor, payload
        from material_events
        where workspace_id = $1
          and event_type = 'source_review_decided'
          and source_id is not null
        order by source_id, id desc
        """,
        workspace_id,
    )
    decisions = []
    for row in rows:
        payload = dict(row["payload"])
        payload["actor"] = row["actor"]
        decisions.append(MaterialSourceReviewDecision.model_validate(payload))
    return {decision.source_id: decision for decision in decisions}


def _workspace(row: asyncpg.Record) -> MaterialWorkspace:
    return MaterialWorkspace(
        id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        adapter_id=row["adapter_id"],
        contract_version=row["contract_version"],
        status=row["status"],
        state=WorkspaceState.model_validate(row["state"]),
        state_seq=row["state_seq"],
        material_set_confirmed_at=row["material_set_confirmed_at"],
        material_set_confirmed_fingerprint=row["material_set_confirmed_fingerprint"],
    )


def _source(row: asyncpg.Record) -> MaterialSource:
    normalized = row["normalized_material"]
    error = row["error"]
    fragments = (
        NormalizedMaterial.model_validate(normalized).fragments
        if normalized is not None
        else []
    )
    return MaterialSource(
        id=row["id"],
        workspace_id=row["workspace_id"],
        account_id=row["account_id"],
        source_label=row["source_label"],
        filename=row["original_filename"],
        object_path=row["object_path"],
        kind=row["kind"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        status=row["status"],
        scope_kind=row["scope_kind"],
        report_section_ids=list(row["report_section_ids"]),
        normalized_material=(
            NormalizedMaterial.model_validate(normalized)
            if normalized is not None
            else None
        ),
        has_normalized_material=(
            bool(row["has_normalized_material"])
            if "has_normalized_material" in row
            else normalized is not None
        ),
        normalized_fragment_count=(
            int(row["normalized_fragment_count"])
            if "normalized_fragment_count" in row
            else len(fragments)
        ),
        normalized_fragment_kinds=(
            list(row["normalized_fragment_kinds"] or [])
            if "normalized_fragment_kinds" in row
            else sorted({fragment.kind for fragment in fragments})
        ),
        processing_steps=[
            ProcessingStep.model_validate(step) for step in row["processing_steps"]
        ],
        error=(
            MaterialProcessingError.model_validate(error) if error is not None else None
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _report_material_binding(row: asyncpg.Record) -> ReportMaterialBinding:
    return ReportMaterialBinding(
        binding_id=row["binding_id"],
        workspace_id=row["workspace_id"],
        source_id=row["source_id"],
        status=row["binding_status"],
        created_at=row["binding_created_at"],
        updated_at=row["binding_updated_at"],
        removed_at=row["removed_at"],
        superseded_at=row["superseded_at"],
    )


def _declaration_revision(row: asyncpg.Record) -> UserFileDeclarationRevision:
    return UserFileDeclarationRevision(
        revision_id=row["declaration_revision_id"],
        binding_id=row["binding_id"],
        revision=row["revision"],
        description=row["description"],
        role=row["role"],
        topic_tags=list(row["topic_tags"]),
        asset_title=row["asset_title"],
        declared_at=row["declared_at"],
    )


async def get_or_create_workspace(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    adapter_id: str,
    contract_version: str,
) -> MaterialWorkspace:
    """在 Report 所有权锁内返回同目标活动 workspace，或建立一份新的 typed state。"""
    async with pool.acquire() as conn, conn.transaction():
        owned = await conn.fetchval(
            "select id from reports where id = $1 and account_id = $2 and status = 'active' for update",
            report_id,
            account_id,
        )
        if owned is None:
            raise MaterialOwnershipError(str(report_id))
        known = await conn.fetchrow(
            """
            select * from material_workspaces
            where report_id = $1 and status = 'active'
            """,
            report_id,
        )
        if known is not None:
            return _workspace(known)
        state = WorkspaceState()
        row = await conn.fetchrow(
            """
            insert into material_workspaces
              (account_id, report_id, adapter_id, contract_version, state)
            values ($1, $2, $3, $4, $5)
            returning *
            """,
            account_id,
            report_id,
            adapter_id,
            contract_version,
            state.model_dump(mode="json"),
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, actor, event_type, payload)
            values ($1, 'system', 'workspace_created', $2)
            """,
            row["id"],
            {"adapterId": adapter_id, "contractVersion": contract_version},
        )
    return _workspace(row)


async def record_material_set_confirmation(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    fingerprint: str,
    confirmed_at: datetime,
) -> None:
    """落下资料集确认时间与指纹；失效判定由调用方在读取时对当前 active binding 集重算比对。"""

    updated = await pool.execute(
        """
        update material_workspaces
        set material_set_confirmed_at = $3,
            material_set_confirmed_fingerprint = $4
        where id = $1 and account_id = $2
        """,
        workspace_id,
        account_id,
        confirmed_at,
        fingerprint,
    )
    if updated == "UPDATE 0":
        raise MaterialOwnershipError(str(workspace_id))


async def get_snapshot(
    pool: asyncpg.Pool | asyncpg.Connection,
    *,
    account_id: UUID,
    workspace_id: UUID,
    include_source_content: bool = True,
) -> MaterialSnapshot:
    """返回 workspace 状态；公开刷新可省略清洗正文，领域裁决默认读取完整来源。"""
    workspace_row = await pool.fetchrow(
        """
        select workspace.*,
               coalesce(
                 (select max(event.id) from material_events event
                  where event.workspace_id = workspace.id),
                 1
               ) as projection_seq
        from material_workspaces workspace
        where workspace.id = $1 and workspace.account_id = $2
        """,
        workspace_id,
        account_id,
    )
    if workspace_row is None:
        raise MaterialOwnershipError(str(workspace_id))
    source_query = (
        """
        select id, workspace_id, account_id, source_label, original_filename,
               object_path, kind, media_type, size_bytes, sha256,
               scope_kind, report_section_ids, status,
               normalized_material,
               normalized_material is not null as has_normalized_material,
               coalesce(jsonb_array_length(normalized_material -> 'fragments'), 0)
                 as normalized_fragment_count,
               coalesce(
                 array(
                   select distinct fragment ->> 'kind'
                   from jsonb_array_elements(
                     coalesce(normalized_material -> 'fragments', '[]'::jsonb)
                   ) as fragment
                   order by 1
                 ),
                 array[]::text[]
               ) as normalized_fragment_kinds,
               processing_steps, error, created_at, updated_at
        from material_sources
        where workspace_id = $1 and account_id = $2
        order by created_at, id
        """
        if include_source_content
        else """
        select id, workspace_id, account_id, source_label, original_filename,
               ''::text as object_path, kind, media_type, size_bytes, sha256,
               scope_kind, report_section_ids, status,
               null::jsonb as normalized_material,
               normalized_material is not null as has_normalized_material,
               coalesce(jsonb_array_length(normalized_material -> 'fragments'), 0)
                 as normalized_fragment_count,
               coalesce(
                 array(
                   select distinct fragment ->> 'kind'
                   from jsonb_array_elements(
                     coalesce(normalized_material -> 'fragments', '[]'::jsonb)
                   ) as fragment
                   order by 1
                 ),
                 array[]::text[]
               ) as normalized_fragment_kinds,
               processing_steps, error, created_at, updated_at
        from material_sources
        where workspace_id = $1 and account_id = $2
        order by created_at, id
        """
    )
    source_rows = await pool.fetch(
        source_query,
        workspace_id,
        account_id,
    )
    ingress_rows = await pool.fetch(
        """
        select payload
        from (
          select id, payload
          from material_events
          where workspace_id = $1 and event_type = 'source_ingress_decided'
          order by id desc
          limit 200
        ) recent
        order by id
        """,
        workspace_id,
    )
    review_decisions = await get_latest_source_review_decisions(
        pool,
        workspace_id=workspace_id,
    )
    return MaterialSnapshot(
        workspace=_workspace(workspace_row),
        sources=[_source(row) for row in source_rows],
        ingress_decisions=[
            MaterialIngressDecision.model_validate(row["payload"])
            for row in ingress_rows
        ],
        review_decisions=review_decisions,
        projection_seq=(
            int(workspace_row["projection_seq"])
            if "projection_seq" in workspace_row
            else int(workspace_row["state_seq"])
        ),
    )


async def reserve_source_upload(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_label: str,
    object_path: str,
    file: ValidatedMaterialFile,
    scope_kind: Literal["profile", "topics", "uncertain"] = "uncertain",
    report_section_ids: tuple[str, ...] = (),
    route_step: ProcessingStep,
) -> MaterialSource:
    """在对象存储写入前登记 durable upload intent。"""
    now = datetime.now(timezone.utc)
    preflight = ProcessingStep(
        step="validated",
        processor="deterministic",
        status="warning" if file.quality_flags else "succeeded",
        parser="file-signature",
        input_fingerprint=file.sha256,
        output_fingerprint=file.sha256,
        quality_flags=file.quality_flags,
        message="",
        started_at=now,
        completed_at=now,
    )
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into material_sources
                  (workspace_id, account_id, source_label, original_filename, object_path,
                   kind, media_type, size_bytes, sha256, scope_kind, report_section_ids,
                   processing_steps)
                select $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                from material_workspaces
                where id = $1 and account_id = $2 and status = 'active'
                returning *
                """,
                workspace_id,
                account_id,
                source_label,
                file.filename,
                object_path,
                file.kind,
                file.media_type,
                file.size_bytes,
                file.sha256,
                scope_kind,
                list(report_section_ids),
                [preflight.model_dump(mode="json"), route_step.model_dump(mode="json")],
            )
            if row is None:
                raise MaterialOwnershipError(str(workspace_id))
            await conn.execute(
                """
                insert into material_events (workspace_id, source_id, actor, event_type, payload)
                values ($1, $2, 'user', 'source_upload_registered', $3)
                """,
                workspace_id,
                row["id"],
                {
                    "kind": file.kind,
                    "scopeKind": scope_kind,
                    "sizeBytes": file.size_bytes,
                    "sha256": file.sha256,
                },
            )
    except asyncpg.UniqueViolationError as error:
        raise MaterialDuplicateSourceError(file.sha256) from error
    return _source(row)


async def reserve_report_file_upload(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_label: str,
    object_path: str,
    file: ValidatedMaterialFile,
    declaration: UserFileDeclaration,
    max_files_per_report: int,
) -> tuple[MaterialSource, ReportMaterialBinding, bool]:
    """原子登记物理 Source、报告 Binding 与首个声明 Revision。"""

    now = datetime.now(timezone.utc)
    preflight = ProcessingStep(
        step="validated",
        processor="deterministic",
        status="warning" if file.quality_flags else "succeeded",
        parser="file-signature",
        input_fingerprint=file.sha256,
        output_fingerprint=file.sha256,
        quality_flags=file.quality_flags,
        message="文件已通过准入检查；尚未开始 File Agent 处理。",
        started_at=now,
        completed_at=now,
    )
    try:
        async with pool.acquire() as conn, conn.transaction():
            workspace = await conn.fetchrow(
                """
                select id from material_workspaces
                where id = $1 and account_id = $2 and status = 'active'
                for update
                """,
                workspace_id,
                account_id,
            )
            if workspace is None:
                raise MaterialOwnershipError(str(workspace_id))
            existing = await conn.fetchrow(
                """
                select source.*
                from material_sources source
                where source.workspace_id = $1 and source.account_id = $2
                  and source.sha256 = $3 and source.status <> 'deleted'
                for update
                """,
                workspace_id,
                account_id,
                file.sha256,
            )
            if existing is not None:
                binding_row = await conn.fetchrow(
                    """
                    select binding.id as binding_id, binding.workspace_id,
                           binding.source_id, binding.status as binding_status,
                           binding.created_at as binding_created_at,
                           binding.updated_at as binding_updated_at,
                           binding.removed_at, binding.superseded_at,
                           revision.id as declaration_revision_id,
                           revision.revision, revision.description, revision.role,
                           revision.topic_tags, revision.asset_title,
                           revision.created_at as declared_at
                    from report_material_bindings binding
                    join lateral (
                      select *
                      from user_file_declaration_revisions
                      where binding_id = binding.id
                      order by revision desc
                      limit 1
                    ) revision on true
                    where binding.workspace_id = $1 and binding.source_id = $2
                      and binding.status <> 'superseded'
                    order by case binding.status when 'active' then 0 else 1 end,
                             binding.created_at desc
                    limit 1
                    for update of binding
                    """,
                    workspace_id,
                    existing["id"],
                )
                if binding_row is None:
                    raise ReportFileSourceConflictError(
                        "同一物理文件尚未绑定当前报告文件入口"
                    )
                binding = _report_material_binding(binding_row)
                if binding.status == "removed":
                    raise ReportMaterialBindingStateError(
                        "相同文件已被移出，请显式恢复原 Binding"
                    )
                current = _declaration_revision(binding_row)
                if not current.matches(declaration):
                    raise ReportFileDeclarationConflictError(
                        "相同文件已有不同声明；请编辑既有文件说明"
                    )
                return _source(existing), binding, True
            count = await active_report_file_count(conn, workspace_id)
            if count >= max_files_per_report:
                raise ReportFileCapacityError(
                    f"当前报告最多接纳 {max_files_per_report} 份文件"
                )
            row = await conn.fetchrow(
                """
                insert into material_sources
                  (workspace_id, account_id, source_label, original_filename, object_path,
                   kind, media_type, size_bytes, sha256, scope_kind, report_section_ids,
                   processing_steps)
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'uncertain', '{}', $10)
                returning *
                """,
                workspace_id,
                account_id,
                source_label,
                file.filename,
                object_path,
                file.kind,
                file.media_type,
                file.size_bytes,
                file.sha256,
                [preflight.model_dump(mode="json")],
            )
            binding_row = await conn.fetchrow(
                """
                insert into report_material_bindings (workspace_id, source_id)
                values ($1, $2)
                returning id as binding_id, workspace_id, source_id,
                          status as binding_status,
                          created_at as binding_created_at,
                          updated_at as binding_updated_at,
                          removed_at, superseded_at
                """,
                workspace_id,
                row["id"],
            )
            revision_id = await conn.fetchval(
                """
                insert into user_file_declaration_revisions
                  (binding_id, workspace_id, revision, description, role,
                   topic_tags, asset_title)
                values ($1, $2, 1, $3, $4, $5, $6)
                returning id
                """,
                binding_row["binding_id"],
                workspace_id,
                declaration.description,
                declaration.role,
                declaration.topic_tags,
                declaration.asset_title,
            )
            await conn.execute(
                """
                insert into material_events (workspace_id, source_id, actor, event_type, payload)
                values ($1, $2, 'user', 'report_file_registered', $3)
                """,
                workspace_id,
                row["id"],
                {
                    "bindingId": str(binding_row["binding_id"]),
                    "declarationRevisionId": str(revision_id),
                    "sha256": file.sha256,
                    "role": declaration.role,
                    "topicTags": declaration.topic_tags,
                    "assetTitle": declaration.asset_title,
                },
            )
    except asyncpg.UniqueViolationError as error:
        raise MaterialDuplicateSourceError(file.sha256) from error
    return _source(row), _report_material_binding(binding_row), False


async def list_report_file_declarations(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
) -> list[
    tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]
]:
    """读取全部 Binding 及其最新声明；removed 仍可见且物理 Source 保留。"""

    rows = await pool.fetch(
        """
        select source.*, binding.id as binding_id, binding.source_id,
               binding.status as binding_status,
               binding.created_at as binding_created_at,
               binding.updated_at as binding_updated_at,
               binding.removed_at, binding.superseded_at,
               revision.id as declaration_revision_id,
               revision.revision, revision.description, revision.role,
               revision.topic_tags, revision.asset_title,
               revision.created_at as declared_at
        from report_material_bindings binding
        join material_sources source on source.id = binding.source_id
        join lateral (
          select *
          from user_file_declaration_revisions
          where binding_id = binding.id
          order by revision desc
          limit 1
        ) revision on true
        where binding.workspace_id = $1 and source.account_id = $2
        order by binding.created_at asc
        """,
        workspace_id,
        account_id,
    )
    return [
        (
            _source(row),
            _report_material_binding(row),
            _declaration_revision(row),
        )
        for row in rows
    ]


async def update_report_file_source_label(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    source_label: str,
) -> None:
    """幂等覆盖文件展示名;original_filename 与声明历史不受影响,不产生 Revision。"""

    result = await pool.execute(
        """
        update material_sources source
        set source_label = $4, updated_at = now()
        from report_material_bindings binding
        where binding.id = $3
          and binding.workspace_id = $2
          and source.id = binding.source_id
          and source.workspace_id = $2
          and source.account_id = $1
        """,
        account_id,
        workspace_id,
        binding_id,
        source_label,
    )
    if result != "UPDATE 1":
        raise MaterialOwnershipError(str(binding_id))


async def update_report_file_declaration(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    declaration: UserFileDeclaration,
    expected_revision: int,
) -> UserFileDeclarationRevision:
    """在 Binding 锁内追加不可变声明 Revision，不原地覆盖历史。"""

    async with pool.acquire() as conn, conn.transaction():
        binding = await conn.fetchrow(
            """
            select binding.id, binding.status, binding.source_id
            from report_material_bindings binding
            join material_sources source on source.id = binding.source_id
            where binding.id = $1 and binding.workspace_id = $2
              and source.account_id = $3
            for update of binding
            """,
            binding_id,
            workspace_id,
            account_id,
        )
        if binding is None:
            raise MaterialOwnershipError(str(binding_id))
        if binding["status"] != "active":
            raise ReportMaterialBindingStateError("只有 active Binding 可以编辑声明")
        current_revision = await conn.fetchval(
            """
            select revision
            from user_file_declaration_revisions
            where binding_id = $1
            order by revision desc
            limit 1
            """,
            binding_id,
        )
        if current_revision != expected_revision:
            raise MaterialStateConflictError("文件说明已被其他操作更新")
        row = await conn.fetchrow(
            """
            insert into user_file_declaration_revisions
              (binding_id, workspace_id, revision, description, role,
               topic_tags, asset_title)
            values ($1, $2, $3, $4, $5, $6, $7)
            returning id as declaration_revision_id, binding_id, revision,
                      description, role, topic_tags, asset_title,
                      created_at as declared_at
            """,
            binding_id,
            workspace_id,
            expected_revision + 1,
            declaration.description,
            declaration.role,
            declaration.topic_tags,
            declaration.asset_title,
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'user', 'report_file_declaration_updated', $3)
            """,
            workspace_id,
            binding["source_id"],
            {
                "bindingId": str(binding_id),
                "declarationRevisionId": str(row["declaration_revision_id"]),
                "role": row["role"],
                "topicTags": list(row["topic_tags"]),
                "assetTitle": row["asset_title"],
                "revision": row["revision"],
            },
        )
    return _declaration_revision(row)


async def remove_report_material_binding(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
) -> None:
    """幂等软移出 Binding；不改变 Source 状态，不删除主对象或备份。"""

    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            select binding.status, binding.source_id
            from report_material_bindings binding
            join material_sources source on source.id = binding.source_id
            where binding.id = $1 and binding.workspace_id = $2
              and source.account_id = $3
            for update of binding
            """,
            binding_id,
            workspace_id,
            account_id,
        )
        if row is None:
            raise MaterialOwnershipError(str(binding_id))
        if row["status"] == "superseded":
            raise ReportMaterialBindingStateError("superseded Binding 不能移出")
        if row["status"] == "removed":
            return
        await conn.execute(
            """
            update report_material_bindings
            set status = 'removed', removed_at = now(), updated_at = now()
            where id = $1
            """,
            binding_id,
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'user', 'report_material_binding_removed', $3)
            """,
            workspace_id,
            row["source_id"],
            {"bindingId": str(binding_id)},
        )


async def restore_report_material_binding(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
    max_files_per_report: int,
) -> None:
    """在容量锁内恢复 Binding；failed Source 不占文件额度。"""

    async with pool.acquire() as conn, conn.transaction():
        workspace = await conn.fetchval(
            """
            select 1 from material_workspaces
            where id = $1 and account_id = $2 and status = 'active'
            for update
            """,
            workspace_id,
            account_id,
        )
        if workspace is None:
            raise MaterialOwnershipError(str(workspace_id))
        row = await conn.fetchrow(
            """
            select binding.status, binding.source_id, source.status as source_status
            from report_material_bindings binding
            join material_sources source on source.id = binding.source_id
            where binding.id = $1 and binding.workspace_id = $2
              and source.account_id = $3
            for update of binding
            """,
            binding_id,
            workspace_id,
            account_id,
        )
        if row is None:
            raise MaterialOwnershipError(str(binding_id))
        if row["status"] == "active":
            return
        if row["status"] == "superseded":
            raise ReportMaterialBindingStateError("superseded Binding 不能恢复")
        if row["source_status"] not in {"failed", "deleted"}:
            count = await active_report_file_count(conn, workspace_id)
            if count >= max_files_per_report:
                raise ReportFileCapacityError(
                    f"当前报告最多接纳 {max_files_per_report} 份文件"
                )
        conflicting = await conn.fetchval(
            """
            select 1
            from report_material_bindings
            where source_id = $1 and status = 'active' and id <> $2
            """,
            row["source_id"],
            binding_id,
        )
        if conflicting is not None:
            raise ReportMaterialBindingStateError("同一 Source 已有 active Binding")
        await conn.execute(
            """
            update report_material_bindings
            set status = 'active', removed_at = null, updated_at = now()
            where id = $1
            """,
            binding_id,
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'user', 'report_material_binding_restored', $3)
            """,
            workspace_id,
            row["source_id"],
            {"bindingId": str(binding_id)},
        )


async def finalize_source_upload(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
    ingress_decision: MaterialIngressDecision,
) -> MaterialSource:
    """对象写入成功后原子发布来源；解析调度由资料集确认路径统一触发。"""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            update material_sources
            set status = 'ready', updated_at = now()
            where id = $1 and workspace_id = $2 and account_id = $3
              and status = 'uploading'
            returning *
            """,
            source_id,
            workspace_id,
            account_id,
        )
        if row is None:
            raise MaterialOwnershipError(str(source_id))
        route = next(
            (
                step.get("route")
                for step in row["processing_steps"]
                if step.get("step") == "routed"
            ),
            None,
        )
        await conn.execute(
            """
            insert into material_events
              (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'system', 'extraction_deferred', $3)
            """,
            workspace_id,
            source_id,
            {"route": route},
        )
        await conn.execute(
            """
            insert into material_events
              (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'system', 'source_ingress_decided', $3)
            """,
            workspace_id,
            source_id,
            ingress_decision.model_dump(mode="json"),
        )
    return _source(row)


async def fail_source_upload(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
    error: MaterialProcessingError,
    ingress_decision: MaterialIngressDecision | None = None,
) -> None:
    """把 durable upload intent 收敛为可见失败态，保留重试与审计依据。"""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            update material_sources
            set status = 'failed', error = $4, updated_at = now()
            where id = $1 and workspace_id = $2 and account_id = $3
              and status = 'uploading'
            returning id
            """,
            source_id,
            workspace_id,
            account_id,
            error.model_dump(mode="json"),
        )
        if row is None:
            raise MaterialOwnershipError(str(source_id))
        await conn.execute(
            """
            insert into material_events
              (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'system', 'source_upload_failed', $3)
            """,
            workspace_id,
            source_id,
            {
                "failureStage": error.failure_stage,
                "reason": error.reason,
                "retryable": error.retryable,
            },
        )
        if ingress_decision is not None:
            await conn.execute(
                """
                insert into material_events
                  (workspace_id, source_id, actor, event_type, payload)
                values ($1, $2, 'system', 'source_ingress_decided', $3)
                """,
                workspace_id,
                source_id,
                ingress_decision.model_dump(mode="json"),
            )


async def delete(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
) -> str:
    """软删除来源并撤销其状态依赖，返回不透明对象路径供 Storage 删除。"""
    async with pool.acquire() as conn, conn.transaction():
        workspace = await conn.fetchrow(
            """
            select state from material_workspaces
            where id = $1 and account_id = $2 and status = 'active'
            for update
            """,
            workspace_id,
            account_id,
        )
        if workspace is None:
            raise MaterialOwnershipError(str(workspace_id))
        row = await conn.fetchrow(
            """
            update material_sources
            set status = 'deleted', normalized_material = null, processing_steps = '[]'::jsonb,
                error = null, deleted_at = now(), updated_at = now()
            where id = $1 and workspace_id = $2 and account_id = $3 and status <> 'deleted'
            returning object_path, original_filename, sha256
            """,
            source_id,
            workspace_id,
            account_id,
        )
        if row is None:
            raise MaterialOwnershipError(str(source_id))
        state = WorkspaceState.model_validate(workspace["state"])
        next_state = stale_source_dependencies(
            state,
            source_id=source_id,
            reason="来源资料已删除",
        )
        await conn.execute(
            """
            update material_workspaces
            set state = $2, state_seq = state_seq + 1, updated_at = now()
            where id = $1
            """,
            workspace_id,
            next_state.model_dump(mode="json"),
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'user', 'source_deleted', $3)
            """,
            workspace_id,
            source_id,
            {"filename": row["original_filename"], "sha256": row["sha256"]},
        )
        await mark_source_stale(
            conn,
            account_id=account_id,
            source_id=source_id,
        )
    return row["object_path"]


async def get_workspace_by_report(
    pool: asyncpg.Pool, *, account_id: UUID, report_id: UUID
) -> MaterialWorkspace | None:
    """按 Report 返回当前活动 workspace；无权访问与不存在均不泄露行。"""
    row = await pool.fetchrow(
        """
        select * from material_workspaces
        where report_id = $1 and account_id = $2 and status = 'active'
        """,
        report_id,
        account_id,
    )
    return _workspace(row) if row is not None else None


async def get_source(
    pool: asyncpg.Pool, *, account_id: UUID, workspace_id: UUID, source_id: UUID
) -> MaterialSource:
    """读取 Account 所有权范围内的单一来源。"""
    row = await pool.fetchrow(
        """
        select * from material_sources
        where id = $1 and workspace_id = $2 and account_id = $3
        """,
        source_id,
        workspace_id,
        account_id,
    )
    if row is None:
        raise MaterialOwnershipError(str(source_id))
    return _source(row)


async def get_source_deletion_target(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
) -> MaterialSourceDeletionTarget:
    """读取删除所需的最小 typed 事实，不解析与删除无关的清洗正文。"""
    row = await pool.fetchrow(
        """
        select source.object_path, source.status, source.error
        from material_sources source
        where source.id = $1 and source.workspace_id = $2 and source.account_id = $3
        """,
        source_id,
        workspace_id,
        account_id,
    )
    if row is None:
        raise MaterialOwnershipError(str(source_id))
    return MaterialSourceDeletionTarget.model_validate(dict(row))


async def update_source_metadata(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
    scope_kind: Literal["profile", "topics", "uncertain"],
    report_section_ids: tuple[str, ...],
) -> MaterialSource:
    """原子更新议题归属，并使不再可写入的未应用提案失效。"""
    async with pool.acquire() as conn, conn.transaction():
        workspace = await conn.fetchrow(
            """
            select state from material_workspaces
            where id = $1 and account_id = $2 and status = 'active'
            for update
            """,
            workspace_id,
            account_id,
        )
        row = await conn.fetchrow(
            """
            select * from material_sources
            where id = $1 and workspace_id = $2 and account_id = $3
            for update
            """,
            source_id,
            workspace_id,
            account_id,
        )
        if workspace is None or row is None or row["status"] == "deleted":
            raise MaterialOwnershipError(str(source_id))
        if row["status"] in {"queued", "processing"}:
            raise MaterialStateConflictError(
                "资料正在处理，完成后才能修改议题归属"
            )
        previous_scope_kind = row["scope_kind"]
        previous_report_section_ids = tuple(row["report_section_ids"])
        next_state = WorkspaceState.model_validate(workspace["state"])
        scope_changed = (
            previous_scope_kind != scope_kind
            or previous_report_section_ids != report_section_ids
        )
        if scope_changed:
            next_state = stale_source_dependencies(
                next_state,
                source_id=source_id,
                reason="资料议题归属已变更",
            )
            await mark_source_stale(
                conn,
                account_id=account_id,
                source_id=source_id,
            )
        row = await conn.fetchrow(
            """
            update material_sources
            set scope_kind = $4, report_section_ids = $5, updated_at = now()
            where id = $1 and workspace_id = $2 and account_id = $3
            returning *
            """,
            source_id,
            workspace_id,
            account_id,
            scope_kind,
            list(report_section_ids),
        )
        await conn.execute(
            """
            update material_workspaces
            set state = $2, state_seq = state_seq + 1, updated_at = now()
            where id = $1
            """,
            workspace_id,
            next_state.model_dump(mode="json"),
        )
        await conn.execute(
            """
            insert into material_events (workspace_id, source_id, actor, event_type, payload)
            values ($1, $2, 'user', 'source_metadata_updated', $3)
            """,
            workspace_id,
            source_id,
            {
                "previousScopeKind": previous_scope_kind,
                "previousReportSectionIds": list(previous_report_section_ids),
                "scopeKind": scope_kind,
                "reportSectionIds": list(report_section_ids),
            },
        )
    return _source(row)


async def append_event(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    actor: Literal["user", "system", "agent"],
    event_type: str,
    payload: dict | None = None,
    source_id: UUID | None = None,
) -> int:
    """追加审计事件；本模块不提供 update/delete 事件接口。"""
    return await pool.fetchval(
        """
        insert into material_events (workspace_id, source_id, actor, event_type, payload)
        values ($1, $2, $3, $4, $5)
        returning id
        """,
        workspace_id,
        source_id,
        actor,
        event_type,
        payload or {},
    )


async def mutate_workspace(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    workspace_id: UUID,
    base_state_seq: int,
    state: WorkspaceState,
    actor: Literal["user", "system", "agent"],
    event_type: str,
    event_payload: dict | None = None,
    source_id: UUID | None = None,
) -> WorkspaceMutationResult:
    """CAS 更新 workspace state，并在同事务追加审计事件；不再有任何后台任务入队副作用。"""
    async with pool.acquire() as conn, conn.transaction():
        new_seq = await conn.fetchval(
            """
        update material_workspaces
        set state = $1, state_seq = state_seq + 1, updated_at = now()
        where id = $2 and account_id = $3 and state_seq = $4 and status = 'active'
        returning state_seq
        """,
            state.model_dump(mode="json"),
            workspace_id,
            account_id,
            base_state_seq,
        )
        if new_seq is None:
            owned = await conn.fetchval(
                "select 1 from material_workspaces where id = $1 and account_id = $2",
                workspace_id,
                account_id,
            )
            if owned is None:
                raise MaterialOwnershipError(str(workspace_id))
            raise MaterialStateConflictError(str(workspace_id))
        await conn.execute(
            """
        insert into material_events (workspace_id, source_id, actor, event_type, payload)
        values ($1, $2, $3, $4, $5)
        """,
            workspace_id,
            source_id,
            actor,
            event_type,
            event_payload or {},
        )
    return WorkspaceMutationResult(state_seq=new_seq)
