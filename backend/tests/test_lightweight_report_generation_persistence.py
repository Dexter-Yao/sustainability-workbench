# ABOUTME: 轻量版报告级生成的幂等、就绪门槛、原子提交与交付物查询测试。
# ABOUTME: 使用 fake asyncpg 固定事务与 SQL 合同，不以 mock 替代领域结果校验。
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.persistence import lightweight_report_generations as generation_dal
from knowledge_package_fixtures import SSE_PACKAGE


NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


class _Transaction:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.transaction_enters += 1

    async def __aexit__(self, *_args: object) -> None:
        self.connection.transaction_exits += 1


class _Connection:
    def __init__(
        self,
        *,
        fetchrows: list[dict[str, object] | None] | None = None,
        fetchvals: list[object] | None = None,
        execute_results: list[str] | None = None,
    ) -> None:
        self.fetchrows = list(fetchrows or ())
        self.fetchvals = list(fetchvals or ())
        self.execute_results = list(execute_results or ())
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_enters = 0
        self.transaction_exits = 0

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def fetchrow(self, sql: str, *args: object):
        self.statements.append((sql, args))
        if not self.fetchrows:
            raise AssertionError(f"没有为 fetchrow 准备返回值：{sql}")
        return self.fetchrows.pop(0)

    async def fetchval(self, sql: str, *args: object):
        self.statements.append((sql, args))
        if not self.fetchvals:
            raise AssertionError(f"没有为 fetchval 准备返回值：{sql}")
        return self.fetchvals.pop(0)

    async def execute(self, sql: str, *args: object) -> str:
        self.statements.append((sql, args))
        if self.execute_results:
            return self.execute_results.pop(0)
        return "INSERT 0 1" if "insert into" in sql.lower() else "UPDATE 1"

    async def fetch(self, sql: str, *args: object):
        self.statements.append((sql, args))
        return []


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def fetchrow(self, sql: str, *args: object):
        return await self.connection.fetchrow(sql, *args)


def _run_row(
    *,
    run_id: UUID,
    account_id: UUID,
    report_id: UUID,
    snapshot_id: UUID,
    idempotency_key: UUID,
    input_fingerprint: str = "a" * 64,
    model_id: str = "luna",
    expected_block_ids: tuple[str, ...] = ("block/a", "block/b"),
    status: str = "queued",
) -> dict[str, object]:
    return {
        "id": run_id,
        "account_id": account_id,
        "report_id": report_id,
        "material_set_snapshot_id": snapshot_id,
        "base_report_state_seq": 1,
        "input_fingerprint": input_fingerprint,
        "idempotency_key": idempotency_key,
        "model_id": model_id,
        "status": status,
        "attempt": 0,
        "max_attempts": 2,
        "lease_token": None,
        "expected_block_ids": list(expected_block_ids),
        "block_results": [],
        "result_report_state_seq": None,
        "result_revision_id": None,
        "failure_code": None,
        "started_at": None,
    }


def _lease(
    *,
    run_id: UUID | None = None,
    account_id: UUID | None = None,
    report_id: UUID | None = None,
    snapshot_id: UUID | None = None,
) -> generation_dal.ReportGenerationLease:
    return generation_dal.ReportGenerationLease(
        run_id=run_id or uuid4(),
        lease_token=uuid4(),
        account_id=account_id or uuid4(),
        report_id=report_id or uuid4(),
        material_set_snapshot_id=snapshot_id or uuid4(),
        base_report_state_seq=1,
        input_fingerprint="a" * 64,
        model_id="luna",
        expected_block_ids=("block/a", "block/b"),
        attempt=1,
    )


def _successful_results() -> tuple[dict, ...]:
    return (
        {
            "blockId": "block/a",
            "kind": "paragraph",
            "status": "ready",
        },
        {
            "blockId": "block/b",
            "kind": "table",
            "status": "omitted",
            "reason": "当前报告期无适用数据行。",
        },
    )


def _artifacts() -> tuple[generation_dal.ReportArtifactWrite, ...]:
    return (
        generation_dal.ReportArtifactWrite(
            artifact_id=uuid4(),
            kind="word",
            filename="报告.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content_fingerprint="b" * 64,
            storage_ref="local/run/report.docx",
        ),
        generation_dal.ReportArtifactWrite(
            artifact_id=uuid4(),
            kind="review",
            filename="客户审阅包.html",
            media_type="text/html",
            content_fingerprint="c" * 64,
            storage_ref="local/run/review.html",
        ),
        generation_dal.ReportArtifactWrite(
            artifact_id=uuid4(),
            kind="internal_audit",
            filename="内部审计包.json",
            media_type="application/json",
            content_fingerprint="d" * 64,
            storage_ref="local/run/internal-audit.json",
        ),
    )


@pytest.mark.asyncio
async def test_enqueue_replays_only_the_same_complete_input() -> None:
    account_id = uuid4()
    report_id = uuid4()
    snapshot_id = uuid4()
    run_id = uuid4()
    idempotency_key = uuid4()
    known = _run_row(
        run_id=run_id,
        account_id=account_id,
        report_id=report_id,
        snapshot_id=snapshot_id,
        idempotency_key=idempotency_key,
    )
    connection = _Connection(fetchrows=[known])

    replayed = await generation_dal.enqueue_generation(
        _Pool(connection),  # type: ignore[arg-type]
        run_id=uuid4(),
        account_id=account_id,
        report_id=report_id,
        material_set_snapshot_id=snapshot_id,
        base_report_state_seq=1,
        input_fingerprint="a" * 64,
        idempotency_key=idempotency_key,
        model_id="luna",
        expected_block_ids=("block/a", "block/b"),
    )

    assert replayed.run_id == run_id
    assert len(connection.statements) == 1

    connection = _Connection(fetchrows=[known])
    with pytest.raises(
        generation_dal.ReportGenerationConflictError,
        match="幂等键",
    ):
        await generation_dal.enqueue_generation(
            _Pool(connection),  # type: ignore[arg-type]
            run_id=uuid4(),
            account_id=account_id,
            report_id=report_id,
            material_set_snapshot_id=uuid4(),
            base_report_state_seq=1,
            input_fingerprint="a" * 64,
            idempotency_key=idempotency_key,
            model_id="luna",
            expected_block_ids=("block/a", "block/b"),
        )


@pytest.mark.asyncio
async def test_enqueue_requires_snapshot_owned_by_the_same_report() -> None:
    account_id = uuid4()
    report_id = uuid4()
    connection = _Connection(
        fetchrows=[None, None],
        fetchvals=[1],
    )

    with pytest.raises(
        generation_dal.ReportGenerationConflictError,
        match="资料集合",
    ):
        await generation_dal.enqueue_generation(
            _Pool(connection),  # type: ignore[arg-type]
            run_id=uuid4(),
            account_id=account_id,
            report_id=report_id,
            material_set_snapshot_id=uuid4(),
            base_report_state_seq=1,
            input_fingerprint="a" * 64,
            idempotency_key=uuid4(),
            model_id="luna",
            expected_block_ids=("block/a",),
        )

    assert any(
        "from material_set_snapshots" in sql
        and "report_id = $2" in sql
        and "account_id = $3" in sql
        for sql, _args in connection.statements
    )


@pytest.mark.asyncio
async def test_claim_requires_current_snapshot_and_every_planned_mapping_scope() -> None:
    connection = _Connection(fetchrows=[None])

    claimed = await generation_dal.claim_generation(
        _Pool(connection),  # type: ignore[arg-type]
        worker_id="worker-1",
    )

    assert claimed is None
    sql = connection.statements[0][0]
    assert "material_set_snapshots" in sql
    assert "jsonb_array_elements" in sql
    assert "file_dossiers" in sql
    assert "file_run.status = 'succeeded'" in sql
    assert "snapshot_payload -> 'mapping_plan' -> 'scopes'" in sql
    assert "plan_scope ->> 'scope_id'" in sql
    assert "mapping_run.status = 'succeeded'" in sql
    assert "file_run.status in ('queued', 'running')" in sql
    assert "mapping_run.status in ('queued', 'running')" in sql


@pytest.mark.asyncio
async def test_complete_generation_is_one_transaction_and_requires_full_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _lease()
    planned = generation_dal.PlannedReportRevision(
        revision_id=uuid4(),
        revision=1,
    )
    run_row = _run_row(
        run_id=lease.run_id,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=lease.material_set_snapshot_id,
        idempotency_key=uuid4(),
        status="running",
    )
    run_row.update(
        {
            "lease_token": lease.lease_token,
            "attempt": 1,
        }
    )
    connection = _Connection(
        fetchrows=[run_row, {"state_seq": 1}],
        fetchvals=[1, 2],
    )

    new_seq = await generation_dal.complete_generation(
        _Pool(connection),  # type: ignore[arg-type]
        lease=lease,
        planned_revision=planned,
        state=StoredReportStateV4(version=4),
        content_fingerprint="e" * 64,
        block_results=_successful_results(),
        artifacts=_artifacts(), package=SSE_PACKAGE,
    )

    assert new_seq == 2
    assert connection.transaction_enters == 1
    assert connection.transaction_exits == 1
    sql = "\n".join(item[0] for item in connection.statements)
    assert "update report_states" in sql
    assert "insert into lightweight_report_revisions" in sql
    assert sql.count("insert into lightweight_report_artifacts") == 3
    assert "set status = 'succeeded'" in sql

    with pytest.raises(ValueError, match="全部适用 Block"):
        await generation_dal.complete_generation(
            _Pool(_Connection()),  # type: ignore[arg-type]
            lease=lease,
            planned_revision=planned,
            state=StoredReportStateV4(version=4),
            content_fingerprint="e" * 64,
            block_results=(_successful_results()[0],),
            artifacts=_artifacts(), package=SSE_PACKAGE,
        )
    with pytest.raises(ValueError, match="三类交付物"):
        await generation_dal.complete_generation(
            _Pool(_Connection()),  # type: ignore[arg-type]
            lease=lease,
            planned_revision=planned,
            state=StoredReportStateV4(version=4),
            content_fingerprint="e" * 64,
            block_results=_successful_results(),
            artifacts=_artifacts()[:1], package=SSE_PACKAGE,
        )


@pytest.mark.asyncio
async def test_export_blocked_completion_saves_report_without_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """导出闸阻断：正文照常保存、零交付物、以 action_required 事件引导工作台补齐。"""
    lease = _lease()
    planned = generation_dal.PlannedReportRevision(revision_id=uuid4(), revision=1)
    run_row = _run_row(
        run_id=lease.run_id,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=lease.material_set_snapshot_id,
        idempotency_key=uuid4(),
        status="running",
    )
    run_row.update({"lease_token": lease.lease_token, "attempt": 1})
    connection = _Connection(
        fetchrows=[run_row, {"state_seq": 1}],
        fetchvals=[1, 2],
    )

    new_seq = await generation_dal.complete_generation(
        _Pool(connection),  # type: ignore[arg-type]
        lease=lease,
        planned_revision=planned,
        state=StoredReportStateV4(version=4),
        content_fingerprint="e" * 64,
        block_results=_successful_results(),
        artifacts=(),
        export_blocking_issues=("读者反馈邮箱未填写",), package=SSE_PACKAGE,
    )

    assert new_seq == 2
    sql = "\n".join(item[0] for item in connection.statements)
    assert "update report_states" in sql
    assert "insert into lightweight_report_artifacts" not in sql
    assert "set status = 'succeeded'" in sql
    event_args = [
        args
        for statement, args in connection.statements
        if "lightweight_report_generation_events" in statement
    ]
    export_blocked_events = [
        args for args in event_args if "export_blocked" in args
    ]
    assert len(export_blocked_events) == 1
    # action_required=True，且 payload 携带阻断明细供审计。
    assert True in export_blocked_events[0]
    assert any("artifacts_ready" not in args for args in event_args)
    assert not any("artifacts_ready" in args for args in event_args)

    # 阻断与交付物互斥：闸没放行时携带交付物是程序错误。
    with pytest.raises(ValueError, match="不得携带交付物"):
        await generation_dal.complete_generation(
            _Pool(_Connection()),  # type: ignore[arg-type]
            lease=lease,
            planned_revision=planned,
            state=StoredReportStateV4(version=4),
            content_fingerprint="e" * 64,
            block_results=_successful_results(),
            artifacts=_artifacts(),
            export_blocking_issues=("读者反馈邮箱未填写",), package=SSE_PACKAGE,
        )


@pytest.mark.asyncio
async def test_failed_completion_update_rolls_back_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _lease()
    run_row = _run_row(
        run_id=lease.run_id,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=lease.material_set_snapshot_id,
        idempotency_key=uuid4(),
        status="running",
    )
    run_row["lease_token"] = lease.lease_token
    run_row["attempt"] = 1
    # revision + 3 artifacts 成功，最终 run CAS 返回 UPDATE 0。
    connection = _Connection(
        fetchrows=[run_row, {"state_seq": 1}],
        fetchvals=[1, 2],
        execute_results=[
            "INSERT 0 1",
            "INSERT 0 1",
            "INSERT 0 1",
            "INSERT 0 1",
            "UPDATE 0",
        ],
    )

    with pytest.raises(generation_dal.ReportGenerationLeaseError):
        await generation_dal.complete_generation(
            _Pool(connection),  # type: ignore[arg-type]
            lease=lease,
            planned_revision=generation_dal.PlannedReportRevision(
                revision_id=uuid4(),
                revision=1,
            ),
            state=StoredReportStateV4(version=4),
            content_fingerprint="e" * 64,
            block_results=_successful_results(),
            artifacts=_artifacts(), package=SSE_PACKAGE,
        )

    assert connection.transaction_enters == connection.transaction_exits == 1


@pytest.mark.asyncio
async def test_fail_generation_never_writes_report_revision_or_artifact() -> None:
    lease = _lease()
    connection = _Connection()

    await generation_dal.fail_generation(
        _Pool(connection),  # type: ignore[arg-type]
        lease=lease,
        failure_code="generation_failed",
        user_message="生成失败，请稍后重试。",
    )

    sql = "\n".join(item[0] for item in connection.statements).lower()
    assert "update lightweight_report_generation_runs" in sql
    assert "insert into lightweight_report_generation_events" in sql
    assert "lease_expires_at > now()" in sql
    assert "report_states" not in sql
    assert "lightweight_report_revisions" not in sql
    assert "lightweight_report_artifacts" not in sql


@pytest.mark.asyncio
async def test_artifact_query_only_returns_successful_customer_visible_artifact() -> None:
    account_id = uuid4()
    report_id = uuid4()
    artifact_id = uuid4()
    row = {
        "id": artifact_id,
        "kind": "word",
        "filename": "报告.docx",
        "media_type": "application/octet-stream",
        "content_fingerprint": "a" * 64,
        "storage_ref": "local/report.docx",
        "report_revision_id": uuid4(),
        "generation_run_id": uuid4(),
    }
    connection = _Connection(fetchrows=[row])

    artifact = await generation_dal.artifact_download_target(
        _Pool(connection),  # type: ignore[arg-type]
        account_id=account_id,
        report_id=report_id,
        artifact_id=artifact_id,
    )

    assert artifact.artifact_id == artifact_id
    sql = connection.statements[0][0]
    assert "join lightweight_report_generation_runs" in sql
    assert "run.status = 'succeeded'" in sql
    assert "artifact.kind <> 'internal_audit'" in sql


def test_generation_baseline_enforces_cross_table_report_lineage() -> None:
    sql = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20260904000000_local_single_user_baseline.sql"
    ).read_text("utf-8").lower()

    assert "material_set_snapshots_id_report_account_key" in sql
    assert "lightweight_report_generation_runs_id_report_account_key" in sql
    assert "lightweight_report_revisions_lineage_key" in sql
    assert (
        'foreign key ("material_set_snapshot_id", "report_id", "account_id")'
        in sql
    )
    assert (
        'foreign key ("result_revision_id", "report_id", "account_id", "id")'
        in sql
    )
    assert (
        'foreign key ("report_revision_id", "report_id", "account_id", '
        '"generation_run_id")'
        in sql
    )
    assert '"jsonb_array_length"("block_results")' in sql
    for table in (
        "lightweight_report_generation_runs",
        "lightweight_report_revisions",
        "lightweight_report_generation_events",
        "lightweight_report_artifacts",
    ):
        assert (
            f'grant select, insert, update, delete on table "public"."{table}"'
            not in sql
        )
