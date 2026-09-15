# ABOUTME: 请求关联测试——验证 FastAPI 生成或透传安全的 X-Request-ID。
# ABOUTME: 非法外部值不得进入日志和 Trace，响应必须返回最终关联 ID。
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sustainability_desk.request_context import RequestContextMiddleware, current_request_id


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {"requestId": current_request_id()}

    return TestClient(app)


def test_request_id_is_preserved() -> None:
    response = _client().get("/probe", headers={"X-Request-ID": "req-12345678"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-12345678"
    assert response.json()["requestId"] == "req-12345678"


def test_invalid_request_id_is_replaced() -> None:
    response = _client().get("/probe", headers={"X-Request-ID": "bad value with spaces"})
    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert request_id != "bad value with spaces"
    assert response.json()["requestId"] == request_id
