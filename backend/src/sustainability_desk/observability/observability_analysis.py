# ABOUTME: AI 观测 JSONL 的只读分析——从完整 v3 轨迹统计任务状态、模型调用、token、耗时和传输重试。
# ABOUTME: 内容字段留给失败归因；用量汇总只消费 model_invocation，避免重复计数。
# ABOUTME(en): Read-only analysis of AI observability JSONL: task status, model calls, tokens, latency, retries.
# ABOUTME(en): Content fields are left for failure attribution; usage sums consume model_invocation only, never twice.
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sustainability_desk.llm.ai_observability import (
    GenerationFinishedEvent,
    GuardrailEvaluationEvent,
    ModelInvocationEvent,
    ObservabilityEvent,
    parse_observability_event,
)


class ObservabilitySummary(BaseModel):
    """一次或多次观测任务的用量摘要。"""

    model_config = ConfigDict(extra="forbid")

    generationRuns: int = 0
    succeededRuns: int = 0
    failedRuns: int = 0
    modelInvocations: int = 0
    failedInvocations: int = 0
    guardrailEvaluations: int = 0
    rejectedOutputs: int = 0
    providerRequests: int = 0
    httpSendAttempts: int = 0
    toolCalls: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    cacheWriteTokens: int = 0
    cacheReadTokens: int = 0
    durationMs: int = 0
    transportAttempts: int = 0


def load_observability_events(path: Path) -> list[ObservabilityEvent]:
    """严格加载新合同 JSONL；空行忽略，旧事件直接校验失败。"""
    events: list[ObservabilityEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(parse_observability_event(line))
    return events


def summarize_observability_events(events: list[ObservabilityEvent]) -> ObservabilitySummary:
    """按 model_invocation 单一口径汇总，generation_finished 只计算任务状态。"""
    invocations = [event for event in events if isinstance(event, ModelInvocationEvent)]
    guardrails = [event for event in events if isinstance(event, GuardrailEvaluationEvent)]
    finished = [event for event in events if isinstance(event, GenerationFinishedEvent)]
    return ObservabilitySummary(
        generationRuns=len(finished),
        succeededRuns=sum(event.status == "succeeded" for event in finished),
        failedRuns=sum(event.status == "failed" for event in finished),
        modelInvocations=len(invocations),
        failedInvocations=sum(event.status == "failed" for event in invocations),
        guardrailEvaluations=len(guardrails),
        rejectedOutputs=sum(event.status == "rejected" for event in guardrails),
        providerRequests=sum(event.providerRequests for event in invocations),
        httpSendAttempts=sum(event.httpSendAttempts for event in invocations),
        toolCalls=sum(event.toolCalls for event in invocations),
        inputTokens=sum(event.inputTokens for event in invocations),
        outputTokens=sum(event.outputTokens for event in invocations),
        cacheWriteTokens=sum(event.cacheWriteTokens for event in invocations),
        cacheReadTokens=sum(event.cacheReadTokens for event in invocations),
        durationMs=sum(event.durationMs for event in invocations),
        transportAttempts=sum(event.transportAttempts for event in invocations),
    )


def summarize_observability_file(path: Path) -> ObservabilitySummary:
    """汇总一个 AI 观测文件。"""
    return summarize_observability_events(load_observability_events(path))
