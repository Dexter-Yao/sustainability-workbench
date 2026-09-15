# ABOUTME: 权益 Grant 的唯一写入口：显式结束当前 Grant 并创建新 Grant，同事务写账户事件。
# ABOUTME: 本机单用户模式下由测试账号引导与测试直接调用；不含任何注册、验证或开通语义。
# ABOUTME(en): Only write entry point for entitlement Grants: ends the current Grant, creates a new one,
# ABOUTME(en): writes the account event in one transaction. No signup, verification or activation logic.
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from sustainability_desk.accounts.entitlement_profiles import require_profile


async def grant_profile(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    profile_id: str,
    ends_at: datetime | None,
    granted_by: str,
    reason: str,
) -> UUID:
    """显式结束当前 Grant 并创建新 Grant。"""
    require_profile(profile_id)
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn, conn.transaction():
        exists = await conn.fetchval("select 1 from accounts where id = $1 for update", account_id)
        if exists is None:
            raise ValueError("Account 不存在")
        await conn.execute(
            "update account_entitlement_grants set ended_at = $2 where account_id = $1 and ended_at is null",
            account_id,
            now,
        )
        grant_id = await conn.fetchval(
            """
            insert into account_entitlement_grants (
              account_id, profile_id, starts_at, ends_at, granted_by, reason
            ) values ($1, $2, $3, $4, $5, $6)
            returning id
            """,
            account_id,
            profile_id,
            now,
            ends_at,
            granted_by,
            reason,
        )
        await conn.execute(
            """
            insert into account_events (account_id, actor, event_type, payload)
            values ($1, 'operator', 'entitlement_granted', $2)
            """,
            account_id,
            {"grantId": str(grant_id), "profileId": profile_id, "reason": reason},
        )
    return grant_id
