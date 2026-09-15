# ABOUTME: 测试基线重建前的只读身份与应用数据盘点，阻止误清理非测试账户。
# ABOUTME: 此命令绝不写库、删除 Auth 或访问 Storage；真正重建由受控 release 脚本在备份后执行。
# ABOUTME(en): Read-only inventory of identities and application data before a test-baseline rebuild, blocking
# ABOUTME(en): cleanup of non-test accounts. Never writes the database, deletes auth users, or touches Storage.
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import asyncpg

from sustainability_desk.ops.bootstrap_internal_accounts import load_registry
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.settings import persistence_settings


@dataclass(frozen=True)
class TestBaselineInventory:
    """重建前可供人工确认的最小盘点，不包含认证密码、token 或报告内容。"""

    registered_test_emails: tuple[str, ...]
    auth_emails: tuple[str, ...]
    application_account_emails: tuple[str, ...]
    report_count: int
    material_source_count: int
    generation_run_count: int


async def inspect_test_baseline(registry_path: Path) -> TestBaselineInventory:
    """读取目标库并拒绝任何不在测试账号注册表中的 Auth 或 Account 邮箱。"""

    settings = persistence_settings()
    if not settings.database_url:
        raise RuntimeError("缺少 SUSTAINABILITY_DESK_DATABASE_URL")
    registry = load_registry(registry_path)
    expected = tuple(sorted(item.email.strip().lower() for item in registry.accounts))
    expected_set = set(expected)
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=1,
        init=_init_connection,
    )
    try:
        auth_rows = await pool.fetch(
            "select lower(email) as email from auth.users where email is not null order by 1"
        )
        account_rows = await pool.fetch(
            "select lower(email) as email from accounts order by 1"
        )
        auth_emails = tuple(str(row["email"]) for row in auth_rows)
        account_emails = tuple(str(row["email"]) for row in account_rows)
        unexpected = sorted((set(auth_emails) | set(account_emails)) - expected_set)
        if unexpected:
            raise RuntimeError(
                "发现非测试账户，拒绝重建应用数据：" + ", ".join(unexpected)
            )
        return TestBaselineInventory(
            registered_test_emails=expected,
            auth_emails=auth_emails,
            application_account_emails=account_emails,
            report_count=int(await pool.fetchval("select count(*) from reports")),
            material_source_count=int(
                await pool.fetchval("select count(*) from material_sources")
            ),
            generation_run_count=int(
                await pool.fetchval(
                    "select count(*) from lightweight_report_generation_runs"
                )
            ),
        )
    finally:
        await pool.close()


async def _main(args: argparse.Namespace) -> None:
    inventory = await inspect_test_baseline(args.registry)
    print(json.dumps(asdict(inventory), ensure_ascii=False, indent=2))
    print("PRECHECK PASSED：仅发现注册表允许的测试身份；本命令未写入或删除任何数据。")


def main() -> None:
    parser = argparse.ArgumentParser(description="测试基线重建前的只读账号白名单盘点")
    parser.add_argument("--registry", type=Path, required=True)
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
