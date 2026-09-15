# ABOUTME: API 层导出闸与诊断端点单测——有阻断 issue 时 /api/export fail-loud(422)；诊断端点与导出闸同一组合根。
# ABOUTME: 直接调端点函数（不经 HTTP/TestClient），避免 httpx 依赖；阻断路径在 render 前 raise，不触发 docx 渲染。
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from types import SimpleNamespace
from uuid import uuid4

from sustainability_desk.api.app import diagnose_report, export_report
from sustainability_desk.api.auth import AuthenticatedUser
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.models import Field, Report
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from knowledge_package_fixtures import SSE_PACKAGE


def _blocking_report() -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_registered_name": Field(
                key="company_registered_name",
                label="公司注册名",
                type="string",
                source="user_input",
                required=True,
                value="",
            )
        },
        sections=[],
    )


def _fake_pool(report_id, owner):
    class Pool:
        async def fetchrow(self, query, *_args):
            now = datetime.now(timezone.utc)
            if "from report_states" in query:
                return {
                    "report_id": report_id,
                    "state": StoredReportStateV4(version=4).model_dump(
                        mode="json",
                    ),
                    "state_seq": 1,
                    "contract_version": contract_version(SSE_PACKAGE),
                }
            if "from account_identities" not in query:
                return {
                    "id": report_id,
                    "title": "t",
                    "report_type": "lightweight",
                    "report_profile_id": "sse_zh_hans@1",
                    "data_classification": "customer",
                    "created_under_profile_id": "local_single_user@1",
                    "contract_version": contract_version(SSE_PACKAGE),
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
            return {
                "account_id": owner,
                "email": "export@example.edu.cn",
                "phone": None,
                "organization_name": None,
                "wechat_id": None,
                "status": "active",
                "registered_at": now,
                "last_active_at": now,
                "grant_id": uuid4(),
                "profile_id": "local_single_user@1",
                "starts_at": now,
                "ends_at": now + timedelta(days=30),
                "onboarding_seen": [],
            }

        async def fetchval(self, *_args):
            return 1

    return Pool()


async def test_export_rejects_blocking_report():
    """owner 报告有阻断级 issue 时导出 fail-loud：422 + 结构化 issues（D2）。"""
    report_id = uuid4()
    owner = uuid4()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=_fake_pool(report_id, owner)))
    )
    with pytest.raises(HTTPException) as exc:
        await export_report(
            _blocking_report(),
            request=request,
            user=AuthenticatedUser(subject=owner, email=None),
            report_id=report_id,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["issues"]
    assert exc.value.detail["blocking"] is True


async def test_diagnose_endpoint_matches_export_gate_composition():
    """诊断端点与导出闸同一组合根：同一报告，抽屉看到的阻断集与导出闸拦截的一致。"""
    report_id = uuid4()
    owner = uuid4()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_pool=_fake_pool(report_id, owner)))
    )
    result = await diagnose_report(
        _blocking_report(),
        request=request,
        user=AuthenticatedUser(subject=owner, email=None),
        report_id=report_id,
    )
    assert result.blocking
    assert any(
        i.fieldKey == "company_registered_name" for i in result.issues
    )
    # readiness 同样注入（stored_state / structured_input_context 已随组合根加载）。
    assert result.readiness is not None
