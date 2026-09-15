# ABOUTME: 清理受控测试账户的合成报告、资料运行与私有交付物，保留 Account、Grant 和登录凭据。
# ABOUTME: 命令默认只报告目标；写操作必须同时选择注册表角色、显式 --apply 和环境确认值。
# ABOUTME(en): Clears synthetic reports, material runs and private deliverables of controlled test accounts, keeping
# ABOUTME(en): Account, Grant and credentials. Reports targets by default; writes need a role, --apply and confirm.
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

import asyncpg

from sustainability_desk.material.intake.storage import (
    MaterialStorageClient,
    MaterialStorageError,
)
from sustainability_desk.ops.bootstrap_internal_accounts import load_registry
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.settings import persistence_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "backend" / "out" / "report_artifacts"
DEFAULT_REGISTRY = REPOSITORY_ROOT / "backend" / "data" / "test_accounts.yaml"
TestAccountRole = Literal["internal_automation"]


class TestDataCleanupError(RuntimeError):
    """测试数据清理前提、范围或完成状态不成立。"""


@dataclass(frozen=True)
class TestAccountTarget:
    """注册表角色已解析为数据库 Account 后的受控删除范围。"""

    account_id: UUID
    email: str
    role: TestAccountRole


def _artifact_root() -> Path:
    configured = os.getenv("SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT")
    root = Path(configured) if configured else DEFAULT_ARTIFACT_ROOT
    if not root.is_absolute():
        raise TestDataCleanupError("SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT 必须为绝对路径")
    return root.resolve()


def _report_artifact_directory(root: Path, report_id: UUID) -> Path:
    target = (root / str(report_id)).resolve()
    if root not in target.parents:
        raise TestDataCleanupError("报告交付物路径越出配置根目录")
    return target


async def _test_account_targets(
    connection: asyncpg.Connection,
    *,
    roles: tuple[TestAccountRole, ...],
    registry_path: Path,
) -> tuple[TestAccountTarget, ...]:
    registry = load_registry(registry_path)
    expected = tuple(
        spec for spec in registry.accounts if spec.role in set(roles)
    )
    if len(expected) != len(roles):
        raise TestDataCleanupError("指定角色不在测试账号注册表中")
    rows = await connection.fetch(
        """
        select id, email
        from accounts
        where email = any($1::text[])
        order by email
        """,
        [item.email.strip().lower() for item in expected],
    )
    found = {row["email"] for row in rows}
    missing = sorted({item.email.strip().lower() for item in expected} - found)
    if missing:
        raise TestDataCleanupError(
            f"目标环境缺少受控测试 Account：{', '.join(missing)}"
        )
    role_by_email = {
        item.email.strip().lower(): item.role for item in expected
    }
    return tuple(
        TestAccountTarget(
            account_id=row["id"],
            email=row["email"],
            role=role_by_email[row["email"]],
        )
        for row in rows
    )


async def _report_targets(
    connection: asyncpg.Connection,
    *,
    accounts: tuple[TestAccountTarget, ...],
) -> tuple[asyncpg.Record, ...]:
    """仅删除每个注册表角色在产品合同下允许创建的测试 Report。"""

    rows = await connection.fetch(
        """
        select id, account_id, title, data_classification, created_under_profile_id
        from reports
        where account_id = any($1::uuid[])
        order by account_id, created_at, id
        """,
        [item.account_id for item in accounts],
    )
    role_by_account = {item.account_id: item.role for item in accounts}
    invalid = []
    for row in rows:
        role = role_by_account[row["account_id"]]
        if role == "internal_automation" and (
            row["data_classification"] != "synthetic"
            or row["created_under_profile_id"] != "local_single_user@1"
        ):
            invalid.append(row)
    if invalid:
        raise TestDataCleanupError("受控测试 Account 出现不属于测试角色的 Report，拒绝清理")
    return tuple(rows)


async def _object_paths(
    connection: asyncpg.Connection,
    *,
    report_ids: tuple[UUID, ...],
) -> tuple[str, ...]:
    if not report_ids:
        return ()
    rows = await connection.fetch(
        """
        select source.object_path
        from material_sources source
        join material_workspaces workspace on workspace.id = source.workspace_id
        where workspace.report_id = any($1::uuid[])
        order by source.object_path
        """,
        list(report_ids),
    )
    return tuple(row["object_path"] for row in rows)


async def _delete_report_rows(
    connection: asyncpg.Connection,
    *,
    report_ids: tuple[UUID, ...],
) -> None:
    """按限制性外键反向删除轻量版运行链，最后删除 Reports。"""

    if not report_ids:
        return
    ids = list(report_ids)
    async with connection.transaction():
        await connection.execute(
            """
            delete from block_material_decision_materials relation
            using block_material_decisions decision
            where relation.decision_id = decision.id
              and decision.report_id = any($1::uuid[])
            """,
            ids,
        )
        await connection.execute(
            "delete from block_material_decisions where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            """
            update lightweight_report_generation_runs
            set status = case
                    when status = 'succeeded' then 'failed'
                    else status
                end,
                result_revision_id = null,
                failure_code = case
                    when status = 'succeeded' then 'test_data_cleanup'
                    else failure_code
                end
            where report_id = any($1::uuid[])
            """,
            ids,
        )
        await connection.execute(
            "delete from lightweight_report_artifacts where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from lightweight_report_generation_events where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from lightweight_report_revisions where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from lightweight_report_generation_runs where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from material_mapping_runs where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from material_set_snapshots where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "update file_agent_runs set dossier_id = null where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from file_dossiers where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute(
            "delete from file_agent_runs where report_id = any($1::uuid[])",
            ids,
        )
        # image_agent_runs 对 reports 是 ON DELETE RESTRICT，必须显式删除；
        # evidence_assets 是 CASCADE，随 reports 自动清除，无需在此列出。
        await connection.execute(
            "delete from image_agent_runs where report_id = any($1::uuid[])",
            ids,
        )
        await connection.execute("delete from reports where id = any($1::uuid[])", ids)


async def _delete_material_objects(
    storage: MaterialStorageClient,
    object_paths: tuple[str, ...],
) -> int:
    """删除本次受控资料对象；前次中断已删除的对象视为已达成目标。"""

    missing_count = 0
    for object_path in object_paths:
        try:
            await storage.delete(object_path)
        except MaterialStorageError as error:
            if "Object not found" not in str(error):
                raise
            missing_count += 1
    return missing_count


async def clear_test_report_data(
    *,
    roles: tuple[TestAccountRole, ...],
    registry_path: Path = DEFAULT_REGISTRY,
    apply: bool = False,
) -> dict[str, object]:
    """按注册表找到目标 Account，dry-run 或清理其全部合成报告资产。"""

    settings = persistence_settings()
    if not settings.database_url:
        raise TestDataCleanupError("缺少 SUSTAINABILITY_DESK_DATABASE_URL")
    if apply and os.getenv("SUSTAINABILITY_DESK_CONFIRM_CLEAR_TEST_DATA") != "YES":
        raise TestDataCleanupError(
            "写入清理需要 SUSTAINABILITY_DESK_CONFIRM_CLEAR_TEST_DATA=YES"
        )
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=2,
        init=_init_connection,
    )
    try:
        async with pool.acquire() as connection:
            accounts = await _test_account_targets(
                connection,
                roles=roles,
                registry_path=registry_path,
            )
            reports = await _report_targets(
                connection,
                accounts=accounts,
            )
            report_ids = tuple(row["id"] for row in reports)
            object_paths = await _object_paths(connection, report_ids=report_ids)
            receipt: dict[str, object] = {
                "roles": list(roles),
                "accounts": [item.email for item in accounts],
                "reportIds": [str(report_id) for report_id in report_ids],
                "materialObjectCount": len(object_paths),
                "missingMaterialObjectCount": 0,
                "artifactDirectoryCount": len(report_ids),
                "status": "dry_run",
            }
            if not apply:
                return receipt
            storage = MaterialStorageClient(settings)
            receipt["missingMaterialObjectCount"] = await _delete_material_objects(
                storage,
                object_paths,
            )
            await _delete_report_rows(connection, report_ids=report_ids)
        artifact_root = _artifact_root()
        for report_id in report_ids:
            directory = _report_artifact_directory(artifact_root, report_id)
            if directory.exists():
                shutil.rmtree(directory)
        return {**receipt, "status": "cleared"}
    finally:
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理注册表受控测试账户的合成报告数据")
    parser.add_argument(
        "--role",
        action="append",
        choices=("internal_automation",),
        default=[],
        help="可重复；省略时清理自动化测试身份",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--apply", action="store_true")
    return parser


async def _main() -> None:
    args = _parser().parse_args()
    roles: tuple[TestAccountRole, ...] = tuple(args.role) or (
        "internal_automation",
    )
    receipt = await clear_test_report_data(
        roles=roles,
        registry_path=args.registry,
        apply=args.apply,
    )
    import json

    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
