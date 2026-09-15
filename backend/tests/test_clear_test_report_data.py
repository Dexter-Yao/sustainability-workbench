# ABOUTME: 验证合成测试报告清理命令的确认门槛与目标范围，避免误触真实数据。
# ABOUTME: 不连接数据库；真实删除顺序由受限命令在已批准的测试环境中执行。
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager

import pytest

from sustainability_desk.ops import clear_test_report_data as cleanup
from sustainability_desk.material.intake.storage import MaterialStorageError



RESTRICT_TABLES_QUERY = """
    select cl.relname as child
    from pg_constraint co
    join pg_class p on p.oid = co.confrelid
    join pg_class cl on cl.oid = co.conrelid
    where co.contype = 'f' and p.relname = 'reports' and co.confdeltype = 'r'
"""


@pytest.mark.asyncio
async def test_every_restricting_report_reference_is_cleared() -> None:
    """所有对 reports 为 RESTRICT 的外键表都必须在删除序列中显式清理。

    回归：新增 RESTRICT 外键表（如 image_agent_runs）时若清理脚本未同步，
    直到真实清理时才以 ForeignKeyViolationError 暴露。

    以真实数据库为准而非 migration 文本：migration 文本里可能含未实际建出的
    表定义（如 block_evidence_decisions）；照文本推断会让
    清理脚本去删不存在的表，反而以 UndefinedTableError 失败。
    CASCADE 的表随 reports 自动删除，不应出现在删除序列里。
    """
    import asyncpg

    from sustainability_desk.persistence.settings import persistence_settings

    try:
        settings = persistence_settings()
        connection = await asyncpg.connect(settings.database_url)
    except Exception as exc:  # noqa: BLE001 — 无库环境跳过，不伪装通过
        pytest.skip(f"本用例需要真实数据库连接：{exc}")

    try:
        rows = await connection.fetch(RESTRICT_TABLES_QUERY)
    finally:
        await connection.close()

    restricting = {row["child"] for row in rows}
    assert restricting, "未查到任何 RESTRICT 外键，查询或 schema 可能已变化"

    source = Path(cleanup.__file__).read_text(encoding="utf-8")
    cleared = set(re.findall(r"delete from (\w+)", source))
    missing = restricting - cleared
    assert not missing, (
        f"这些表对 reports 为 ON DELETE RESTRICT 但未被清理，真实删除会被外键拦下：{sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_apply_requires_explicit_environment_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cleanup,
        "persistence_settings",
        lambda: SimpleNamespace(database_url="postgresql://test"),
    )

    async def unexpected_pool(*_args, **_kwargs):
        raise AssertionError("确认门槛前不得连接数据库")

    monkeypatch.setattr(cleanup.asyncpg, "create_pool", unexpected_pool)
    monkeypatch.delenv("SUSTAINABILITY_DESK_CONFIRM_CLEAR_TEST_DATA", raising=False)

    with pytest.raises(cleanup.TestDataCleanupError, match="CONFIRM_CLEAR"):
        await cleanup.clear_test_report_data(
            roles=("internal_automation",),
            apply=True,
        )


def test_report_artifact_directory_cannot_escape_configured_root(
    tmp_path,
) -> None:
    root = tmp_path.resolve()

    target = cleanup._report_artifact_directory(root, uuid4())

    assert target.parent == root


@pytest.mark.asyncio
async def test_non_synthetic_report_refuses_cleanup() -> None:
    class Connection:
        async def fetch(self, *_args, **_kwargs):
            return (
                {
                    "id": uuid4(),
                    "account_id": account_id,
                    "data_classification": "operator_authorized",
                    "created_under_profile_id": "other_profile@1",
                },
            )

    account_id = uuid4()
    with pytest.raises(cleanup.TestDataCleanupError, match="不属于测试角色"):
        await cleanup._report_targets(
            Connection(),
            accounts=(
                cleanup.TestAccountTarget(
                    account_id=account_id,
                    email="internal-automation@example.com",
                    role="internal_automation",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_missing_private_object_is_idempotent_during_cleanup() -> None:
    class Storage:
        async def delete(self, _object_path: str) -> None:
            raise MaterialStorageError("Storage HTTP 400: Object not found")

    missing_count = await cleanup._delete_material_objects(
        Storage(),
        ("reports/test/file.docx",),
    )

    assert missing_count == 1


@pytest.mark.asyncio
async def test_cleanup_breaks_generation_revision_cycle_before_deletion() -> None:
    class Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        @asynccontextmanager
        async def transaction(self):
            yield

        async def execute(self, statement: str, *_args) -> None:
            self.statements.append(statement)

    connection = Connection()
    await cleanup._delete_report_rows(
        connection,
        report_ids=(uuid4(),),
    )

    sql = "\n".join(connection.statements)
    assert "when status = 'succeeded' then 'failed'" in sql
    assert sql.index("delete from lightweight_report_revisions") < sql.index(
        "delete from lightweight_report_generation_runs"
    )
