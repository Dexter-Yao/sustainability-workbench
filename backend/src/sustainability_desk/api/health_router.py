# ABOUTME: 进程存活与运行前置条件健康合同。
# ABOUTME: Readiness 仅在数据库、资料领域表和私有 Storage 配置同时就绪时通过。
# ABOUTME(en): Health contract for process liveness and runtime preconditions.
# ABOUTME(en): Readiness passes only when database, material domain tables and private Storage config are all ready.
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from sustainability_desk.persistence.settings import persistence_settings

router = APIRouter(prefix="/api/health", tags=["health"])


class LivenessProjection(BaseModel):
    """仅表示 FastAPI 进程能够处理请求。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class ReadinessComponents(BaseModel):
    """用户主链路依赖的最小运行前置条件。"""

    model_config = ConfigDict(extra="forbid")

    database: Literal["ready", "not_ready"]
    material_schema: Literal["ready", "not_ready"]
    storage_config: Literal["ready", "not_ready"]


class ReadinessProjection(BaseModel):
    """部署与负载均衡可直接消费的 fail-closed readiness。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    components: ReadinessComponents


@router.get("/live", response_model=LivenessProjection)
async def liveness() -> LivenessProjection:
    """进程存活探针；不声称数据库或资料链路可用。"""
    return LivenessProjection()


@router.get("/ready", response_model=ReadinessProjection)
async def readiness(request: Request) -> ReadinessProjection | JSONResponse:
    """检查数据库、资料领域表与 Storage 服务端配置。"""
    pool = getattr(request.app.state, "db_pool", None)
    database_ready = False
    material_schema_ready = False
    if pool is not None:
        try:
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    """
                    select
                      true as database_ready,
                      to_regclass('public.material_workspaces') as material_workspaces,
                      to_regclass('public.material_sources') as material_sources,
                      to_regclass('public.material_events') as material_events
                    """
                )
            database_ready = bool(row and row["database_ready"])
            material_schema_ready = bool(
                row
                and all(
                    row[name]
                    for name in (
                        "material_workspaces",
                        "material_sources",
                        "material_events",
                    )
                )
            )
        except Exception:
            database_ready = False
            material_schema_ready = False

    settings = persistence_settings()
    storage_ready = bool(settings.supabase_url and settings.supabase_service_key)
    ready = database_ready and material_schema_ready and storage_ready
    projection = ReadinessProjection(
        status="ready" if ready else "not_ready",
        components=ReadinessComponents(
            database="ready" if database_ready else "not_ready",
            material_schema="ready" if material_schema_ready else "not_ready",
            storage_config="ready" if storage_ready else "not_ready",
        ),
    )
    if ready:
        return projection
    return JSONResponse(status_code=503, content=projection.model_dump(mode="json"))
