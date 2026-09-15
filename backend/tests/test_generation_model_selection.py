# ABOUTME: 生成模型选择的裁定合同——只接受当前环境可选的注册条目，judge 模型不可选。
# ABOUTME: 本文件不调用外部模型；只校验裁定逻辑与可选集合的构成。
"""模型选择裁定。

界面可以列出模型，但**能否使用由服务端裁定**：客户端按 id 请求，不自行解释可用性
（与 `ReportProfileOption` 同一原则）。

两条性质本测试固化：

1. **「已注册」不等于「可选」**。密钥缺失的条目点下去才失败，等于把配置错误推迟到
   生成现场；可选集合的判据必须与 `llm.client.build_model` 同源。
2. **judge 模型不可选**。换 judge 需重跑校准集，不是界面上一次点选能决定的事。
"""

from __future__ import annotations

import pytest

from sustainability_desk.llm.model_registry import (
    JUDGE_MODEL_IDS,
    REGISTRY,
    ModelSelectionError,
    Provider,
    get_spec,
    model_is_selectable,
    resolve_default_model_id,
    resolve_selected_model_id,
    selectable_generation_model_ids,
)

#: 通用兼容条目：只需一对密钥与端点即可启用，是换环境者的主要入口。
COMPAT = "openai-compatible"


@pytest.fixture(autouse=True)
def _clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """逐例清空全部模型凭据，避免本机 .env 让断言随环境漂移。"""

    for spec in REGISTRY.values():
        monkeypatch.delenv(spec.api_key_env, raising=False)
        if spec.azure_endpoint_env:
            monkeypatch.delenv(spec.azure_endpoint_env, raising=False)
    monkeypatch.delenv("SUSTAINABILITY_DESK_DEFAULT_MODEL_ID", raising=False)


def test_registered_but_unconfigured_model_is_not_selectable() -> None:
    assert selectable_generation_model_ids() == ()
    assert model_is_selectable(get_spec(COMPAT)) is False


def test_key_alone_enables_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    assert COMPAT in selectable_generation_model_ids()


def test_azure_needs_both_key_and_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据与 build_model 同源：Azure 缺端点即不可用，不能只看密钥。"""

    azure_ids = [
        model_id
        for model_id, spec in REGISTRY.items()
        if spec.provider is Provider.AZURE_OPENAI and model_id not in JUDGE_MODEL_IDS
    ]
    assert azure_ids, "注册表应至少有一个非 judge 的 Azure 生成模型"
    target = get_spec(azure_ids[0])

    monkeypatch.setenv(target.api_key_env, "k")
    assert model_is_selectable(target) is False
    monkeypatch.setenv(target.azure_endpoint_env or "", "https://example.invalid/")
    assert model_is_selectable(target) is True


def test_judge_models_are_never_selectable_for_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for judge_id in JUDGE_MODEL_IDS:
        spec = get_spec(judge_id)
        monkeypatch.setenv(spec.api_key_env, "k")
        if spec.azure_endpoint_env:
            monkeypatch.setenv(spec.azure_endpoint_env, "https://example.invalid/")
        assert judge_id not in selectable_generation_model_ids()


def test_omitted_request_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    monkeypatch.setenv("SUSTAINABILITY_DESK_DEFAULT_MODEL_ID", COMPAT)
    assert resolve_selected_model_id(None) == COMPAT


def test_selectable_request_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    assert resolve_selected_model_id(COMPAT) == COMPAT


def test_unconfigured_and_unregistered_requests_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ModelSelectionError, match="不可选"):
        resolve_selected_model_id(COMPAT)

    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    with pytest.raises(ModelSelectionError, match="不可选"):
        resolve_selected_model_id("gpt-5.6-luna")


def test_refusal_message_never_leaks_env_var_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """错误文案是用户可见投影：只含 id 与可选集合，不含密钥或端点变量名。"""

    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    with pytest.raises(ModelSelectionError) as raised:
        resolve_selected_model_id("terra")
    message = str(raised.value)
    for spec in REGISTRY.values():
        assert spec.api_key_env not in message
        if spec.azure_endpoint_env:
            assert spec.azure_endpoint_env not in message


def test_default_resolution_is_unaffected_by_selection_helpers() -> None:
    """默认取值仍只看环境变量与注册表默认，不因可选集合为空而改变。"""

    assert resolve_default_model_id() == "luna"
