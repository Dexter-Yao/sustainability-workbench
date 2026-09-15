# ABOUTME: 私有对象 Storage transport 的回归测试，证明 materials 上传经 service-role HTTP 边界。
# ABOUTME: 本测试仅使用 MockTransport，不访问实际 Storage 或暴露 service key。
from __future__ import annotations

import httpx
import pytest

from sustainability_desk.material.intake.storage import MaterialStorageClient
from sustainability_desk.persistence.private_storage_transport import (
    PrivateStorageTransport,
    PrivateStorageTransportError,
)
from sustainability_desk.persistence.settings import PersistenceSettings


def _settings() -> PersistenceSettings:
    return PersistenceSettings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_service_key="test-service-role-key",
    )


@pytest.mark.asyncio
async def test_materials_use_private_service_role_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    materials = MaterialStorageClient(_settings(), client=client)

    await materials.upload("account/workspace/source.docx", b"material", "application/octet-stream")
    await client.aclose()

    assert [request.url.path.split("/")[4] for request in requests] == ["materials"]
    assert all(request.headers["authorization"] == "Bearer test-service-role-key" for request in requests)
    assert all(request.headers["apikey"] == "test-service-role-key" for request in requests)
    assert all(request.headers["x-upsert"] == "false" for request in requests)


@pytest.mark.asyncio
async def test_transport_exposes_http_classification_without_response_body_leakage() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, text="private detail"))
    )
    transport = PrivateStorageTransport(_settings(), client=client)

    with pytest.raises(PrivateStorageTransportError, match="HTTP 404") as error:
        await transport.read("exports", "missing.docx")
    await client.aclose()

    assert error.value.status_code == 404
