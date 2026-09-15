# ABOUTME: report-bound 评分模板路由测试，确保模板必须绑定 Report 身份与权威状态。
# ABOUTME: xlsx 生成和往返由资产层测试覆盖；此处锁定认证边界与旧路由退役。

import httpx
import pytest

from sustainability_desk.api.app import app


@pytest.mark.anyio
async def test_report_bound_assessment_template_requires_login():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/reports/00000000-0000-0000-0000-000000000001/"
            "structured-inputs/assessment/template",
        )

    assert response.status_code == 503 or response.status_code == 401


@pytest.mark.anyio
async def test_retired_unbound_assessment_template_is_not_exposed():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/assessment/template")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_quantitative_metric_summary_image_requires_login():
    """派生指标图端点不得匿名可达（无 Authorization 头必须 401/503，不得进入渲染）。"""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/visualizations/quantitative-metric-summary",
            json={
                "report": {"title": "t", "fields": {}, "sections": []},
                "spec": {"kind": "quantitative_metric_summary", "metricKeys": []},
            },
        )

    assert response.status_code == 503 or response.status_code == 401


@pytest.mark.anyio
async def test_assessment_matrix_image_requires_login():
    """双重重要性矩阵图端点不得匿名可达（无 Authorization 头必须 401/503，不得进入渲染）。"""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/assessment/matrix",
            json={"reportingYear": 2025, "topics": []},
        )

    assert response.status_code == 503 or response.status_code == 401
