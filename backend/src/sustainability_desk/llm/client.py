# ABOUTME: 构造 Pydantic AI 模型与 Agent 的唯一工厂——生成与评测共用；按注册表把模型接到 Azure OpenAI 或任一 OpenAI 兼容端点。
# ABOUTME: 密钥与模型端点从 backend/.env 读取（已 gitignore）；绝不打印或硬编码密钥值。
# ABOUTME(en): The sole factory for Pydantic AI models and Agents, shared by generation and eval; wires per the registry
# ABOUTME(en): to Azure OpenAI or any OpenAI-compatible endpoint. Keys come from backend/.env, never printed or stored.
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models import Model
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID, ModelSpec, Provider, get_spec
from sustainability_desk.llm.provider_transport import record_provider_http_send

logger = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND / ".env")

# 显式请求超时：连接 10s、整体 300s（够单次生成含推理，不依赖 SDK 默认值）。
_HTTP_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
# 连接池上限须高于全局并发（MAX_INFLIGHT_LLM_CALLS=100），否则默认 100 连接会成为瓶颈。
_HTTP_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)


def provider_http_client() -> httpx.AsyncClient:
    """构造所有模型 Provider 共用的 HTTP 出口并记录实际发送。"""
    return httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        limits=_HTTP_LIMITS,
        event_hooks={"request": [record_provider_http_send]},
    )

OutputT = TypeVar("OutputT")
DepsT = TypeVar("DepsT")


def _profile(spec: ModelSpec) -> OpenAIModelProfile | None:
    """思考模式的 Qwen 不支持 tool_choice=required，改用 auto；其余用自动探测的默认 profile。"""
    if spec.tool_choice_required:
        return None
    return OpenAIModelProfile(openai_supports_tool_choice_required=False)


@lru_cache(maxsize=None)
def build_model(model_id: str = DEFAULT_MODEL_ID) -> Model:
    """按模型 id 构造 Pydantic AI 模型；每 id 一个实例（复用底层 HTTP 客户端），并发与评测共享。"""
    spec = get_spec(model_id)
    api_key = os.environ.get(spec.api_key_env)
    if not api_key:
        raise ValueError(f"模型 {spec.id} 的密钥环境变量 {spec.api_key_env} 未配置")
    model_name = spec.resolve_model_name()
    if spec.provider is Provider.AZURE_OPENAI:
        endpoint = os.environ.get(spec.azure_endpoint_env or "")
        if not endpoint:
            raise ValueError(f"模型 {spec.id} 的端点环境变量 {spec.azure_endpoint_env} 未配置")
        logger.info("模型 %s → Azure OpenAI 部署 %s", model_id, model_name)
        return OpenAIResponsesModel(
            model_name,
            provider=AzureProvider(
                azure_endpoint=endpoint, api_version=spec.api_version, api_key=api_key,
                http_client=provider_http_client(),
            ),
            profile=_profile(spec),
        )
    base_url = spec.resolve_base_url()
    logger.info("模型 %s → %s @ %s", model_id, model_name, base_url)
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=base_url, api_key=api_key,
            http_client=provider_http_client(),
        ),
        profile=_profile(spec),
    )


def _model_settings(spec: ModelSpec) -> OpenAIChatModelSettings | None:
    """据注册表装配模型设置：推理力度与采样温度；Responses 调用面用其专属设置类。"""
    kwargs: dict = {}
    if spec.reasoning_effort:
        kwargs["openai_reasoning_effort"] = spec.reasoning_effort
    if spec.default_temperature is not None:
        kwargs["temperature"] = spec.default_temperature
    if not kwargs:
        return None
    settings_cls = OpenAIResponsesModelSettings if spec.api_surface == "responses" else OpenAIChatModelSettings
    return settings_cls(**kwargs)


def build_agent(
    model_id: str = DEFAULT_MODEL_ID,
    *,
    output_type: type[OutputT],
    instructions: str,
    retries: int = 2,
    deps_type: type[DepsT] = object,
) -> Agent[DepsT, OutputT]:
    """按模型 id 与结构化输出类型装配 Agent。

    native_structured_output 的模型走 json_schema(NativeOutput)；其余走默认 ToolOutput。
    """
    spec = get_spec(model_id)
    model_name = spec.resolve_model_name()
    structured = NativeOutput(output_type) if spec.native_structured_output else output_type
    settings = _model_settings(spec)
    agent = Agent(
        build_model(model_id),
        output_type=structured,
        deps_type=deps_type,
        instructions=instructions,
        retries=retries,
        model_settings=settings,
    )
    setattr(
        agent,
        "_sustainability_desk_observability_context",
        {
            "modelId": spec.id,
            "modelName": model_name,
            "instructions": instructions,
            "modelSettings": settings if settings is not None else {},
            "outputSchema": TypeAdapter(output_type).json_schema(),
        },
    )
    return agent
