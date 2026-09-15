# ABOUTME: 浏览器与 CLI 共用的认证运行时配置端点合同测试。
# ABOUTME: 端点只发布公开 Auth 字段；未配置时必须 fail-closed，不能退回前端环境变量。
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from sustainability_desk.api.runtime_router import client_configuration
from sustainability_desk.persistence.settings import persistence_settings


def test_runtime_client_config_projects_only_public_auth_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sustainability_desk.api.runtime_router.persistence_settings",
        lambda: SimpleNamespace(
            public_client_configured=True,
            supabase_project="sustainability-desk-local",
            environment="development",
            public_supabase_url="https://auth.example.test/",
            public_supabase_anon_key="public-anon-key",
        ),
    )

    response = client_configuration()

    assert response.supabase_url == "https://auth.example.test"
    assert response.supabase_anon_key == "public-anon-key"
    assert response.environment == "development"
    assert response.supabase_project == "sustainability-desk-local"
    assert response.report_contract_version


def test_runtime_client_config_rejects_missing_public_auth_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sustainability_desk.api.runtime_router.persistence_settings",
        lambda: SimpleNamespace(
            public_client_configured=False,
            supabase_project="sustainability-desk-local",
        ),
    )

    with pytest.raises(HTTPException) as exc:
        client_configuration()

    assert exc.value.status_code == 503


def test_runtime_client_config_rejects_private_supabase_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sustainability_desk.api.runtime_router.persistence_settings",
        lambda: SimpleNamespace(
            public_client_configured=True,
            supabase_project="sustainability-desk-local",
            public_supabase_url="https://sustainability-desk-vpc.example.test",
        ),
    )

    with pytest.raises(HTTPException) as exc:
        client_configuration()

    assert exc.value.status_code == 503


def test_public_runtime_settings_remain_distinct_from_server_auth_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUSTAINABILITY_DESK_PUBLIC_SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUSTAINABILITY_DESK_PUBLIC_SUPABASE_ANON_KEY", "public-anon-key")
    monkeypatch.setenv("SUSTAINABILITY_DESK_SUPABASE_SERVICE_KEY", "server-only-key")
    persistence_settings.cache_clear()

    settings = persistence_settings()

    assert settings.public_client_configured
    assert settings.supabase_service_key == "server-only-key"
    persistence_settings.cache_clear()
