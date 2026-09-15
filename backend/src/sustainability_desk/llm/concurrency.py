# ABOUTME: 生成链路的并发原语——单点全局限流 + 瞬时错误退避的 LLM 调用（run_agent）、顺序对应+失败隔离的 fan-out（bounded_gather）。
# ABOUTME: 块级与行级 fan-out 嵌套时真实 LLM 并发在 run_agent 单点封顶，避免撞 DashScope 限流；bounded_gather 只管调度与结果对齐。
# ABOUTME(en): Generation concurrency primitives: run_agent (single global throttle plus transient-error backoff) and
# ABOUTME(en): bounded_gather (order-preserving, failure-isolated fan-out). Real LLM concurrency is capped at run_agent.
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai import BinaryContent, capture_run_messages
from pydantic_ai.messages import ModelMessagesTypeAdapter

from sustainability_desk.llm.ai_observability import (
    InvocationContext,
    ModelTraceError,
    ModelTraceRequest,
    ModelTraceResult,
    prompt_fingerprint,
    record_model_invocation,
)
from sustainability_desk.llm.provider_transport import observe_provider_transport

logger = logging.getLogger(__name__)

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")

# 全局在飞 LLM 调用上限：块×行嵌套 fan-out 下真实并发在此单点封顶（choke point）；瞬时限流由 run_agent 退避兜底。
MAX_INFLIGHT_LLM_CALLS = 100
_TRANSIENT_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_TRANSIENT_RETRIES = 3

_llm_semaphore: asyncio.Semaphore | None = None
_llm_loop: asyncio.AbstractEventLoop | None = None


def _binary_descriptor(
    data: bytes,
    *,
    media_type: str = "application/octet-stream",
) -> dict[str, str | int]:
    """只记录二进制的稳定身份与大小，禁止把原始内容写入观测轨迹。"""

    return {
        "kind": "binary_descriptor",
        "mediaType": media_type,
        "byteLength": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _serialized_binary(value: Any) -> bytes:
    """还原 SDK JSON 中的 base64 二进制；异常编码仍按不透明字节处理。"""

    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return value.encode("utf-8")
    return str(value).encode("utf-8")


def _json_value(value: Any) -> Any:
    """把 SDK/Pydantic 对象冻结为 JSON，同时把所有二进制替换为描述符。"""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, BinaryContent):
        return _binary_descriptor(value.data, media_type=value.media_type)
    if isinstance(value, bytes):
        return _binary_descriptor(value)
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="python"))
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        if value.get("kind") == "binary" and "data" in value:
            media_type = value.get("media_type", value.get("mediaType"))
            return _binary_descriptor(
                _serialized_binary(value["data"]),
                media_type=(
                    media_type
                    if isinstance(media_type, str)
                    else "application/octet-stream"
                ),
            )
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_json_value(item) for item in value]
    return str(value)


def _trace_prompt(user_prompt: Any, sensitive_values: Sequence[str]) -> str:
    """把非文本 Pydantic AI prompt 稳定投影为观测文本，并遮蔽短时凭据。"""
    rendered = (
        user_prompt
        if isinstance(user_prompt, str)
        else json.dumps(_json_value(user_prompt), ensure_ascii=False, sort_keys=True)
    )
    for value in sensitive_values:
        if value:
            rendered = rendered.replace(value, "[REDACTED_EPHEMERAL_VALUE]")
    return rendered


def _redact_value(value: Any, sensitive_values: Sequence[str]) -> Any:
    """递归遮蔽 SDK 消息历史中的显式短时值。"""
    if isinstance(value, str):
        for sensitive in sensitive_values:
            if sensitive:
                value = value.replace(sensitive, "[REDACTED_EPHEMERAL_VALUE]")
        return value
    if isinstance(value, list):
        return [_redact_value(item, sensitive_values) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_value(item, sensitive_values)
            for key, item in value.items()
        }
    return value


def _trace_request(
    agent: Any,
    user_prompt: str,
    invocation: InvocationContext,
) -> ModelTraceRequest:
    context = getattr(agent, "_sustainability_desk_observability_context", {})
    model_settings = _json_value(context.get("modelSettings", {}))
    output_schema = _json_value(context.get("outputSchema", {}))
    return ModelTraceRequest(
        taskContext=invocation.taskContext,
        systemPrompt=str(context.get("instructions", "")),
        userPrompt=user_prompt,
        modelSettings=model_settings if isinstance(model_settings, dict) else {},
        outputSchema=output_schema if isinstance(output_schema, dict) else {},
    )


def _serialized_message_history(
    serialized: bytes | str,
    sensitive_values: Sequence[str],
) -> list[Any]:
    """把 SDK 消息序列化结果转换为脱敏、无二进制的 trace 投影。"""
    if isinstance(serialized, bytes):
        try:
            payload = _json_value(json.loads(serialized.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = _json_value(serialized)
    else:
        payload = _json_value(serialized)
    messages = payload if isinstance(payload, list) else [payload]
    redacted = _redact_value(messages, sensitive_values)
    return _without_model_reasoning(redacted)


def _without_model_reasoning(value: Any) -> list[Any]:
    """删除模型思维片段，保留工具交互、重试和结构化输出的可复现证据。"""

    reasoning_keys = {"reasoning", "reasoning_content", "thinking"}
    reasoning_kinds = {"reasoning", "reasoningpart", "thinking", "thinkingpart"}

    def clean(item: Any) -> Any | None:
        if isinstance(item, list):
            return [cleaned for value in item if (cleaned := clean(value)) is not None]
        if not isinstance(item, dict):
            return item
        part_kind = next(
            (
                str(item[key]).replace("_", "").lower()
                for key in ("part_kind", "partKind", "kind", "type")
                if key in item
            ),
            "",
        )
        if part_kind in reasoning_kinds:
            return None
        return {
            key: cleaned
            for key, value in item.items()
            if key not in reasoning_keys
            if (cleaned := clean(value)) is not None
        }

    cleaned = clean(value)
    return cleaned if isinstance(cleaned, list) else ([] if cleaned is None else [cleaned])


def _message_history(result: Any, sensitive_values: Sequence[str]) -> list[Any]:
    serializer = getattr(result, "all_messages_json", None)
    if not callable(serializer):
        return []
    return _serialized_message_history(serializer(), sensitive_values)


def _captured_message_history(
    messages: Sequence[Any],
    sensitive_values: Sequence[str],
) -> list[Any]:
    """序列化异常前已交换的 SDK 消息，保留 interrupted 状态用于归因。"""
    if not messages:
        return []
    return _serialized_message_history(
        ModelMessagesTypeAdapter.dump_json(list(messages)),
        sensitive_values,
    )


def _trace_error(
    exc: Exception,
    sensitive_values: Sequence[str] = (),
) -> ModelTraceError:
    body = _redact_value(
        _json_value(getattr(exc, "body", None)),
        sensitive_values,
    )
    def redacted_message(error: BaseException) -> str:
        message = str(error)
        for sensitive in sensitive_values:
            if sensitive:
                message = message.replace(
                    sensitive,
                    "[REDACTED_EPHEMERAL_VALUE]",
                )
        return message

    causes: list[dict[str, str]] = []
    seen: set[int] = set()
    cause = exc.__cause__ or (
        None if exc.__suppress_context__ else exc.__context__
    )
    while cause is not None and id(cause) not in seen and len(causes) < 8:
        seen.add(id(cause))
        causes.append({
            "type": type(cause).__name__,
            "message": redacted_message(cause),
        })
        cause = cause.__cause__ or (
            None if cause.__suppress_context__ else cause.__context__
        )
    status_code = getattr(exc, "status_code", None)
    return ModelTraceError(
        type=type(exc).__name__,
        message=redacted_message(exc),
        statusCode=status_code if isinstance(status_code, int) else None,
        body=body,
        causes=causes,
    )


def _llm_slots() -> asyncio.Semaphore:
    """惰性创建全局 LLM 并发信号量；生产为单一长驻事件循环故只建一次，事件循环变更（如逐测试）时重建。"""
    global _llm_semaphore, _llm_loop
    loop = asyncio.get_running_loop()
    if _llm_semaphore is None or _llm_loop is not loop:
        _llm_semaphore = asyncio.Semaphore(MAX_INFLIGHT_LLM_CALLS)
        _llm_loop = loop
    return _llm_semaphore


async def run_agent(
    agent: Any,
    user_prompt: Any,
    invocation: InvocationContext,
    *,
    sensitive_values: Sequence[str] = (),
    **run_kwargs: Any,
) -> Any:
    """执行一次 agent.run：全局限流 + 对瞬时错误（429/5xx）指数退避重试。

    这是所有生成侧 LLM 调用的唯一出口——真实并发在此封顶，速率限制在此退避，
    与叶级 guardrail 的业务重试、Pydantic AI 的结构化输出重试互不重叠。
    """
    from pydantic_ai.exceptions import ModelHTTPError

    async with _llm_slots():
        delay = 1.0
        started = time.monotonic()
        observed_prompt = _trace_prompt(user_prompt, sensitive_values)
        prompt_hash = prompt_fingerprint(agent, observed_prompt)
        trace_request = _trace_request(agent, observed_prompt, invocation)
        transport_errors: list[ModelTraceError] = []
        partial_message_history: list[Any] = []
        with observe_provider_transport() as provider_transport:
            for attempt in range(_MAX_TRANSIENT_RETRIES):
                captured_messages: list[Any]
                try:
                    with capture_run_messages() as captured_messages:
                        captured_start = len(captured_messages)
                        result = await agent.run(user_prompt, **run_kwargs)
                    usage_value = getattr(result, "usage", None)
                    if callable(usage_value):
                        usage_value = usage_value()
                    raw_usage = asdict(usage_value) if usage_value is not None else {}
                    record_model_invocation(
                        invocation,
                        request=trace_request,
                        result=ModelTraceResult(
                            messageHistory=_message_history(result, sensitive_values),
                            structuredOutput=_json_value(result.output),
                            transportErrors=transport_errors,
                        ),
                        usage=raw_usage,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        transport_attempts=attempt + 1,
                        http_send_attempts=provider_transport.http_send_attempts,
                        prompt_hash=prompt_hash,
                    )
                    return result
                except ModelHTTPError as exc:
                    partial_message_history.extend(_captured_message_history(
                        captured_messages[captured_start:],
                        sensitive_values,
                    ))
                    transient = exc.status_code in _TRANSIENT_HTTP_STATUS
                    if transient and attempt < _MAX_TRANSIENT_RETRIES - 1:
                        transport_errors.append(_trace_error(exc, sensitive_values))
                        logger.warning(
                            "LLM 瞬时错误 HTTP %s，第 %d 次退避 %.1fs 后重试",
                            exc.status_code, attempt + 1, delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    record_model_invocation(
                        invocation,
                        request=trace_request,
                        result=ModelTraceResult(
                            messageHistory=partial_message_history,
                            transportErrors=transport_errors,
                            error=_trace_error(exc, sensitive_values),
                        ),
                        usage=None,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        transport_attempts=attempt + 1,
                        http_send_attempts=provider_transport.http_send_attempts,
                        error_code=f"http_{exc.status_code}",
                        prompt_hash=prompt_hash,
                    )
                    raise
                except Exception as exc:
                    partial_message_history.extend(_captured_message_history(
                        captured_messages[captured_start:],
                        sensitive_values,
                    ))
                    record_model_invocation(
                        invocation,
                        request=trace_request,
                        result=ModelTraceResult(
                            messageHistory=partial_message_history,
                            transportErrors=transport_errors,
                            error=_trace_error(exc, sensitive_values),
                        ),
                        usage=None,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        transport_attempts=attempt + 1,
                        http_send_attempts=provider_transport.http_send_attempts,
                        error_code=type(exc).__name__,
                        prompt_hash=prompt_hash,
                    )
                    raise


async def bounded_gather(
    items: Sequence[ItemT],
    worker: Callable[[ItemT], Awaitable[ResultT]],
    *,
    limit: int,
) -> list[ResultT | Exception]:
    """并发对每个 item 执行 worker，最多 limit 个同时进行（真实 LLM 并发另由 run_agent 全局封顶）。

    返回列表与 items 顺序一一对应；单个 worker 抛出的异常就地返回（不中断其余、不外抛）。
    """
    semaphore = asyncio.Semaphore(limit)

    async def _run(item: ItemT) -> ResultT:
        async with semaphore:
            return await worker(item)

    return await asyncio.gather(*(_run(item) for item in items), return_exceptions=True)
