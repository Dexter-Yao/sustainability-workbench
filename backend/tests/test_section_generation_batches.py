# ABOUTME: 整节生成批次数据库集成测试——初次不计、成功才计、并发预留、租约释放与 state_seq 原子性。
# ABOUTME: 直连本地 Supabase；不调用真实模型，本地栈未启动时整组跳过。
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest

from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import _init_connection
from sustainability_desk.persistence.section_generations import (
    GenerationAlreadyRunningError,
    GenerationBatchStatusConflictError,
    GenerationIdempotencyConflictError,
    GenerationQuotaExceededError,
    GenerationStateConflictError,
    complete_batch,
    fail_batch,
    reserve_batch,
    rewrite_allowance,
)
from knowledge_package_fixtures import SSE_PACKAGE

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
STATE = {
    "version": 4,
    "fields": {},
    "intakeItems": {},
    "generatedBlocks": {},
    "tableBlocks": {},
}
EXPECTED = ("climate_change.gov_structure",)
RESULTS = [
    {
        "blockId": EXPECTED[0],
        "kind": "paragraph",
        "status": "ready",
        "variants": [{"displayTitle": None, "content": "生成正文"}],
    }
]


@pytest.fixture
async def pool():
    try:
        value = await asyncpg.create_pool(
            LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3
        )
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield value
    await value.close()


@pytest.fixture
async def account(pool):
    account_id = uuid4()
    await pool.execute(
        "insert into accounts (id, email) values ($1, $2)",
        account_id,
        f"{account_id}@example.edu.cn",
    )
    yield account_id
    await pool.execute("delete from accounts where id = $1", account_id)


async def _report(pool, account_id):
    return await reports_dal.create_report(
        pool,
        account_id=account_id,
        title="批次测试",
        report_type="lightweight",
        report_profile_id="sse_zh_hans@1",
        data_classification="customer",
        contract_version=contract_version(SSE_PACKAGE),
        initial_state=STATE,
        active_scope_limit=5,
        profile_id="local_single_user@1",
    )


async def _reserve(pool, account_id, report_id, seq, *, key=None, quota=3):
    return await reserve_batch(
        pool,
        account_id=account_id,
        report_id=report_id,
        section_key="climate_change",
        expected_block_ids=EXPECTED,
        idempotency_key=key or uuid4(),
        base_state_seq=seq,
        regeneration_quota=quota,
        input_fingerprint="a" * 64,
    )


async def test_initial_is_free_and_only_successful_regenerations_consume(pool, account):
    report = await _report(pool, account)
    seq = 1
    initial = await _reserve(pool, account, report.id, seq)
    assert initial.mode == "initial"
    seq = await complete_batch(pool, batch=initial, results=RESULTS, package=SSE_PACKAGE)
    allowance = await rewrite_allowance(
        pool, report_id=report.id, section_key="climate_change", quota=3
    )
    assert (allowance.used, allowance.remaining) == (0, 3)

    failed = await _reserve(pool, account, report.id, seq)
    assert failed.mode == "regeneration"
    await fail_batch(pool, failed.id, "block_failed")
    allowance = await rewrite_allowance(
        pool, report_id=report.id, section_key="climate_change", quota=3
    )
    assert (allowance.used, allowance.reserved, allowance.remaining) == (0, 0, 3)

    for used in range(1, 4):
        batch = await _reserve(pool, account, report.id, seq)
        seq = await complete_batch(pool, batch=batch, results=RESULTS, package=SSE_PACKAGE)
        allowance = await rewrite_allowance(
            pool, report_id=report.id, section_key="climate_change", quota=3
        )
        assert allowance.used == used
    with pytest.raises(GenerationQuotaExceededError):
        await _reserve(pool, account, report.id, seq)


async def test_active_batch_reserves_section_and_expired_lease_releases(pool, account):
    report = await _report(pool, account)
    active = await _reserve(pool, account, report.id, 1)
    with pytest.raises(GenerationAlreadyRunningError):
        await _reserve(pool, account, report.id, 1)
    await pool.execute(
        "update section_regeneration_batches set lease_expires_at = $2 where id = $1",
        active.id,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    replacement = await _reserve(pool, account, report.id, 1)
    assert replacement.mode == "initial"
    assert (
        await pool.fetchval(
            "select status from section_regeneration_batches where id = $1", active.id
        )
        == "failed"
    )


async def test_expired_batch_cannot_patch_report_even_without_replacement(
    pool, account
):
    report = await _report(pool, account)
    batch = await _reserve(pool, account, report.id, 1)
    await pool.execute(
        "update section_regeneration_batches set lease_expires_at = $2 where id = $1",
        batch.id,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(GenerationBatchStatusConflictError):
        await complete_batch(pool, batch=batch, results=RESULTS, package=SSE_PACKAGE)
    state = await reports_dal.get_state(pool, account, report.id)
    assert state.state["generatedBlocks"] == {}
    assert (
        await pool.fetchval(
            "select status from section_regeneration_batches where id = $1", batch.id
        )
        == "failed"
    )


async def test_state_conflict_fails_batch_without_patching_report(pool, account):
    report = await _report(pool, account)
    batch = await _reserve(pool, account, report.id, 1)
    await reports_dal.put_state(
        pool, account, report.id, {**STATE, "fields": {"x": 1}}, 1
    )
    with pytest.raises(GenerationStateConflictError):
        await complete_batch(pool, batch=batch, results=RESULTS, package=SSE_PACKAGE)
    state = await reports_dal.get_state(pool, account, report.id)
    assert state.state["fields"] == {"x": 1}
    assert state.state["generatedBlocks"] == {}
    assert (
        await pool.fetchval(
            "select status from section_regeneration_batches where id = $1", batch.id
        )
        == "failed"
    )


async def test_idempotency_replay_and_cross_report_reuse_rejected(pool, account):
    first = await _report(pool, account)
    second = await _report(pool, account)
    key = uuid4()
    batch = await _reserve(pool, account, first.id, 1, key=key)
    await complete_batch(pool, batch=batch, results=RESULTS, package=SSE_PACKAGE)
    replay = await _reserve(pool, account, first.id, 1, key=key)
    assert replay.replayed is True and replay.id == batch.id
    with pytest.raises(GenerationIdempotencyConflictError):
        await _reserve(pool, account, second.id, 1, key=key)
