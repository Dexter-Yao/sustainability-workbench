# ABOUTME: 本地观测事实到 OTLP 后端（OTLP/HTTP）的镜像投影——本地 JSONL 是真相，此处只投影。
# ABOUTME: 上报失败 fail-loud 记日志并计数（SDK 会静默吞导出异常，spec §6 实测）；无端点配置即整体停用。
# ABOUTME(en): Mirror projection of local observability facts to an OTLP/HTTP backend — local JSONL is the truth.
# ABOUTME(en): Export failures fail loud into logs and a counter (the SDK swallows them); no endpoint disables it.
from __future__ import annotations

import atexit
import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)

ENDPOINT_ENV = "SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT"
HEADERS_ENV = "SUSTAINABILITY_DESK_OTLP_TRACES_HEADERS"
# 进程角色（api / material-worker / report-workflow-worker）；缺省即不写该属性。
# 三个进程属于同一个 OTLP 后端 应用，角色只用于区分实例，不参与应用身份。
SERVICE_ROLE_ENV = "SUSTAINABILITY_DESK_SERVICE_ROLE"

# OTLP 后端控制台的应用名；
# backend 与两个 worker 共用同一个应用，进程差异落在 service.instance.id。
# 取技术标识而非品牌名：改名不应连带打断既有后端里的应用身份与历史统计。
SERVICE_NAME = "sustainability-desk"

# 非生产环境的应用名后缀。本机 eval、实验与抓取即使配了端点，也落在独立应用里，
# 不污染真实用户生成的 token 与耗时统计。环境判定取 RuntimeEnvironment，
# 不做「有没有 systemd」这类自动推断——推断判错时没有任何告警，只会让统计悄悄失真。
NON_PRODUCTION_SUFFIX = "-nonprod"

# 单 span 的属性上限。**该值源自阿里云 ARMS 的实测行为**（超过 128 个属性即静默丢弃，
# 且丢的是先写入的头部），不是 OTLP 协议约束：Langfuse、LangSmith 等后端没有这条限制。
# 收紧到 120 留余量，并让关键检索键最后写入，故在任何后端下都安全，只是对无此限制的
# 后端偏保守。换后端且确认无属性上限时可调高；调高前先实测，不要照搬本注释的数字。
MAX_SPAN_ATTRIBUTES = 120
_FLUSH_BATCH = 64
_FLUSH_INTERVAL_SECONDS = 3.0


def _trace_id_int(trace_id: str) -> int:
    """业务 trace_id（run_id 字符串）到 OTLP 128 位 trace id 的确定性映射。"""
    digest = hashlib.sha256(trace_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:16], "big") or 1


def _span_id_int(span_id: str) -> int:
    try:
        return int(span_id, 16) or 1
    except ValueError:
        digest = hashlib.sha256(span_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") or 1


def _capped_attributes(
    bulk: dict[str, object], critical: dict[str, object]
) -> dict[str, object]:
    """按 OTLP 后端 丢弃语义排布属性：批量在前、关键检索键最后写入，总量封顶。

    Python dict 保序，OTLP 序列化按插入序输出；超限被丢的是先写入的头部，
    因此关键键放尾部即可在截断下存活。
    """
    budget = MAX_SPAN_ATTRIBUTES - len(critical) - 1  # 预留截断标记位
    ordered: dict[str, object] = {}
    truncated = 0
    for key, value in bulk.items():
        if key in critical:
            continue
        if len(ordered) >= budget:
            truncated += 1
            continue
        ordered[key] = value
    if truncated:
        ordered["sustainability_desk.attributes_truncated"] = truncated
    ordered.update(critical)
    return ordered


def _attribute_value(value: object) -> object:
    """OTLP 属性只接受标量与同质数组；其余序列化为字符串。"""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return list(value)
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


@lru_cache(maxsize=1)
def _resource():
    """镜像 span 的 resource：应用身份 + 运行环境 + 可选进程角色。

    不声明任何后端专有的 resource 属性（如阿里云 ARMS 的 `acs.arms.service.feature`）：
    识别 GenAI 应用是后端按 span 的 `gen_ai.*` 语义自行判定的事，客户端再写一份只会漂移，
    也会把某一家后端的约定固化进通用导出路径。
    """
    from opentelemetry.sdk.resources import Resource

    from sustainability_desk.runtime_environment import runtime_environment

    environment = runtime_environment().environment
    service_name = (
        SERVICE_NAME
        if environment == "production"
        else f"{SERVICE_NAME}{NON_PRODUCTION_SUFFIX}"
    )
    attributes: dict[str, str] = {
        "service.name": service_name,
        "deployment.environment": environment,
    }
    role = os.getenv(SERVICE_ROLE_ENV, "").strip()
    if role:
        attributes["service.instance.id"] = role
    return Resource.create(attributes)


@dataclass(frozen=True)
class MirrorSpan:
    """一条待镜像 span 的最小事实；与 OTel SDK 类型解耦，便于测试与排序控制。"""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_ns: int
    end_ns: int
    ok: bool
    attributes: dict[str, object] = field(default_factory=dict)


class OtlpTraceMirror:
    """把阶段与模型调用事实批量镜像到 OTLP 端点的后台投影器。

    - 端点缺省即停用（本地开发零开销），配置来自环境变量 SUSTAINABILITY_DESK_OTLP_TRACES_*。
    - 每批导出核对 SpanExportResult：失败记 error 日志并累计 failed_batches，
      不向业务抛——但绝不静默（OTel SDK 自身会吞异常，不能依赖它报错）。
    """

    def __init__(self) -> None:
        self._endpoint = os.getenv(ENDPOINT_ENV, "").strip()
        self._queue: list[MirrorSpan] = []
        self._lock = threading.Lock()
        self._exporter = None
        self._timer: threading.Timer | None = None
        self._resource_snapshot = None
        self.failed_batches = 0
        self.exported_spans = 0
        if self._endpoint:
            self._exporter = self._build_exporter()
            # resource 必须在此提前求值：Resource.create 内部走线程池，
            # 若推迟到 atexit flush（短命进程首批 span 未满就退出），解释器
            # 关闭后提交线程池任务会抛 RuntimeError，整批 span 丢失。
            self._resource_snapshot = _resource()
            atexit.register(self.flush)

    @property
    def enabled(self) -> bool:
        return self._exporter is not None

    def _build_exporter(self):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        headers: dict[str, str] = {}
        raw_headers = os.getenv(HEADERS_ENV, "").strip()
        for item in filter(None, raw_headers.split(",")):
            key, _, value = item.partition("=")
            if key and value:
                headers[key.strip()] = value.strip()
        return OTLPSpanExporter(endpoint=self._endpoint, headers=headers or None)

    def enqueue(self, span: MirrorSpan) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._queue.append(span)
            should_flush = len(self._queue) >= _FLUSH_BATCH
            if not should_flush and self._timer is None:
                self._timer = threading.Timer(_FLUSH_INTERVAL_SECONDS, self.flush)
                self._timer.daemon = True
                self._timer.start()
        if should_flush:
            self.flush()

    def flush(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            batch, self._queue = self._queue, []
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if not batch:
            return
        readable = [self._to_readable(span) for span in batch]
        try:
            result = self._exporter.export(readable)
        except Exception:  # noqa: BLE001 — 观测导出不拖垮业务，但必须留下明确失败事实
            self.failed_batches += 1
            logger.exception("OTLP 镜像导出抛异常：%d 条 span 丢失", len(batch))
            return
        from opentelemetry.sdk.trace.export import SpanExportResult

        if result is not SpanExportResult.SUCCESS:
            self.failed_batches += 1
            logger.error(
                "OTLP 镜像导出失败（%s）：%d 条 span 未落库；上报 200 不代表成功，"
                "验收以 trace search 回读为准",
                result,
                len(batch),
            )
            return
        self.exported_spans += len(batch)

    def discard_pending_for_tests(self) -> None:
        """清空待导出队列、取消定时器并注销 atexit 回调——仅供测试隔离。"""
        with self._lock:
            self._queue.clear()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        atexit.unregister(self.flush)

    def _to_readable(self, span: MirrorSpan):
        from opentelemetry.sdk.trace import ReadableSpan
        from opentelemetry.sdk.util.instrumentation import InstrumentationScope
        from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
        from opentelemetry.trace.status import Status, StatusCode

        context = SpanContext(
            trace_id=_trace_id_int(span.trace_id),
            span_id=_span_id_int(span.span_id),
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        parent = (
            SpanContext(
                trace_id=_trace_id_int(span.trace_id),
                span_id=_span_id_int(span.parent_span_id),
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
            if span.parent_span_id
            else None
        )
        return ReadableSpan(
            name=span.name,
            context=context,
            parent=parent,
            attributes={k: _attribute_value(v) for k, v in span.attributes.items()},
            start_time=span.start_ns,
            end_time=span.end_ns,
            status=Status(StatusCode.OK if span.ok else StatusCode.ERROR),
            kind=SpanKind.INTERNAL,
            # 测试可在停用实例上注入假 exporter，此时快照为空，就地求值兜底。
            resource=(
                self._resource_snapshot
                if self._resource_snapshot is not None
                else _resource()
            ),
            instrumentation_scope=InstrumentationScope("sustainability_desk.observability"),
        )


_MIRROR: OtlpTraceMirror | None = None
_MIRROR_LOCK = threading.Lock()


def trace_mirror() -> OtlpTraceMirror:
    global _MIRROR
    if _MIRROR is None:
        with _MIRROR_LOCK:
            if _MIRROR is None:
                _MIRROR = OtlpTraceMirror()
    return _MIRROR


def reset_trace_mirror_for_tests() -> None:
    """丢弃单例并彻底解除其退出职责——仅供测试隔离。

    只置 None 不够：启用态实例在 __init__ 里注册过 atexit flush，若队列
    还有残留 span，解释器退出时会出网上报甚至崩溃（线程池已关闭）。
    """
    global _MIRROR
    with _MIRROR_LOCK:
        if _MIRROR is not None:
            _MIRROR.discard_pending_for_tests()
        _MIRROR = None
