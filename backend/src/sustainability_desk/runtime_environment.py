# ABOUTME: 运行环境合同——集中声明环境、数据库项目名、发布版本和 AI 观测落盘位置。
# ABOUTME: 启动时执行防误连断言，非生产进程不得连接生产 Supabase 项目。
# ABOUTME(en): Runtime environment contract — declares environment, database project name, release version, trace root.
# ABOUTME(en): Asserts the boundary at startup: a non-production process must never connect to production Supabase.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[2]


class RuntimeEnvironment(BaseSettings):
    """进程级运行标识；不承载密钥。"""

    model_config = SettingsConfigDict(
        env_prefix="SUSTAINABILITY_DESK_",
        env_file=BACKEND / ".env",
        extra="ignore",
    )

    environment: Literal["local", "development", "production", "test"] = "local"
    supabase_project: str = ""
    release_id: str = "local"
    git_sha: str = "unknown"
    observability_root: Path | None = None



def assert_environment_boundary(
    runtime: RuntimeEnvironment,
    *,
    persistence_configured: bool,
    supabase_url: str = "",
) -> None:
    """在建立数据库连接前验证环境与 Supabase 项目的一致性。

    本机单用户模式只保留两条硬边界：local 只能连 loopback 的本机栈，
    production 必须显式声明项目名且不得连 loopback。项目名不绑定任何托管实例 id。
    """
    if not persistence_configured:
        return
    host = urlparse(supabase_url).hostname if supabase_url else None
    loopback = host in {"127.0.0.1", "::1", "localhost"}
    if runtime.environment == "production":
        if not runtime.supabase_project:
            raise RuntimeError("生产环境必须声明 SUSTAINABILITY_DESK_SUPABASE_PROJECT")
        if supabase_url and loopback:
            raise RuntimeError("生产环境不得连接 loopback Supabase")
        return
    if runtime.environment == "local":
        if runtime.supabase_project != "sustainability-desk-local":
            raise RuntimeError("本地环境必须连接 sustainability-desk-local")
        if not loopback:
            raise RuntimeError("本地环境只能连接 loopback Supabase")
        return

@lru_cache(maxsize=1)
def runtime_environment() -> RuntimeEnvironment:
    """读取并缓存当前进程运行环境。"""
    return RuntimeEnvironment()
