# ABOUTME: 产品生成任务投影集成测试——running 写入、逐调用用量聚合和最终状态更新。
# ABOUTME: 直连本地 Supabase Postgres；栈未启动时跳过，账号归属通过 reports.account_id。
from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.llm.ai_observability import (
    ModelTraceRequest,
    ModelTraceResult,
    create_observation_run,
    observe_generation,
    record_model_invocation,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.generation_runs import (
    finish_generation_run,
    finish_generation_run_safely,
    start_generation_run,
    start_generation_run_safely,
)
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
STATE_V4 = {"version": 4, "fields": {}, "intakeItems": {}, "generatedBlocks": {}, "tableBlocks": {}}


@pytest.fixture
async def pool():
    try:
        value = await asyncpg.create_pool(
            LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3
        )
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield value
    await value.close()


@pytest.fixture
async def report(pool):
    owner = uuid4()
    await pool.execute("insert into auth.users (id) values ($1)", owner)
    account_id = await pool.fetchval(
        "insert into accounts (email) values ($1) returning id", f"runs-{owner}@example.edu.cn"
    )
    summary = await reports_dal.create_report(
        pool, account_id, "观测测试", "lightweight", "sse_zh_hans@1", "customer",
        contract_version(SSE_PACKAGE), STATE_V4, 1, "local_single_user@1"
    )
    yield summary
    await pool.execute("delete from public.accounts where id = $1", account_id)
    await pool.execute("delete from auth.users where id = $1", owner)


def _run(report_id, tmp_path):
    return create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="product_generation",
        report_id=str(report_id),
        block_id="climate.gov_structure",
        root=tmp_path,
    )


async def test_generation_run_aggregates_model_invocations(pool, report, tmp_path):
    run = _run(report.id, tmp_path)
    await start_generation_run(pool, run)
    with unit_span(run), observe_generation(run):
        record_model_invocation(
            run.invocation(),
            request=ModelTraceRequest(systemPrompt="system", userPrompt="first"),
            result=ModelTraceResult(structuredOutput="first"),
            usage={"requests": 1, "input_tokens": 100, "output_tokens": 20},
            duration_ms=50,
            transport_attempts=1,
            prompt_hash="sha256:first",
        )
        record_model_invocation(
            run.invocation(),
            request=ModelTraceRequest(systemPrompt="system", userPrompt="second"),
            result=ModelTraceResult(structuredOutput="second"),
            usage={"requests": 2, "tool_calls": 1, "input_tokens": 80, "output_tokens": 30},
            duration_ms=75,
            transport_attempts=2,
            prompt_hash="sha256:second",
        )
    await finish_generation_run(pool, run)

    row = await pool.fetchrow("select * from generation_runs where id = $1", run.runId)
    assert row["status"] == "succeeded"
    assert row["model_invocations"] == 2
    assert row["provider_requests"] == 3
    assert row["tool_calls"] == 1
    assert row["input_tokens"] == 180
    assert row["output_tokens"] == 50
    assert row["transport_attempts"] == 3
    assert row["finished_at"] is not None

    audit = await pool.fetchrow(
        "select actor, payload from report_events where report_id = $1 and event_type = 'generation_finished'",
        report.id,
    )
    assert audit["actor"] == "llm"
    assert audit["payload"]["runId"] == run.runId


async def test_failed_generation_run_is_persisted(pool, report, tmp_path):
    run = _run(report.id, tmp_path)
    await start_generation_run(pool, run)
    with pytest.raises(RuntimeError):
        with unit_span(run), observe_generation(run):
            record_model_invocation(
                run.invocation(),
                request=ModelTraceRequest(systemPrompt="system", userPrompt="failed"),
                result=ModelTraceResult(
                    error={"type": "ModelHTTPError", "message": "HTTP 503", "statusCode": 503}
                ),
                usage=None,
                duration_ms=10,
                transport_attempts=3,
                error_code="http_503",
                prompt_hash="sha256:failed",
            )
            raise RuntimeError("model failed")
    await finish_generation_run(pool, run)

    row = await pool.fetchrow("select status, error_code, transport_attempts from generation_runs where id = $1", run.runId)
    assert tuple(row) == ("failed", "RuntimeError", 3)


async def test_safe_wrappers_skip_missing_pool(report, tmp_path):
    run = _run(report.id, tmp_path)
    await start_generation_run_safely(None, run)
    with unit_span(run), observe_generation(run):
        pass
    await finish_generation_run_safely(None, run)
