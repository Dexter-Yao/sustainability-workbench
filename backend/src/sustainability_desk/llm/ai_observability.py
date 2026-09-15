# ABOUTME: AI 运行观测合同——逐次保存完整模型交换、计量信息与生成守卫判定。
# ABOUTME: 每次调用显式携带 InvocationContext；JSONL 是受限权限的诊断证据，不承担报告状态持久化。
# ABOUTME(en): AI run observability: persists the full model exchange, usage metering and guardrail verdicts per call.
# ABOUTME(en): Every call carries an explicit InvocationContext; the JSONL is diagnostic evidence, not report state.
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from sustainability_desk.observability.registry import Stage

BACKEND = Path(__file__).resolve().parents[3]
DEFAULT_OBSERVABILITY_ROOT = BACKEND / "out" / "observability"
# v3：operation 由工作单元根阶段（typed Stage）派生；每条模型调用携带 spanId/stageId，
# 结构性归属于一个阶段 span（spec 决策点 C）。历史 v2 文件不可变、按原 TTL 过期。
SCHEMA_VERSION = "sustainability_desk.ai_observability.v3"

WorkloadKind = Literal["product_generation", "evaluation"]
GenerationStatus = Literal["running", "succeeded", "failed"]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:10]}"


def _observation_path(root: Path, run_id: str) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return root / day / f"{run_id}.jsonl"


class InvocationUsage(BaseModel):
    """一次 provider 调用的可计量用量。"""

    model_config = ConfigDict(extra="forbid")

    providerRequests: int = Field(default=0, ge=0)
    toolCalls: int = Field(default=0, ge=0)
    inputTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    cacheWriteTokens: int = Field(default=0, ge=0)
    cacheReadTokens: int = Field(default=0, ge=0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "InvocationUsage":
        raw = dict(value or {})
        return cls(
            providerRequests=int(raw.get("requests", raw.get("providerRequests", 0)) or 0),
            toolCalls=int(raw.get("toolCalls", raw.get("tool_calls", 0)) or 0),
            inputTokens=int(raw.get("inputTokens", raw.get("input_tokens", 0)) or 0),
            outputTokens=int(raw.get("outputTokens", raw.get("output_tokens", 0)) or 0),
            cacheWriteTokens=int(
                raw.get("cacheWriteTokens", raw.get("cache_write_tokens", 0)) or 0
            ),
            cacheReadTokens=int(
                raw.get("cacheReadTokens", raw.get("cache_read_tokens", 0)) or 0
            ),
        )


class ModelTraceRequest(BaseModel):
    """一次逻辑模型调用的完整输入；不对用户资料做删减或脱敏。"""

    model_config = ConfigDict(extra="forbid")

    taskContext: JsonValue | None = None
    systemPrompt: str
    userPrompt: str
    modelSettings: dict[str, JsonValue] = Field(default_factory=dict)
    outputSchema: dict[str, JsonValue] = Field(default_factory=dict)


class ModelTraceError(BaseModel):
    """模型调用失败详情；保留 provider 可用的状态与响应体。"""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    statusCode: int | None = None
    body: JsonValue | None = None
    causes: list["ModelTraceCause"] = Field(default_factory=list)


class ModelTraceCause(BaseModel):
    """Provider/SDK 包装错误以下的脱敏异常链节点。"""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str


class ModelTraceResult(BaseModel):
    """一次逻辑模型调用的完整可观测结果。"""

    model_config = ConfigDict(extra="forbid")

    messageHistory: list[JsonValue] = Field(default_factory=list)
    structuredOutput: JsonValue | None = None
    transportErrors: list[ModelTraceError] = Field(default_factory=list)
    error: ModelTraceError | None = None


class GuardrailIssueTrace(BaseModel):
    """守卫问题的可持久化投影。"""

    model_config = ConfigDict(extra="forbid")

    key: str
    message: str
    evidence: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class InvocationContext:
    """传给唯一模型出口的显式归属信息；run_agent 不从环境推断调用归属。"""

    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    modelId: str
    invocationOrdinal: int
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    # v3：本次调用发生时所在的阶段 span。由 invocation() 从当前任务上下文捕获，
    # 模型调用因此结构性归属于一个 span——无 span 的调用在运行期不可表达。
    spanId: str
    stageId: str
    evidenceSelectorKind: str
    intakeFactCount: int
    metricEvidenceCount: int
    evidenceLevel: str
    contextFingerprint: str
    taskContext: JsonValue | None
    run: "ObservationRun"
    # 本块生成时可参照的在先支柱正文条数；排查跨块复述时可直接过滤。
    priorDisclosureCount: int = 0
    # 归属客户账号（gen_ai.user.id 镜像用）。只进镜像属性不进 JSONL 事件——
    # 本地事实经 reportId 即可 join 到账号，不复制一份会漂移的归属。
    userId: str = ""

    def __post_init__(self) -> None:
        if self.invocationOrdinal < 1:
            raise ValueError("invocationOrdinal 必须大于等于 1")
        if not self.spanId or not self.stageId:
            raise ValueError("模型调用必须归属于一个阶段 span（spanId/stageId 不得为空）")


class GenerationStartedEvent(BaseModel):
    """一次生成任务开始。"""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal["sustainability_desk.ai_observability.v3"] = SCHEMA_VERSION
    eventType: Literal["generation_started"] = "generation_started"
    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    timestamp: str
    status: Literal["running"] = "running"


class ModelInvocationEvent(BaseModel):
    """一次真实模型调用；同时拥有完整交换内容与计量事实。"""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal["sustainability_desk.ai_observability.v3"] = SCHEMA_VERSION
    eventType: Literal["model_invocation"] = "model_invocation"
    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    timestamp: str
    status: Literal["succeeded", "failed"]
    modelId: str
    invocationOrdinal: int = Field(ge=1)
    providerRequests: int = Field(default=0, ge=0)
    toolCalls: int = Field(default=0, ge=0)
    inputTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    cacheWriteTokens: int = Field(default=0, ge=0)
    cacheReadTokens: int = Field(default=0, ge=0)
    durationMs: int = Field(default=0, ge=0)
    transportAttempts: int = Field(default=1, ge=1)
    httpSendAttempts: int = Field(default=0, ge=0)
    errorCode: str = ""
    promptFingerprint: str
    spanId: str
    stageId: str
    evidenceSelectorKind: str = ""
    intakeFactCount: int = Field(default=0, ge=0)
    priorDisclosureCount: int = Field(default=0, ge=0)
    metricEvidenceCount: int = Field(default=0, ge=0)
    evidenceLevel: str = ""
    contextFingerprint: str = ""
    request: ModelTraceRequest
    result: ModelTraceResult

    @model_validator(mode="after")
    def _result_matches_status(self) -> "ModelInvocationEvent":
        if self.status == "failed" and self.result.error is None:
            raise ValueError("失败的模型调用必须保存 error")
        if self.status == "succeeded" and self.result.error is not None:
            raise ValueError("成功的模型调用不得保存 error")
        return self


class GuardrailEvaluationEvent(BaseModel):
    """结构化输出进入业务前的确定性守卫判定。"""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal["sustainability_desk.ai_observability.v3"] = SCHEMA_VERSION
    eventType: Literal["guardrail_evaluation"] = "guardrail_evaluation"
    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    timestamp: str
    status: Literal["accepted", "rejected"]
    modelId: str
    invocationOrdinal: int = Field(ge=1)
    issues: list[GuardrailIssueTrace] = Field(default_factory=list)
    retryInstruction: str = ""

    @model_validator(mode="after")
    def _issues_match_status(self) -> "GuardrailEvaluationEvent":
        if self.status == "rejected" and not self.issues:
            raise ValueError("拒绝的守卫判定必须保存 issues")
        if self.status == "accepted" and self.issues:
            raise ValueError("通过的守卫判定不得保存 issues")
        return self


class GenerationFinishedEvent(BaseModel):
    """一次生成任务的最终业务状态。"""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal["sustainability_desk.ai_observability.v3"] = SCHEMA_VERSION
    eventType: Literal["generation_finished"] = "generation_finished"
    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    timestamp: str
    status: Literal["succeeded", "failed"]
    modelId: str
    durationMs: int = Field(default=0, ge=0)
    errorCode: str = ""


ObservabilityEvent = Annotated[
    GenerationStartedEvent
    | ModelInvocationEvent
    | GuardrailEvaluationEvent
    | GenerationFinishedEvent,
    Field(discriminator="eventType"),
]
OBSERVABILITY_EVENT_ADAPTER = TypeAdapter(ObservabilityEvent)


class ObservationRun(BaseModel):
    """一次任务的内存状态；JSONL 是逐事件事实，数据库是产品任务聚合投影。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    runId: str
    traceId: str
    requestId: str
    workloadKind: WorkloadKind
    reportId: str
    blockId: str
    operation: str
    modelId: str
    environment: str
    releaseId: str
    gitSha: str
    contractVersion: str
    userId: str = ""
    path: Path
    startedAt: str
    finishedAt: str | None = None
    status: GenerationStatus = "running"
    errorCode: str = ""
    durationMs: int = 0
    nextInvocationOrdinal: int = 1
    collectedEvents: list[
        GenerationStartedEvent
        | ModelInvocationEvent
        | GuardrailEvaluationEvent
        | GenerationFinishedEvent
    ] = Field(default_factory=list)

    def invocation(
        self,
        *,
        block_id: str | None = None,
        model_id: str | None = None,
        evidence_selector_kind: str = "",
        intake_fact_count: int = 0,
        prior_disclosure_count: int = 0,
        metric_evidence_count: int = 0,
        evidence_level: str = "",
        context_fingerprint: str = "",
        task_context: JsonValue | None = None,
    ) -> InvocationContext:
        """分配一次模型调用的稳定序号并返回显式上下文。

        v3：同时捕获当前任务上下文中的阶段 span。调用点必须位于本 run 的某个
        open_stage 内——缺失或跨 trace 即抛错，模型调用不允许游离于阶段体系之外。
        """
        from sustainability_desk.observability.stages import current_stage

        stage = current_stage()
        if stage is None:
            raise RuntimeError(
                f"模型调用（run {self.runId}）不在任何阶段 span 内——"
                "调用点必须被本工作单元的 open_stage 包围"
            )
        if stage.trace_id != self.traceId:
            raise RuntimeError(
                f"当前阶段 span 属于 trace {stage.trace_id}，"
                f"与观测任务 {self.traceId} 不一致——疑似跨工作单元捕获"
            )
        with _WRITE_LOCK:
            ordinal = self.nextInvocationOrdinal
            self.nextInvocationOrdinal += 1
        return InvocationContext(
            runId=self.runId,
            traceId=self.traceId,
            requestId=self.requestId,
            workloadKind=self.workloadKind,
            reportId=self.reportId,
            blockId=block_id or self.blockId,
            operation=self.operation,
            modelId=model_id or self.modelId,
            invocationOrdinal=ordinal,
            environment=self.environment,
            releaseId=self.releaseId,
            gitSha=self.gitSha,
            contractVersion=self.contractVersion,
            spanId=stage.span_id,
            stageId=stage.stage.id,
            evidenceSelectorKind=evidence_selector_kind,
            intakeFactCount=intake_fact_count,
            priorDisclosureCount=prior_disclosure_count,
            metricEvidenceCount=metric_evidence_count,
            evidenceLevel=evidence_level,
            contextFingerprint=context_fingerprint,
            taskContext=task_context,
            run=self,
            userId=self.userId,
        )


_WRITE_LOCK = threading.Lock()


def create_observation_run(
    stage: "Stage",
    *,
    model_id: str,
    workload_kind: WorkloadKind,
    report_id: str = "",
    block_id: str,
    root: Path | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    environment: str | None = None,
    release_id: str | None = None,
    git_sha: str | None = None,
    user_id: str = "",
    contract_version: str,
) -> ObservationRun:
    """建立尚未开始的观测任务；调用方随后用 observe_generation 包围真实工作。

    v3：只接受 unit_root 阶段常量，operation 词汇由其派生——不再是自由字符串。
    ``contract_version`` is the pinned version of the report (or package) the unit works on.
    """
    from sustainability_desk.request_context import current_request_id
    from sustainability_desk.runtime_environment import runtime_environment

    if not stage.unit_root:
        raise ValueError(
            f"观测任务只能以工作单元根阶段建立；{stage.id} 未声明 unit_root"
        )
    runtime = runtime_environment()
    rid = run_id or _run_id()
    return ObservationRun(
        runId=rid,
        traceId=rid,
        requestId=request_id if request_id is not None else current_request_id(),
        workloadKind=workload_kind,
        reportId=report_id,
        blockId=block_id,
        operation=stage.id,
        modelId=model_id,
        environment=environment or runtime.environment,
        releaseId=release_id or runtime.release_id,
        gitSha=git_sha or runtime.git_sha,
        contractVersion=contract_version,
        userId=user_id,
        path=_observation_path(root or runtime.observability_root or DEFAULT_OBSERVABILITY_ROOT, rid),
        startedAt=_timestamp(),
    )


def _common(run: ObservationRun) -> dict[str, Any]:
    return {
        "runId": run.runId,
        "traceId": run.traceId,
        "requestId": run.requestId,
        "workloadKind": run.workloadKind,
        "reportId": run.reportId,
        "blockId": run.blockId,
        "operation": run.operation,
        "environment": run.environment,
        "releaseId": run.releaseId,
        "gitSha": run.gitSha,
        "contractVersion": run.contractVersion,
    }


class ObservationTraceMissingError(RuntimeError):
    """工作单元成功收尾却没有留下观测轨迹文件。

    轨迹是交付期审计引用的解析目标，缺失必须停在产生它的工作单元边界，
    而不是流到交付阶段才以 FileNotFoundError 暴露。
    """


def _write_event(
    run: ObservationRun,
    event: GenerationStartedEvent
    | ModelInvocationEvent
    | GuardrailEvaluationEvent
    | GenerationFinishedEvent,
) -> None:
    run.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    run.path.parent.chmod(0o700)
    line = event.model_dump_json()
    with _WRITE_LOCK:
        run.collectedEvents.append(event)
        with run.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        run.path.chmod(0o600)


@contextmanager
def observe_generation(run: ObservationRun) -> Iterator[ObservationRun]:
    """记录任务开始/结束；调用归属由显式传递的 ObservationRun 决定。"""
    started_monotonic = time.monotonic()
    _write_event(run, GenerationStartedEvent(**_common(run), timestamp=run.startedAt))
    try:
        yield run
    except BaseException as exc:
        run.status = "failed"
        run.errorCode = type(exc).__name__
        raise
    else:
        run.status = "succeeded"
    finally:
        run.finishedAt = _timestamp()
        run.durationMs = max(0, round((time.monotonic() - started_monotonic) * 1000))
        _write_event(
            run,
            GenerationFinishedEvent(
                **_common(run),
                timestamp=run.finishedAt,
                status="failed" if run.status == "failed" else "succeeded",
                modelId=run.modelId,
                durationMs=run.durationMs,
                errorCode=run.errorCode,
            ),
        )
        # 成功收尾必须留下可被 locate_observation_trace 找到的轨迹：下游把
        # observationRunId 写进 receipt 并据此在交付期解析，轨迹缺失会在很晚才以
        # FileNotFoundError 暴露（全部块生成成功仍整体判 failed）。
        # 在工作单元收尾处就地断言，让偏航停在产生它的边界，而不是流到交付。
        if run.status == "succeeded" and not run.path.is_file():
            raise ObservationTraceMissingError(
                f"观测轨迹未落盘：run_id={run.runId}，operation={run.operation}"
            )


@contextmanager
def observe_unit(run: ObservationRun, stage: Stage) -> Iterator[ObservationRun]:
    """开启工作单元根 span 并记录任务始末——根 span 与 run 生命周期一致时的标准入口。

    生成主链的根 span 生命周期长于 observe_generation（还覆盖交付段），须分开管理；
    eval 与其他"一个 run 即一个单元"的调用方用本入口，免去两层样板。
    """
    from sustainability_desk.observability.stages import open_stage

    with open_stage(
        stage,
        trace_id=run.runId,
        report_id=run.reportId,
    ), observe_generation(run):
        yield run


def prompt_fingerprint(agent: Any, user_prompt: str) -> str:
    """为完整 prompt 计算稳定指纹，支持同内容调用聚合。"""
    observability_context = getattr(agent, "_sustainability_desk_observability_context", {})
    payload = {
        "instructions": str(observability_context.get("instructions", "")),
        "userPrompt": user_prompt,
        "modelSettings": observability_context.get("modelSettings", {}),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def record_model_invocation(
    context: InvocationContext,
    *,
    request: ModelTraceRequest,
    result: ModelTraceResult,
    usage: Mapping[str, Any] | None,
    duration_ms: int,
    transport_attempts: int,
    http_send_attempts: int = 0,
    error_code: str = "",
    prompt_hash: str,
) -> None:
    """立即写出一次逻辑模型调用；SDK 内部 provider 请求由 usage 计数。"""
    run = context.run
    if context.runId != run.runId:
        raise RuntimeError("InvocationContext 与当前 AI 观测任务不一致")
    measured = InvocationUsage.from_mapping(usage)
    event = ModelInvocationEvent(
        runId=context.runId,
        traceId=context.traceId,
        requestId=context.requestId,
        workloadKind=context.workloadKind,
        reportId=context.reportId,
        blockId=context.blockId,
        operation=context.operation,
        environment=context.environment,
        releaseId=context.releaseId,
        gitSha=context.gitSha,
        contractVersion=context.contractVersion,
        timestamp=_timestamp(),
        status="failed" if error_code else "succeeded",
        modelId=context.modelId,
        invocationOrdinal=context.invocationOrdinal,
        **measured.model_dump(),
        durationMs=max(0, duration_ms),
        transportAttempts=max(1, transport_attempts),
        httpSendAttempts=max(0, http_send_attempts),
        errorCode=error_code,
        promptFingerprint=prompt_hash,
        spanId=context.spanId,
        stageId=context.stageId,
        evidenceSelectorKind=context.evidenceSelectorKind,
        intakeFactCount=context.intakeFactCount,
        priorDisclosureCount=context.priorDisclosureCount,
        metricEvidenceCount=context.metricEvidenceCount,
        evidenceLevel=context.evidenceLevel,
        contextFingerprint=context.contextFingerprint,
        request=request,
        result=result,
    )
    _write_event(run, event)
    _mirror_invocation(event, user_id=context.userId)


def _provider_name(model_id: str) -> str:
    """模型服务商标识：取注册表声明的 vendor。

    不从端点主机名反推——自建、代理与网关端点的主机名与服务商无关，反推会给出错误标识。
    注册表查不到时退回 "unknown"：观测投影不得因模型标识异常而中断业务。
    """
    from sustainability_desk.llm.model_registry import REGISTRY

    spec = REGISTRY.get(model_id)
    return spec.vendor if spec is not None else "unknown"


def _genai_content_attributes(
    request: ModelTraceRequest, result: ModelTraceResult
) -> dict[str, str]:
    """OTLP 后端控制台按 GenAI 标准键渲染输入输出原文；键名与消息结构以
    《LLM Trace 字段定义说明》为准。sustainability_desk.request/result 仍是完整事实，
    这里只是同一正文的标准键投影，供链路追踪页与推理轨迹视图直接展示。
    """

    def _dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    attributes = {
        "gen_ai.system_instructions": _dump(
            [{"type": "text", "content": request.systemPrompt}]
        ),
        # system 消息并入 input.messages：推理轨迹视图只渲染 messages 两键，
        # 单独的 system_instructions 不出现在对话流里。
        "gen_ai.input.messages": _dump(
            [
                {
                    "role": "system",
                    "parts": [{"type": "text", "content": request.systemPrompt}],
                },
                {
                    "role": "user",
                    "parts": [{"type": "text", "content": request.userPrompt}],
                },
            ]
        ),
        # span 详情「信息」页读 input.value/output.value，不读 messages 两键。
        "input.value": request.userPrompt,
    }
    if result.structuredOutput is not None:
        output_content = (
            result.structuredOutput
            if isinstance(result.structuredOutput, str)
            else _dump(result.structuredOutput)
        )
        attributes["gen_ai.output.messages"] = _dump(
            [
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "content": output_content}],
                    "finish_reason": "stop",
                }
            ]
        )
        attributes["output.value"] = output_content
    return attributes


def mirror_span_for_invocation(event: ModelInvocationEvent, *, user_id: str = ""):
    """一次模型调用事实到镜像 span 的确定性投影；实时镜像与历史补推共用。

    span 时间由事件自身的 timestamp/durationMs 还原，补推历史事件时 span
    仍落在原发生时刻。user_id 不在 JSONL 事件内（经 reportId 可 join 到账号），
    补推侧缺省为空即可。
    """
    from sustainability_desk.observability.otlp_export import MirrorSpan, _capped_attributes

    end_ns = int(
        datetime.fromisoformat(event.timestamp).timestamp() * 1_000_000_000
    )
    span_seed = f"{event.runId}:{event.invocationOrdinal}"
    critical: dict[str, object] = {
        "sustainability_desk.report_id": event.reportId,
        "sustainability_desk.stage": event.stageId,
        "sustainability_desk.trace": event.traceId,
        "sustainability_desk.run_id": event.runId,
        "sustainability_desk.ordinal": event.invocationOrdinal,
        # OTLP 后端 靠这三个键判定 AI 应用与模型调用；缺 span.kind 时
        # 服务端只登记普通 XTRACE 服务，AI 面板与 Token 统计全空
        # （对照实测二分到 span.kind 单键）。
        "gen_ai.span.kind": "LLM",
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": _provider_name(event.modelId),
        # OTLP 后端 按 agent.name 聚合对话；LLM 调用归属其工作单元根阶段
        # （operation 即 unit_root 阶段 id），缺失时控制台整列显示 "--"。
        "gen_ai.agent.name": event.operation,
        # 会话=报告：同一报告的多次生成运行在会话分析页聚合浏览；
        # 无报告归属的工作单元（eval 等）退回 run 自身为一次会话。
        "gen_ai.session.id": event.reportId or event.runId,
    }
    if user_id:
        critical["gen_ai.user.id"] = user_id
    # span 显示名携带业务身份：blockId 定位到披露块，#序号与本地 JSONL 的
    # invocationOrdinal 一一对应（调查时按序号即可 join 回完整事实）。
    display_label = event.blockId or event.modelId
    return MirrorSpan(
        trace_id=event.traceId,
        span_id=hashlib.sha256(span_seed.encode("utf-8")).hexdigest()[:16],
        parent_span_id=event.spanId,
        name=f"llm {display_label} #{event.invocationOrdinal}",
        start_ns=end_ns - event.durationMs * 1_000_000,
        end_ns=end_ns,
        ok=not event.errorCode,
        attributes=_capped_attributes(
            {
                # 正文用少数几个大属性承载（体积不是瓶颈，数量才是；spec §6）。
                "sustainability_desk.request": event.request.model_dump_json(),
                "sustainability_desk.result": event.result.model_dump_json(),
                **_genai_content_attributes(event.request, event.result),
                "gen_ai.request.model": event.modelId,
                "gen_ai.response.model": event.modelId,
                "gen_ai.usage.input_tokens": event.inputTokens,
                "gen_ai.usage.output_tokens": event.outputTokens,
                "sustainability_desk.error_code": event.errorCode,
                "sustainability_desk.block_id": event.blockId,
                "sustainability_desk.context_fingerprint": event.contextFingerprint,
            },
            critical,
        ),
    )


def _mirror_invocation(event: ModelInvocationEvent, *, user_id: str) -> None:
    """把模型调用投影为镜像 span（正文两边都写，spec §4）。本地 JSONL 是真相。"""
    from sustainability_desk.observability.otlp_export import trace_mirror

    mirror = trace_mirror()
    if not mirror.enabled:
        return
    mirror.enqueue(mirror_span_for_invocation(event, user_id=user_id))


def record_guardrail_evaluation(
    context: InvocationContext,
    *,
    issues: list[GuardrailIssueTrace],
    retry_instruction: str,
) -> None:
    """保存一次结构化输出的业务守卫结果，并与模型调用序号严格关联。"""

    run = context.run
    if context.runId != run.runId:
        raise RuntimeError("InvocationContext 与当前 AI 观测任务不一致")
    _write_event(
        run,
        GuardrailEvaluationEvent(
            runId=context.runId,
            traceId=context.traceId,
            requestId=context.requestId,
            workloadKind=context.workloadKind,
            reportId=context.reportId,
            blockId=context.blockId,
            operation=context.operation,
            environment=context.environment,
            releaseId=context.releaseId,
            gitSha=context.gitSha,
            contractVersion=context.contractVersion,
            timestamp=_timestamp(),
            status="rejected" if issues else "accepted",
            modelId=context.modelId,
            invocationOrdinal=context.invocationOrdinal,
            issues=issues,
            retryInstruction=retry_instruction,
        ),
    )


def parse_observability_event(line: str) -> ObservabilityEvent:
    """严格解析完整观测合同；历史无正文事件不在支持范围内。"""
    return OBSERVABILITY_EVENT_ADAPTER.validate_json(line)


def locate_observation_trace(run_id: str, *, root: Path | None = None) -> Path:
    """按稳定 run ID 定位受限 JSONL；歧义或缺失均 fail-closed。"""

    from sustainability_desk.runtime_environment import runtime_environment

    trace_root = root or runtime_environment().observability_root or DEFAULT_OBSERVABILITY_ROOT
    matches = tuple(trace_root.rglob(f"{run_id}.jsonl")) if trace_root.exists() else ()
    if len(matches) != 1:
        raise FileNotFoundError(
            f"观测 trace 必须唯一存在：run_id={run_id}，matches={len(matches)}"
        )
    return matches[0]
