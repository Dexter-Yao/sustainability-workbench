# ABOUTME: 服务健康端点合同测试，区分进程存活与资料运行前置条件。
# ABOUTME: Readiness 必须 fail-closed，不得用 FastAPI 文档页代替数据库与资料表检查。
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from sustainability_desk.api.app import app


class _ReadyConnection:
    async def fetchrow(self, _query: str) -> dict[str, object]:
        return {
            "database_ready": True,
            "material_workspaces": "material_workspaces",
            "material_sources": "material_sources",
            "material_events": "material_events",
        }


class _NotReadyConnection(_ReadyConnection):
    async def fetchrow(self, _query: str) -> dict[str, object]:
        row = await super().fetchrow(_query)
        row["material_sources"] = None
        return row


class _Pool:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_liveness_only_proves_process_is_serving() -> None:
    app.state.db_pool = None
    response = TestClient(app).get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_requires_database_material_tables_and_storage_config(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sustainability_desk.api.health_router.persistence_settings",
        lambda: type(
            "_Settings",
            (),
            {"supabase_url": "https://example.invalid", "supabase_service_key": "secret"},
        )(),
    )
    app.state.db_pool = _Pool(_ReadyConnection())
    response = TestClient(app).get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {
            "database": "ready",
            "material_schema": "ready",
            "storage_config": "ready",
        },
    }


def test_readiness_fails_closed_when_material_schema_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "sustainability_desk.api.health_router.persistence_settings",
        lambda: type(
            "_Settings",
            (),
            {"supabase_url": "https://example.invalid", "supabase_service_key": "secret"},
        )(),
    )
    app.state.db_pool = _Pool(_NotReadyConnection())
    response = TestClient(app).get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["material_schema"] == "not_ready"
