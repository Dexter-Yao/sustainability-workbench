# ABOUTME: Account bootstrap、Grant 与活跃报告上限的本地 Supabase 集成测试。
# ABOUTME: 本地栈未启动时跳过；测试只创建自身 Auth/Account 数据并在结束时清理。
from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from sustainability_desk.accounts.grants import grant_profile
from sustainability_desk.accounts.service import active_report_slot_limit, get_account_context, report_capabilities
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.topic_registry import all_report_sections
from sustainability_desk.accounts.service import PRIMARY_IDENTITY_ISSUER
from sustainability_desk.persistence import reports
from sustainability_desk.persistence.db import _init_connection
from knowledge_package_fixtures import SSE_PACKAGE, SSE_REPORT_PROFILE_ID

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
STATE_V4 = {"version": 4, "fields": {}, "intakeItems": {}, "generatedBlocks": {}, "tableBlocks": {}}


@pytest.fixture
async def pool():
    try:
        value = await asyncpg.create_pool(LOCAL_DB, min_size=1, max_size=3, init=_init_connection, timeout=3)
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield value
    await value.close()


@pytest.fixture
async def verified_subject(pool):
    subject = uuid4()
    email = f"account-{subject}@example.edu.cn"
    await pool.execute(
        "insert into auth.users (id, email, email_confirmed_at) values ($1, $2, now())",
        subject,
        email,
    )
    yield subject, email
    account_id = await pool.fetchval(
        "select account_id from account_identities where identity_subject = $1", subject
    )
    if account_id:
        await pool.execute("delete from accounts where id = $1", account_id)
    await pool.execute("delete from auth.users where id = $1", subject)


async def _bootstrap(pool, subject, email, *, profile_id="local_single_user@1", ends_at=None):
    """本机单用户模式：直接建立 Account 与身份映射并授予档位（与 ops.bootstrap_internal_accounts 同一落库形态）。"""
    async with pool.acquire() as conn, conn.transaction():
        account_id = await conn.fetchval(
            "insert into accounts (email, organization_name) values ($1, $2) returning id",
            email,
            "测试机构",
        )
        await conn.execute(
            "insert into account_identities (account_id, identity_issuer, identity_subject) values ($1, $2, $3)",
            account_id,
            PRIMARY_IDENTITY_ISSUER,
            subject,
        )
    await grant_profile(
        pool,
        account_id=account_id,
        profile_id=profile_id,
        ends_at=ends_at,
        granted_by="test",
        reason="local_test_bootstrap",
    )
    return await get_account_context(pool, subject)


def _state() -> dict[str, object]:
    return STATE_V4.copy()


async def _create(pool, context, *, title: str, classification: str = "customer"):
    return await reports.create_report(
        pool,
        account_id=context.account_id,
        title=title,
        report_type="lightweight",
        report_profile_id="sse_zh_hans@1",
        data_classification=classification,
        contract_version=contract_version(SSE_PACKAGE),
        initial_state=_state(),
        active_scope_limit=active_report_slot_limit(
            context, created_under_profile_id=context.profile_id
        ),
        profile_id=context.profile_id,
    )


async def test_bootstrap_projects_full_simplified_scope(pool, verified_subject) -> None:
    subject, email = verified_subject
    context = await _bootstrap(pool, subject, email)
    assert context.profile_id == "local_single_user@1"
    capabilities = report_capabilities(context, created_under_profile_id=context.profile_id, report_profile_id=SSE_REPORT_PROFILE_ID)
    assert capabilities["allowed_report_section_ids"] == [
        section.id for section in all_report_sections(SSE_PACKAGE)
    ]
    assert context.capabilities()["active_report_limit"] == 20


async def test_active_report_limit_is_enforced_by_current_profile(pool, verified_subject) -> None:
    subject, email = verified_subject
    context = await _bootstrap(pool, subject, email)
    limit = context.profile.active_report_limit
    for index in range(limit):
        result = await _create(pool, context, title=f"报告 {index}")
        assert result.created_under_profile_id == "local_single_user@1"
    with pytest.raises(reports.ActiveReportLimitError):
        await _create(pool, context, title="超额报告")
