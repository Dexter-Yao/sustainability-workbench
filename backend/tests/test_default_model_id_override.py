# ABOUTME: 生成默认模型的环境覆盖合同——调用期解析、未注册即 fail-loud、不动导入期常量。
# ABOUTME: 本文件不调用外部模型；只校验取值口的行为与与常量的关系。
"""默认模型的环境覆盖。

自有部署名（`luna`）只存在于本项目的 Azure 资源上，换环境的人无法复现；若切换模型必须改
源码，则「克隆即可用」不成立。覆盖因此走环境变量。

两条性质本测试固化：

1. **调用期解析**。`DEFAULT_MODEL_ID` 是导入期事实（多个模块级常量与函数默认参数绑定它，
   eval 候选元组亦以它为首位），不能改成 env 读取；覆盖只经 `resolve_default_model_id()`。
2. **未注册即失败**。静默回落会让「我配了自己的模型」变成悄悄用了一个在对方环境里
   并不存在的部署名，失败现场离配置点很远。
"""

from __future__ import annotations

import pytest

from sustainability_desk.llm.model_registry import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_ID_ENV,
    REGISTRY,
    resolve_default_model_id,
)


def test_unset_env_falls_back_to_registry_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DEFAULT_MODEL_ID_ENV, raising=False)
    assert resolve_default_model_id() == DEFAULT_MODEL_ID


def test_blank_env_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """空串与只含空白不是「选了一个空模型」，按未设置处理。"""

    monkeypatch.setenv(DEFAULT_MODEL_ID_ENV, "   ")
    assert resolve_default_model_id() == DEFAULT_MODEL_ID


def test_registered_id_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一已注册条目都可作为默认；通用兼容条目是换环境者的主要入口。"""

    assert "openai-compatible" in REGISTRY
    monkeypatch.setenv(DEFAULT_MODEL_ID_ENV, "openai-compatible")
    assert resolve_default_model_id() == "openai-compatible"


def test_unregistered_id_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEFAULT_MODEL_ID_ENV, "gpt-5.6-luna")
    with pytest.raises(ValueError, match="不在模型注册表内"):
        resolve_default_model_id()


def test_resolution_happens_at_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一进程内先后两次调用应各自反映当时的环境，且常量本身不被改写。"""

    monkeypatch.setenv(DEFAULT_MODEL_ID_ENV, "openai-compatible")
    assert resolve_default_model_id() == "openai-compatible"
    monkeypatch.delenv(DEFAULT_MODEL_ID_ENV, raising=False)
    assert resolve_default_model_id() == DEFAULT_MODEL_ID
    assert DEFAULT_MODEL_ID == "luna"
