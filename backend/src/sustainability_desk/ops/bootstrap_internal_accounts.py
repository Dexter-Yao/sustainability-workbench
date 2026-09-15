# ABOUTME: 从版本化测试账号注册表绑定 Auth 身份、产品 Account、初始 Grant 与受限运营权限。
# ABOUTME: 默认 dry-run；空环境可创建该身份，已有身份只复用，不重置密码或当前 Grant。
# ABOUTME(en): Binds auth identity, product Account, initial Grant and operator permissions from the test-account
# ABOUTME(en): registry. Dry-run by default; an existing identity is reused, never password- or Grant-reset.
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal
from uuid import UUID

import asyncpg
import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.accounts.entitlement_profiles import require_profile
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.settings import persistence_settings


class TestAccountSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str
    role: Literal["internal_automation", "internal_manual"]
    auth_mode: Literal["managed_auth"]
    bootstrap_profile_id: str
    password_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    organization_name: str | None = None
    operator_permissions: tuple[Literal["internal_audit_reviewer"], ...] = ()

    @model_validator(mode="after")
    def validate_role(self) -> "TestAccountSpec":
        expected_profile_id = {
            "internal_automation": "local_single_user@1",
            "internal_manual": "local_single_user@1",
        }[self.role]
        if self.bootstrap_profile_id != expected_profile_id:
            raise ValueError(f"{self.role} 必须使用 {expected_profile_id}")
        return self


class TestAccountRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2]
    accounts: tuple[TestAccountSpec, ...]

    @model_validator(mode="after")
    def validate_unique_emails(self) -> "TestAccountRegistry":
        emails = [item.email.strip().lower() for item in self.accounts]
        if not emails or len(emails) != len(set(emails)):
            raise ValueError("测试账号邮箱必须非空且唯一")
        return self


def load_registry(path: Path) -> TestAccountRegistry:
    return TestAccountRegistry.model_validate(yaml.safe_load(path.read_text("utf-8")))


def load_passwords_from_stdin(*, specs: tuple[TestAccountSpec, ...]) -> dict[str, str]:
    """读取本机经加密标准输入传来的测试密码，不记录或持久化密码内容。"""

    try:
        raw_payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise RuntimeError("--password-stdin 需要邮箱到密码的 JSON 对象") from error
    if not isinstance(raw_payload, dict):
        raise RuntimeError("--password-stdin 需要邮箱到密码的 JSON 对象")
    expected_emails = {spec.email.strip().lower() for spec in specs}
    passwords = {
        str(email).strip().lower(): password
        for email, password in raw_payload.items()
        if isinstance(email, str) and isinstance(password, str) and password
    }
    if set(passwords) != expected_emails:
        raise RuntimeError("--password-stdin 的账号集合必须与本次受控角色完全一致")
    return passwords


async def _create_auth_user(settings, spec: TestAccountSpec, password: str) -> UUID:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users",
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            json={"email": spec.email.strip().lower(), "password": password, "email_confirm": True},
        )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Auth 用户创建失败: HTTP {response.status_code} {response.text[:160]}")
    return UUID(response.json()["id"])


async def _ensure_product_account(
    pool: asyncpg.Pool, spec: TestAccountSpec, subject: UUID
) -> None:
    """幂等创建或验证 Account；现有 Account 不降级 Grant。"""

    assert spec.bootstrap_profile_id is not None
    require_profile(spec.bootstrap_profile_id)
    email = spec.email.strip().lower()
    async with pool.acquire() as conn, conn.transaction():
        identity = await conn.fetchrow(
            """
            select account_id from account_identities
            where identity_issuer = 'primary' and identity_subject = $1
            """,
            subject,
        )
        if identity is None:
            account_id = await conn.fetchval(
                """
                insert into accounts (email, organization_name) values ($1, $2)
                returning id
                """,
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
                ) values ($1, $2, now(), 'provision_test_accounts', 'test_account_baseline')
                returning id
                """,
                account_id,
                spec.bootstrap_profile_id,
            )
            await conn.execute(
                """
                insert into account_events (account_id, actor, event_type, payload)
                values ($1, 'operator', 'entitlement_granted', $2)
                """,
                account_id,
                {"grantId": str(grant_id), "profileId": spec.bootstrap_profile_id},
            )
        else:
            account_id = identity["account_id"]
        for permission in spec.operator_permissions:
            await conn.execute(
                """
                insert into account_operator_permissions (account_id, permission, granted_by, reason)
                values ($1, $2, 'provision_test_accounts', 'test_account_baseline')
                on conflict (account_id, permission) do nothing
                """,
                account_id,
                permission,
            )


async def run(args: argparse.Namespace) -> None:
    settings = persistence_settings()
    if not settings.database_url:
        raise SystemExit("缺少 SUSTAINABILITY_DESK_DATABASE_URL")
    if args.apply and not (settings.supabase_url and settings.supabase_service_key):
        raise SystemExit("--apply 需要 SUSTAINABILITY_DESK_SUPABASE_URL 与 SUSTAINABILITY_DESK_SUPABASE_SERVICE_KEY")
    registry = load_registry(args.registry)
    requested_roles = set(args.role)
    specs = tuple(
        spec for spec in registry.accounts if not requested_roles or spec.role in requested_roles
    )
    if not specs:
        raise SystemExit("指定的测试账号角色不在注册表中")
    password_stdin = bool(getattr(args, "password_stdin", False))
    if password_stdin and not args.apply:
        raise SystemExit("--password-stdin 只能与 --apply 一起使用")
    passwords = load_passwords_from_stdin(specs=specs) if password_stdin else {}
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=2, init=_init_connection
    )
    try:
        for spec in specs:
            existing = await pool.fetchrow(
                "select id, email_confirmed_at from auth.users where lower(email) = lower($1)",
                spec.email,
            )
            action = "reuse" if existing else "create"
            print(
                f"{spec.email}: auth={action}, product=ensure {spec.bootstrap_profile_id}, "
                f"role={spec.role}"
            )
            if not args.apply:
                continue
            if existing is not None and existing["email_confirmed_at"] is None:
                raise RuntimeError(f"现有 Auth 用户邮箱未验证: {spec.email}")
            if existing is None:
                password = passwords.get(spec.email.strip().lower()) if password_stdin else os.environ.get(spec.password_env)
                if not password:
                    raise RuntimeError(f"缺少密码环境变量 {spec.password_env}")
                subject = await _create_auth_user(settings, spec, password)
            else:
                subject = existing["id"]
            await _ensure_product_account(pool, spec, subject)
        if not args.apply:
            print("DRY RUN：未写入；确认测试账号角色与目标环境后追加 --apply")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="按测试账号注册表 provision Auth 绑定、Account 与初始 Grant")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="仅供本机受控凭据通过加密标准输入进行一次性远端 bootstrap；不读取密码环境变量。",
    )
    parser.add_argument(
        "--role",
        action="append",
        choices=("internal_automation", "internal_manual"),
        default=[],
        help="仅 provision 指定角色；不传时按完整注册表检查。",
    )
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
