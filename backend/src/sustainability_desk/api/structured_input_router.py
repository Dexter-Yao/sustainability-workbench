# ABOUTME: 轻量版 report-bound 结构化输入 API，统一目录、当前值、模板、在线整批写入与 xlsx 原子导入。
# ABOUTME: HTTP 层只处理身份、文件边界和 typed 错误；适用性、期间、单位、freshness 与 CAS 由服务端拥有。
# ABOUTME(en): Lightweight report-bound structured input API: catalog, current values, templates, writes, xlsx import.
# ABOUTME(en): HTTP handles identity, file bounds and typed errors; applicability, period, units, CAS are server-owned.
from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from sustainability_desk.contract.product_name import workbook_content_disposition
from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    get_account_context,
    effective_report_scope,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.contract.models import MaterialityThreshold
from sustainability_desk.contract.report_api import (
    AssessmentInputResponse,
    PutAssessmentInputRequest,
    PutQuantitativeMetricsRequest,
    QuantitativeMetricsResponse,
    StructuredInputErrorResponse,
    StructuredInputMutationResponse,
    StructuredInputPreconditionResponse,
)
from sustainability_desk.contract.structured_inputs import StructuredInputWorkbookError
from sustainability_desk.accounts.report_execution_scope import execution_scope_kind_for_profile
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    default_report_profile_id,
    knowledge_package_for_profile,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.db import get_pool
from sustainability_desk.structured_input_service import (
    StructuredInputRequestError,
    StructuredInputService,
    blank_unified_workbook_template,
)

router = APIRouter(
    prefix="/api/reports/{report_id}/structured-inputs",
    tags=["structured-inputs"],
)

# 账户级结构化输入面：唯一成员是不绑定报告的空白统一填报工作簿模板。
account_router = APIRouter(
    prefix="/api/structured-inputs",
    tags=["structured-inputs"],
)

Pool = Annotated[asyncpg.Pool, Depends(get_pool)]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_STRUCTURED_INPUT_BYTES = 20 * 1024 * 1024
STRUCTURED_INPUT_409_RESPONSES = {
    409: {"model": StructuredInputErrorResponse},
}


async def _service(
    *,
    report_id: UUID,
    user: CurrentUser,
    pool: asyncpg.Pool,
) -> StructuredInputService:
    try:
        context = await get_account_context(pool, user.subject)
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "account_access_denied",
                "message": "Account 权益状态异常。",
            },
        ) from None
    if not context.capabilities()["can_edit_existing"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "report_edit_denied",
                "message": "Account 当前不能访问报告。",
            },
        )
    try:
        summary = await reports_dal.get_report_summary(
            pool, context.account_id, report_id
        )
    except reports_dal.ReportNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"code": "report_not_found", "message": "报告不存在。"},
        ) from None
    return StructuredInputService(
        pool=pool,
        account_id=context.account_id,
        report_id=report_id,
        execution_scope=effective_report_scope(
            context,
            created_under_profile_id=summary.created_under_profile_id,
            report_profile_id=summary.report_profile_id,
        ),
        knowledge_package=knowledge_package_for_profile(summary.report_profile_id),
    )


async def _raise_domain_error(
    error: Exception,
    *,
    service: StructuredInputService,
) -> JSONResponse:
    if isinstance(error, reports_dal.ReportNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "report_not_found", "message": "报告不存在。"},
        ) from error
    if isinstance(error, reports_dal.ReportProfileMismatchError):
        response = StructuredInputPreconditionResponse(
            code="simplified_v4_required",
            message="结构化输入仅适用于轻量版 V4 报告，请使用对应报告流程。",
        )
        return JSONResponse(
            status_code=409,
            content=response.model_dump(mode="json"),
        )
    if isinstance(error, reports_dal.StateConflictError):
        conflict = await service.conflict_response(error)
        return JSONResponse(
            status_code=409,
            content=conflict.model_dump(mode="json"),
        )
    if isinstance(error, StructuredInputWorkbookError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "structured_input_workbook_invalid",
                "message": "工作簿未通过完整校验，未写入任何数据。",
                "errors": [
                    item.model_dump(mode="json") for item in error.errors
                ],
            },
        ) from error
    if isinstance(error, StructuredInputRequestError):
        # *_not_available 是范围拒绝（评分不收集 / 基础资料工作簿不在范围内），统一 403。
        if error.code.endswith("_not_available"):
            raise HTTPException(
                status_code=403,
                detail={"code": error.code, "message": error.message},
            ) from error
        if error.code == "contract_upgrade_required":
            response = StructuredInputPreconditionResponse(
                code="contract_upgrade_required",
                message=error.message,
            )
            return JSONResponse(
                status_code=409,
                content=response.model_dump(mode="json"),
            )
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": error.message},
        ) from error
    raise error


async def _read_limited_xlsx(file: UploadFile) -> bytes:
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=415,
            detail={
                "code": "xlsx_required",
                "message": "结构化输入文件必须为 .xlsx。",
            },
        )
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_STRUCTURED_INPUT_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "structured_input_too_large",
                    "message": "结构化输入文件不得超过 20MB。",
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get(
    "/assessment",
    response_model=AssessmentInputResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_assessment(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> AssessmentInputResponse | JSONResponse:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.assessment()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/assessment/template",
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_assessment_template(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> Response:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        content = await service.assessment_template()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("重要性评分表", "materiality-scoring"),
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "/assessment",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def put_assessment(
    report_id: UUID,
    request: PutAssessmentInputRequest,
    user: CurrentUser,
    pool: Pool,
) -> StructuredInputMutationResponse | JSONResponse:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.put_assessment(request)
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.post(
    "/assessment/import",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def import_assessment(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    file: UploadFile = File(...),
    expected_state_seq: int = Form(ge=1),
    financial_threshold: float = Form(),
    impact_threshold: float = Form(),
) -> StructuredInputMutationResponse | JSONResponse:
    content = await _read_limited_xlsx(file)
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.import_assessment(
            content=content,
            expected_state_seq=expected_state_seq,
            threshold=MaterialityThreshold(
                financial=financial_threshold,
                impact=impact_threshold,
            ),
        )
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/quantitative-metrics",
    response_model=QuantitativeMetricsResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_quantitative_metrics(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> QuantitativeMetricsResponse | JSONResponse:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.quantitative_metrics()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/quantitative-metrics/template",
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_quantitative_template(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> Response:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        content = await service.quantitative_template()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("ESG定量信息表", "quantitative-metrics"),
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "/quantitative-metrics",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def put_quantitative_metrics(
    report_id: UUID,
    request: PutQuantitativeMetricsRequest,
    user: CurrentUser,
    pool: Pool,
) -> StructuredInputMutationResponse | JSONResponse:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.put_quantitative_metrics(request)
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.post(
    "/quantitative-metrics/import",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def import_quantitative_metrics(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    file: UploadFile = File(...),
    expected_state_seq: int = Form(ge=1),
) -> StructuredInputMutationResponse | JSONResponse:
    content = await _read_limited_xlsx(file)
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.import_quantitative_metrics(
            content=content,
            expected_state_seq=expected_state_seq,
        )
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/unified-workbook/template",
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_unified_workbook_template(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> Response:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        content = await service.unified_workbook_template()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("统一填报工作簿", "unified-workbook"),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/unified-workbook/import",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def import_unified_workbook(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    file: UploadFile = File(...),
    expected_state_seq: int = Form(ge=1),
    financial_threshold: float | None = Form(default=None),
    impact_threshold: float | None = Form(default=None),
) -> StructuredInputMutationResponse | JSONResponse:
    content = await _read_limited_xlsx(file)
    service = await _service(report_id=report_id, user=user, pool=pool)
    threshold = (
        MaterialityThreshold(
            financial=financial_threshold,
            impact=impact_threshold,
        )
        if financial_threshold is not None and impact_threshold is not None
        else None
    )
    try:
        return await service.import_unified_workbook(
            content=content,
            expected_state_seq=expected_state_seq,
            threshold=threshold,
        )
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/report-basics/template",
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_report_basics_template(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> Response:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        content = await service.report_basics_template()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("企业及报告基本信息表", "report-basics"),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/report-basics/import",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def import_report_basics(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    file: UploadFile = File(...),
    expected_state_seq: int = Form(ge=1),
) -> StructuredInputMutationResponse | JSONResponse:
    content = await _read_limited_xlsx(file)
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.import_report_basics(
            content=content,
            expected_state_seq=expected_state_seq,
        )
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)


@router.get(
    "/topic-questions/template",
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def get_topic_questions_template(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> Response:
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        content = await service.topic_questions_template()
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("议题信息填写表", "topic-questions"),
            "Cache-Control": "no-store",
        },
    )


@account_router.get("/unified-workbook/blank-template")
async def get_unified_workbook_blank_template(
    user: CurrentUser,
    pool: Pool,
) -> Response:
    """账户级空白统一填报工作簿：不绑定报告；导入时任选目标报告并按覆盖语义写入。"""

    try:
        context = await get_account_context(pool, user.subject)
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "account_access_denied",
                "message": "Account 权益状态异常。",
            },
        ) from None
    if execution_scope_kind_for_profile(context.profile_id) != "full_simplified":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "unified_workbook_not_available",
                "message": "当前账户范围不提供统一填报工作簿。",
            },
        )
    # The account-level blank master follows the default package new reports are created on.
    content = await asyncio.to_thread(
        blank_unified_workbook_template,
        knowledge_package_for_profile(default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE)),
    )
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": workbook_content_disposition("统一填报工作簿模板", "unified-workbook-template"),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/topic-questions/import",
    response_model=StructuredInputMutationResponse,
    responses=STRUCTURED_INPUT_409_RESPONSES,
)
async def import_topic_questions(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    file: UploadFile = File(...),
    expected_state_seq: int = Form(ge=1),
) -> StructuredInputMutationResponse | JSONResponse:
    content = await _read_limited_xlsx(file)
    service = await _service(report_id=report_id, user=user, pool=pool)
    try:
        return await service.import_topic_questions(
            content=content,
            expected_state_seq=expected_state_seq,
        )
    except Exception as error:  # noqa: BLE001 - 单一 typed HTTP 投影边界
        return await _raise_domain_error(error, service=service)
