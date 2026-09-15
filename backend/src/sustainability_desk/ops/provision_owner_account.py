# ABOUTME: 用持有人自己的邮箱建立首个可登录账号：Auth 身份、Account、身份映射与初始 Grant。
# ABOUTME(en): Provisions the owner's own first sign-in account: auth identity, Account, mapping and initial grant.
"""首用户建号。

与 `ops.bootstrap_internal_accounts` 的分工：那条命令按
`backend/data/test_accounts.yaml` 建立**内部受控测试身份**（`internal_automation` /
`internal_manual`），角色是封闭枚举，邮箱是 `@example.com`。本命令建立的是**产品持有人
自己的账号**，邮箱由调用方给出，不进任何注册表——两类身份不共用一个出口，以免把
「内部测试身份」和「真实用户」混成同一份清单。

认证栈刻意关闭公开注册（`supabase/config.toml` 的 `[auth] enable_signup = false`），
因此新环境的第一个账号只能由本命令建立。

默认只报告将要做什么；写入需同时给 `--apply` 与环境确认值，与
`ops.clear_test_report_data` 的房规一致。密码只经环境变量注入单次进程，不落文件、
不进日志、不写入仓库。

用法：

    uv run --project backend python -m sustainability_desk.ops.provision_owner_account \\
        --email you@example.com

    SUSTAINABILITY_DESK_OWNER_PASSWORD='<12+ 位含大小写与数字>' \\
        SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES \\
        uv run --project backend python -m sustainability_desk.ops.provision_owner_account \\
        --email you@example.com --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from dataclasses import dataclass
from uuid import UUID

import asyncpg
import httpx

from sustainability_desk.accounts.entitlement_profiles import require_profile
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.settings import persistence_settings

#: 持有人账号的初始权益档；本机单用户形态只有这一档。
OWNER_PROFILE_ID = "local_single_user@1"
#: Grant 与事件的来源标识，便于与内部测试身份建立的 Grant 区分。
GRANTED_BY = "provision_owner_account"
PASSWORD_ENV = "SUSTAINABILITY_DESK_OWNER_PASSWORD"
CONFIRM_ENV = "SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER"

#: 与数据库 accounts_email_check 同口径的最小形态校验，提前给出可读错误。
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class OwnerProvisionError(RuntimeError):
    """建号前提、输入或完成状态不成立。"""


@dataclass(frozen=True)
class OwnerAccountSpec:
    """一个持有人账号的建立意图。"""

    email: str
    organization_name: str | None = None

    def normalized_email(self) -> str:
        return self.email.strip().lower()


async def _create_auth_user(settings, *, email: str, password: str) -> UUID:
    """在认证栈创建已确认邮箱的用户；失败只暴露状态码，不回显上游响应体。"""

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users",
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            json={"email": email, "password": password, "email_confirm": True},
        )
    if response.status_code not in (200, 201):
        raise OwnerProvisionError(
            f"认证用户创建失败（HTTP {response.status_code}）；"
            "密码需至少 12 位且同时含小写、大写与数字"
        )
    return UUID(response.json()["id"])


async def _ensure_product_account(
    pool: asyncpg.Pool, spec: OwnerAccountSpec, subject: UUID
) -> None:
    """幂等建立 Account、身份映射与初始 Grant；已存在的账号不重置、不降级。"""

    require_profile(OWNER_PROFILE_ID)
    email = spec.normalized_email()
    async with pool.acquire() as conn, conn.transaction():
        identity = await conn.fetchrow(
            """
            select account_id from account_identities
            where identity_issuer = 'primary' and identity_subject = $1
            """,
            subject,
        )
        if identity is not None:
            return
        account_id = await conn.fetchval(
            "insert into accounts (email, organization_name) values ($1, $2) returning id",
            email,
            spec.organization_name,
        )
        await conn.execute(
            """
            insert into account_identities (account_id, identity_issuer, identity_subject)
            values ($1, 'primary', $2)
            """,
            account_id,
            subject,
        )
        grant_id = await conn.fetchval(
            """
            insert into account_entitlement_grants (
              account_id, profile_id, starts_at, granted_by, reason
            ) values ($1, $2, now(), $3, 'owner_first_account')
            returning id
            """,
            account_id,
            OWNER_PROFILE_ID,
            GRANTED_BY,
        )
        await conn.execute(
            """
            insert into account_events (account_id, actor, event_type, payload)
            values ($1, 'operator', 'entitlement_granted', $2)
            """,
            account_id,
            {"grantId": str(grant_id), "profileId": OWNER_PROFILE_ID},
        )


async def run(args: argparse.Namespace) -> None:
    """报告或执行一次建号。"""

    spec = OwnerAccountSpec(email=args.email, organization_name=args.organization_name)
    email = spec.normalized_email()
    if not _EMAIL.match(email):
        raise SystemExit("--email 需要形如 name@example.com 的邮箱")

    settings = persistence_settings()
    if not settings.database_url:
        raise SystemExit("缺少 SUSTAINABILITY_DESK_DATABASE_URL")
    if args.apply and not (settings.supabase_url and settings.supabase_service_key):
        raise SystemExit(
            "--apply 需要 SUSTAINABILITY_DESK_SUPABASE_URL 与 "
            "SUSTAINABILITY_DESK_SUPABASE_SERVICE_KEY"
        )
    if args.apply and os.getenv(CONFIRM_ENV) != "YES":
        raise SystemExit(f"写入建号需要 {CONFIRM_ENV}=YES")

    require_profile(OWNER_PROFILE_ID)
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=2, init=_init_connection
    )
    try:
        existing = await pool.fetchrow(
            "select id, email_confirmed_at from auth.users where lower(email) = lower($1)",
            email,
        )
        action = "reuse" if existing else "create"
        print(f"{email}: auth={action}, product=ensure {OWNER_PROFILE_ID}")
        if not args.apply:
            print(f"DRY RUN：未写入；确认邮箱与目标环境后追加 --apply 并设 {CONFIRM_ENV}=YES")
            return
        if existing is not None:
            if existing["email_confirmed_at"] is None:
                raise OwnerProvisionError("现有认证用户的邮箱未验证，拒绝继续")
            subject = existing["id"]
        else:
            password = os.environ.get(PASSWORD_ENV)
            if not password:
                raise OwnerProvisionError(f"缺少密码环境变量 {PASSWORD_ENV}")
            subject = await _create_auth_user(settings, email=email, password=password)
        await _ensure_product_account(pool, spec, subject)
        print(f"已就绪：用 {email} 登录 http://localhost:3000")
    finally:
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用持有人自己的邮箱建立首个可登录账号（默认 dry run）"
    )
    parser.add_argument("--email", required=True, help="登录邮箱；不进任何注册表文件。")
    parser.add_argument(
        "--organization-name",
        default=None,
        help="可选的组织名，仅用于账号展示。",
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    asyncio.run(run(_parser().parse_args()))


if __name__ == "__main__":
    main()
