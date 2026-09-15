# ABOUTME: 重要性 API 所有权测试，保证目录、当前值和写入只保留 report-bound 单一语义。
# ABOUTME: 旧的 query-param scope/resolve 入口必须消失，避免客户端继续拥有适用性副本。
from sustainability_desk.api.app import app


def test_assessment_api_has_one_report_bound_owner() -> None:
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.update(
                nested.path
                for nested in original_router.routes
                if hasattr(nested, "path")
            )

    assert "/api/reports/{report_id}/structured-inputs/assessment" in paths
    assert (
        "/api/reports/{report_id}/structured-inputs/assessment/template"
        in paths
    )
    assert (
        "/api/reports/{report_id}/structured-inputs/assessment/import"
        in paths
    )
    assert "/api/assessment/scope" not in paths
    assert "/api/assessment/resolve" not in paths
    assert "/api/assessment/template" not in paths
    assert "/api/assessment/parse" not in paths
