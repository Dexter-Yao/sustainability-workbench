# ABOUTME: 账户 API：当前账户的权益与能力投影、首次引导已读状态。
# ABOUTME: 本机单用户模式没有注册、验证与开通端点；账号只由 ops.bootstrap_internal_accounts 建立。
# ABOUTME(en): Account API: entitlement and capability projection of the current account, plus onboarding seen state.
# ABOUTME(en): Local single-user mode has no signup or activation endpoints; accounts come only from ops bootstrap.
from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.accounts.service import (
    INTERNAL_AUDIT_REVIEWER_PERMISSION,
    AccountEntitlementError,
    AccountNotFoundError,
    get_account_context,
    has_account_permission,
    touch_account_activity,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.persistence.db import get_pool

router = APIRouter(prefix="/api/account", tags=["account"])
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]


@router.get("")
async def current_account(user: CurrentUser, pool: Pool) -> dict[str, object]:
    try:
        context = await get_account_context(pool, user.subject)
        context = await touch_account_activity(pool, context)
    except AccountNotFoundError:
        raise HTTPException(status_code=404, detail="Account 尚未建立")
    except AccountEntitlementError:
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    projection = context.api_projection()
    projection["capabilities"]["can_review_internal_audit"] = await has_account_permission(
        pool,
        account_id=context.account_id,
        permission=INTERNAL_AUDIT_REVIEWER_PERMISSION,
    )
    return projection


class OnboardingSeenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # coach mark 步骤 key 由前端界面拥有；后端只约束格式与规模，不硬编码步骤集。
    steps: list[str] = Field(max_length=32)


@router.put("/onboarding-seen")
async def put_onboarding_seen(
    request: OnboardingSeenRequest, user: CurrentUser, pool: Pool
) -> dict[str, object]:
    """全量替换首次引导已读步骤（design.md §6.1）；空数组即「重新开启引导」。"""

    for step in request.steps:
        if not step or len(step) > 64:
            raise HTTPException(status_code=422, detail="步骤 key 必须为 1–64 字符")
    try:
        context = await get_account_context(pool, user.subject)
    except AccountNotFoundError:
        raise HTTPException(status_code=404, detail="Account 尚未建立")
    except AccountEntitlementError:
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    seen = sorted(set(request.steps))
    await pool.execute(
        "update accounts set onboarding_seen = $2 where id = $1",
        context.account_id,
        seen,
    )
    return {"onboarding_seen": seen}
