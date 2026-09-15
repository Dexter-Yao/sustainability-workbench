# ABOUTME: 报告创建与轻量版状态快照端点——JWT 保护的创建、列表、归档与乐观锁编辑。
# ABOUTME: 报告准备状态按 Profile 解析；写入经乐观锁 base_seq 校验。
# ABOUTME(en): Report creation and lightweight state snapshot endpoints — JWT-protected create, list, archive, edit.
# ABOUTME(en): Report preparation state resolves per Profile; writes are checked against the optimistic base_seq.
from __future__ import annotations

import logging
from functools import partial
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    CapabilityDeniedError,
    effective_report_profile,
    get_account_context,
    report_capabilities,
    active_report_slot_limit,
    require_report_creation,
)
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.contract.api_error import api_error
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.report_api import (
    GenerationModelOption,
    GenerationModelOptionsResponse,
    PutReportStateResponse,
    ReportListResponse,
    ReportStateResponse,
    ReportSummaryResponse,
    RewriteAllowanceResponse,
    ReportProfileOption,
    ReportProfileOptionsResponse,
)
from sustainability_desk.llm.model_registry import (
    get_spec,
    resolve_default_model_id,
    selectable_generation_model_ids,
)
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    ReportType,
    assert_report_profile_operation,
    default_report_profile_id,
    knowledge_package_for_profile,
    load_report_profile_registry,
    require_report_profile,
)
from sustainability_desk.contract.new_report_state import new_report_state
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.assessment_classify import inapplicable_scored_topics
from sustainability_desk.contract.report_values import is_valid_contact_email
from sustainability_desk.contract.topic_registry import applicability_facts_from_values
from sustainability_desk.material.intake.storage import MaterialStorageClient, MaterialStorageError
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence import section_generations
from sustainability_desk.persistence.db import get_pool
from sustainability_desk.persistence.settings import persistence_settings

logger = logging.getLogger("sustainability_desk.reports_router")

router = APIRouter(prefix="/api/reports", tags=["reports"])

Pool = Annotated[asyncpg.Pool, Depends(get_pool)]

class CreateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: ReportType = DEFAULT_CUSTOMER_REPORT_TYPE
    # Registered report Profile (knowledge package × product semantics). Omitted → the server
    # default for the report type; a Profile of another report type is rejected.
    report_profile_id: str | None = Field(default=None, pattern=r"^[a-z_]+@[1-9][0-9]*$")
    title: str = Field(default="未命名报告", min_length=1, max_length=200)
    # 本报告承载的是真实企业数据还是合成测试数据。默认 customer：漏声明时按真实客户
    # 处理是安全的一侧，反之会让客户数据落到宽松治理口径。
    data_classification: Literal["synthetic", "customer"] = "customer"


class PutStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: StoredReportStateV4
    base_seq: int = Field(ge=1)


def _initial_state(report_type: ReportType, package: KnowledgePackage) -> dict[str, Any]:
    """新报告的首个状态：字段集与默认值都取自该报告的知识包。

    由服务端产出而非客户端送入：客户端只有一份静态合同投影
    （`frontend/public/contract.json`，上交所简体），拿它初始化会把内地包独有字段
    （科技伦理适用范围、董事会出席率等）写进港交所报告，而 `plan_report` 会把
    客户端字段合并到包字段之上，这些多余字段此后每次加载都会保留下来。
    """

    if report_type != DEFAULT_CUSTOMER_REPORT_TYPE:
        raise ValueError("当前仅开放轻量版报告")
    return new_report_state(package).model_dump(by_alias=True, mode="json")


@router.get("/profiles", response_model=ReportProfileOptionsResponse)
def report_profile_options() -> ReportProfileOptionsResponse:
    """建报可选的报告配置清单。

    只读产品目录：不含用户数据，也不做权益裁决——能否建仍由 POST /api/reports
    按账户权益判定。声明在 /{report_id} 之前，否则 "profiles" 会被当作报告 id。
    """

    registry = load_report_profile_registry()
    options = tuple(
        ReportProfileOption(
            report_profile_id=profile_id,
            display_name=profile.display_name,
            language=knowledge_package_for_profile(profile_id).language,
        )
        for profile_id, profile in registry.profiles.items()
        if profile.report_type == DEFAULT_CUSTOMER_REPORT_TYPE
    )
    return ReportProfileOptionsResponse(
        profiles=options,
        default_report_profile_id=default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE),
    )


@router.get("/generation-models", response_model=GenerationModelOptionsResponse)
def generation_model_options() -> GenerationModelOptionsResponse:
    """当前环境可选的生成模型清单。

    只读产品目录：只列凭据齐备者，且只暴露 id 与服务商标识——部署名、端点与
    密钥环境变量名是服务端事实，不进客户端。与 /profiles 同理声明在 /{report_id}
    之前，否则 "generation-models" 会被当作报告 id。
    """

    return GenerationModelOptionsResponse(
        models=tuple(
            GenerationModelOption(model_id=model_id, vendor=get_spec(model_id).vendor)
            for model_id in selectable_generation_model_ids()
        ),
        default_model_id=resolve_default_model_id(),
    )


@router.get("")
async def list_reports(user: CurrentUser, pool: Pool) -> ReportListResponse:
    context = await _account_context(pool, user)
    items = await reports_dal.list_reports(pool, context.account_id)
    return ReportListResponse(
        reports=[ReportSummaryResponse.model_validate(item.__dict__) for item in items]
    )


@router.post("", status_code=201)
async def create_report(
    req: CreateReportRequest, user: CurrentUser, pool: Pool
) -> ReportSummaryResponse:
    try:
        context = await require_report_creation(pool, user.subject, req.report_type)
        if req.report_type != DEFAULT_CUSTOMER_REPORT_TYPE:
            raise CapabilityDeniedError("当前仅开放轻量版报告")
        report_profile_id = req.report_profile_id or default_report_profile_id(req.report_type)
        if require_report_profile(report_profile_id).report_type != req.report_type:
            # A request-shape mismatch (422), not an entitlement decision.
            raise ValueError("报告配置与报告类型不匹配")
        knowledge_package = knowledge_package_for_profile(report_profile_id)
        summary = await reports_dal.create_report(
            pool,
            account_id=context.account_id,
            title=req.title,
            report_type=req.report_type,
            report_profile_id=report_profile_id,
            # 数据分类是「这份报告里实际是什么数据」的事实断言，不能由账号权益推导。
            # 默认 customer：漏声明时按真实客户处理是安全的一侧。
            data_classification=req.data_classification,
            contract_version=contract_version(knowledge_package),
            initial_state=_initial_state(req.report_type, knowledge_package),
            active_scope_limit=active_report_slot_limit(
                context, created_under_profile_id=context.profile_id
            ),
            profile_id=context.profile_id,
        )
    except reports_dal.ActiveReportLimitError as exc:
        # 名额上限对用户是可自助解决的状态：给稳定 code 供前端引导去删除报告，
        # 给可行动文案供用户阅读；account_id 只作排查上下文，写日志不进响应体。
        raise api_error(
            status_code=403,
            code="active_report_limit_reached",
            message=f"活跃报告已达上限（{exc.limit} 份），删除不再需要的报告后可新建",
            cause=exc,
            log_context=f"account_id={exc.account_id} scope={exc.scope}",
        ) from exc
    except CapabilityDeniedError as exc:
        raise api_error(
            status_code=403,
            code="capability_denied",
            message=str(exc),
            cause=exc,
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    return ReportSummaryResponse.model_validate(summary.__dict__)


@router.delete("/{report_id}", status_code=204)
async def archive_report(report_id: UUID, user: CurrentUser, pool: Pool) -> None:
    """删除报告：报告行留作审计，用户上传的文件在存储侧真删。"""
    context = await _account_context(pool, user)
    try:
        purgeable = await reports_dal.archive_report(pool, context.account_id, report_id)
    except reports_dal.ReportNotFoundError as exc:
        raise api_error(
            status_code=404,
            code="report_not_found",
            message="报告不存在",
            cause=exc,
            log_context=f"report_id={report_id}",
        ) from exc
    if not purgeable:
        return
    # 删除对用户已经生效，存储回收失败不应把它变成一次失败的删除；留日志供运维补收。
    try:
        storage = MaterialStorageClient(persistence_settings())
    except MaterialStorageError:
        logger.warning(
            "report_file_purge_skipped report_id=%s file_count=%s", report_id, len(purgeable),
            exc_info=True,
        )
        return
    for object_path in purgeable:
        try:
            await storage.delete(object_path)
        except MaterialStorageError:
            logger.warning(
                "report_file_purge_failed report_id=%s file_count=%s", report_id, len(purgeable),
                exc_info=True,
            )


@router.get("/{report_id}/state")
async def get_state(
    report_id: UUID, user: CurrentUser, pool: Pool
) -> ReportStateResponse:
    context = await _account_context(pool, user)
    try:
        summary = await reports_dal.get_report_summary(pool, context.account_id, report_id)
        _require_report_flow(summary)
        state = await reports_dal.get_state(pool, context.account_id, report_id)
    except reports_dal.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ReportStateResponse.model_validate({
        "state": state.state,
        "state_seq": state.state_seq,
        "contract_version": state.contract_version,
        "report_profile_id": summary.report_profile_id,
        "capabilities": report_capabilities(
            context,
            created_under_profile_id=summary.created_under_profile_id,
            report_profile_id=summary.report_profile_id,
        ),
    })


@router.get("/{report_id}/rewrite-allowance")
async def get_rewrite_allowance(
    report_id: UUID,
    user: CurrentUser,
    pool: Pool,
    section_key: str = Query(min_length=1, max_length=200),
) -> RewriteAllowanceResponse:
    """返回当前报告某章节的服务端权威重写额度。"""
    try:
        context = await _account_context(pool, user)
        summary = await reports_dal.get_report_summary(pool, context.account_id, report_id)
    except reports_dal.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_report_flow(summary)
    profile = effective_report_profile(
        context,
        created_under_profile_id=summary.created_under_profile_id,
    )
    allowance = await section_generations.rewrite_allowance(
        pool,
        report_id=report_id,
        section_key=section_key,
        quota=profile.section_regeneration_limit,
    )
    return RewriteAllowanceResponse(
        section_key=section_key,
        quota=allowance.quota,
        used=allowance.used,
        remaining=allowance.remaining,
    )


@router.put("/{report_id}/state")
async def put_state(
    report_id: UUID, req: PutStateRequest, user: CurrentUser, pool: Pool
) -> PutReportStateResponse:
    _require_valid_reader_feedback_email(req.state)
    state = req.state.model_dump(by_alias=True, mode="json")
    context = await _account_context(pool, user)
    try:
        summary = await reports_dal.get_report_summary(pool, context.account_id, report_id)
        _require_report_flow(summary)
        # 评分完整性只在生成一步与结构化输入提交边界阻断。范围外评分已在入口收窄。
        new_seq = await reports_dal.put_state(
            pool,
            context.account_id,
            report_id,
            state,
            req.base_seq,
            # 收窄必须作用于锁内权威覆盖之后的落库状态：assessmentInput 是服务端
            # 拥有字段，入口收窄请求体会被 _preserve_server_owned 丢弃。
            transform=partial(
                _narrowed_to_applicable_assessment_scope,
                package=knowledge_package_for_profile(summary.report_profile_id),
            ),
        )
    except reports_dal.ReportNotFoundError as exc:
        raise api_error(
            status_code=404,
            code="report_not_found",
            message="报告不存在",
            cause=exc,
            log_context=f"report_id={report_id}",
        ) from exc
    except reports_dal.StateConflictError as exc:
        raise api_error(
            status_code=409,
            code="state_conflict",
            message="状态快照已在别处更新，请加载最新内容后重试",
            cause=exc,
        ) from exc
    except ValueError as exc:
        # 该捕获面罩住合同装配：planner 的 ValueError 消息带内部模板
        # 文件名与定位串，透传即泄露。用户文案固定在代码侧，原文只进日志。
        raise api_error(
            status_code=403,
            code="report_scope_violation",
            message="本次修改包含当前报告范围之外的内容，已阻止保存",
            cause=exc,
            log_context=f"report_id={report_id}",
        ) from exc
    return PutReportStateResponse(state_seq=new_seq)


def _narrowed_to_applicable_assessment_scope(
    state: StoredReportStateV4,
    *,
    package: KnowledgePackage,
) -> StoredReportStateV4:
    """把评分收窄到当前适用范围后再落库——适用性由基本信息决定，评分只能是其子集。

    用户在基本信息判定某议题不适用，该议题的评分随即失去意义；这是直接后果而非
    需要征询的取舍，因此在写入边界静默对齐，不打断编辑，也不需要用户重填一遍。
    收窄经 DAL put_state 的 transform 在锁内、权威覆盖之后执行，下游不再见到范围外评分。

    少填仍是合法草稿，不在此处补齐；范围外评分若绕过本函数进入生成，
    由 InapplicableScoredTopicsError fail-loud。
    """

    inapplicable = inapplicable_scored_topics(
        state.assessmentInput,
        applicability_facts_from_values(field_values=state.fields),
        package=package,
    )
    if not inapplicable or state.assessmentInput is None:
        return state
    dropped = {topic.id for topic in inapplicable}
    return state.model_copy(
        update={
            "assessmentInput": state.assessmentInput.model_copy(
                update={
                    "scores": [
                        score
                        for score in state.assessmentInput.scores
                        if score.assessmentTopicId not in dropped
                    ]
                }
            )
        }
    )


def _require_valid_reader_feedback_email(state: StoredReportStateV4) -> None:
    """写入边界拒绝格式非法的读者反馈邮箱；存量数据的读取路径不受影响。"""

    package = state.appendixPackage
    email = package.readerFeedbackContactInformation.email if package else None
    if email is None or not email.strip():
        return
    if not is_valid_contact_email(email.strip()):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_reader_feedback_email",
                "message": "读者反馈邮箱格式不正确，请输入形如 name@company.com 的邮箱地址",
                "field": "appendixPackage.readerFeedbackContactInformation.email",
            },
        )


def _require_report_flow(summary: reports_dal.ReportSummary) -> None:
    """仅允许仍由轻量版 Report state 流程拥有的操作进入该 HTTP 边界。"""

    try:
        assert_report_profile_operation(summary.report_profile_id, "report_flow")
    except ValueError:
        raise HTTPException(status_code=409, detail="报告 Profile 不可识别")


async def _account_context(pool: asyncpg.Pool, user):
    try:
        context = await get_account_context(pool, user.subject)
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="Account 权益状态异常")
    if not context.capabilities()["can_edit_existing"]:
        raise HTTPException(status_code=403, detail="Account 当前不能访问报告")
    return context
