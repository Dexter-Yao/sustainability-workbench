# ABOUTME: 模型注册表契约测试，防止评估默认模型与项目运行模型发生漂移。
# ABOUTME: 本文件不调用外部模型；只校验 SSOT 常量、端点解析与 fail-loud 行为。
import pytest
from pydantic import ValidationError

from sustainability_desk.llm.model_registry import (
    DEFAULT_MODEL_ID,
    JUDGE_MODEL_ID,
    JUDGE_MODEL_IDS,
    REGISTRY,
    ModelSpec,
    Provider,
    get_spec,
)


def test_judge_defaults_use_azure_terra_only() -> None:
    assert JUDGE_MODEL_ID == "terra"
    assert JUDGE_MODEL_IDS == ("terra",)
    spec = get_spec(JUDGE_MODEL_ID)
    assert spec.provider is Provider.AZURE_OPENAI
    assert spec.model_name == "gpt-5.6-terra"
    assert spec.api_surface == "responses"


def test_generation_default_is_azure_luna_on_responses_api() -> None:
    spec = get_spec(DEFAULT_MODEL_ID)
    assert spec.provider is Provider.AZURE_OPENAI
    assert spec.model_name == "gpt-5.6-luna"
    assert spec.api_surface == "responses"
    assert spec.azure_endpoint_env == "AZURE_OPENAI_ENDPOINT"
    assert spec.api_version


def test_judge_and_generation_share_one_azure_resource() -> None:
    """judge 与生成是同资源异部署：密钥与端点环境变量一致，部署名不同。"""
    judge, generation = get_spec(JUDGE_MODEL_ID), get_spec(DEFAULT_MODEL_ID)
    assert judge.api_key_env == generation.api_key_env
    assert judge.azure_endpoint_env == generation.azure_endpoint_env
    assert judge.model_name != generation.model_name


def test_registry_keeps_secrets_out_and_pins_surface_per_provider() -> None:
    for spec in REGISTRY.values():
        assert spec.api_key_env.isupper()
        assert spec.vendor and spec.vendor.islower()
        if spec.provider is Provider.AZURE_OPENAI:
            assert spec.base_url is None and spec.base_url_env is None
            assert spec.api_surface == "responses" and spec.azure_endpoint_env
        else:
            assert (spec.base_url or spec.base_url_env) and spec.api_surface == "chat_completions"
    with pytest.raises(ValueError, match="未注册模型"):
        get_spec("gpt-5.6-luna")


def test_provider_shape_mismatches_fail_loud_at_construction() -> None:
    """provider 与端点/调用面错配在构造时即报错，不留到调用现场。"""
    with pytest.raises(ValidationError, match="只允许 responses"):
        ModelSpec(
            id="bad", provider=Provider.AZURE_OPENAI, model_name="m", vendor="azure_openai",
            api_key_env="K", azure_endpoint_env="E",
        )
    with pytest.raises(ValidationError, match="必须声明 base_url"):
        ModelSpec(id="bad", provider=Provider.OPENAI_COMPAT, model_name="m", vendor="v", api_key_env="K")


def test_generic_compatible_entry_reads_endpoint_and_model_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通用兼容条目让任意 OpenAI 兼容服务无需改代码即可接入。"""
    spec = get_spec("openai-compatible")
    assert spec.resolve_base_url() == "https://api.openai.com/v1"
    assert spec.resolve_model_name() == "gpt-4o-mini"

    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("OPENAI_COMPAT_MODEL_NAME", "qwen3:8b")
    assert spec.resolve_base_url() == "http://127.0.0.1:11434/v1"
    assert spec.resolve_model_name() == "qwen3:8b"


def test_registered_vendor_endpoints_override_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """已登记服务商同样可改端点，用于代理网关或私有部署。"""
    spec = get_spec("qwen3.7-plus")
    assert "dashscope.aliyuncs.com" in spec.resolve_base_url()
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://gateway.internal/v1")
    assert spec.resolve_base_url() == "https://gateway.internal/v1"


def test_pdf_vision_uses_the_general_generation_model_registry() -> None:
    assert "qwen3.5-ocr" not in REGISTRY
    assert get_spec("qwen3.7-plus").api_surface == "chat_completions"
