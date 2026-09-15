# ABOUTME: 资料集合快照「当前性」持久化回归——同指纹幂等重建必须刷新确认时间，
# ABOUTME: 用户改回旧资料组合后 latest_material_set_snapshot 指向重建的那套而非按首建时间误判。
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
import pytest

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.material.mapping.snapshot import (
    build_material_set_snapshot,
)
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import _init_connection
from knowledge_package_fixtures import SSE_PACKAGE

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
STATE_V4 = {"version": 4, "fields": {}, "intakeItems": {}, "generatedBlocks": {}, "tableBlocks": {}}


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3)
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield p
    await p.close()


@dataclass(frozen=True)
class _Principal:
    subject: UUID
    account_id: UUID
    report_id: UUID
    workspace_id: UUID


@pytest.fixture
async def principal(pool):
    subject = uuid4()
    await pool.execute("insert into auth.users (id) values ($1)", subject)
    account_id = await pool.fetchval(
        "insert into accounts (email) values ($1) returning id",
        f"snapshot-{subject}@example.edu.cn",
    )
    summary = await reports_dal.create_report(
        pool,
        account_id=account_id,
        title="快照排序",
        report_type="lightweight",
        report_profile_id="lightweight@1",
        data_classification="customer",
        contract_version=contract_version(SSE_PACKAGE),
        initial_state=STATE_V4,
        active_scope_limit=1,
        profile_id="local_single_user@1",
    )
    workspace_id = await pool.fetchval(
        """
        insert into material_workspaces (account_id, report_id, adapter_id, contract_version)
        values ($1, $2, 'test-adapter', $3) returning id
        """,
        account_id,
        summary.id,
        contract_version(SSE_PACKAGE),
    )
    yield _Principal(subject, account_id, summary.id, workspace_id)
    await pool.execute("delete from material_set_snapshots where account_id = $1", account_id)
    await pool.execute("delete from material_workspaces where id = $1", workspace_id)
    await pool.execute("delete from accounts where id = $1", account_id)
    await pool.execute("delete from auth.users where id = $1", subject)


async def _store(pool, principal: _Principal):
    snapshot = build_material_set_snapshot(report_id=principal.report_id, members=())
    return await pipeline_dal.store_material_set_snapshot(
        pool,
        account_id=principal.account_id,
        workspace_id=principal.workspace_id,
        snapshot=snapshot,
    )


async def test_rebuilding_prior_fingerprint_makes_it_latest_again(pool, principal):
    """空集与非空集交替确认：重建旧指纹后它必须重新成为「当前快照」。"""
    empty_first = await _store(pool, principal)

    # 中间出现另一个指纹的快照（伪造成员指纹即可制造不同 input_fingerprint）。
    other_fingerprint = "b" * 64
    await pool.execute(
        """
        insert into material_set_snapshots (
          id, account_id, report_id, workspace_id, input_fingerprint, snapshot_payload, created_at
        ) values ($1, $2, $3, $4, $5, $6, now() - interval '1 second')
        """,
        uuid4(),
        principal.account_id,
        principal.report_id,
        principal.workspace_id,
        other_fingerprint,
        {"marker": "other"},
    )
    # 用户改回最初的资料组合：同指纹幂等重建。
    rebuilt = await _store(pool, principal)
    # 身份不变（幂等），确认时间刷新。
    assert rebuilt.snapshot.snapshot_id == empty_first.snapshot.snapshot_id

    latest = await pipeline_dal.latest_material_set_snapshot(
        pool, account_id=principal.account_id, report_id=principal.report_id
    )
    assert latest is not None
    assert latest.snapshot.input_fingerprint == rebuilt.snapshot.input_fingerprint
    assert latest.snapshot.input_fingerprint != other_fingerprint
