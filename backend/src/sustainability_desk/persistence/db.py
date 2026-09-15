# ABOUTME: asyncpg 连接池生命周期与 FastAPI 依赖——池挂在 app.state，持久化未配置时依赖返回 503。
# ABOUTME: jsonb 编解码统一在池初始化处声明（parse at boundary），业务代码不各自 json.dumps。
# ABOUTME(en): asyncpg pool lifecycle and FastAPI dependency — pool lives on app.state; unconfigured yields 503.
# ABOUTME(en): jsonb codecs are declared once at pool init (parse at boundary); business code never json.dumps.
from __future__ import annotations

import json

import asyncpg
from fastapi import HTTPException, Request

from sustainability_desk.persistence.settings import PersistenceSettings


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool(settings: PersistenceSettings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10,
        init=_init_connection,
    )


def get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="持久化服务未配置")
    return pool
