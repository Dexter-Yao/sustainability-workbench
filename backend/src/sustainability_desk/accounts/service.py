# ABOUTME: Account、认证身份、当前 Grant 与版本化 Profile 的唯一能力投影服务。
# ABOUTME: 缺映射、缺 Grant、过期或未知 Profile 均 fail-closed；报告服务不得自行解释权益。
# ABOUTME(en): Only capability-projection service over Account, auth identity, current Grant and versioned Profile.
# ABOUTME(en): Missing mapping or Grant, expiry and unknown Profile fail closed; report services never read grants.
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from sustainability_desk.accounts.entitlement_profiles import EntitlementProfile, require_profile
from sustainability_desk.accounts.report_execution_scope import execution_scope_for_profile
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    ReportType,
    default_report_profile_id,
    knowledge_package_for_profile,
)
from sustainability_desk.contract.topic_registry import all_report_sections

PRIMARY_IDENTITY_ISSUER = "primary"
INTERNAL_AUDIT_REVIEWER_PERMISSION = "internal_audit_reviewer"


class AccountNotFoundError(Exception):
    """认证主体尚未映射到产品 Account。"""


class AccountEntitlementError(Exception):
    """Account 没有可判定的当前权益。"""


class CapabilityDeniedError(Exception):
    """请求超出当前 Account 能力。

    消息即用户文案：API 边界直接把它作为错误响应的 message 呈现，因此只能写面向用户的
    中文句子。需要携带 account_id、profile_id 等排查上下文时，加独立属性并由边界写日志，
    不要拼进消息（见 `docs/schema-contract.md` 的错误响应契约）。
    """


@dataclass(frozen=True)
class AccountContext:
    account_id: UUID
    email: str | None
    organization_name: str | None
    status: str
    registered_at: datetime
    last_active_at: datetime
    grant_id: UUID
    profile_id: str
    starts_at: datetime
    ends_at: datetime | None
    profile: EntitlementProfile
    # 首次引导 coach mark 的已读步骤集（design.md §6.1）；只影响界面提示，不参与能力裁决。
    onboarding_seen: tuple[str, ...] = ()

    @property
    def expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.ends_at is not None and self.ends_at <= now

    @property
    def active(self) -> bool:
        return (
            self.status == "active"
            and self.starts_at <= datetime.now(timezone.utc)
            and not self.expired
        )

    def capabilities(self) -> dict[str, object]:
        active = self.active
        grant_started = self.starts_at <= datetime.now(timezone.utc)
        # Account-level capabilities have no report yet: they describe the package a new report
        # would be created on by default.
        scope = execution_scope_for_profile(
            self.profile_id,
            knowledge_package=knowledge_package_for_profile(
                default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE)
            ),
        )
        return {
            "allowed_report_section_ids": [
                section.id for section in all_report_sections(scope.knowledge_package)
            ],
            "section_regeneration_limit": self.profile.section_regeneration_limit,
            "can_create_report": active,
            # 活跃报告上限;列表页据此在达限时预先置灰"新建报告"并说明,
            # 而不是让用户点击后才收到 403。
            "active_report_limit": self.profile.active_report_limit,
            "can_generate": active,
            "can_regenerate_sections": active,
            "can_export_word": active and scope.can_export_word,
            "material_agent_enabled": active and scope.material_agent_enabled,
            "can_edit_existing": self.status == "active" and grant_started,
            "collects_materiality_assessment": scope.collects_materiality_assessment,
            "allowed_quantitative_metric_keys": sorted(
                scope.allowed_quantitative_metric_keys()
            ),
            "allowed_report_artifact_kinds": sorted(
                scope.allowed_report_artifact_kinds
            ),
        }

    def api_projection(self) -> dict[str, object]:
        return {
            "account": {
                "id": str(self.account_id),
                "email": self.email,
                "organization_name": self.organization_name,
                "status": self.status,
                "registered_at": self.registered_at.isoformat(),
                "last_active_at": self.last_active_at.isoformat(),
                "onboarding_seen": list(self.onboarding_seen),
            },
            "entitlement": {
                "grant_id": str(self.grant_id),
                "profile_id": self.profile_id,
                "starts_at": self.starts_at.isoformat(),
                "ends_at": self.ends_at.isoformat() if self.ends_at else None,
                "expired": self.expired,
            },
            "capabilities": self.capabilities(),
        }


def _account_context(row: asyncpg.Record) -> AccountContext:
    """把已限定为唯一当前 Grant 的数据库行解析为 Account 能力事实。"""

    if row["grant_id"] is None:
        raise AccountEntitlementError(str(row["account_id"]))
    try:
        profile = require_profile(row["profile_id"])
    except ValueError as exc:
        raise AccountEntitlementError(str(row["account_id"])) from exc
    return AccountContext(
        account_id=row["account_id"],
        email=row["email"],
        organization_name=row["organization_name"],
        status=row["status"],
        registered_at=row["registered_at"],
        last_active_at=row["last_active_at"],
        grant_id=row["grant_id"],
        profile_id=row["profile_id"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        profile=profile,
        onboarding_seen=tuple(row["onboarding_seen"] or ()),
    )


async def get_account_context(pool: asyncpg.Pool, subject: UUID) -> AccountContext:
    row = await pool.fetchrow(
        """
        select a.id as account_id, a.email, a.organization_name, a.status,
               a.registered_at, a.last_active_at, a.onboarding_seen, g.id as grant_id,
               g.profile_id, g.starts_at, g.ends_at
        from account_identities i
        join accounts a on a.id = i.account_id
        left join account_entitlement_grants g
          on g.account_id = a.id and g.ended_at is null
        where i.identity_issuer = $1 and i.identity_subject = $2
        """,
        PRIMARY_IDENTITY_ISSUER,
        subject,
    )
    if row is None:
        raise AccountNotFoundError(str(subject))
    return _account_context(row)


async def get_account_context_for_account(
    pool: asyncpg.Pool, account_id: UUID
) -> AccountContext:
    """供无认证主体的后台任务按 Account 重新裁决当前权益。"""

    row = await pool.fetchrow(
        """
        select a.id as account_id, a.email, a.organization_name, a.status,
               a.registered_at, a.last_active_at, a.onboarding_seen, g.id as grant_id,
               g.profile_id, g.starts_at, g.ends_at
        from accounts a
        left join account_entitlement_grants g
          on g.account_id = a.id and g.ended_at is null
        where a.id = $1
        """,
        account_id,
    )
    if row is None:
        raise AccountNotFoundError(str(account_id))
    return _account_context(row)


async def has_account_permission(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    permission: str,
) -> bool:
    """读取运营权限；权限独立于 Grant，避免客户权益意外获得内部审阅能力。"""

    return bool(
        await pool.fetchval(
            """
            select 1 from account_operator_permissions
            where account_id = $1 and permission = $2
            """,
            account_id,
            permission,
        )
    )


async def touch_account_activity(
    pool: asyncpg.Pool, context: AccountContext
) -> AccountContext:
    """应用启动时至多每日更新一次活跃时间，避免每个 API 请求制造写放大。"""
    touched_at = await pool.fetchval(
        """
        update accounts set last_active_at = now()
        where id = $1 and last_active_at < now() - interval '24 hours'
        returning last_active_at
        """,
        context.account_id,
    )
    return replace(context, last_active_at=touched_at) if touched_at else context


def effective_report_profile(
    context: AccountContext,
    *,
    created_under_profile_id: str,
) -> EntitlementProfile:
    """Report 的权益跟随当前 Grant；创建时 Profile 只作存档，不再影响裁决。"""

    require_profile(created_under_profile_id)
    return context.profile


def effective_report_scope(
    context: AccountContext,
    *,
    created_under_profile_id: str,
    report_profile_id: str,
):
    """返回单份 Report 的当前有效执行范围，供 HTTP 与 worker 共同重用。"""

    require_profile(created_under_profile_id)
    return execution_scope_for_profile(
        context.profile_id,
        knowledge_package=knowledge_package_for_profile(report_profile_id),
    )


def active_report_slot_limit(
    context: AccountContext, *, created_under_profile_id: str
) -> int:
    """读取当前 Account 可保留的活跃报告名额。"""

    require_profile(created_under_profile_id)
    return context.profile.active_report_limit


def report_capabilities(
    context: AccountContext,
    *,
    created_under_profile_id: str,
    report_profile_id: str,
) -> dict[str, object]:
    """投影 Account 与单份 Report 合并后的实际能力，供前后端共同显示和裁决。"""
    profile = effective_report_profile(
        context,
        created_under_profile_id=created_under_profile_id,
    )
    active = context.active
    scope = effective_report_scope(
        context,
        created_under_profile_id=created_under_profile_id,
        report_profile_id=report_profile_id,
    )
    return {
        "allowed_report_section_ids": [
            section.id for section in all_report_sections(scope.knowledge_package)
        ],
        "section_regeneration_limit": profile.section_regeneration_limit,
        "can_generate": active,
        "can_regenerate_sections": active,
        "can_export_word": active and scope.can_export_word,
        "material_agent_enabled": active and scope.material_agent_enabled,
        "collects_materiality_assessment": scope.collects_materiality_assessment,
        "allowed_quantitative_metric_keys": sorted(
            scope.allowed_quantitative_metric_keys()
        ),
        "allowed_report_artifact_kinds": sorted(
            scope.allowed_report_artifact_kinds
        ),
    }


async def require_report_creation(
    pool: asyncpg.Pool, subject: UUID, report_type: ReportType
) -> AccountContext:
    context = await get_account_context(pool, subject)
    if not context.capabilities()["can_create_report"] or report_type != "lightweight":
        raise CapabilityDeniedError("当前账户不能创建该类型报告")
    return context
