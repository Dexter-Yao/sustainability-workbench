# ABOUTME: 产品生成任务数据库投影——任务开始写 running，结束按 model_invocation 聚合真实用量并更新最终状态。
# ABOUTME: 数据库异常只记录日志，不覆盖模型或业务异常；账号归属通过 reports.account_id 保持单一真相源。
# ABOUTME(en): Database projection of product generation runs — writes running at start, aggregates real usage
# ABOUTME(en): from model_invocation at the end. DB errors only log, never mask model or business errors.
from __future__ import annotations

import logging
from datetime import datetime

import asyncpg

from sustainability_desk.llm.ai_observability import ModelInvocationEvent, ObservationRun

logger = logging.getLogger(__name__)


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def start_generation_run(pool: asyncpg.Pool, run: ObservationRun) -> None:
    """在模型调用前写入权威 running 行。"""
    await pool.execute(
        """
        insert into generation_runs
          (id, trace_id, request_id, report_id, block_id, operation, model_id,
           status, started_at, created_at, updated_at)
        values ($1, $2, $3, $4::uuid, $5, $6, $7, 'running', $8, now(), now())
        """,
        run.runId,
        run.traceId,
        run.requestId,
        run.reportId,
        run.blockId,
        run.operation,
        run.modelId,
        _time(run.startedAt),
    )


async def finish_generation_run(pool: asyncpg.Pool, run: ObservationRun) -> None:
    """按逐调用事件聚合一次产品任务，并记一条任务完成审计事件。"""
    invocations = [
        event for event in run.collectedEvents if isinstance(event, ModelInvocationEvent)
    ]
    result = await pool.execute(
        """
        update generation_runs
        set model_invocations = $2,
            provider_requests = $3,
            tool_calls = $4,
            input_tokens = $5,
            output_tokens = $6,
            cache_write_tokens = $7,
            cache_read_tokens = $8,
            duration_ms = $9,
            transport_attempts = $10,
            status = $11,
            error_code = $12,
            finished_at = $13,
            updated_at = now()
        where id = $1
        """,
        run.runId,
        len(invocations),
        sum(event.providerRequests for event in invocations),
        sum(event.toolCalls for event in invocations),
        sum(event.inputTokens for event in invocations),
        sum(event.outputTokens for event in invocations),
        sum(event.cacheWriteTokens for event in invocations),
        sum(event.cacheReadTokens for event in invocations),
        run.durationMs,
        sum(event.transportAttempts for event in invocations),
        run.status,
        run.errorCode,
        _time(run.finishedAt),
    )
    if result != "UPDATE 1":
        raise RuntimeError(f"生成任务开始记录不存在: {run.runId}")
    await pool.execute(
        """
        insert into report_events (report_id, actor, event_type, payload)
        values ($1::uuid, 'llm', 'generation_finished', $2)
        """,
        run.reportId,
        {
            "runId": run.runId,
            "blockId": run.blockId,
            "status": run.status,
            "modelId": run.modelId,
            "operation": run.operation,
        },
    )


async def start_generation_run_safely(
    pool: asyncpg.Pool | None, run: ObservationRun
) -> None:
    """写开始记录；失败只记日志，生成链继续。"""
    if pool is None:
        return
    try:
        await start_generation_run(pool, run)
    except Exception:
        logger.exception("生成任务开始记录失败 runId=%s reportId=%s", run.runId, run.reportId)


async def finish_generation_run_safely(
    pool: asyncpg.Pool | None, run: ObservationRun
) -> None:
    """写最终聚合；失败只记日志，不覆盖模型或业务异常。"""
    if pool is None:
        return
    try:
        await finish_generation_run(pool, run)
    except Exception:
        logger.exception("生成任务完成记录失败 runId=%s reportId=%s", run.runId, run.reportId)
