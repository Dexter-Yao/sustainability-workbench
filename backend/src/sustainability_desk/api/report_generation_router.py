# ABOUTME: 轻量版报告级生成的受保护 HTTP 边界，提供创建、进度查询和客户交付物下载。
# ABOUTME: 路由只暴露公共投影；内部审计包、Storage 引用、Prompt、成本与 debug 均不可达。
# ABOUTME(en): Protected HTTP boundary for lightweight report-level generation: create, poll progress, download.
# ABOUTME(en): Routes expose public projections only; audit packages, Storage refs, prompts, cost and debug stay out.
from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    get_account_context,
    report_capabilities,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.contract.assessment_classify import InapplicableScoredTopicsError
from sustainability_desk.contract.block_provenance import ReportBlockProvenanceProjection
from sustainability_desk.contract.report_generation import (
    CreateReportGenerationRequest,
    ReportGenerationProjection,
)
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    require_report_profile,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import get_pool
from sustainability_desk.report_projection import (
    ReportGenerationArtifactIntegrityError,
    ReportGenerationArtifactNotFoundError,
    ReportGenerationArtifactReader,
    ReportGenerationConflictError,
    ReportGenerationEnqueuePort,
    ReportGenerationNotFoundError,
    LightweightReportGenerationService,
)
from sustainability_desk.lightweight_report_generation import (
    ReportGenerationInputNotReadyError,
    enqueue_report_generation,
    report_artifact_root,
)

router = APIRouter(
    prefix="/api/reports/{report_id}/generations",
    tags=["report-generations"],
)
Pool = Annotated[asyncpg.Pool, Depends(get_pool)]


class _GenerationCommandPort:
    """把 HTTP 命令交给唯一生成准备服务，不复制快照或指纹语义。"""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def enqueue(
        self,
        *,
        account_id: UUID,
        report_id: UUID,
        request: CreateReportGenerationRequest,
    ) -> UUID:
        try:
            return await enqueue_report_generation(
                self._pool,
                account_id=account_id,
                report_id=report_id,
                request=request,
            )
        except ReportGenerationInputNotReadyError as error:
            raise ReportGenerationConflictError(str(error)) from error


class _LocalArtifactReader:
    """读取报告私有产物根目录；持久化引用不能逃逸该目录。"""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or report_artifact_root()).resolve()

    async def read(self, storage_ref: str) -> bytes:
        target = (self._root / storage_ref).resolve()
        if target == self._root or self._root not in target.parents:
            raise ReportGenerationArtifactNotFoundError("报告交付物不存在")
        try:
            return target.read_bytes()
        except (FileNotFoundError, IsADirectoryError, OSError) as error:
            raise ReportGenerationArtifactNotFoundError(
                "报告交付物不存在"
            ) from error


def report_generation_enqueue_port(pool: Pool) -> ReportGenerationEnqueuePort:
    """接入拥有资格、资料快照、指纹与幂等语义的生成准备服务。"""

    return _GenerationCommandPort(pool)


def report_generation_artifact_reader() -> ReportGenerationArtifactReader:
    """接入本地私有交付物根目录。"""

    return _LocalArtifactReader()


EnqueuePort = Annotated[
    ReportGenerationEnqueuePort,
    Depends(report_generation_enqueue_port),
]
ArtifactReader = Annotated[
    ReportGenerationArtifactReader,
    Depends(report_generation_artifact_reader),
]


async def authorized_report_projection(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    enqueue_port: EnqueuePort,
    artifact_reader: ArtifactReader,
) -> LightweightReportGenerationService:
    try:
        context = await get_account_context(pool, user.subject)
        summary = await reports_dal.get_report_summary(
            pool,
            context.account_id,
            report_id,
        )
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    except reports_dal.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        profile = require_report_profile(summary.report_profile_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if profile.report_type != DEFAULT_CUSTOMER_REPORT_TYPE:
        raise HTTPException(
            status_code=409,
            detail="该端点仅支持轻量版报告生成",
        )
    capabilities = report_capabilities(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )
    if not capabilities["can_generate"]:
        raise HTTPException(status_code=403, detail="当前 Account 无权生成该报告")
    return LightweightReportGenerationService(
        pool=pool,
        account_id=context.account_id,
        report_id=report_id,
        workbench_enabled=profile.workbench_enabled,
        enqueue_port=enqueue_port,
        artifact_reader=artifact_reader,
        allowed_artifact_kinds=frozenset(
            capabilities["allowed_report_artifact_kinds"]
        ),
    )


Service = Annotated[
    LightweightReportGenerationService,
    Depends(authorized_report_projection),
]


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, ReportGenerationNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ReportGenerationArtifactNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ReportGenerationConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ReportGenerationArtifactIntegrityError):
        return HTTPException(status_code=409, detail=str(error))
    # 存量报告仍可能持有范围外评分（写入边界只拦新写入）；告知用户具体议题与
    # 恢复方式，不留下无信息 500。
    if isinstance(error, InapplicableScoredTopicsError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "assessment_scope_mismatch",
                "message": error.message,
            },
        )
    raise error


def _safe_content_disposition(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    clean = "".join(
        character
        for character in leaf
        if ord(character) >= 32 and ord(character) != 127
    ).strip()
    if not clean:
        clean = "sustainability-desk-report-artifact"
    encoded = quote(clean, safe="!#$&+-.^_`|~")
    return (
        "attachment; filename=sustainability-desk-report-artifact; "
        f"filename*=UTF-8''{encoded}"
    )


@router.post(
    "",
    response_model=ReportGenerationProjection,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report_generation(
    request: CreateReportGenerationRequest,
    service: Service,
) -> ReportGenerationProjection:
    try:
        return await service.create_generation(request)
    except Exception as error:
        raise _translate(error)


@router.get(
    "/latest",
    response_model=ReportGenerationProjection,
)
async def get_latest_report_generation(
    service: Service,
) -> ReportGenerationProjection:
    try:
        return await service.get_latest_generation()
    except Exception as error:
        raise _translate(error)


@router.get(
    "/latest/block-provenance",
    response_model=ReportBlockProvenanceProjection,
)
async def get_latest_block_provenance(
    service: Service,
) -> ReportBlockProvenanceProjection:
    """Per-block provenance of the latest successful revision; codes and display names only."""

    try:
        return await service.get_block_provenance()
    except Exception as error:
        raise _translate(error)


@router.get(
    "/{run_id}",
    response_model=ReportGenerationProjection,
)
async def get_report_generation(
    run_id: UUID,
    service: Service,
) -> ReportGenerationProjection:
    try:
        return await service.get_generation(run_id)
    except Exception as error:
        raise _translate(error)


@router.get("/{run_id}/artifacts/{artifact_id}/download")
async def download_report_artifact(
    run_id: UUID,
    artifact_id: UUID,
    service: Service,
) -> Response:
    try:
        artifact = await service.download_artifact(
            run_id=run_id,
            artifact_id=artifact_id,
        )
    except Exception as error:
        raise _translate(error)
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": _safe_content_disposition(
                artifact.filename
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
