# ABOUTME: 浏览器与本地 CLI 共同读取的公开运行时配置投影。
# ABOUTME: 只发布 Auth URL、anon key 与环境标识；服务端连接串、JWT secret、service key 永不进入响应。
# ABOUTME(en): Public runtime configuration projection read by both the browser and the local CLI.
# ABOUTME(en): Publishes only auth URL, anon key and environment; connection strings and secrets never appear.
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    default_report_profile_id,
    knowledge_package_for_profile,
)
from sustainability_desk.persistence.settings import persistence_settings

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


class ClientRuntimeConfiguration(BaseModel):
    """由当前 API release 公开的浏览器／CLI 认证配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: str = Field(min_length=1, max_length=40)
    supabase_project: str = Field(min_length=1, max_length=100)
    supabase_url: str = Field(pattern=r"^https?://")
    supabase_anon_key: str = Field(min_length=1)
    report_contract_version: str = Field(min_length=1)


@router.get("/client-config", response_model=ClientRuntimeConfiguration)
def client_configuration() -> ClientRuntimeConfiguration:
    settings = persistence_settings()
    if not settings.public_client_configured or not settings.supabase_project:
        raise HTTPException(status_code=503, detail="浏览器认证配置未完成")
    if "-vpc." in settings.public_supabase_url:
        raise HTTPException(status_code=503, detail="浏览器认证地址不能使用私网 Supabase 端点")
    return ClientRuntimeConfiguration(
        environment=settings.environment,
        supabase_project=settings.supabase_project,
        supabase_url=settings.public_supabase_url.rstrip("/"),
        supabase_anon_key=settings.public_supabase_anon_key,
        report_contract_version=contract_version(
            knowledge_package_for_profile(default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE))
        ),
    )
