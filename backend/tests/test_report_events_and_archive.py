# ABOUTME: 导出存档的集成测试——验证 docx 上传 exports 桶与 sha256 审计事件。
# ABOUTME: 直连本地 Supabase 栈（Postgres + Storage）；栈未启动时整组跳过。
from __future__ import annotations

import hashlib
from uuid import uuid4

import asyncpg
import httpx
import pytest
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.export_archive import archive_export
from sustainability_desk.persistence.settings import PersistenceSettings
from knowledge_package_fixtures import SSE_PACKAGE

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_SUPABASE = "http://127.0.0.1:54321"
LOCAL_SERVICE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
STATE_V4 = {"version": 4, "fields": {}, "intakeItems": {}, "generatedBlocks": {}, "tableBlocks": {}}


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3)
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield p
    await p.close()


@pytest.fixture
async def owner_and_report(pool):
    owner = uuid4()
    await pool.execute("insert into auth.users (id) values ($1)", owner)
    account_id = await pool.fetchval(
        "insert into accounts (email) values ($1) returning id", f"events-{owner}@example.edu.cn"
    )
    await pool.execute(
        "insert into account_identities (account_id, identity_issuer, identity_subject) values ($1, 'primary', $2)",
        account_id, owner,
    )
    await pool.execute(
        "insert into account_entitlement_grants (account_id, profile_id, starts_at, ends_at, granted_by, reason) values ($1, 'local_single_user@1', now(), now() + interval '1 year', 'test', 'integration_test')",
        account_id,
    )
    summary = await reports_dal.create_report(
        pool, account_id, "事件测试", "lightweight", "sse_zh_hans@1", "customer",
        contract_version(SSE_PACKAGE), STATE_V4, 1, "local_single_user@1"
    )
    yield owner, summary
    await pool.execute("delete from public.accounts where id = $1", account_id)
    await pool.execute("delete from auth.users where id = $1", owner)


async def test_archive_export_uploads_and_records_event(pool, owner_and_report):
    """Supabase Storage 这条路径仍然可用——留给把对象存到 Supabase 的安装。

    storage-api 不在运行时跳过：它默认已不启动（本地对象存储是默认值），
    此时该服务不可达是预期状态，不是回归。跳过而非失败，与本仓「栈未起即 skip」
    的既有约定一致。
    """
    _, summary = owner_and_report
    try:
        async with httpx.AsyncClient(timeout=2.0) as probe:
            await probe.get(f"{LOCAL_SUPABASE}/storage/v1/version")
    except httpx.HTTPError:
        pytest.skip("storage-api 未运行（默认不启动，对象走本机磁盘）")
    # local_storage_root 置空以走 Supabase Storage 这条路径——本用例钉的就是它。
    settings = PersistenceSettings(
        _env_file=None,
        database_url=LOCAL_DB,
        supabase_url=LOCAL_SUPABASE,
        supabase_service_key=LOCAL_SERVICE_KEY,
        local_storage_root="",
    )
    data = b"fake-docx-bytes-for-archive-test"
    await archive_export(pool, settings, summary.id, data)

    event = await pool.fetchrow(
        "select payload from report_events where report_id = $1 and event_type = 'report_exported'",
        summary.id,
    )
    assert event is not None
    payload = event["payload"]
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()
    assert payload["archived"] is True
    assert payload["objectPath"].startswith(str(summary.id))

    # 对象确实存在于 exports 桶
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(
            f"{LOCAL_SUPABASE}/storage/v1/object/exports/{payload['objectPath']}",
            headers={"Authorization": f"Bearer {LOCAL_SERVICE_KEY}"},
        )
    assert res.status_code == 200 and res.content == data


async def test_archive_export_records_event_even_without_storage(pool, owner_and_report):
    """两处存储都不可用时仍记事件，并如实标 archived=false。

    这条钉的是「导出不因存档失败而受影响」：对象存储是审计副本，不是交付路径——
    交付物本就落在 report_artifact_root。故两个根都置空，模拟谁都收不下的情形。
    """
    _, summary = owner_and_report
    settings = PersistenceSettings(
        _env_file=None,
        database_url=LOCAL_DB,
        supabase_url="",
        supabase_service_key="",
        local_storage_root="",
    )
    await archive_export(pool, settings, summary.id, b"bytes")
    event = await pool.fetchrow(
        "select payload from report_events where report_id = $1 and event_type = 'report_exported' order by id desc limit 1",
        summary.id,
    )
    assert event["payload"]["archived"] is False and event["payload"]["objectPath"] is None


async def test_archive_export_writes_to_local_object_storage(pool, owner_and_report, tmp_path):
    """默认（本地对象存储）下存档真的落盘，而不是恒记 archived=false。

    关掉 storage-api 之后，如果 _upload 只认 Supabase 这一条路，每次导出都会记
    archived=false——审计事件看起来像「一直上传失败」，而实际是根本没人在收。
    这种「失败」和真失败无法区分，比没有存档更糟。
    """
    _, summary = owner_and_report
    settings = PersistenceSettings(
        _env_file=None,
        database_url=LOCAL_DB,
        supabase_url="",
        supabase_service_key="",
        local_storage_root=str(tmp_path / "object-storage"),
    )
    data = b"local-archive-bytes"
    await archive_export(pool, settings, summary.id, data)

    event = await pool.fetchrow(
        "select payload from report_events where report_id = $1 and event_type = 'report_exported' order by id desc limit 1",
        summary.id,
    )
    payload = event["payload"]
    assert payload["archived"] is True
    stored = tmp_path / "object-storage" / "exports" / payload["objectPath"]
    assert stored.read_bytes() == data
