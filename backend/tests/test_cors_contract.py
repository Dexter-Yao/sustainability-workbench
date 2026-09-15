# ABOUTME: 本地前后端跨域合同测试，确保项目声明的两个回环入口均能通过浏览器预检。
# ABOUTME: 公网 origin 不属于开发 CORS 白名单，生产继续依赖 Nginx 同源代理。
import pytest
from fastapi.testclient import TestClient

from sustainability_desk.api.app import app


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
def test_local_frontend_origins_pass_cors_preflight(origin: str) -> None:
    response = TestClient(app).options(
        "/api/account",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_is_not_allowed() -> None:
    response = TestClient(app).options(
        "/api/account",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
