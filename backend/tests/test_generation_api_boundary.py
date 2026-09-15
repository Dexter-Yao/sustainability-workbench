# ABOUTME: 在线生成 API 边界测试——公开入口只保留服务端原子整节生成。
# ABOUTME: 单块、整表、单行与全文生成端点均不得重新进入产品 API。
from sustainability_desk.api.app import app


def test_only_section_generation_is_public() -> None:
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/reports/{report_id}/sections/{section_key}/generations" in paths
    assert "/api/generate" not in paths
    assert "/api/generate-all" not in paths
    assert "/api/table/generate" not in paths
    assert "/api/table/regenerate-row" not in paths
