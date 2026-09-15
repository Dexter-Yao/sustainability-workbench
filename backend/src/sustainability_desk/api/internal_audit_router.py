# ABOUTME: 内部审计包的受限运营读取 API，仅独立权限可跨 Account 查看与下载。
# ABOUTME: 客户交付物继续走报告所有者端点；本路由不暴露正文、trace、存储路径或普通报告编辑能力。
# ABOUTME(en): Restricted operator read API for internal audit packages; only a separate permission may cross Accounts.
# ABOUTME(en): Customer deliverables stay on owner endpoints; no prose, trace, storage path or report editing here.
from __future__ import annotations

from hashlib import sha256
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from sustainability_desk.accounts.service import (
    INTERNAL_AUDIT_REVIEWER_PERMISSION,
    AccountEntitlementError,
    AccountNotFoundError,
    get_account_context,
    has_account_permission,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.api.report_generation_router import (
    _safe_content_disposition,
    report_generation_artifact_reader,
)
from sustainability_desk.persistence import lightweight_report_generations as generations_dal
from sustainability_desk.persistence.db import get_pool
from sustainability_desk.contract.report_api import (
    InternalAuditArtifactListResponse,
    InternalAuditArtifactResponse,
)

router = APIRouter(prefix="/api/internal/audit-artifacts", tags=["internal-audit"])
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]


async def _require_internal_audit_reviewer(user: CurrentUser, pool: Pool) -> None:
    try:
        context = await get_account_context(pool, user.subject)
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="内部审计权限不可用")
    allowed = await has_account_permission(
        pool,
        account_id=context.account_id,
        permission=INTERNAL_AUDIT_REVIEWER_PERMISSION,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="无权读取内部审计包")


@router.get("")
async def list_audit_artifacts(
    user: CurrentUser, pool: Pool
) -> InternalAuditArtifactListResponse:
    await _require_internal_audit_reviewer(user, pool)
    artifacts = await generations_dal.list_internal_audit_artifacts(pool)
    return InternalAuditArtifactListResponse(
        artifacts=[
            InternalAuditArtifactResponse(
                artifact_id=item.artifact.artifact_id,
                report_id=item.report_id,
                report_title=item.report_title,
                account_email=item.account_email,
                filename=item.artifact.filename,
                created_at=item.created_at.isoformat(),
                download_href=f"/api/internal/audit-artifacts/{item.artifact.artifact_id}/download",
            )
            for item in artifacts
        ]
    )


@router.get("/{artifact_id}/download")
async def download_audit_artifact(
    artifact_id: UUID, user: CurrentUser, pool: Pool
) -> Response:
    await _require_internal_audit_reviewer(user, pool)
    try:
        item = await generations_dal.internal_audit_artifact_download_target(
            pool, artifact_id=artifact_id
        )
        content = await report_generation_artifact_reader().read(item.artifact.storage_ref)
    except generations_dal.ReportGenerationPersistenceError:
        raise HTTPException(status_code=404, detail="内部审计包不存在")
    if sha256(content).hexdigest() != item.artifact.content_fingerprint:
        raise HTTPException(status_code=409, detail="内部审计包完整性验证失败")
    return Response(
        content=content,
        media_type=item.artifact.media_type,
        headers={
            "Content-Disposition": _safe_content_disposition(item.artifact.filename),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
