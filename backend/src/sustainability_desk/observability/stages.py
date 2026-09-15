# ABOUTME: 链路阶段 span 的唯一开启出口，运行期强制阶段登记、同 trace 嵌套与适用范围三条不变量。
# ABOUTME: 只接受 registry 内的 typed Stage 常量；span 父子由真实调用结构决定，没有声明式树。
# ABOUTME(en): Only entry point for opening a stage span, enforcing registration, same-trace nesting and scope.
# ABOUTME(en): Accepts only typed Stage constants from the registry; span parentage follows real calls, not a tree.
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sustainability_desk.accounts.report_execution_scope import ReportScopeKind
from sustainability_desk.observability.registry import Stage, registered_stage
from sustainability_desk.observability.stage_trace import (
    StageRecord,
    append_stage_record,
    stage_trace_path,
)


class StageError(Exception):
    """阶段观测的合同违例基类。链路结构错误必须当场失败，不得静默继续。"""


class StageUnregistered(StageError):
    """传入的 stage 不在 registry 内，或与登记定义不一致——疑似绕过声明处自造对象。"""


class StageTraceMismatch(StageError):
    """父 span 属于另一条 trace。跨工作单元不伪造父子，靠 report_id 属性聚合。"""


class StageScopeViolation(StageError):
    """在不适用的执行范围内开启阶段，或范围受限阶段缺少 report_id / scope。"""


class PipelineStageMissing(StageError):
    """声明必经的阶段事实缺失。产出静默缺失比失败更危险，必须阻断（spec §3.5）。"""


@dataclass
class StageHandle:
    """一个已开启阶段的运行期句柄。"""

    stage: Stage
    trace_id: str
    report_id: str
    span_id: str
    parent_span_id: str | None
    scope: ReportScopeKind | None
    started_at: float
    started_at_utc: str
    attributes: dict[str, object] = field(default_factory=dict)
    finished_at: float | None = None
    status: str = "running"
    error_code: str = ""
    # 轨迹落盘失败的原因；非空即表示该阶段事实未进入可查证轨迹。
    persist_error: str = ""
    # 本 trace 的根句柄（根自身指向自己）。子 span 收束时把 (stageId, attributes)
    # 记到根，供收束断言在内存中比对必经阶段，不依赖轨迹文件回读。
    root: "StageHandle | None" = None
    executed_stage_facts: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return int((end - self.started_at) * 1000)

    def set_attribute(self, key: str, value: object) -> None:
        """写入业务属性。键须落在 sustainability_desk.* 或 gen_ai.* 命名空间（spec §4）。"""
        if not key.startswith(("sustainability_desk.", "gen_ai.")):
            raise StageError(
                f"阶段属性 {key} 不在允许的命名空间；业务语义用 sustainability_desk.*，"
                "LLM 标准语义用 gen_ai.*"
            )
        self.attributes[key] = value


# 同一任务上下文内的当前阶段；跨工作单元不依赖它（父子只表达单元内真实嵌套）。
_CURRENT_STAGE: ContextVar[StageHandle | None] = ContextVar(
    "sustainability_desk_current_stage", default=None
)


def current_stage() -> StageHandle | None:
    return _CURRENT_STAGE.get()


def require_current_stage(action: str) -> StageHandle:
    """取当前任务上下文中的阶段 span；缺失即 fail-loud。

    v3 起模型调用必须结构性归属于 span（invocation 拒绝无 span 的调用）；
    在业务层提前失败能给出比 invocation 层更贴近现场的错误信息。
    """
    handle = _CURRENT_STAGE.get()
    if handle is None:
        raise StageError(
            f"{action}不在任何阶段 span 内——调用方（生成服务或 eval 入口）"
            "必须先开启工作单元根 span"
        )
    return handle


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _check_invariants(
    stage: Stage,
    parent: StageHandle | None,
    trace_id: str,
    report_id: str,
    scope: ReportScopeKind | None,
) -> None:
    registered = registered_stage(stage.id)
    if registered is None or registered != stage:
        raise StageUnregistered(
            f"阶段 {stage.id} 未登记于 registry 或与登记定义不一致"
        )

    if stage.scopes is not None:
        if scope is None:
            raise StageScopeViolation(
                f"阶段 {stage.id} 受报告执行范围约束，必须传入 scope"
            )
        if scope not in stage.scopes:
            raise StageScopeViolation(
                f"阶段 {stage.id} 不适用于执行范围 {scope}（适用：{sorted(stage.scopes)}）"
            )
        if not report_id:
            raise StageScopeViolation(
                f"阶段 {stage.id} 属报告链路，report_id 不得为空"
            )

    if parent is not None and parent.trace_id != trace_id:
        raise StageTraceMismatch(
            f"阶段 {stage.id} 的父 span 属于 trace {parent.trace_id}，"
            f"与本阶段 trace {trace_id} 不符——跨工作单元不得伪造父子"
        )


@contextmanager
def open_stage(
    stage: Stage,
    *,
    trace_id: str,
    report_id: str,
    scope: ReportScopeKind | None = None,
    parent: StageHandle | None = None,
    trace_root: Path | None = None,
    **attributes: object,
) -> Iterator[StageHandle]:
    """开启一个已登记阶段。stage 是声明处导出的 typed 常量，不接受字符串。

    trace_id 恒为所在工作单元的 run_id（与 ObservationRun.runId 同值，spec 决策点 A）。
    parent 显式传入或取同任务 ContextVar；父子只表达单元内真实嵌套，跨单元靠
    sustainability_desk.report_id 聚合，不伪造父子。

    阶段结束时把事实写入轨迹文件；未指定 trace_root 时按运行时观测根目录落盘。
    落盘失败不得掩盖业务异常，但也不静默吞掉——见 finally 中的处理。
    """
    effective_parent = parent if parent is not None else _CURRENT_STAGE.get()
    _check_invariants(stage, effective_parent, trace_id, report_id, scope)

    handle = StageHandle(
        stage=stage,
        trace_id=trace_id,
        report_id=report_id,
        span_id=_new_span_id(),
        parent_span_id=effective_parent.span_id if effective_parent else None,
        scope=scope,
        started_at=time.monotonic(),
        started_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    handle.root = effective_parent.root if effective_parent is not None else handle
    for key, value in attributes.items():
        handle.set_attribute(key, value)

    token = _CURRENT_STAGE.set(handle)
    try:
        yield handle
    except Exception as exc:
        handle.status = "failed"
        handle.error_code = type(exc).__name__
        raise
    else:
        handle.status = "succeeded"
    finally:
        handle.finished_at = time.monotonic()
        _CURRENT_STAGE.reset(token)
        root = handle.root
        if root is not None:
            root.executed_stage_facts.append((handle.stage.id, dict(handle.attributes)))
        _persist(handle, trace_root)


def _persist(handle: StageHandle, trace_root: Path | None) -> None:
    """落盘一条阶段事实。

    观测故障不得拖垮业务，因此不向上抛；但也不能静默——写入失败会打断
    完整性断言赖以比对的事实链，故记入 handle 供调用方与测试查证。
    """
    from sustainability_desk.runtime_environment import runtime_environment
    from sustainability_desk.llm.ai_observability import DEFAULT_OBSERVABILITY_ROOT

    root = trace_root or runtime_environment().observability_root or DEFAULT_OBSERVABILITY_ROOT
    record = StageRecord(
        traceId=handle.trace_id,
        spanId=handle.span_id,
        parentSpanId=handle.parent_span_id,
        stageId=handle.stage.id,
        kind=handle.stage.kind,
        reportId=handle.report_id,
        scope=handle.scope,
        status=handle.status,
        errorCode=handle.error_code,
        durationMs=handle.duration_ms,
        startedAt=handle.started_at_utc,
        attributes=dict(handle.attributes),
    )
    try:
        append_stage_record(stage_trace_path(Path(root), handle.trace_id), record)
    except Exception as exc:  # noqa: BLE001 — 观测写入失败不得掩盖业务异常
        handle.persist_error = f"{type(exc).__name__}: {exc}"
    _mirror(record)


# Stage.kind 到 OTLP 后端 GenAI 语义的投影。agent/tool 一一对应；其余 kind
# （orchestration/llm/deterministic/external_process）统一投影为 CHAIN：
# - 不得标 LLM——kind="llm" 的阶段本身不是一次模型调用（真正的调用由
#   _mirror_invocation 产出独立 span），标成 LLM 会重复计模型调用与 Token；
# - 也不能不标——无 gen_ai.span.kind 的 span 不进 AI 应用视图（链路追踪页
#   调用树会缺整段编排骨架，树塌成平铺 LLM span），CHAIN 无计量语义。
_GENAI_SPAN_KIND: dict[str, str] = {"agent": "AGENT", "tool": "TOOL"}


def _genai_attributes(stage_id: str, kind: str) -> dict[str, object]:
    """阶段的 GenAI 语义属性；registry 的 kind 与 id 是唯一来源，不另起一套命名。"""
    span_kind = _GENAI_SPAN_KIND.get(kind)
    if span_kind is None:
        return {"gen_ai.span.kind": "CHAIN"}
    attributes: dict[str, object] = {"gen_ai.span.kind": span_kind}
    if span_kind == "AGENT":
        attributes["gen_ai.agent.name"] = stage_id
        attributes["gen_ai.operation.name"] = "invoke_agent"
    else:
        attributes["gen_ai.tool.name"] = stage_id
        attributes["gen_ai.operation.name"] = "execute_tool"
    return attributes


# 阶段属性中的业务身份键：进入 span 名称与 input.value，使控制台里同名阶段可区分
# （几十个 generation.block 在调用树里不带 block_id 无法定位）。
_IDENTITY_ATTR_KEYS = (
    "sustainability_desk.block_id",
    "sustainability_desk.row_ordinal",
    "sustainability_desk.source_id",
    "sustainability_desk.attempt",
)


def _stage_span_name(record: StageRecord) -> str:
    """span 显示名 = 阶段词汇 + 业务身份（block/行号/资料源），无身份时保持阶段 id。"""
    parts = [record.stageId]
    block_id = record.attributes.get("sustainability_desk.block_id")
    if block_id:
        parts.append(str(block_id))
    row_ordinal = record.attributes.get("sustainability_desk.row_ordinal")
    if row_ordinal is not None:
        parts.append(f"r{row_ordinal}")
    source_id = record.attributes.get("sustainability_desk.source_id")
    if source_id:
        parts.append(str(source_id)[:8])
    return " ".join(parts)


def _stage_io_attributes(record: StageRecord) -> dict[str, object]:
    """CHAIN span 的 input.value/output.value 摘要——控制台「信息」页与会话/链路
    列表读这对键；身份进 input、状态与结果属性进 output，不承载正文。"""
    identity = [record.stageId]
    results = [record.status]
    for key, value in record.attributes.items():
        text = str(value)
        if len(text) > 60:
            continue
        short = key.removeprefix("sustainability_desk.")
        if key in _IDENTITY_ATTR_KEYS:
            identity.append(f"{short}={text}")
        else:
            results.append(f"{short}={text}")
    if record.parentSpanId is None and record.reportId:
        identity.append(f"report={record.reportId[:8]}")
    return {"input.value": " ".join(identity), "output.value": " ".join(results)}


def mirror_span_for_stage_record(record: StageRecord):
    """一条阶段事实到镜像 span 的确定性投影；实时镜像与历史补推共用。"""
    from sustainability_desk.observability.otlp_export import MirrorSpan, _capped_attributes

    start_ns = int(
        datetime.fromisoformat(record.startedAt).timestamp() * 1_000_000_000
    )
    return MirrorSpan(
        trace_id=record.traceId,
        span_id=record.spanId,
        parent_span_id=record.parentSpanId,
        name=_stage_span_name(record),
        start_ns=start_ns,
        end_ns=start_ns + record.durationMs * 1_000_000,
        ok=record.status == "succeeded",
        attributes=_capped_attributes(
            dict(record.attributes)
            | {"sustainability_desk.error_code": record.errorCode}
            | _stage_io_attributes(record),
            # 关键检索键最后写入：属性超限时 OTLP 后端 丢先写入的头部（spec §6）。
            {
                "sustainability_desk.report_id": record.reportId,
                "sustainability_desk.stage": record.stageId,
                "sustainability_desk.trace": record.traceId,
                "sustainability_desk.scope": record.scope or "",
                # 会话=报告；无报告归属的工作单元退回 trace 自身（与模型调用
                # span 的口径一致，会话分析页才能把整棵树归入同一会话）。
                "gen_ai.session.id": record.reportId or record.traceId,
            }
            | _genai_attributes(record.stageId, record.kind),
        ),
    )


def _mirror(record: StageRecord) -> None:
    """把阶段事实投影到 OTLP 后端 镜像（未配置端点即空操作）。本地 JSONL 是真相。"""
    from sustainability_desk.observability.otlp_export import trace_mirror

    mirror = trace_mirror()
    if not mirror.enabled:
        return
    mirror.enqueue(mirror_span_for_stage_record(record))
