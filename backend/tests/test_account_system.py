# ABOUTME: Account/Profile 的纯合同测试，验证单档权益、能力投影与测试账号注册表。
# ABOUTME: 数据库事务、跨 Account 所有权和审计权限由 persistence/API 集成测试覆盖。
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sustainability_desk.accounts.entitlement_profiles import load_entitlement_registry, require_profile
from sustainability_desk.contract.topic_registry import all_report_sections
from sustainability_desk.accounts.service import (
    AccountContext,
    report_capabilities,
)
from sustainability_desk.ops.bootstrap_internal_accounts import load_registry
from knowledge_package_fixtures import SSE_PACKAGE, SSE_REPORT_PROFILE_ID

ROOT = Path(__file__).resolve().parents[2]


def _context(profile_id: str, *, expired: bool = False) -> AccountContext:
    now = datetime.now(timezone.utc)
    return AccountContext(
        account_id=uuid4(),
        email="person@example.edu.cn",
        organization_name=None,
        status="active",
        registered_at=now,
        last_active_at=now,
        grant_id=uuid4(),
        profile_id=profile_id,
        starts_at=now - timedelta(days=31),
        ends_at=now - timedelta(days=1) if expired else now + timedelta(days=1),
        profile=require_profile(profile_id),
    )


def test_profiles_match_current_product_contract() -> None:
    registry = load_entitlement_registry()
    assert set(registry.profiles) == {"local_single_user@1"}
    profile = registry.profiles["local_single_user@1"]
    assert profile.active_report_limit == 20
    assert profile.section_regeneration_limit == 10


def test_expired_grant_keeps_manual_edit_but_loses_active_capabilities() -> None:
    capabilities = _context("local_single_user@1", expired=True).capabilities()
    assert capabilities["can_edit_existing"]
    assert not capabilities["can_create_report"]
    assert not capabilities["can_generate"]
    assert not capabilities["can_export_word"]


def test_report_capabilities_project_full_simplified_scope() -> None:
    capabilities = report_capabilities(
        _context("local_single_user@1"), created_under_profile_id="local_single_user@1", report_profile_id=SSE_REPORT_PROFILE_ID
    )
    assert capabilities["allowed_report_section_ids"] == [
        section.id for section in all_report_sections(SSE_PACKAGE)
    ]
    assert capabilities["material_agent_enabled"] is True
    assert capabilities["can_export_word"] is True
    assert capabilities["allowed_report_artifact_kinds"] == ["review", "word"]


def test_account_capabilities_expose_active_report_limit() -> None:
    capabilities = _context("local_single_user@1").capabilities()
    assert capabilities["active_report_limit"] == 20
    assert capabilities["can_create_report"]


def test_test_account_registry_declares_automated_and_manual_internal_identities() -> None:
    registry = load_registry(ROOT / "backend/data/test_accounts.yaml")
    assert len(registry.accounts) == 2
    internal, manual = registry.accounts
    assert internal.email == "internal-automation@example.com"
    assert internal.operator_permissions == (
        "internal_audit_reviewer",
    )
    assert internal.role == "internal_automation"
    assert internal.bootstrap_profile_id == "local_single_user@1"
    assert (manual.email, manual.role, manual.bootstrap_profile_id) == (
        "internal-manual@example.com", "internal_manual", "local_single_user@1"
    )
    assert manual.operator_permissions == ()


def test_data_classification_is_declared_not_derived_from_entitlement() -> None:
    """数据分类是「里面实际是什么数据」的事实断言，不由账号权益档位推导。

    内部账号代最终用户收集资料并在系统内建报是**正当路径**，此时报告主体是真实企业；
    若按账号档位推导分类，这类报告会被错标为 synthetic。
    故不得按账号档位拦截 customer 声明：操作者身份不决定报告承载什么数据。
    """
    from sustainability_desk.api.reports_router import CreateReportRequest

    field = CreateReportRequest.model_fields["data_classification"]
    # 漏声明时按真实客户处理：错标为客户只会让治理更严，反之会让客户数据落到宽松口径。
    assert field.default == "customer"
    assert CreateReportRequest(data_classification="synthetic").data_classification == (
        "synthetic"
    )
    # 内部档位同样可声明 customer——代客户操作不是违规，不设档位闸门。
    assert CreateReportRequest(data_classification="customer").data_classification == (
        "customer"
    )
