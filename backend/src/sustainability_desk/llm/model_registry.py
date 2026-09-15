# ABOUTME: 大模型注册表——provider × 模型的唯一事实来源；密钥与端点只存环境变量名，绝不存值。
# ABOUTME: 生成与 judge 默认走 Azure OpenAI（Responses API）；OpenAI 兼容端点登记为通用条目。新增模型 = 加一条 ModelSpec。
# ABOUTME(en): Model registry: the source of truth for provider x model; keys and endpoints kept as env var names only.
# ABOUTME(en): Generation and judge default to Azure OpenAI (Responses API); adding a model means adding one ModelSpec.
from __future__ import annotations

import os
from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator


class Provider(str, Enum):
    """模型供应方。"""

    AZURE_OPENAI = "azure_openai"        # Azure OpenAI 资源，走 Responses API
    OPENAI_COMPAT = "openai_compat"      # OpenAI 兼容的 Chat Completions 端点


class ModelSpec(BaseModel):
    """注册表中一个模型的事实与调用能力。

    语义各自独立：
    - vendor：服务商标识，观测投影按 OTel `gen_ai.provider.name` 取此值。显式声明而非从端点主机名反推——
      自建与代理端点的主机名与服务商无关，反推会给出错误标识。
    - thinking：该模型启用思考以提升输出质量。
    - reasoning_effort：推理力度；留空即用供应方默认。
    - tool_choice_required：模型是否支持 tool_choice=required。思考模式的 Qwen 不支持，置 False（改用 auto）。
    - native_structured_output：结构化输出走 json_schema(NativeOutput) 而非 function tool。
    - default_temperature：采样温度；思考/推理模型置 None（不传）。
    - api_surface：调用面。responses 只对 Azure OpenAI 开放；兼容端点只走 chat_completions。

    端点解析：Azure 从 `azure_endpoint_env` 读资源端点；兼容端点优先读 `base_url_env`，
    未配置时退回 `base_url` 字面量。二者至少有一个。模型名同理，`model_name_env` 优先于 `model_name`。
    取值一律在调用时解析而非导入时读取，注册表本身不持有任何值。
    """

    id: str
    provider: Provider
    model_name: str                          # 供应方侧的模型名或部署名
    model_name_env: str | None = None        # 模型名的环境变量名（优先于 model_name）
    vendor: str                              # 服务商标识（观测投影用），如 azure_openai / dashscope
    api_key_env: str                         # 仅环境变量名，绝不存值
    base_url: str | None = None              # OpenAI 兼容端点的默认地址
    base_url_env: str | None = None          # OpenAI 兼容端点地址的环境变量名（优先于 base_url）
    azure_endpoint_env: str | None = None    # Azure 资源端点的环境变量名
    api_version: str | None = None           # Azure API 版本
    thinking: bool = False
    reasoning_effort: str | None = None
    tool_choice_required: bool = True
    native_structured_output: bool = False
    default_temperature: float | None = None
    api_surface: Literal["chat_completions", "responses"] = "chat_completions"

    @model_validator(mode="after")
    def _check_provider_shape(self) -> ModelSpec:
        """按 provider 校验端点与调用面的搭配，错配在导入时即 fail-loud。"""
        if self.provider is Provider.AZURE_OPENAI:
            if self.api_surface != "responses":
                raise ValueError(f"模型 {self.id}：Azure OpenAI 只允许 responses 调用面")
            if not self.azure_endpoint_env:
                raise ValueError(f"模型 {self.id}：Azure OpenAI 必须声明 azure_endpoint_env")
            if self.base_url or self.base_url_env:
                raise ValueError(f"模型 {self.id}：Azure OpenAI 不使用 base_url")
        else:
            if self.api_surface != "chat_completions":
                raise ValueError(f"模型 {self.id}：兼容端点只允许 chat_completions 调用面")
            if not (self.base_url or self.base_url_env):
                raise ValueError(f"模型 {self.id}：兼容端点必须声明 base_url 或 base_url_env")
        return self

    def resolve_model_name(self) -> str:
        """解析供应方侧模型名：环境变量优先，未配置时用字面量默认值。"""
        if self.model_name_env:
            configured = os.environ.get(self.model_name_env, "").strip()
            if configured:
                return configured
        return self.model_name

    def resolve_base_url(self) -> str:
        """解析兼容端点地址：环境变量优先，未配置时用字面量默认值；都没有即 fail-loud。"""
        if self.base_url_env:
            configured = os.environ.get(self.base_url_env, "").strip()
            if configured:
                return configured
            if not self.base_url:
                raise ValueError(f"模型 {self.id} 的端点环境变量 {self.base_url_env} 未配置")
        if not self.base_url:
            raise ValueError(f"模型 {self.id} 未声明端点地址")
        return self.base_url


_DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# GPT-5.6 的 Responses API 需要 preview 版本；不复用旧 Chat Completions 的全局版本号。
_AZURE_RESPONSES_API_VERSION = "2025-03-01-preview"

REGISTRY: dict[str, ModelSpec] = {
    # 生成默认：Azure OpenAI 上的 gpt-5.6 luna 部署，推理模型，结构化输出走 json_schema。
    "luna": ModelSpec(
        id="luna", provider=Provider.AZURE_OPENAI, model_name="gpt-5.6-luna", vendor="azure_openai",
        api_key_env="AZURE_OPENAI_API_KEY", azure_endpoint_env="AZURE_OPENAI_ENDPOINT",
        api_version=_AZURE_RESPONSES_API_VERSION, api_surface="responses",
        thinking=True, native_structured_output=True,
    ),
    # judge 专用：Azure OpenAI 上的 gpt-5.6 terra 部署，与生成模型同资源、异部署。
    "terra": ModelSpec(
        id="terra", provider=Provider.AZURE_OPENAI, model_name="gpt-5.6-terra", vendor="azure_openai",
        api_key_env="AZURE_OPENAI_API_KEY", azure_endpoint_env="AZURE_OPENAI_ENDPOINT",
        api_version=_AZURE_RESPONSES_API_VERSION, api_surface="responses",
        thinking=True, native_structured_output=True,
    ),
    # 通用兼容端点：地址与密钥都从环境变量读，任何 OpenAI 兼容服务（自建 vLLM / Ollama / 代理网关 / 其他厂商）
    # 都可经此条目接入，模型名同样由环境变量指定，无需改代码。
    "openai-compatible": ModelSpec(
        id="openai-compatible", provider=Provider.OPENAI_COMPAT,
        model_name="gpt-4o-mini", model_name_env="OPENAI_COMPAT_MODEL_NAME",
        vendor="openai_compat",
        api_key_env="OPENAI_COMPAT_API_KEY", base_url_env="OPENAI_COMPAT_BASE_URL",
        base_url="https://api.openai.com/v1",
    ),
    # 生成候选：DashScope 兼容接口，均默认开启思考。Qwen 思考模式需 tool_choice=auto。
    "qwen3.7-max": ModelSpec(
        id="qwen3.7-max", provider=Provider.OPENAI_COMPAT, model_name="qwen3.7-max", vendor="dashscope",
        api_key_env="DASHSCOPE_API_KEY", base_url=_DASHSCOPE, base_url_env="DASHSCOPE_BASE_URL",
        thinking=True, tool_choice_required=False,
    ),
    "qwen3.7-plus": ModelSpec(
        id="qwen3.7-plus", provider=Provider.OPENAI_COMPAT, model_name="qwen3.7-plus", vendor="dashscope",
        api_key_env="DASHSCOPE_API_KEY", base_url=_DASHSCOPE, base_url_env="DASHSCOPE_BASE_URL",
        thinking=True, tool_choice_required=False,
    ),
    "qwen3.6-flash": ModelSpec(
        id="qwen3.6-flash", provider=Provider.OPENAI_COMPAT, model_name="qwen3.6-flash", vendor="dashscope",
        api_key_env="DASHSCOPE_API_KEY", base_url=_DASHSCOPE, base_url_env="DASHSCOPE_BASE_URL",
        thinking=True, tool_choice_required=False,
    ),
    "glm-5.2": ModelSpec(
        id="glm-5.2", provider=Provider.OPENAI_COMPAT, model_name="glm-5.2", vendor="dashscope",
        api_key_env="DASHSCOPE_API_KEY", base_url=_DASHSCOPE, base_url_env="DASHSCOPE_BASE_URL", thinking=True,
    ),
    "kimi-k2.7-code": ModelSpec(
        id="kimi-k2.7-code", provider=Provider.OPENAI_COMPAT, model_name="kimi-k2.7-code", vendor="dashscope",
        api_key_env="DASHSCOPE_API_KEY", base_url=_DASHSCOPE, base_url_env="DASHSCOPE_BASE_URL", thinking=True,
    ),
    # 其他常见服务商的兼容端点：默认地址已登记，配好对应密钥即可用。
    "deepseek-chat": ModelSpec(
        id="deepseek-chat", provider=Provider.OPENAI_COMPAT, model_name="deepseek-chat", vendor="deepseek",
        api_key_env="DEEPSEEK_API_KEY", base_url="https://api.deepseek.com/v1",
        base_url_env="DEEPSEEK_BASE_URL",
    ),
    "moonshot-kimi-k2": ModelSpec(
        id="moonshot-kimi-k2", provider=Provider.OPENAI_COMPAT, model_name="kimi-k2-0905-preview",
        vendor="moonshot", api_key_env="MOONSHOT_API_KEY", base_url="https://api.moonshot.cn/v1",
        base_url_env="MOONSHOT_BASE_URL",
    ),
    "zhipu-glm-4.6": ModelSpec(
        id="zhipu-glm-4.6", provider=Provider.OPENAI_COMPAT, model_name="glm-4.6", vendor="zhipu",
        api_key_env="ZHIPU_API_KEY", base_url="https://open.bigmodel.cn/api/paas/v4",
        base_url_env="ZHIPU_BASE_URL",
    ),
}

# judge 模型（评测）：换 judge 后校准集须重跑，不能只改常量。
JUDGE_MODEL_IDS: tuple[str, ...] = ("terra",)
JUDGE_MODEL_ID = "terra"
# 生成默认：产品运行时、资料 agent、图像 agent 与实验 CLI 共用此值，可经调用方显式覆盖。
# 本常量是**导入期**事实：5 个模块级常量与 20 余个函数默认参数在导入时绑定它，
# eval 的候选元组与 test_model_registry 也按它断言 Azure luna 部署。故它保持字面量，
# 环境覆盖走下面的 resolve_default_model_id()——在调用期解析，与 ModelSpec.resolve_* 同一纪律。
DEFAULT_MODEL_ID = "luna"

#: 生成默认模型的环境覆盖。自有部署名（luna/terra）只存在于本项目的 Azure 资源上，
#: 换环境的人无法复现，故必须能不改源码就切到自己的模型。
DEFAULT_MODEL_ID_ENV = "SUSTAINABILITY_DESK_DEFAULT_MODEL_ID"


def resolve_default_model_id() -> str:
    """解析本次运行的生成默认模型；未设环境变量即用注册表默认。

    在**调用期**读取环境变量，不在导入期：注册表不持有任何取值，
    且导入期读取会让同一进程内的覆盖时机变得不可预期。

    未注册的 id 立即 fail-loud——静默回落到 luna 会让「我明明配了自己的模型」
    变成一次悄悄用了别人部署名的调用，而那个部署在对方环境里根本不存在。
    """

    configured = os.environ.get(DEFAULT_MODEL_ID_ENV, "").strip()
    if not configured:
        return DEFAULT_MODEL_ID
    if configured not in REGISTRY:
        raise ValueError(
            f"{DEFAULT_MODEL_ID_ENV}={configured!r} 不在模型注册表内；"
            f"可用: {sorted(REGISTRY)}"
        )
    return configured


class ModelSelectionError(ValueError):
    """请求指定的生成模型在当前环境不可用。"""


def resolve_selected_model_id(requested: str | None) -> str:
    """裁定本次生成实际使用的模型 id。

    省略即用当前默认（环境变量或注册表默认）。给出时必须落在
    `selectable_generation_model_ids()` 内——仅「已注册」不够：密钥缺失的条目
    点下去才失败，那等于把配置错误推迟到生成现场。

    错误消息只含 id 与可选集合，不含密钥或端点的环境变量名。
    """

    if requested is None:
        return resolve_default_model_id()
    selectable = selectable_generation_model_ids()
    if requested not in selectable:
        raise ModelSelectionError(
            f"生成模型 {requested!r} 在当前环境不可选；可选: {list(selectable)}"
        )
    return requested


def model_is_selectable(spec: ModelSpec) -> bool:
    """判断该模型在当前环境是否真的可用（凭据齐备）。

    判据与 `llm.client.build_model` 完全一致：密钥必配，Azure 另需资源端点。
    二者若分裂，界面会列出一个点下去才失败的选项。

    只返回布尔值——环境变量名是服务端事实，不进任何用户可见投影。
    """

    if not os.environ.get(spec.api_key_env, "").strip():
        return False
    if spec.provider is Provider.AZURE_OPENAI:
        return bool(os.environ.get(spec.azure_endpoint_env or "", "").strip())
    return True


def selectable_generation_model_ids() -> tuple[str, ...]:
    """当前环境可选作生成模型的已注册 id，按注册表声明顺序。

    judge 专用模型不在其中：换 judge 需重跑校准集（见 JUDGE_MODEL_ID 注释），
    不是界面上一次点选可以决定的事。
    """

    return tuple(
        model_id
        for model_id, spec in REGISTRY.items()
        if model_id not in JUDGE_MODEL_IDS and model_is_selectable(spec)
    )


def get_spec(model_id: str) -> ModelSpec:
    """按 id 取 ModelSpec；未注册即 fail-loud。"""
    if model_id not in REGISTRY:
        raise ValueError(f"未注册模型: {model_id!r}；可用: {sorted(REGISTRY)}")
    return REGISTRY[model_id]
