# ABOUTME: 记录一次逻辑模型调用实际进入 HTTP transport 前的发送尝试数。
# ABOUTME: 计数通过 ContextVar 绑定 run_agent，跨并发任务隔离且不拥有调用配额语义。
# ABOUTME(en): Records how many send attempts one logical model call made before entering the HTTP transport.
# ABOUTME(en): The counter binds to run_agent via a ContextVar, isolated across tasks, owning no call-quota semantics.
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx


@dataclass
class ProviderTransportObservation:
    """一次逻辑模型调用内实际进入 Provider HTTP 出口的计数。"""

    http_send_attempts: int = 0


_CURRENT_OBSERVATION: ContextVar[ProviderTransportObservation | None] = ContextVar(
    "sustainability_desk_provider_transport_observation",
    default=None,
)


@contextmanager
def observe_provider_transport() -> Iterator[ProviderTransportObservation]:
    """为当前异步上下文建立独立的 Provider transport 计数。"""

    observation = ProviderTransportObservation()
    token = _CURRENT_OBSERVATION.set(observation)
    try:
        yield observation
    finally:
        _CURRENT_OBSERVATION.reset(token)


async def record_provider_http_send(_request: httpx.Request) -> None:
    """HTTP request hook：预算预留成功后记录一次真实发送尝试。"""

    observation = _CURRENT_OBSERVATION.get()
    if observation is not None:
        observation.http_send_attempts += 1
