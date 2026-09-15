# ABOUTME: 验证 File/Mapping 运行持久化保存严格输入与 BlockMaterialDecision，不落地 Mapping 企业事实。
# ABOUTME: 迁移仅替换轻量版材料选择表，不触及 P3 的 evidence_facts 领域表。
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sustainability_desk.material.intake.file_agent_contract import (
    FileAgentContext,
    FileAgentProductTask,
    FileAgentRunCheckpoint,
    FileAgentRunReceipt,
    FileAgentRunResult,
    FileAgentTraceEvent,
    FileMaterialScope,
    FileSourceRevision,
)
from sustainability_desk.material.intake.models import UserFileDeclaration
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision, ValidatedMappingResult
from sustainability_desk.material.mapping.snapshot import MaterialSetMember, build_frozen_mapping_plan, build_material_set_snapshot
from sustainability_desk.material.mapping.scope import MappingBlockTask, MappingScopeDefinition
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal


class _Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql, *args):
        self.statements.append((sql, args))
        return self.rows.pop(0)

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        return "UPDATE 1"

    async def executemany(self, sql, args):
        self.executemany_calls.append((sql, args))


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def fetchrow(self, sql, *args):
        return await self.connection.fetchrow(sql, *args)

    async def execute(self, sql, *args):
        return await self.connection.execute(sql, *args)


def _file_context(report_id):
    revision = FileSourceRevision(source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1)
    return FileAgentContext(
        source_revision=revision, filename="气候制度.docx", material_kind="docx", size_bytes=1024,
        declaration=UserFileDeclaration(description="公司提交的气候治理制度资料。", role="semantic_material", topic_tags=["气候变化"]),
        product_task=FileAgentProductTask(
            report_id=report_id,
            material_scopes=(FileMaterialScope(alias="scope_climate", scope_id="report-section:climate", title="气候", kind="esg_topic"),),
        ),
        available_tools=("convert_file", "read_file"),
    )


@pytest.mark.asyncio
async def test_enqueue_file_agent_run_persists_typed_context() -> None:
    account_id, report_id, workspace_id, binding_id, declaration_id, run_id = (uuid4() for _ in range(6))
    context = _file_context(report_id)
    row = {
        "id": run_id, "account_id": account_id, "report_id": report_id, "workspace_id": workspace_id,
        "binding_id": binding_id, "source_id": context.source_revision.source_id, "declaration_revision_id": declaration_id,
        "input_fingerprint": "b" * 64, "idempotency_key": "file-agent:test", "harness_version": "file-agent@1",
        "status": "queued", "attempt": 0, "max_attempts": 3, "input_payload": context.model_dump(mode="json"),
        "checkpoint": None, "dossier_id": None,
    }
    connection = _Connection([row])
    stored = await pipeline_dal.enqueue_file_agent_run(
        _Pool(connection), run_id=run_id, account_id=account_id, report_id=report_id, workspace_id=workspace_id,
        binding_id=binding_id, declaration_revision_id=declaration_id, context=context, input_fingerprint="b" * 64,
        idempotency_key="file-agent:test", harness_version="file-agent@1",
    )
    assert "insert into file_agent_runs" in connection.statements[0][0]
    assert stored.context == context


@pytest.mark.asyncio
async def test_finish_mapping_persists_ordered_material_decisions_only() -> None:
    account_id, report_id, workspace_id, binding_id, dossier_id, source_id, run_id, lease_token, material_id = (uuid4() for _ in range(9))
    scope = MappingScopeDefinition(
        scope_id="report-section:climate", scope_kind="esg_topic", title="气候", report_section_id="climate",
        block_tasks=(MappingBlockTask(block_id="block/climate", title="治理", semantic_task="说明治理", absence_behavior="generate_context_only"),),
    )
    member = MaterialSetMember(binding_id=binding_id, dossier_id=dossier_id, source_id=source_id, source_sha256="a" * 64, declaration_revision=1, dossier_fingerprint="b" * 64)
    snapshot = build_material_set_snapshot(
        report_id=report_id, members=(member,),
        mapping_plan=build_frozen_mapping_plan(candidate_dossier_ids=(dossier_id,), routed_scopes=((scope, (dossier_id,)),)),
    )
    result = ValidatedMappingResult(
        scope_id=scope.scope_id,
        block_decisions=(BlockMaterialDecision(
            scope_id=scope.scope_id, block_id="block/climate", disposition="supported", material_ids=(material_id,), reason="资料直接支持。",
        ),),
    )
    connection = _Connection([{
        "id": run_id, "account_id": account_id, "report_id": report_id, "workspace_id": workspace_id,
        "snapshot_id": snapshot.snapshot_id, "scope_id": scope.scope_id, "attempt": 1,
        "snapshot_payload": snapshot.model_dump(mode="json"),
    }])
    await pipeline_dal.finish_mapping_run(
        _Pool(connection), run_id=run_id, lease_token=lease_token, result=result, receipt={"observationRunId": "trace"},
    )
    sql = "\n".join(statement for statement, _ in connection.statements)
    assert "insert into block_material_decisions" in sql
    assert "material_mapping_facts" not in sql
    assert connection.executemany_calls[0][0].find("block_material_decision_materials") >= 0


def _failed_file_result(*, run_id, attempt, context, failure_code="UnexpectedModelBehavior"):
    now = datetime.now(timezone.utc)
    return FileAgentRunResult(
        status="failed", dossier=None, checkpoint=None,
        receipt=FileAgentRunReceipt(
            run_id=run_id, attempt=attempt, status="failed",
            source_revision=context.source_revision, started_at=now, finished_at=now,
            tool_receipts=(),
            trace_events=(FileAgentTraceEvent(sequence=1, occurred_at=now, event_type="run_failed", detail_code=failure_code),),
            failure_code=failure_code,
        ),
    )


def _running_file_row(*, run_id, context, attempt, max_attempts=3):
    return {
        "id": run_id, "account_id": uuid4(), "report_id": context.product_task.report_id,
        "workspace_id": uuid4(), "binding_id": uuid4(), "source_id": context.source_revision.source_id,
        "attempt": attempt, "max_attempts": max_attempts, "input_payload": context.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_finish_file_agent_run_requeues_retryable_failure_within_attempt_budget() -> None:
    run_id, lease_token, report_id = uuid4(), uuid4(), uuid4()
    context = _file_context(report_id)
    connection = _Connection([_running_file_row(run_id=run_id, context=context, attempt=1)])
    await pipeline_dal.finish_file_agent_run(
        _Pool(connection), run_id=run_id, lease_token=lease_token,
        result=_failed_file_result(run_id=run_id, attempt=1, context=context),
        retryable_failure=True,
    )
    update_sql = connection.statements[-1][0]
    assert "status = 'queued'" in update_sql
    assert "finished_at = null" in update_sql
    assert "coalesce($4, checkpoint)" in update_sql
    assert "insert into file_dossiers" not in "\n".join(sql for sql, _ in connection.statements)


@pytest.mark.asyncio
async def test_finish_file_agent_run_lands_terminal_failed_when_attempts_exhausted() -> None:
    run_id, lease_token, report_id = uuid4(), uuid4(), uuid4()
    context = _file_context(report_id)
    connection = _Connection([_running_file_row(run_id=run_id, context=context, attempt=3)])
    await pipeline_dal.finish_file_agent_run(
        _Pool(connection), run_id=run_id, lease_token=lease_token,
        result=_failed_file_result(run_id=run_id, attempt=3, context=context),
        retryable_failure=True,
    )
    update_sql = connection.statements[-1][0]
    assert "status = 'failed'" in update_sql
    assert "finished_at = now()" in update_sql


@pytest.mark.asyncio
async def test_finish_file_agent_run_keeps_terminal_failed_for_non_retryable_failure() -> None:
    run_id, lease_token, report_id = uuid4(), uuid4(), uuid4()
    context = _file_context(report_id)
    connection = _Connection([_running_file_row(run_id=run_id, context=context, attempt=1)])
    await pipeline_dal.finish_file_agent_run(
        _Pool(connection), run_id=run_id, lease_token=lease_token,
        result=_failed_file_result(run_id=run_id, attempt=1, context=context, failure_code="AccountEntitlementError"),
        retryable_failure=False,
    )
    update_sql = connection.statements[-1][0]
    assert "status = 'failed'" in update_sql
    assert "finished_at = now()" in update_sql


@pytest.mark.asyncio
async def test_finish_file_agent_run_rejects_retryable_flag_on_non_failed_result() -> None:
    run_id, report_id = uuid4(), uuid4()
    context = _file_context(report_id)
    checkpoint = FileAgentRunCheckpoint(
        run_id=run_id, source_revision=context.source_revision, product_task=context.product_task,
        completed_requests=(), tool_receipts=(), next_tool_sequence=1,
    )
    now = datetime.now(timezone.utc)
    suspended = FileAgentRunResult(
        status="suspended", dossier=None, checkpoint=checkpoint,
        receipt=FileAgentRunReceipt(
            run_id=run_id, attempt=1, status="suspended",
            source_revision=context.source_revision, started_at=now, finished_at=now,
            tool_receipts=(),
            trace_events=(FileAgentTraceEvent(sequence=1, occurred_at=now, event_type="run_suspended", detail_code="waiting_external"),),
        ),
    )
    with pytest.raises(ValueError, match="retryable_failure"):
        await pipeline_dal.finish_file_agent_run(
            _Pool(_Connection([])), run_id=run_id, lease_token=uuid4(),
            result=suspended, retryable_failure=True,
        )


@pytest.mark.asyncio
async def test_fail_mapping_run_requeues_retryable_failure_by_attempt_budget() -> None:
    connection = _Connection([])
    await pipeline_dal.fail_mapping_run(
        _Pool(connection), run_id=uuid4(), lease_token=uuid4(),
        failure_code="UnexpectedModelBehavior", receipt={"failureType": "UnexpectedModelBehavior"},
        retryable_failure=True,
    )
    sql, args = connection.statements[-1]
    assert "case when $5::boolean and attempt < max_attempts" in sql
    assert "then 'queued' else 'failed'" in sql
    assert args[-1] is True


@pytest.mark.asyncio
async def test_fail_mapping_run_rejects_retryable_needs_attention() -> None:
    with pytest.raises(ValueError, match="needs_attention"):
        await pipeline_dal.fail_mapping_run(
            _Pool(_Connection([])), run_id=uuid4(), lease_token=uuid4(),
            failure_code="MappingProposalError", receipt={},
            needs_attention=True, retryable_failure=True,
        )
