# ABOUTME: 资料工作区的 Account/Report 受保护 HTTP 边界，映射上传、文件准入与来源生命周期操作。
# ABOUTME: 路由只做请求解析和错误语义；资料 SSOT、Storage 与原子报告写入由 MaterialWorkspaceService 拥有。
# ABOUTME(en): Account/Report-protected HTTP boundary of the material workspace: upload, file intake, source lifecycle.
# ABOUTME(en): Routes only parse requests and map errors; the material SSOT and Storage belong to the service.
from __future__ import annotations

import json
from typing import Annotated, Literal, Protocol
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    get_account_context,
    report_capabilities,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.contract.assessment_classify import InapplicableScoredTopicsError
from sustainability_desk.contract.report_profiles import (
    assert_report_profile_operation,
    knowledge_package_for_profile,
)
from sustainability_desk.contract.report_preparation import ReportPreparationProjection
from sustainability_desk.contract.report_lineage import ReportLineageProjection
from sustainability_desk.material.workspace import (
    MaterialAccessDeniedError,
    MaterialConflictError,
    MaterialNotFoundError,
    MaterialRequestError,
    MaterialServiceUnavailableError,
    MaterialWorkspaceService,
)
from sustainability_desk.material.intake.models import UserFileDeclaration
from sustainability_desk.material.intake.public_models import (
    MaterialSourceContentProjection,
    MaterialWorkspaceProjection,
    ReportFileIntakeProjection,
)
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.report_lineage import get_projection as get_lineage_projection
from sustainability_desk.persistence.db import get_pool

router = APIRouter(prefix="/api/reports/{report_id}", tags=["materials"])

Pool = Annotated[asyncpg.Pool, Depends(get_pool)]
ScopeKind = Literal["profile", "topics", "uncertain", "report"]


class MaterialService(Protocol):
    async def get_snapshot(self) -> dict: ...


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeRequest(StrictRequest):
    scope_kind: ScopeKind
    report_section_ids: list[str] = Field(default_factory=list)


class ReportFileDeclarationPatchRequest(StrictRequest):
    declaration: UserFileDeclaration
    expected_revision: int = Field(ge=1)


class PrimaryInputModeRequest(StrictRequest):
    """议题级主输入路径选择请求（资料工作区状态）。"""

    primary_input_mode: Literal["materials", "questions"]
    base_workspace_state_seq: int = Field(ge=1)


class ReportPrimaryInputModeRequest(StrictRequest):
    """报告级填报方式二选一请求；CAS 基线是报告状态而非资料工作区。"""

    primary_input_mode: Literal["materials", "questions"]
    base_report_state_seq: int = Field(ge=1)


class SourceReviewDecisionRequest(StrictRequest):
    decision: Literal["reviewed_accepted", "excluded_by_user"]
    reason: str = Field(min_length=1, max_length=1_000)
    expected_normalized_material_fingerprint: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


async def authorized_material_service(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
) -> MaterialWorkspaceService:
    """按 Report Profile 建立资料服务，禁止在两个 Adapter 间复用报告写入语义。"""
    try:
        context = await get_account_context(pool, user.subject)
        summary = await reports_dal.get_report_summary(
            pool, context.account_id, report_id
        )
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    except reports_dal.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    capabilities = report_capabilities(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )
    if not capabilities["material_agent_enabled"]:
        raise HTTPException(status_code=403, detail="当前报告未开通资料 Agent")
    try:
        assert_report_profile_operation(summary.report_profile_id, "report_flow")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return MaterialWorkspaceService(
        pool=pool,
        account_id=context.account_id,
        report_id=report_id,
        report_contract_version=summary.contract_version,
        knowledge_package=knowledge_package_for_profile(summary.report_profile_id),
        allowed_report_section_ids=frozenset(
            capabilities["allowed_report_section_ids"]
        ),
        # 定量信息不是生成门槛：留空按「尚未收集」在范围
        # 投影确定性补全；此处只保留目录收窄语义由 capabilities 另行投影。
        required_quantitative_metric_keys=None,
    )

Service = Annotated[MaterialWorkspaceService, Depends(authorized_material_service)]
WorkspaceProjection = MaterialWorkspaceProjection


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, MaterialNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, MaterialAccessDeniedError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, MaterialConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, MaterialRequestError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, MaterialServiceUnavailableError):
        return HTTPException(status_code=503, detail=str(error))
    # 资料链路要装配 Report 才能算映射范围，因此会遇到 contract 层的范围违例；
    # 它是用户可自行修复的输入问题，必须说清楚，不能穿透成无信息 500。
    if isinstance(error, InapplicableScoredTopicsError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "assessment_scope_mismatch",
                "message": error.message,
            },
        )
    raise error


async def _run(operation):
    try:
        return await operation
    except (
        MaterialNotFoundError,
        MaterialAccessDeniedError,
        MaterialConflictError,
        MaterialRequestError,
        MaterialServiceUnavailableError,
        InapplicableScoredTopicsError,
    ) as error:
        raise _translate(error)


def _section_ids(raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=422, detail="report_section_ids 必须是 JSON 数组"
        ) from error
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HTTPException(
            status_code=422, detail="report_section_ids 必须是字符串数组"
        )
    if len(value) != len(set(value)):
        raise HTTPException(status_code=422, detail="report_section_ids 不得重复")
    return tuple(value)


def _file_declarations(raw: str) -> tuple[UserFileDeclaration, ...]:
    """解析 multipart 中逐文件声明；文件与声明的等长关系由服务层裁决。"""

    try:
        value = json.loads(raw)
        return tuple(TypeAdapter(list[UserFileDeclaration]).validate_python(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=422,
            detail="文件说明必须是合法的逐文件声明数组",
        ) from error


@router.get("/material-workspace", response_model=WorkspaceProjection)
async def get_material_workspace(service: Service) -> WorkspaceProjection:
    return await _run(service.get_snapshot())


@router.get("/file-intake", response_model=ReportFileIntakeProjection)
async def get_report_file_intake(service: Service) -> ReportFileIntakeProjection:
    """准备中心读取文件准入投影；不返回旧工作台的范围、提案或解析正文。"""

    return await _run(service.get_report_file_intake())


@router.get("/preparation", response_model=ReportPreparationProjection)
async def get_report_preparation(
    service: Service,
) -> ReportPreparationProjection:
    """读取轻量版四类输入、最低生成资格与可选能力。"""
    return await _run(service.get_report_preparation())


@router.post(
    "/file-intake/files",
    status_code=201,
    response_model=ReportFileIntakeProjection,
)
async def upload_report_files(
    service: Service,
    files: Annotated[list[UploadFile], File()],
    declarations: Annotated[str, Form()],
) -> ReportFileIntakeProjection:
    return await _run(
        service.upload_report_files(
            files,
            declarations=_file_declarations(declarations),
        )
    )


@router.post(
    "/file-intake/confirm",
    response_model=ReportFileIntakeProjection,
)
async def confirm_material_set(service: Service) -> ReportFileIntakeProjection:
    """用户确认资料集齐备；说明未齐时返回 409，成功后对齐入队 File Agent。"""

    return await _run(service.confirm_material_set())


@router.patch(
    "/file-intake/files/{binding_id}",
    response_model=ReportFileIntakeProjection,
)
async def update_report_file_declaration(
    binding_id: UUID,
    request: ReportFileDeclarationPatchRequest,
    service: Service,
) -> ReportFileIntakeProjection:
    return await _run(
        service.update_report_file_declaration(
            binding_id,
            declaration=request.declaration,
            expected_revision=request.expected_revision,
        )
    )


class ReportFileSourceLabelRequest(StrictRequest):
    source_label: str = Field(min_length=1, max_length=140)


class LayoutAssetCaptionRequest(StrictRequest):
    caption: str = Field(min_length=1, max_length=50)


class LayoutAssetCertificateFactRequest(StrictRequest):
    """用户更正的证书事实；字段与入口解析同名，只收报告会呈现的三项加持证主体。"""

    certificate_name: str = Field(min_length=1, max_length=120)
    issuer: str | None = Field(default=None, max_length=120)
    covered_scope: str | None = Field(default=None, max_length=600)
    holder_name: str | None = Field(default=None, max_length=120)


@router.patch(
    "/file-intake/files/{binding_id}/label",
    response_model=ReportFileIntakeProjection,
)
async def update_report_file_source_label(
    binding_id: UUID,
    request: ReportFileSourceLabelRequest,
    service: Service,
) -> ReportFileIntakeProjection:
    """更新文件展示名;不产生声明修订,不影响确认状态与已完成的分析。"""

    return await _run(
        service.update_report_file_source_label(
            binding_id,
            source_label=request.source_label,
        )
    )


@router.get("/layout-assets/{asset_id}/image")
async def get_layout_asset_image(
    asset_id: UUID,
    service: Service,
) -> Response:
    """返回归一化原图,与 Word 导出同一图源。"""

    data, media_type = await _run(service.get_layout_asset_image(asset_id))
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.patch(
    "/layout-assets/{asset_id}/caption",
    response_model=ReportFileIntakeProjection,
)
async def update_layout_asset_caption(
    asset_id: UUID,
    request: LayoutAssetCaptionRequest,
    service: Service,
) -> ReportFileIntakeProjection:
    """用户改写题注;归属转为用户,识别重跑不再覆盖。"""

    return await _run(
        service.update_layout_asset_caption(asset_id, caption=request.caption)
    )


@router.patch(
    "/layout-assets/{asset_id}/certificate-fact",
    response_model=ReportFileIntakeProjection,
)
async def update_layout_asset_certificate_fact(
    asset_id: UUID,
    request: LayoutAssetCertificateFactRequest,
    service: Service,
) -> ReportFileIntakeProjection:
    """用户更正证书事实；归属转为用户，识别重跑不再覆盖。"""

    return await _run(
        service.update_layout_asset_certificate_fact(
            asset_id,
            certificate_fact=request.model_dump(),
        )
    )


@router.post(
    "/file-intake/files/{binding_id}/remove",
    response_model=ReportFileIntakeProjection,
)
async def remove_report_file(
    binding_id: UUID,
    service: Service,
) -> ReportFileIntakeProjection:
    return await _run(service.remove_report_file(binding_id))


@router.post(
    "/file-intake/files/{binding_id}/restore",
    response_model=ReportFileIntakeProjection,
)
async def restore_report_file(
    binding_id: UUID,
    service: Service,
) -> ReportFileIntakeProjection:
    return await _run(service.restore_report_file(binding_id))


@router.get("/report-lineage", response_model=ReportLineageProjection)
async def get_report_lineage(
    report_id: UUID,
    service: Service,
    pool: Pool,
) -> ReportLineageProjection:
    """返回同一报告授权用户可读的资料—输入—Block 谱系；不返回 Prompt 或原始对象路径。"""

    try:
        return await get_lineage_projection(
            pool,
            account_id=service.account_id,
            report_id=report_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

@router.post(
    "/material-sources",
    status_code=201,
    response_model=WorkspaceProjection,
)
async def upload_material_sources(
    service: Service,
    files: Annotated[list[UploadFile], File()],
    scope_kind: Annotated[Literal["profile", "topics", "uncertain"], Form()],
    report_section_ids: Annotated[str, Form()] = "[]",
) -> WorkspaceProjection:
    if not 1 <= len(files) <= 10:
        raise HTTPException(status_code=422, detail="每批必须上传 1 至 10 份资料")
    return await _run(
        service.upload_sources(
            files,
            scope_kind=scope_kind,
            report_section_ids=_section_ids(report_section_ids),
        )
    )


@router.get(
    "/material-sources/{source_id}/content",
    response_model=MaterialSourceContentProjection,
)
async def get_material_source_content(
    source_id: UUID, service: Service
) -> MaterialSourceContentProjection:
    return await _run(service.get_source_content(source_id))


@router.patch("/material-sources/{source_id}", response_model=WorkspaceProjection)
async def update_material_source(
    source_id: UUID, request: ScopeRequest, service: Service
) -> WorkspaceProjection:
    return await _run(
        service.update_source_metadata(
            source_id,
            scope_kind=request.scope_kind,
            report_section_ids=tuple(request.report_section_ids),
        )
    )


@router.delete("/material-sources/{source_id}", response_model=WorkspaceProjection)
async def delete_material_source(
    source_id: UUID, service: Service
) -> WorkspaceProjection:
    return await _run(service.delete_source(source_id))


@router.post(
    "/material-sources/{source_id}/review-decision",
    response_model=WorkspaceProjection,
)
async def record_material_source_review_decision(
    source_id: UUID,
    request: SourceReviewDecisionRequest,
    service: Service,
) -> WorkspaceProjection:
    """记录绑定当前解析指纹的人类裁决，供后续运行冻结消费。"""

    return await _run(
        service.record_source_review_decision(
            source_id,
            decision=request.decision,
            actor="user",
            reason=request.reason,
            expected_normalized_material_fingerprint=(
                request.expected_normalized_material_fingerprint
            ),
        )
    )


@router.patch(
    "/material-topics/{report_section_id}/primary-input-mode",
    response_model=MaterialWorkspaceProjection,
)
async def update_material_topic_primary_input_mode(
    report_section_id: str,
    request: PrimaryInputModeRequest,
    service: Service,
) -> MaterialWorkspaceProjection:
    return await _run(
        service.update_topic_primary_input_mode(
            report_section_id,
            primary_input_mode=request.primary_input_mode,
            base_workspace_state_seq=request.base_workspace_state_seq,
        )
    )


@router.patch(
    "/primary-input-mode",
    response_model=MaterialWorkspaceProjection,
)
async def update_report_primary_input_mode(
    request: ReportPrimaryInputModeRequest,
    service: Service,
) -> MaterialWorkspaceProjection:
    """报告级主输入路径二选一；只改分步流编排，不改写任何已填输入。"""
    return await _run(
        service.update_report_primary_input_mode(
            primary_input_mode=request.primary_input_mode,
            base_report_state_seq=request.base_report_state_seq,
        )
    )
