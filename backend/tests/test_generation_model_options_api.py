# ABOUTME: 生成模型清单端点的响应合同——只列凭据齐备者，且不泄漏部署名、端点与变量名。
# ABOUTME: 不调用外部模型；只断言投影形态与边界。
"""生成模型清单端点。

界面据此渲染选择器，因此这份投影同时是**用户可见边界**：部署名（如某资源上的具体
部署）、端点地址与密钥环境变量名都是服务端事实，泄漏它们既无助于选择，也把基础设施
拓扑写进了客户端。

另一条：清单只列凭据齐备者。列出一个点下去才失败的选项，等于把配置错误推迟到生成现场。

注意 `llm.client` 在 import 时 `load_dotenv(backend/.env)`，故清空凭据必须在 import 之后
做（本机 .env 有真实密钥时否则会让断言随环境漂移）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sustainability_desk.api.app import app
from sustainability_desk.llm.model_registry import REGISTRY, JUDGE_MODEL_IDS

ENDPOINT = "/api/reports/generation-models"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_model_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """逐例清空全部模型凭据，使断言不依赖本机 .env。"""

    for spec in REGISTRY.values():
        monkeypatch.delenv(spec.api_key_env, raising=False)
        if spec.azure_endpoint_env:
            monkeypatch.delenv(spec.azure_endpoint_env, raising=False)
    monkeypatch.delenv("SUSTAINABILITY_DESK_DEFAULT_MODEL_ID", raising=False)


def test_no_credentials_yields_empty_list(client: TestClient) -> None:
    """一个模型都没配时清单为空——不假装 luna 可用。"""

    body = client.get(ENDPOINT).json()
    assert body["models"] == []
    assert body["default_model_id"] == "luna"


def test_configured_model_appears_with_id_and_vendor_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    body = client.get(ENDPOINT).json()
    assert body["models"] == [
        {"model_id": "openai-compatible", "vendor": "openai_compat"}
    ]


def test_judge_model_never_offered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """judge 换了要重跑校准集，不是界面上一次点选能决定的事。"""

    for judge_id in JUDGE_MODEL_IDS:
        spec = REGISTRY[judge_id]
        monkeypatch.setenv(spec.api_key_env, "k")
        if spec.azure_endpoint_env:
            monkeypatch.setenv(spec.azure_endpoint_env, "https://example.invalid/")
    offered = {item["model_id"] for item in client.get(ENDPOINT).json()["models"]}
    assert offered.isdisjoint(set(JUDGE_MODEL_IDS))


def test_response_carries_only_id_and_vendor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每个选项只有 id 与 vendor 两个键，且 id 必须是注册表键本身。

    这里断言**解析后的取值**而非原文子串：注册表存在 id 与部署名互为子串的条目
    （`zhipu-glm-4.6` 对 `glm-4.6`），子串扫描会把「正当暴露的 id」误判成泄漏。
    形态收紧到只有两个键，部署名就没有落脚处。
    """

    for spec in REGISTRY.values():
        monkeypatch.setenv(spec.api_key_env, "k")
        if spec.azure_endpoint_env:
            monkeypatch.setenv(spec.azure_endpoint_env, "https://example.invalid/")

    models = client.get(ENDPOINT).json()["models"]
    assert models, "配齐凭据后应至少有一个可选模型"
    for option in models:
        assert set(option) == {"model_id", "vendor"}
        assert option["model_id"] in REGISTRY
        assert option["vendor"] == REGISTRY[option["model_id"]].vendor


def test_response_never_leaks_env_var_names_or_endpoints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """密钥/端点的环境变量名与端点地址在任何形态下都不得出现。"""

    for spec in REGISTRY.values():
        monkeypatch.setenv(spec.api_key_env, "k")
        if spec.azure_endpoint_env:
            monkeypatch.setenv(spec.azure_endpoint_env, "https://example.invalid/")

    raw = client.get(ENDPOINT).text

    for spec in REGISTRY.values():
        assert spec.api_key_env not in raw
        assert (spec.azure_endpoint_env or "@absent@") not in raw
        assert (spec.base_url_env or "@absent@") not in raw
        assert (spec.base_url or "@absent@") not in raw
