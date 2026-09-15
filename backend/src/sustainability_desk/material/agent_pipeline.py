# ABOUTME: 编排 File Agent、不可变资料快照和章节 Mapping 的可恢复后台节点。
# ABOUTME: worker 只消费租约与冻结输入；不调用旧预处理、关键词检索、VLM 或用户答案映射。
# ABOUTME(en): Resumable background nodes orchestrating the File Agent, frozen snapshots and section Mapping.
# ABOUTME(en): The worker consumes leases and frozen inputs only; no legacy preprocessing, retrieval or VLM.
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4

import asyncpg

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.compiled_definition import (
    CompiledReportDefinition,
    load_compiled_report_definition,
)
from sustainability_desk.contract.layout_asset_slots import layout_asset_slots
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    effective_report_scope,
    get_account_context_for_account,
)
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.prompt_profiles import load_prompt_profile
from sustainability_desk.llm.ai_observability import (
    create_observation_run,
    observe_generation,
)
from sustainability_desk.accounts.entitlement_profiles import ReportScopeKind
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import open_stage
from sustainability_desk.material.intake.file_agent_ai import (
    FileUnderstandingAgentAdapter,
    build_report_need_catalog,
)
from sustainability_desk.material.intake.file_agent_contract import (
    FileAgentContext,
    FileAgentProductTask,
    FileMaterialScope,
    FileAgentRunReceipt,
    FileAgentRunResult,
    FileAgentTraceEvent,
    FileSourceRevision,
)
from sustainability_desk.material.intake.file_agent_workspace import (
    AVAILABLE_TOOLS,
    FileAgentWorkspace,
)
from sustainability_desk.material.intake.image_agent_ai import (
    ImageUnderstandingAgentAdapter,
    build_run_receipt as build_image_run_receipt,
    freeze_image_dossier,
    model_image_pixel_size,
    prepare_model_image,
)
from sustainability_desk.material.intake.image_agent_contract import (
    ImageAgentContext,
    ImageAgentProductTask,
)
from sustainability_desk.material.intake.models import UserFileDeclaration
from sustainability_desk.material.intake.storage import MaterialStorageClient
from sustainability_desk.material.mapping.agent import (
    MappingAgentDeps,
    MappingAgentRunner,
)
from sustainability_desk.material.mapping.scope import (
    assemble_mapping_tasks,
    material_routes_to_scope,
)
from sustainability_desk.material.mapping.report_assembly import (
    EffectiveMappingTaskAssembly,
    assemble_effective_mapping_tasks,
    require_current_mapping_scope,
)
from sustainability_desk.material.mapping.snapshot import (
    build_frozen_mapping_plan,
    build_material_set_snapshot,
    member_from_dossier,
)
from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import material_intake as material_dal
from sustainability_desk.persistence import reports as reports_dal

FILE_AGENT_HARNESS_VERSION = "sustainability_desk.file-agent-harness.v9"
MAPPING_HARNESS_VERSION = "sustainability_desk.mapping-agent-harness.v8"
IMAGE_AGENT_HARNESS_VERSION = "sustainability_desk.image-agent-harness.v2"
MAPPING_POLICY_ID = "lightweight-material-selection@1"
DEFAULT_FILE_AGENT_MODEL_ID = DEFAULT_MODEL_ID
DEFAULT_MAPPING_MODEL_ID = DEFAULT_MODEL_ID
DEFAULT_IMAGE_AGENT_MODEL_ID = DEFAULT_MODEL_ID

# ---- 链路阶段声明（与使用处同址，导入即登记；spec 决策点 B）----
_PIPELINE_SCOPES: tuple[ReportScopeKind, ...] = ("full_simplified",)

FILE_AGENT_STAGE = register_stage(
    Stage(id="material.file_agent", kind="agent", scopes=_PIPELINE_SCOPES, unit_root=True)
)
IMAGE_AGENT_STAGE = register_stage(
    Stage(id="material.image_agent", kind="agent", scopes=_PIPELINE_SCOPES, unit_root=True)
)
MAPPING_RUN_STAGE = register_stage(
    Stage(id="material.mapping_agent", kind="agent", scopes=_PIPELINE_SCOPES, unit_root=True)
)
MAPPING_SCOPE_CHECK_STAGE = register_stage(
    Stage(id="material.mapping.scope_check", kind="deterministic", scopes=_PIPELINE_SCOPES)
)
# synchronize 不受执行范围约束：三个调用点中两个在 API 请求内（无工作单元、无 scope），
# worker 侧触发时若本 run 已因权益校验失败，scope 同样不可得。
MAPPING_SYNCHRONIZE_STAGE = register_stage(
    Stage(id="material.mapping.synchronize", kind="deterministic")
)


def _fingerprint(value: object) -> str:
    payload = (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else value
    )
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def file_material_scopes(
    definition: CompiledReportDefinition,
    effective_assembly: EffectiveMappingTaskAssembly,
) -> tuple[FileMaterialScope, ...]:
    """派生 File Agent 的资料 scope 目录：完整报告定义的全部 scope，标记本次报告覆盖。

    目录不随权益范围或重要性评估收窄——否则只对范围外议题有价值的资料在类型系统里
    无法表达为「相关但不在本次报告」，只能被判成 not_relevant 而静默丢弃。Mapping 任务
    仍只按 `effective_assembly` 建立，范围外 scope 的资料自然不进入生成上下文。
    """

    covered_scope_ids = frozenset(
        scope.scope_id for scope in effective_assembly.mapping_tasks.scopes
    )
    return tuple(
        FileMaterialScope(
            alias=f"scope_{ordinal}",
            scope_id=item.scope_id,
            title=item.title,
            kind=item.scope_kind,
            within_report_scope=item.scope_id in covered_scope_ids,
        )
        for ordinal, item in enumerate(assemble_mapping_tasks(definition).scopes, start=1)
    )


def _report_identity(
    state: StoredReportStateV4,
) -> tuple[str | None, str | None]:
    subject = str(state.fields.get("company_registered_name") or "").strip()
    period_start = str(state.fields.get("report_period_start") or "").strip()
    period_end = str(state.fields.get("report_period_end") or "").strip()
    period = " 至 ".join(item for item in (period_start, period_end) if item)
    return subject or None, period or None


async def enqueue_file_agent_for_binding(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
) -> pipeline_dal.FileAgentRunRecord | None:
    """为当前 active 语义资料创建或复用 File Agent Run。"""

    records = await material_dal.list_report_file_declarations(
        pool,
        account_id=account_id,
        workspace_id=workspace_id,
    )
    selected = next(
        (
            item
            for item in records
            if item[1].binding_id == binding_id
        ),
        None,
    )
    if selected is None:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "待调度 Binding 不存在"
        )
    source, binding, declaration_revision = selected
    if binding.status != "active" or declaration_revision.role != "semantic_material":
        return None
    account_context = await get_account_context_for_account(pool, account_id)
    report_summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    execution_scope = effective_report_scope(
        account_context,
        created_under_profile_id=report_summary.created_under_profile_id,
        report_profile_id=report_summary.report_profile_id,
    )
    if not account_context.active or not execution_scope.material_agent_enabled:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "当前报告未开通资料 Agent"
        )
    report = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        account_id,
        report_id,
    )
    subject, period = _report_identity(report.state)
    declaration = UserFileDeclaration.model_validate(
        declaration_revision.model_dump(
            include={"description", "role", "topic_tags", "asset_title"}
        )
    )
    definition = load_compiled_report_definition(execution_scope.knowledge_package)
    material_scopes = file_material_scopes(
        definition,
        assemble_effective_mapping_tasks(definition, report.state, execution_scope),
    )
    context = FileAgentContext(
        source_revision=FileSourceRevision(
            source_id=source.id,
            source_sha256=source.sha256,
            declaration_revision=declaration_revision.revision,
        ),
        filename=source.filename,
        material_kind=source.kind,
        size_bytes=source.size_bytes,
        declaration=declaration,
        product_task=FileAgentProductTask(
            report_id=report_id,
            report_subject_name=subject,
            report_period_label=period,
            scope_label=execution_scope.model_context_scope_label,
            material_scopes=material_scopes,
        ),
        available_tools=AVAILABLE_TOOLS,
    )
    input_fingerprint = _fingerprint(
        {
            "context": context.model_dump(mode="json"),
            "reportNeedCatalog": build_report_need_catalog(context.product_task.material_scopes),
            "harnessVersion": FILE_AGENT_HARNESS_VERSION,
        }
    )
    await pipeline_dal.supersede_file_agent_runs(
        pool,
        report_id=report_id,
        binding_id=binding_id,
        except_input_fingerprint=input_fingerprint,
    )
    return await pipeline_dal.enqueue_file_agent_run(
        pool,
        run_id=uuid4(),
        account_id=account_id,
        report_id=report_id,
        workspace_id=workspace_id,
        binding_id=binding_id,
        declaration_revision_id=declaration_revision.revision_id,
        context=context,
        input_fingerprint=input_fingerprint,
        idempotency_key=f"file-agent:{binding_id}:{input_fingerprint}",
        harness_version=FILE_AGENT_HARNESS_VERSION,
    )


async def enqueue_image_agent_for_binding(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    binding_id: UUID,
) -> pipeline_dal.ImageAgentRunRecord | None:
    """为当前 active 排版素材创建或复用 Image Agent Run。"""

    records = await material_dal.list_report_file_declarations(
        pool,
        account_id=account_id,
        workspace_id=workspace_id,
    )
    selected = next(
        (
            item
            for item in records
            if item[1].binding_id == binding_id
        ),
        None,
    )
    if selected is None:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "待调度 Binding 不存在"
        )
    source, binding, declaration_revision = selected
    if binding.status != "active" or declaration_revision.role != "layout_asset":
        return None
    account_context = await get_account_context_for_account(pool, account_id)
    report_summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    execution_scope = effective_report_scope(
        account_context,
        created_under_profile_id=report_summary.created_under_profile_id,
        report_profile_id=report_summary.report_profile_id,
    )
    if not account_context.active or not execution_scope.material_agent_enabled:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "当前报告未开通资料 Agent"
        )
    report = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        account_id,
        report_id,
    )
    subject, period = _report_identity(report.state)
    declaration = UserFileDeclaration.model_validate(
        declaration_revision.model_dump(
            include={"description", "role", "topic_tags", "asset_title"}
        )
    )
    material_scopes = tuple(
        FileMaterialScope(
            alias=f"scope_{ordinal}",
            scope_id=slot.scope_id,
            title=slot.scope_title,
            kind=slot.scope_kind,
        )
        for ordinal, slot in enumerate(
            layout_asset_slots(load_compiled_report_definition(execution_scope.knowledge_package)),
            start=1,
        )
    )
    context = ImageAgentContext(
        source_revision=FileSourceRevision(
            source_id=source.id,
            source_sha256=source.sha256,
            declaration_revision=declaration_revision.revision,
        ),
        filename=source.filename,
        material_kind=source.kind,
        size_bytes=source.size_bytes,
        declaration=declaration,
        product_task=ImageAgentProductTask(
            report_id=report_id,
            report_subject_name=subject,
            report_period_label=period,
            scope_label=execution_scope.model_context_scope_label,
            material_scopes=material_scopes,
        ),
    )
    input_fingerprint = _fingerprint(
        {
            "context": context.model_dump(mode="json"),
            "harnessVersion": IMAGE_AGENT_HARNESS_VERSION,
        }
    )
    await pipeline_dal.supersede_image_agent_runs(
        pool,
        report_id=report_id,
        binding_id=binding_id,
        except_input_fingerprint=input_fingerprint,
    )
    return await pipeline_dal.enqueue_image_agent_run(
        pool,
        run_id=uuid4(),
        account_id=account_id,
        report_id=report_id,
        workspace_id=workspace_id,
        binding_id=binding_id,
        declaration_revision_id=declaration_revision.revision_id,
        context=context,
        input_fingerprint=input_fingerprint,
        idempotency_key=f"image-agent:{binding_id}:{input_fingerprint}",
        harness_version=IMAGE_AGENT_HARNESS_VERSION,
    )


NON_RETRYABLE_WORKER_ERROR_TYPES = (
    AccountEntitlementError,
    pipeline_dal.MaterialAgentPipelinePersistenceError,
    ValueError,
)


def is_retryable_worker_error(error: BaseException) -> bool:
    """判定 worker 失败能否在 attempt 余量内回置 queued 重试。

    权益失效、持久化合同不一致与冻结输入契约错误是确定性失败，重跑同一输入
    不会改变结果；其余（模型行为异常、网络与存储等瞬时错误）默认可重试，
    成本由 max_attempts 封顶。
    """

    return not isinstance(error, NON_RETRYABLE_WORKER_ERROR_TYPES)


def _failed_file_result(
    lease: pipeline_dal.FileAgentRunLease,
    *,
    failure_code: str,
) -> FileAgentRunResult:
    now = datetime.now(timezone.utc)
    return FileAgentRunResult(
        status="failed",
        dossier=None,
        checkpoint=None,
        receipt=FileAgentRunReceipt(
            run_id=lease.run_id,
            attempt=lease.attempt,
            status="failed",
            source_revision=lease.context.source_revision,
            started_at=now,
            finished_at=now,
            tool_receipts=(),
            trace_events=(
                FileAgentTraceEvent(
                    sequence=1,
                    occurred_at=now,
                    event_type="run_failed",
                    detail_code=failure_code[:100],
                ),
            ),
            failure_code=failure_code[:100],
        ),
    )


async def process_one_file_agent_run(
    pool: asyncpg.Pool,
    *,
    storage: MaterialStorageClient,
    worker_id: str,
    model_id: str = DEFAULT_FILE_AGENT_MODEL_ID,
    report_id: UUID | None = None,
) -> bool:
    """领取并执行一个 File Agent 节点；失败也保存 typed receipt。"""

    lease = await pipeline_dal.claim_file_agent_run(
        pool,
        worker_id=worker_id,
        report_id=report_id,
    )
    if lease is None:
        return False
    execution_scope = None
    file_stage = None
    try:
        execution_scope = await _assert_pipeline_scope(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            required_capability="material_agent",
            topic_tags=lease.context.declaration.topic_tags,
        )
        source = await material_dal.get_source(
            pool,
            account_id=lease.account_id,
            workspace_id=lease.workspace_id,
            source_id=lease.context.source_revision.source_id,
        )
        source_bytes = await storage.download(
            source.object_path,
            max_bytes=source.size_bytes + 1,
        )
        workspace = FileAgentWorkspace(
            source_bytes=source_bytes,
            context=lease.context,
        )
        if lease.checkpoint is not None:
            # checkpoint 重放会重新执行解析（可能含逐页 OCR），属 CPU 重活；
            # 卸载到线程池,避免阻塞并发 worker 的事件循环。模型 tool loop 内的
            # 解析由 pydantic_ai 对同步工具自动经 executor 执行,无需额外处理。
            await asyncio.to_thread(workspace.restore, lease.checkpoint)
        observation = create_observation_run(
            FILE_AGENT_STAGE,
            model_id=model_id,
            workload_kind="product_generation",
            report_id=str(lease.report_id),
            block_id=f"file:{lease.context.source_revision.source_id}",
            run_id=str(lease.run_id),
            user_id=str(lease.account_id),
            contract_version=contract_version(execution_scope.knowledge_package),
        )
        with open_stage(
            FILE_AGENT_STAGE,
            # traceId 恒为工作单元 run_id，与模型事件文件名对齐（spec 决策点 A）；
            # 报告级聚合靠 report_id 字段，不再借 report_id 充当 traceId。
            trace_id=str(lease.run_id),
            report_id=str(lease.report_id),
            scope=execution_scope.kind,
            **{
                "sustainability_desk.source_id": str(lease.context.source_revision.source_id),
                "sustainability_desk.attempt": lease.attempt,
            },
        ) as file_stage:
            with observe_generation(observation):
                result = await FileUnderstandingAgentAdapter(
                    model_id=model_id,
                    texts=load_prompt_profile(
                        execution_scope.knowledge_package
                    ).agent_instructions.file_agent,
                ).run(
                    workspace,
                    observation=observation,
                    run_id=lease.run_id,
                    attempt=lease.attempt,
                )
        await _assert_pipeline_scope(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            required_capability="material_agent",
            topic_tags=lease.context.declaration.topic_tags,
        )
        retryable_failure = False
    except Exception as error:  # noqa: BLE001 - worker 终态必须持久化
        result = _failed_file_result(
            lease,
            failure_code=type(error).__name__,
        )
        retryable_failure = is_retryable_worker_error(error)
    await pipeline_dal.finish_file_agent_run(
        pool,
        run_id=lease.run_id,
        lease_token=lease.lease_token,
        result=result,
        retryable_failure=retryable_failure,
    )
    if (
        await pipeline_dal.unfinished_file_agent_work(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
        )
    ).total == 0:
        # 快照冻结与 scope 扇出是本文件唯一的关键路由决策点；它由"最后一个完成的
        # file run"触发，故其 span 归入该 run 的 trace。API 侧的另两个调用点不在
        # 任何工作单元内，失败由具名异常 fail-loud，不开 span。
        with open_stage(
            MAPPING_SYNCHRONIZE_STAGE,
            trace_id=str(lease.run_id),
            report_id=str(lease.report_id),
            scope=execution_scope.kind if execution_scope is not None else None,
            # 根 span 已收束但父子事实仍然成立：本决策点由该 file run 触发，
            # 挂其根下保持"一个单元 trace 恰一个根"的树形不变量。
            parent=file_stage,
        ):
            await synchronize_mapping_runs(
                pool,
                account_id=lease.account_id,
                report_id=lease.report_id,
            )
    return True


def _image_agent_scope_alias_map(context: ImageAgentContext) -> dict[str, str]:
    return {
        scope.alias: scope.scope_id
        for scope in context.product_task.material_scopes
    }


async def process_one_image_agent_run(
    pool: asyncpg.Pool,
    *,
    storage: MaterialStorageClient,
    worker_id: str,
    model_id: str = DEFAULT_IMAGE_AGENT_MODEL_ID,
    report_id: UUID | None = None,
) -> bool:
    """领取并执行一个 Image Agent 节点；成功时同一事务内提升为 confirmed 排版素材证据资产。

    不触发 synchronize_mapping_runs——排版素材不进入语义资料 Mapping 链路。
    """

    lease = await pipeline_dal.claim_image_agent_run(
        pool,
        worker_id=worker_id,
        report_id=report_id,
    )
    if lease is None:
        return False
    started_at = datetime.now(timezone.utc)
    try:
        execution_scope = await _assert_pipeline_scope(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            required_capability="material_agent",
            topic_tags=lease.context.declaration.topic_tags,
        )
        source = await material_dal.get_source(
            pool,
            account_id=lease.account_id,
            workspace_id=lease.workspace_id,
            source_id=lease.source_id,
        )
        source_bytes = await storage.download(
            source.object_path,
            max_bytes=source.size_bytes + 1,
        )
        media_type = source.media_type
        # 图片预处理（Pillow 解码/降采样、单页 PDF 渲染）是 CPU 重活,卸载到线程池。
        model_image = await asyncio.to_thread(
            prepare_model_image, source_bytes, media_type=media_type
        )
        width_px, height_px = await asyncio.to_thread(
            model_image_pixel_size, source_bytes, media_type=media_type
        )
        context = lease.context.model_copy(
            update={"image_width_px": width_px, "image_height_px": height_px}
        )
        observation = create_observation_run(
            IMAGE_AGENT_STAGE,
            model_id=model_id,
            workload_kind="product_generation",
            report_id=str(lease.report_id),
            block_id=f"file:{lease.source_id}",
            run_id=str(lease.run_id),
            user_id=str(lease.account_id),
            contract_version=contract_version(execution_scope.knowledge_package),
        )
        with open_stage(
            IMAGE_AGENT_STAGE,
            trace_id=str(lease.run_id),
            report_id=str(lease.report_id),
            scope=execution_scope.kind,
            **{
                "sustainability_desk.source_id": str(lease.source_id),
                "sustainability_desk.attempt": lease.attempt,
            },
        ):
            with observe_generation(observation):
                draft = await ImageUnderstandingAgentAdapter(
                    model_id=model_id,
                    texts=load_prompt_profile(
                        execution_scope.knowledge_package
                    ).agent_instructions.image_agent,
                ).run(
                    context,
                    model_image,
                    observation=observation,
                )
        await _assert_pipeline_scope(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            required_capability="material_agent",
            topic_tags=lease.context.declaration.topic_tags,
        )
        dossier = freeze_image_dossier(
            draft,
            context=context,
            scope_alias_to_id=_image_agent_scope_alias_map(context),
        )
    except Exception as error:  # noqa: BLE001 - worker 终态必须持久化
        receipt = build_image_run_receipt(
            run_id=lease.run_id,
            observation_run_id=None,
            attempt=lease.attempt,
            context=lease.context,
            started_at=started_at,
            failure_code=type(error).__name__,
        )
        await pipeline_dal.finish_image_agent_run(
            pool,
            run_id=lease.run_id,
            lease_token=lease.lease_token,
            status="failed",
            output_payload=None,
            receipt=receipt,
            retryable_failure=is_retryable_worker_error(error),
        )
        return True
    receipt = build_image_run_receipt(
        run_id=lease.run_id,
        observation_run_id=observation.runId,
        attempt=lease.attempt,
        context=context,
        started_at=started_at,
        dossier_fingerprint=dossier.dossier_fingerprint,
    )
    async with pool.acquire() as connection, connection.transaction():
        await pipeline_dal.finish_image_agent_run(
            connection,
            run_id=lease.run_id,
            lease_token=lease.lease_token,
            status="succeeded",
            output_payload=dossier.model_dump(mode="json"),
            receipt=receipt,
        )
        await layout_asset_dal.promote_layout_asset(
            connection,
            report_id=lease.report_id,
            account_id=lease.account_id,
            material_source_id=lease.source_id,
            caption=(
                lease.context.declaration.asset_title
                if lease.context.declaration.asset_title
                else dossier.caption
            ),
            alt_text=dossier.alt_text,
            width_px=width_px,
            height_px=height_px,
            category=dossier.category,
            placement_scope_id=dossier.scope_id,
            fingerprint=dossier.dossier_fingerprint,
            certificate_fact=(
                dossier.certificate_fact.model_dump(mode="json")
                if dossier.certificate_fact
                else None
            ),
        )
    return True


async def synchronize_mapping_runs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> UUID | None:
    """冻结当前 Dossier 路由；仅对确有候选资料的 scope 建立 Mapping Run。"""

    if (
        await pipeline_dal.unfinished_file_agent_work(
            pool,
            account_id=account_id,
            report_id=report_id,
        )
    ).total:
        return None
    workspace = await material_dal.get_workspace_by_report(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if workspace is None:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "报告没有活动资料工作区"
        )
    dossier_records = await pipeline_dal.list_current_dossiers(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    relevant_records = tuple(
        record for record in dossier_records if record.dossier.candidate_for_mapping
    )
    account_context = await get_account_context_for_account(pool, account_id)
    report_summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    execution_scope = effective_report_scope(
        account_context,
        created_under_profile_id=report_summary.created_under_profile_id,
        report_profile_id=report_summary.report_profile_id,
    )
    if not account_context.active or not execution_scope.material_agent_enabled:
        raise pipeline_dal.MaterialAgentPipelinePersistenceError(
            "当前报告未开通资料 Agent"
        )
    report_state = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        account_id,
        report_id,
    )
    effective_assembly = assemble_effective_mapping_tasks(
        load_compiled_report_definition(execution_scope.knowledge_package),
        report_state.state,
        execution_scope,
    )
    routed_scopes = tuple(
        (
            scope,
            tuple(
                record.dossier.dossier_id
                for record in relevant_records
                if any(
                    material_routes_to_scope(scope, material.applicable_scope_ids)
                    for material in record.dossier.materials
                )
            ),
        )
        for scope in effective_assembly.mapping_tasks.scopes
    )
    mapping_plan = build_frozen_mapping_plan(
        candidate_dossier_ids=tuple(
            record.dossier.dossier_id for record in relevant_records
        ),
        routed_scopes=routed_scopes,
    )
    snapshot = build_material_set_snapshot(
        report_id=report_id,
        members=tuple(
            member_from_dossier(
                binding_id=record.binding_id,
                dossier=record.dossier,
            )
            for record in dossier_records
        ),
        mapping_plan=mapping_plan,
    )
    stored_snapshot = await pipeline_dal.store_material_set_snapshot(
        pool,
        account_id=account_id,
        workspace_id=workspace.id,
        snapshot=snapshot,
    )
    snapshot = stored_snapshot.snapshot
    scope_by_id = {scope.scope_id: scope for scope, _ in routed_scopes}
    for plan_scope in snapshot.mapping_plan.scopes:
        scope = scope_by_id[plan_scope.scope_id]
        scope_dossier_ids = plan_scope.dossier_ids
        input_fingerprint = _fingerprint(
            {
                "snapshot": snapshot.input_fingerprint,
                "scope": scope.model_dump(mode="json"),
                "selectedDossierIds": [
                    str(dossier_id) for dossier_id in scope_dossier_ids
                ],
                "mappingPolicy": MAPPING_POLICY_ID,
                "harnessVersion": MAPPING_HARNESS_VERSION,
            }
        )
        await pipeline_dal.enqueue_mapping_run(
            pool,
            run_id=uuid4(),
            account_id=account_id,
            report_id=report_id,
            workspace_id=workspace.id,
            snapshot_id=snapshot.snapshot_id,
            scope=scope,
            dossier_ids=scope_dossier_ids,
            input_fingerprint=input_fingerprint,
            idempotency_key=(
                f"mapping:{scope.scope_id}:{input_fingerprint}"
            ),
            mapping_policy_id=MAPPING_POLICY_ID,
            harness_version=MAPPING_HARNESS_VERSION,
        )
    return snapshot.snapshot_id


async def _current_mapping_task_assembly(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> EffectiveMappingTaskAssembly:
    """重新读取当前 state 与报告权限，供 Mapping worker 在模型调用前后 fail-closed。"""

    execution_scope = await _assert_pipeline_scope(
        pool,
        account_id=account_id,
        report_id=report_id,
        required_capability="material_agent",
    )
    report_state = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        account_id,
        report_id,
    )
    return assemble_effective_mapping_tasks(
        load_compiled_report_definition(execution_scope.knowledge_package),
        report_state.state,
        execution_scope,
    )


async def process_one_mapping_run(
    pool: asyncpg.Pool,
    *,
    storage: MaterialStorageClient,
    worker_id: str,
    model_id: str = DEFAULT_MAPPING_MODEL_ID,
    report_id: UUID | None = None,
    scope_id: str | None = None,
) -> bool:
    """领取并执行一个已冻结且非空的章节 Mapping。"""

    lease = await pipeline_dal.claim_mapping_run(
        pool,
        worker_id=worker_id,
        report_id=report_id,
        scope_id=scope_id,
    )
    if lease is None:
        return False
    try:
        execution_scope = await _assert_pipeline_scope(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            required_capability="material_agent",
        )
    except Exception as error:  # noqa: BLE001 - 无权限时终结已领取租约
        await pipeline_dal.fail_mapping_run(
            pool,
            run_id=lease.run_id,
            lease_token=lease.lease_token,
            failure_code=type(error).__name__,
            receipt={"failureType": type(error).__name__},
            retryable_failure=is_retryable_worker_error(error),
        )
        return True
    observation = create_observation_run(
        MAPPING_RUN_STAGE,
        model_id=model_id,
        workload_kind="product_generation",
        report_id=str(lease.report_id),
        block_id=lease.input.scope.scope_id,
        run_id=str(lease.run_id),
        user_id=str(lease.account_id),
        contract_version=contract_version(execution_scope.knowledge_package),
    )
    try:
        # 单元根 span 覆盖 scope 一致性校验与模型调用：装配期失败若不在 span 内
        # 就零轨迹、无从归因，故与模型调用同处一棵 span 树，共享单元 trace。
        with open_stage(
            MAPPING_RUN_STAGE,
            trace_id=str(lease.run_id),
            report_id=str(lease.report_id),
            scope=execution_scope.kind,
            **{"sustainability_desk.scope_id": lease.input.scope.scope_id},
        ) as mapping_stage:
            with open_stage(
                MAPPING_SCOPE_CHECK_STAGE,
                trace_id=str(lease.run_id),
                report_id=str(lease.report_id),
                scope=execution_scope.kind,
            ):
                current_assembly = await _current_mapping_task_assembly(
                    pool,
                    account_id=lease.account_id,
                    report_id=lease.report_id,
                )
                require_current_mapping_scope(current_assembly, lease.input.scope)
            records = await pipeline_dal.load_dossiers(
                pool,
                account_id=lease.account_id,
                report_id=lease.report_id,
                dossier_ids=lease.input.dossier_ids,
            )
            if not records:
                raise pipeline_dal.MaterialAgentPipelinePersistenceError(
                    "冻结 Mapping plan 不得创建空 dossier 运行"
                )
            mapping_stage.set_attribute("sustainability_desk.dossier_count", len(records))
            deps = MappingAgentDeps(
                scope=lease.input.scope,
                dossier_entries=tuple(record.mapping_entry() for record in records),
            )
            with observe_generation(observation):
                result = await MappingAgentRunner(
                    observation=observation,
                    model_id=model_id,
                    texts=load_prompt_profile(
                        execution_scope.knowledge_package
                    ).agent_instructions.mapping_agent,
                ).run(deps)
        current_assembly = await _current_mapping_task_assembly(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
        )
        require_current_mapping_scope(current_assembly, lease.input.scope)
        await pipeline_dal.finish_mapping_run(
            pool,
            run_id=lease.run_id,
            lease_token=lease.lease_token,
            result=result,
            receipt={
                "observationRunId": observation.runId,
                "attempt": lease.attempt,
                "mappingPolicyId": MAPPING_POLICY_ID,
                "harnessVersion": MAPPING_HARNESS_VERSION,
            },
        )
    except Exception as error:  # noqa: BLE001 - worker 必须终结租约
        await pipeline_dal.fail_mapping_run(
            pool,
            run_id=lease.run_id,
            lease_token=lease.lease_token,
            failure_code=type(error).__name__,
            receipt={
                "observationRunId": observation.runId,
                "attempt": lease.attempt,
                "failureType": type(error).__name__,
            },
            retryable_failure=is_retryable_worker_error(error),
        )
    return True


async def _assert_pipeline_scope(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    required_capability: Literal["material_agent"],
    topic_tags: list[str] | None = None,
):
    """在 worker 调用模型前重算授权；队列输入仅可审计，不持续授权。"""

    context = await get_account_context_for_account(pool, account_id)
    summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    scope = effective_report_scope(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )
    if required_capability == "material_agent" and (
        not context.active or not scope.material_agent_enabled
    ):
        raise AccountEntitlementError("资料 Agent 权益已失效")
    return scope
