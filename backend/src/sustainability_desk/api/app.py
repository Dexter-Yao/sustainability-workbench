# ABOUTME: FastAPI 服务——报告诊断/导出、整节原子生成与确定性派生的产品 API。
# ABOUTME: 本地开发用；CORS 放行项目声明的前端回环入口；渲染基底（规范化模板）首次请求时构建并缓存。
# ABOUTME(en): FastAPI service — product API for report diagnostics/export, atomic whole-section generation and
# ABOUTME(en): deterministic derivation. Local development; CORS allows declared frontend loopback origins.
import logging
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField

from sustainability_desk.contract.models import (
    AssessmentResult,
    DerivedVisualizationSpec,
    Report,
)
from sustainability_desk.contract.assessment_classify import (
    resolve_materiality_assessment,
)
from sustainability_desk.contract.api_error import register_error_handlers
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.compiled_definition import COMPILED_SEMANTICS_VERSION
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.structured_inputs import StructuredInputContext
from sustainability_desk.contract.section_generation import SectionGenerationResponse
from sustainability_desk.contract.report_api import (
    ModuleTitleGenerationResponse,
    SectionGenerationFreshnessResponse,
)
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    bind_knowledge_package,
    knowledge_package_of,
)
from sustainability_desk.contract.report_profiles import (
    DEFAULT_CUSTOMER_REPORT_TYPE,
    ReportProfileOperation,
    assert_report_profile_operation,
    default_report_profile_id,
    knowledge_package_for_profile,
)
from sustainability_desk.diagnostics import Diagnostics, diagnose_in_scope
from sustainability_desk.lightweight_report_generation import (
    resolve_layout_images,
    resolve_section_mapped_evidence,
)
from sustainability_desk.material.intake.storage import MaterialStorageClient
from sustainability_desk.export.docx_renderer import render_final_docx
from sustainability_desk.export.format_profile import load_format_profile
from sustainability_desk.export.normalize_template import normalize_template
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import open_stage
from sustainability_desk.llm.ai_observability import create_observation_run, observe_generation
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.prompts import generation_blocks
from sustainability_desk.api.auth import CurrentUser
from sustainability_desk.api.account_router import router as account_router
from sustainability_desk.api.reports_router import router as reports_router
from sustainability_desk.api.material_router import router as material_router
from sustainability_desk.api.health_router import router as health_router
from sustainability_desk.api.report_generation_router import (
    router as report_generation_router,
)
from sustainability_desk.api.internal_audit_router import router as internal_audit_router
from sustainability_desk.api.runtime_router import router as runtime_router
from sustainability_desk.api.structured_input_router import (
    account_router as structured_input_account_router,
    router as structured_input_router,
)
from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    AccountContext,
    effective_report_profile,
    effective_report_scope,
    get_account_context,
)
from sustainability_desk.accounts.entitlement_profiles import EntitlementProfile
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence.db import create_pool
from sustainability_desk.persistence.section_generations import (
    GenerationAlreadyRunningError,
    GenerationBatchStatusConflictError,
    GenerationIdempotencyConflictError,
    GenerationQuotaExceededError,
    GenerationStateConflictError,
    complete_batch,
    fail_batch,
    latest_successful_input_fingerprint,
    material_gated_block_ids,
    public_results_from_state,
    reserve_batch,
    rewrite_allowance,
    section_generation_input_fingerprint,
    unsuccessful_generation_results,
)
from sustainability_desk.persistence.export_archive import archive_export
from sustainability_desk.persistence.product_telemetry import (
    record_export_blocked,
    record_page_error,
    record_page_reached,
)
from sustainability_desk.persistence.generation_runs import (
    finish_generation_run_safely,
    start_generation_run_safely,
)
from sustainability_desk.persistence.settings import persistence_settings
from sustainability_desk.request_context import RequestContextMiddleware
from sustainability_desk.runtime_environment import (
    assert_environment_boundary,
    runtime_environment,
)

PRODUCT_MODEL_ID = DEFAULT_MODEL_ID
LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

ROOT = Path(__file__).resolve().parents[4]
BACKEND = Path(__file__).resolve().parents[3]
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# 应用入口统一日志配置：各模块 getLogger(__name__) 的 warning 经此输出（库层不自配 handler）
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = persistence_settings()
    assert_environment_boundary(
        runtime_environment(),
        persistence_configured=settings.configured,
        supabase_url=settings.supabase_url,
    )
    _app.state.db_pool = await create_pool(settings) if settings.configured else None
    try:
        yield
    finally:
        if _app.state.db_pool is not None:
            await _app.state.db_pool.close()


app = FastAPI(title="Sustainability Desk API", lifespan=_lifespan)
register_error_handlers(app)
app.include_router(health_router)
app.include_router(runtime_router)
app.include_router(account_router)
app.include_router(reports_router)
app.include_router(material_router)
app.include_router(report_generation_router)
app.include_router(internal_audit_router)
app.include_router(structured_input_router)
app.include_router(structured_input_account_router)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_shells: dict[str, Path] = {}


def _get_shell(package: KnowledgePackage) -> Path:
    """Normalised export base template of a package, built once per process."""
    shell = _shells.get(package.id)
    if shell is None:
        shell = normalize_template(
            package.base_template_path,
            BACKEND / "out" / f"base_{package.id}.docx",
            profile=load_format_profile(package),
        )
        _shells[package.id] = shell
    return shell


async def _stored_export_diagnostics(
    pool,
    context: AccountContext,
    report_id: UUID,
    summary: reports_dal.ReportSummary,
    report: Report,
) -> tuple[Diagnostics, Report, StoredReportStateV4]:
    """诊断与导出闸的唯一组合根：范围投影 + 权威 state + 结构化输入上下文。

    预检抽屉与导出闸必须消费同一集合；任何一侧单独改动都会重现「抽屉说可导出、
    导出却 422」的分叉。返回投影后的 Report 供导出渲染复用，并一并返回已校验的
    权威 state——排版素材的放置事实只在 state.imageBlocks 里，导出若不读它就会
    把用户放好的图静默丢掉。
    """
    scope = effective_report_scope(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )
    # The client never decides which package a report belongs to; the Profile row does.
    projected = scope.project_report(
        bind_knowledge_package(report, scope.knowledge_package)
    )
    stored = await reports_dal.get_state(pool, context.account_id, report_id)
    if stored.contract_version != contract_version(scope.knowledge_package):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "contract_upgrade_required",
                "message": "报告使用的契约版本已过期，请重建报告。",
            },
        )
    stored_state = StoredReportStateV4.model_validate(stored.state)
    diag = diagnose_in_scope(
        projected,
        scope=scope,
        stored_state=stored_state,
        structured_input_context=StructuredInputContext(
            reportId=report_id,
            contractVersion=stored.contract_version,
            compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
        ),
    )
    return diag, projected, stored_state


@app.post("/api/reports/{report_id}/diagnose")
async def diagnose_report(
    report: Report, request: Request, user: CurrentUser, report_id: UUID
) -> Diagnostics:
    """报告诊断：与 /api/export 同一组合根，前端预检面板与导出闸同源同集。"""
    pool, context, report_summary = await _account_report_context(
        request,
        report_id,
        user,
        capability="can_edit_existing",
    )
    diag, _projected, _stored_state = await _stored_export_diagnostics(
        pool, context, report_id, report_summary, report
    )
    return diag


class PageReachedRequest(BaseModel):
    """页面到达上报：只接受既有 screenId，浏览器不能自定义事件语义。"""

    model_config = ConfigDict(extra="forbid")

    screen_id: str


class PageErrorRequest(BaseModel):
    """前端错误上报：只接受位置与受控类型，错误消息与堆栈不进审计表。"""

    model_config = ConfigDict(extra="forbid")

    screen_id: str
    kind: str


@app.post("/api/reports/{report_id}/telemetry/page-reached", status_code=204)
async def report_page_reached(
    body: PageReachedRequest, request: Request, user: CurrentUser, report_id: UUID
) -> Response:
    """记录页面到达。观测不得改变产品行为，未知 screenId 静默丢弃而非报错。"""
    pool, _context, _summary = await _account_report_context(
        request, report_id, user, capability="can_edit_existing"
    )
    await record_page_reached(pool, report_id, body.screen_id)
    return Response(status_code=204)


@app.post("/api/reports/{report_id}/telemetry/page-error", status_code=204)
async def report_page_error(
    body: PageErrorRequest, request: Request, user: CurrentUser, report_id: UUID
) -> Response:
    """记录前端错误发生的页面与类型；诊断细节留在浏览器控制台，不落库。"""
    pool, _context, _summary = await _account_report_context(
        request, report_id, user, capability="can_edit_existing"
    )
    await record_page_error(pool, report_id, body.screen_id, body.kind)
    return Response(status_code=204)


class PlanRequest(BaseModel):
    """议题装配请求：实例事实与其已钉住的契约版本分开传递。"""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    report: Report
    expected_contract_version: str | None = None


class ContractUpgradeRequiredError(Exception):
    """报告固定的契约版本与当前运行时契约不一致。"""


def _fields_with_client_values(contract_fields: dict, client_fields: dict) -> dict:
    """包合同的字段集，取客户端同名字段已填的值。

    字段的**定义**（存在与否、标签、类型、选项）归知识包；客户端只拥有用户填进去的
    **值**。客户端多出的字段一律丢弃——它们来自另一个包的合同投影，不是这份报告的事实。
    """

    merged = {}
    for key, field in contract_fields.items():
        client = client_fields.get(key)
        merged[key] = field if client is None else field.model_copy(update={"value": client.value})
    return merged


def plan_report(
    report: Report,
    *,
    package: KnowledgePackage,
    expected_contract_version: str | None = None,
) -> dict:
    """按报告配置与完整适用评估清单装配议题章节，并产出议题诊断（工作台运行时调用）。

    重要性策略与生成侧权威装配（report_revision.build_company_inputs）同判定：
    无评分输入 → complete_coverage 全议题装配；有评分 → 按重要性结果装配。
    两条路径必须给出同一棵章节树，否则前端窄投影会既看不到也导不出议题正文。
    评分表确定/变更时由前端调用，前端按 block id merge 保留已有正文。
    """
    if (
        expected_contract_version is not None
        and expected_contract_version != contract_version(package)
    ):
        raise ContractUpgradeRequiredError

    from sustainability_desk.contract.loader import load_package_contract
    from sustainability_desk.llm.topic_validate import validate_topic_templates_or_raise
    from sustainability_desk.planner import (
        TopicGuardError,
        assemble_report,
        load_topic_intake,
        load_topic_templates,
        merge_prose,
    )

    # 入口绑定报告所属知识包：客户端投影（frontend/public/contract.json）不带 knowledgePackageId，
    # 而包由服务端从 report_profile_id 权威解析。不在此绑定，下游每个按包解析的调用都要
    # 各自补传 package，漏一处即运行期 ValueError（曾表现为基本资料页整页 500）。
    report = bind_knowledge_package(report, package)

    contract = load_package_contract(package)
    templates = load_topic_templates(package)
    intake = load_topic_intake(package)
    validate_topic_templates_or_raise(templates, intake, package=package)
    planning_contract = contract.model_copy(
        update={
            # 字段集只认包合同，客户端只贡献同名字段的**值**：客户端投影
            # （frontend/public/contract.json）是单包的静态快照，整体合并会把内地包独有
            # 字段（科技伦理适用范围、董事会出席率等）带进港交所报告，且此后每次装配
            # 都保留下来——基本资料页会因此长出该包根本没有的必填题。
            "fields": _fields_with_client_values(contract.fields, report.fields),
            "disclosureProfile": report.disclosureProfile or contract.disclosureProfile,
            "assessmentInput": report.assessmentInput,
        }
    )
    assessment = None
    if report.assessmentInput is not None:
        try:
            assessment = resolve_materiality_assessment(
                report.assessmentInput, planning_contract
            )
        except ValueError:
            # 评分输入仍是草稿（未覆盖全部适用议题，或适用范围变化留有多余评分）：
            # 编辑期装配按「尚无评分输入」回退 complete_coverage，中途浏览/离开不报错；
            # 评分完整性只在生成前置门禁与结构化输入提交边界阻断。生成侧
            # build_company_inputs 的严格校验只在门禁通过后运行，两条路径不会分叉。
            assessment = None
    try:
        result = assemble_report(
            planning_contract,
            templates,
            assessment=assessment,
            intake_items=intake,
            complete_coverage=assessment is None,
        )
    except (TopicGuardError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    merged, added, dropped = merge_prose(result.report, report)
    from sustainability_desk.contract.models import ReportMeta
    from sustainability_desk.contract.stakeholder_engagement import (
        apply_stakeholder_engagement_projection,
    )

    # 装配用过的重要性策略必须随 Report 返回:下游 /diagnose 与 /api/export
    # 消费同一份 meta,不回写会与生成侧(report_revision 同判定)
    # 得出相反的门禁结论(无评分报告被误判为"必须完成重要性评分")。
    merged = merged.model_copy(
        update={
            "meta": (merged.meta or ReportMeta()).model_copy(
                update={
                    "materialityStrategy": (
                        "complete_coverage" if assessment is None else None
                    )
                }
            )
        }
    )
    merged = apply_stakeholder_engagement_projection(merged)
    return {
        "report": merged,
        "diagnostics": [asdict(d) for d in result.diagnostics],
        "added": added,
        "dropped": dropped,
    }


@app.post("/api/plan", response_model=None)
async def plan_report_endpoint(
    req: PlanRequest, request: Request, user: CurrentUser
) -> dict | JSONResponse:
    """装配当前 Runtime Report；版本不一致时要求产品显式升级。"""
    try:
        pool, context, report_summary = await _account_report_context(
            request, req.report_id, user, capability="can_edit_existing"
        )
        stored = await reports_dal.get_state(pool, context.account_id, req.report_id)
        if (
            req.expected_contract_version is not None
            and req.expected_contract_version != stored.contract_version
        ):
            raise ContractUpgradeRequiredError
        scope = effective_report_scope(
            context,
            created_under_profile_id=report_summary.created_under_profile_id,
            report_profile_id=report_summary.report_profile_id,
        )
        result = plan_report(
            req.report,
            package=scope.knowledge_package,
            expected_contract_version=stored.contract_version,
        )
        result["report"] = scope.project_report(result["report"])
        return result
    except ContractUpgradeRequiredError:
        return JSONResponse(
            status_code=409,
            content={
                "code": "contract_upgrade_required",
                "message": "该报告使用的契约版本与当前版本不一致，需显式升级后才能继续编辑。",
            },
        )


@app.post("/api/export")
async def export_report(
    report: Report, request: Request, user: CurrentUser, report_id: UUID
) -> Response:
    """填充 Report → Word，返回 .docx 字节流；存在阻断级 issue 时 fail-loud 拒绝导出。

    report_id 必填；登录用户必须拥有该报告，导出产物以 sha256 指纹存档进 exports 桶并记审计事件。
    """
    pool, context, report_summary = await _account_report_context(
        request,
        report_id,
        user,
        capability="can_export_word",
        profile_operation="export",
    )
    diag, report, stored_state = await _stored_export_diagnostics(
        pool, context, report_id, report_summary, report
    )
    if diag.blocking:
        # 生成链路的 export_blocked 有台账，工作台这条 422 同样要落台账，否则漏斗不可见。
        await record_export_blocked(
            pool,
            report_id,
            tuple(i.code for i in diag.issues if i.level == "block"),
        )
        raise HTTPException(
            status_code=422,
            detail={"blocking": True, "issues": [i.model_dump() for i in diag.issues]},
        )
    # 排版素材的放置事实只在权威 state 里：不重建这份映射，用户放好的图会在
    # 人工修订后的导出中静默消失（渲染器拿不到该块的图组时什么都不画）。
    # 以服务端 state 为准而非请求体，放置权威与生成路径同源。
    package = knowledge_package_of(report)
    resolved_images = await resolve_layout_images(
        pool,
        account_id=context.account_id,
        report_id=report_id,
        state=stored_state,
        records=await layout_asset_dal.current_layout_asset_records(pool, report_id),
        storage=MaterialStorageClient(persistence_settings()),
        package=package,
    )
    with tempfile.TemporaryDirectory() as td:
        out = render_final_docx(
            report,
            _get_shell(package),
            Path(td) / "export.docx",
            resolved_images=resolved_images,
        )
        data = out.read_bytes()
    await archive_export(pool, persistence_settings(), report_id, data)
    return Response(
        content=data,
        media_type=DOCX_MIME,
        headers={"Content-Disposition": "attachment; filename=report.docx"},
    )


async def _account_context(request: Request, user) -> AccountContext:
    """从认证主体解析产品 Account；任何映射或 Grant 异常都 fail-closed。"""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="持久化服务未配置")
    try:
        return await get_account_context(pool, user.subject)
    except (AccountNotFoundError, AccountEntitlementError):
        raise HTTPException(status_code=403, detail="Account 权益状态异常")


async def _account_report_context(
    request: Request,
    report_id: UUID,
    user,
    *,
    capability: str,
    profile_operation: ReportProfileOperation = "report_flow",
) -> tuple[object, AccountContext, reports_dal.ReportSummary]:
    """统一的 Report 所有权与能力断言；service role 不因数据库权限而跳过产品授权。"""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(status_code=503, detail="持久化服务未配置")
    context = await _account_context(request, user)
    try:
        summary = await reports_dal.get_report_summary(
            pool, context.account_id, report_id
        )
    except reports_dal.ReportNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        assert_report_profile_operation(
            summary.report_profile_id,
            profile_operation,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not bool(context.capabilities().get(capability)):
        raise HTTPException(status_code=403, detail="当前 Account 权益不允许该操作")
    return pool, context, summary


def _effective_report_profile(
    context: AccountContext, report: reports_dal.ReportSummary
) -> EntitlementProfile:
    """投影该报告当前有效的权益 Profile（跟随当前 Grant）。"""
    return effective_report_profile(
        context,
        created_under_profile_id=report.created_under_profile_id,
    )


async def _generation_pool(request: Request, report_id: UUID, user) -> "object":
    pool, _context, _report = await _account_report_context(
        request, report_id, user, capability="can_generate"
    )
    return pool


# API 直连生成的两个工作单元根阶段（与使用处同址登记；请求级工作单元，
# 报告执行范围语义由请求授权层持有，此处不重复约束）。
SECTION_GENERATION_STAGE = register_stage(
    Stage(id="api.section_generation", kind="orchestration", unit_root=True)
)
MODULE_TITLES_GENERATION_STAGE = register_stage(
    Stage(id="api.report_module_titles_generation", kind="llm", unit_root=True)
)


@asynccontextmanager
async def _product_generation(
    pool,
    *,
    account_id: UUID,
    report_id: UUID,
    block_id: str,
    stage: Stage,
    contract_version: str,
):
    """包围一次产品生成任务，并保证成功或失败都尝试更新数据库聚合。"""
    run = create_observation_run(
        stage,
        model_id=PRODUCT_MODEL_ID,
        workload_kind="product_generation",
        report_id=str(report_id),
        block_id=block_id,
        user_id=str(account_id),
        contract_version=contract_version,
    )
    await start_generation_run_safely(pool, run)
    try:
        with open_stage(
            stage,
            trace_id=run.runId,
            report_id=str(report_id),
        ), observe_generation(run):
            yield run
    finally:
        await finish_generation_run_safely(pool, run)


class SectionGenerationRequest(BaseModel):
    """整节生成请求；块清单、批次类型和配额全部由服务端派生。"""

    model_config = ConfigDict(extra="forbid")

    report: Report
    base_state_seq: int = PydanticField(ge=1)
    idempotency_key: UUID


def _find_section(report: Report, section_key: str):
    def walk(sections, inherited_report_section: str | None = None):
        for section in sections:
            report_section_id = section.reportSectionId or inherited_report_section
            if section.key == section_key:
                return section, report_section_id
            found = walk(section.children or [], report_section_id)
            if found is not None:
                return found
        return None

    return walk(report.sections)


def _public_batch_response(
    *,
    batch,
    state: dict,
    state_seq: int,
    allowance,
) -> SectionGenerationResponse:
    return SectionGenerationResponse.model_validate({
        "batch_id": str(batch.id),
        "mode": batch.mode,
        "replayed": batch.replayed,
        "state_seq": state_seq,
        "results": public_results_from_state(state, batch.expected_block_ids),
        "section_titles": state.get("sectionTitles") or {},
        "input_fingerprint": batch.input_fingerprint,
        "freshness": "fresh",
        "company_business_summary": (state.get("fields") or {}).get(
            "company_business_summary"
        ),
        "allowance": {
            "quota": allowance.quota,
            "used": allowance.used,
            "reserved": allowance.reserved,
            "remaining": allowance.remaining,
        },
    })


@app.post("/api/reports/{report_id}/sections/{section_key}/generations")
async def generate_section(
    report_id: UUID,
    section_key: str,
    req: SectionGenerationRequest,
    request: Request,
    user: CurrentUser,
) -> SectionGenerationResponse:
    """服务端整节编排：预留额度、并发生成、完整成功后原子写回目标页面。"""
    from sustainability_desk.llm.derive import (
        COMPANY_BUSINESS_SUMMARY_KEY,
        company_profile_text,
        derive_company_business_summary,
        needs_company_business_summary,
    )
    from sustainability_desk.llm.generate_all import blocks_for_section, generate_all

    pool, context, report_summary = await _account_report_context(
        request,
        report_id,
        user,
        capability="can_regenerate_sections",
        # 整节重写只存在于工作台；轻量版关闭工作台后必须在服务端拒绝，而非只靠前端隐藏入口。
        profile_operation="workbench",
    )
    profile = _effective_report_profile(context, report_summary)
    stored = await reports_dal.get_state(pool, context.account_id, report_id)
    scope = effective_report_scope(
        context,
        created_under_profile_id=report_summary.created_under_profile_id,
        report_profile_id=report_summary.report_profile_id,
    )
    if stored.contract_version != contract_version(scope.knowledge_package):
        raise HTTPException(status_code=409, detail="报告契约版本需要显式升级")
    canonical = plan_report(
        req.report,
        package=scope.knowledge_package,
        expected_contract_version=stored.contract_version,
    )["report"]
    located = _find_section(canonical, section_key)
    if located is None:
        raise HTTPException(status_code=404, detail="页面不存在")
    _section, report_section_id = located
    if (
        report_section_id is not None
        and report_section_id not in scope.allowed_report_section_ids
    ):
        raise HTTPException(status_code=403, detail="当前 Account 权益不包含该议题")
    blocks = blocks_for_section(canonical, section_key)
    expected_block_ids = tuple(block.id for block in blocks)
    if not expected_block_ids:
        raise HTTPException(status_code=422, detail="该页面没有可生成块")
    # 证据门控块必须带着冻结 Mapping 决定进生成：缺决定时门控会关闭、块被判受控省略，
    # 而受控省略在账本里是「成功」，于是既有正文被静默抹平（todos §3.6 记录的那条）。
    # 故此处装配冻结证据；装配不成（报告尚无资料快照）而本节确有门控块时 fail-closed 拒绝，
    # 不放行也不静默丢内容。资格判定用编译合同而非运行期 selector 嗅探——
    # 账本自己的口径就是「资格以编译合同为准，不信任结果自述」。
    gated_in_section = frozenset(expected_block_ids) & material_gated_block_ids(
        scope.knowledge_package
    )
    mapped_evidence = await resolve_section_mapped_evidence(
        pool,
        account_id=context.account_id,
        report_id=report_id,
        expected_block_ids=expected_block_ids,
    )
    if gated_in_section and mapped_evidence is None:
        raise HTTPException(
            status_code=422,
            detail="该页面包含按资料出具的内容，需先完成资料处理后再重写本节。",
        )
    material_snapshot_record = await pipeline_dal.latest_material_set_snapshot(
        pool,
        account_id=context.account_id,
        report_id=report_id,
    )
    # 资料集合指纹进新鲜度：重写开始消费冻结资料后，资料变化必须让指纹变化，
    # 否则资料已更新而页面仍报 fresh。三处调用（预留、完成、查新鲜度）必须同源，
    # 否则账本与新鲜度会互相矛盾。
    material_set_fingerprint = (
        material_snapshot_record.snapshot.input_fingerprint
        if material_snapshot_record is not None
        else None
    )
    input_fingerprint = section_generation_input_fingerprint(
        canonical,
        section_key,
        material_set_fingerprint=material_set_fingerprint,
    )
    try:
        batch = await reserve_batch(
            pool,
            account_id=context.account_id,
            report_id=report_id,
            section_key=section_key,
            expected_block_ids=expected_block_ids,
            idempotency_key=req.idempotency_key,
            base_state_seq=req.base_state_seq,
            regeneration_quota=profile.section_regeneration_limit,
            input_fingerprint=input_fingerprint,
        )
    except GenerationQuotaExceededError:
        raise HTTPException(status_code=403, detail="本页重写次数已达上限")
    except GenerationAlreadyRunningError:
        raise HTTPException(status_code=409, detail="本页已有生成任务正在进行")
    except GenerationIdempotencyConflictError:
        raise HTTPException(status_code=409, detail="幂等键已用于其他请求")
    except GenerationStateConflictError:
        raise HTTPException(status_code=409, detail="状态快照已在别处更新")
    except GenerationBatchStatusConflictError:
        raise HTTPException(
            status_code=409, detail="生成批次租约已过期或状态已变化，报告未发生修改"
        )

    if batch.replayed:
        replay_state = await reports_dal.get_state(pool, context.account_id, report_id)
        allowance = await rewrite_allowance(
            pool,
            report_id=report_id,
            section_key=section_key,
            quota=profile.section_regeneration_limit,
        )
        return _public_batch_response(
            batch=batch,
            state=replay_state.state,
            state_seq=replay_state.state_seq,
            allowance=allowance,
        )

    company_summary: str | None = None
    try:
        async with _product_generation(
            pool,
            account_id=context.account_id,
            report_id=report_id,
            block_id=section_key,
            stage=SECTION_GENERATION_STAGE,
            contract_version=stored.contract_version,
        ) as observation:
            # 是否需要派生由 llm/derive 单点判定，与整报告生成链路同源。
            summary_field = canonical.fields.get(COMPANY_BUSINESS_SUMMARY_KEY)
            if summary_field is not None and not summary_field.value:
                if needs_company_business_summary(
                    company_profile_text(canonical), package=scope.knowledge_package
                ):
                    company_summary = await derive_company_business_summary(
                        canonical,
                        model_id=PRODUCT_MODEL_ID,
                        observation=observation,
                    )
                    if company_summary:
                        summary_field.value = company_summary
            results = await generate_all(
                canonical,
                section_key=section_key,
                n=1,
                model_id=PRODUCT_MODEL_ID,
                observation=observation,
                # 与报告级生成同一取值：空表按受控省略处理，门控块带着冻结决定进生成。
                empty_table_policy="omit",
                mapped_evidence_by_block=mapped_evidence,
            )
            # 表格省略在工作台整节重写中按失败处理。
            if unsuccessful_generation_results(
                results, allow_contract_omissions=False, package=scope.knowledge_package
            ):
                raise ValueError("整节存在未完成块")
        completed_input_fingerprint = section_generation_input_fingerprint(
            canonical,
            section_key,
            material_set_fingerprint=material_set_fingerprint,
        )
        new_seq = await complete_batch(
            pool,
            batch=batch,
            results=results,
            package=scope.knowledge_package,
            company_business_summary=company_summary,
            input_fingerprint=completed_input_fingerprint,
        )
        batch = replace(batch, input_fingerprint=completed_input_fingerprint)
    except GenerationStateConflictError:
        raise HTTPException(status_code=409, detail="状态快照已在别处更新")
    except ValueError as exc:
        await fail_batch(pool, batch.id, str(exc))
        raise HTTPException(status_code=422, detail="本页未能完整生成，报告未发生修改")
    except Exception as exc:
        await fail_batch(pool, batch.id, type(exc).__name__)
        logging.getLogger(__name__).exception(
            "整节生成失败 reportId=%s sectionKey=%s batchId=%s",
            report_id,
            section_key,
            batch.id,
        )
        raise HTTPException(status_code=502, detail="本页生成失败，报告未发生修改")

    updated = await reports_dal.get_state(pool, context.account_id, report_id)
    allowance = await rewrite_allowance(
        pool,
        report_id=report_id,
        section_key=section_key,
        quota=profile.section_regeneration_limit,
    )
    return _public_batch_response(
        batch=batch,
        state=updated.state,
        state_seq=new_seq,
        allowance=allowance,
    )


class SectionGenerationFreshnessRequest(BaseModel):
    """当前 Report 的页面输入与最近成功生成批次的比较请求。"""

    model_config = ConfigDict(extra="forbid")

    report: Report


@app.post("/api/reports/{report_id}/sections/{section_key}/generation-freshness")
async def section_generation_freshness(
    report_id: UUID,
    section_key: str,
    req: SectionGenerationFreshnessRequest,
    request: Request,
    user: CurrentUser,
) -> SectionGenerationFreshnessResponse:
    """比较当前模型可见输入与最近成功生成输入；不生成内容且不消耗额度。"""
    pool, context, report_summary = await _account_report_context(
        request, report_id, user, capability="can_generate"
    )
    canonical = plan_report(
        req.report,
        package=knowledge_package_for_profile(report_summary.report_profile_id),
        expected_contract_version=report_summary.contract_version,
    )["report"]
    if _find_section(canonical, section_key) is None:
        raise HTTPException(status_code=404, detail="页面不存在")
    freshness_snapshot = await pipeline_dal.latest_material_set_snapshot(
        pool,
        account_id=context.account_id,
        report_id=report_id,
    )
    current = section_generation_input_fingerprint(
        canonical,
        section_key,
        material_set_fingerprint=(
            freshness_snapshot.snapshot.input_fingerprint
            if freshness_snapshot is not None
            else None
        ),
    )
    generated = await latest_successful_input_fingerprint(
        pool,
        report_id=report_id,
        section_key=section_key,
    )
    status = (
        "not_generated"
        if generated is None
        else "fresh"
        if generated == current
        else "stale"
    )
    return SectionGenerationFreshnessResponse(
        status=status,
        current_input_fingerprint=current,
        generated_input_fingerprint=generated,
    )


class ReportModuleTitlesGenerationRequest(BaseModel):
    """用户显式触发的五模块标题生成请求。"""

    model_config = ConfigDict(extra="forbid")

    report: Report
    base_state_seq: int = PydanticField(ge=1)


@app.post("/api/reports/{report_id}/module-titles/generations")
async def generate_module_titles(
    report_id: UUID,
    req: ReportModuleTitlesGenerationRequest,
    request: Request,
    user: CurrentUser,
) -> ModuleTitleGenerationResponse:
    """显式执行一次报告级调用，完整成功后原子保存五个动态 H1 标题。"""
    from sustainability_desk.contract.section_titles import module_fingerprint
    from sustainability_desk.llm.generate_module_titles import generate_report_module_titles

    pool, context, report_summary = await _account_report_context(
        request,
        report_id,
        user,
        capability="can_generate",
        # 用户显式触发的标题重算是工作台工具栏动作；报告生成链路直接调用底层函数，
        # 不经本端点，因此这里收紧不影响轻量版生成。
        profile_operation="workbench",
    )
    stored = await reports_dal.get_state(pool, context.account_id, report_id)
    if stored.state_seq != req.base_state_seq:
        raise HTTPException(status_code=409, detail="状态快照已在别处更新")
    canonical = plan_report(
        req.report,
        package=knowledge_package_for_profile(report_summary.report_profile_id),
        expected_contract_version=stored.contract_version,
    )["report"]
    async with _product_generation(
        pool,
        account_id=context.account_id,
        report_id=report_id,
        block_id="report.module_titles",
        stage=MODULE_TITLES_GENERATION_STAGE,
        contract_version=stored.contract_version,
    ) as observation:
        try:
            generated = await generate_report_module_titles(
                canonical,
                model_id=PRODUCT_MODEL_ID,
                observation=observation,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    module_sections = {
        section.reportModuleId: section
        for section in canonical.sections
        if section.reportModuleId is not None
    }
    state = dict(stored.state)
    section_titles = dict(state.get("sectionTitles") or {})
    response_titles: dict[str, dict[str, str]] = {}
    for item in generated.modules:
        section = module_sections[item.reportModuleId]
        value = {
            "text": item.displayTitle,
            "origin": "generated",
            "inputFingerprint": module_fingerprint(section, canonical),
        }
        section_titles[section.key] = value
        response_titles[section.key] = value
    state["sectionTitles"] = section_titles
    try:
        new_seq = await reports_dal.put_state(
            pool,
            context.account_id,
            report_id,
            state,
            req.base_state_seq,
        )
    except reports_dal.StateConflictError:
        raise HTTPException(status_code=409, detail="状态快照已在别处更新")
    return ModuleTitleGenerationResponse.model_validate(
        {"section_titles": response_titles, "state_seq": new_seq}
    )


class MetricSummaryImageRequest(BaseModel):
    """确定性派生指标图请求：Report 实例 + schema 声明的可视化规格。"""

    report: Report
    spec: DerivedVisualizationSpec
    # Preview images are not bound to a stored report; the caller names the Profile whose
    # metric catalog applies, defaulting to the Profile new reports are created on.
    report_profile_id: str | None = None


@app.post("/api/visualizations/quantitative-metric-summary")
def quantitative_metric_summary_image(
    req: MetricSummaryImageRequest, user: CurrentUser
) -> Response:
    """按 image.derivedVisualization 规格渲染 ESG 定量指标摘要 PNG；与 Word 导出共用后端图源。

    仅要求登录态，不绑定具体报告：渲染只读 req.report 派生图像，不做报告级授权检查。
    """
    from sustainability_desk.export.metric_summary_chart import (
        render_quantitative_metric_summary,
    )

    package = knowledge_package_for_profile(
        req.report_profile_id or default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE)
    )
    try:
        png = render_quantitative_metric_summary(
            # 只借该 Profile 的指标目录渲图，不主张这份 Report 属于该包：
            # 未指名 Profile 时默认值是「新建报告用的那个包」，与 Report 的实际来源无关。
            bind_knowledge_package(req.report, package, validate_references=False),
            req.spec.metricKeys,
            featured_metric_keys=req.spec.featuredMetricKeys,
            display_mode=req.spec.displayMode,
            group_by=req.spec.groupBy,
        )
    except Exception as exc:  # noqa: BLE001 — API 层转为可读错误；导出层仍有自己的占位回退
        raise HTTPException(
            status_code=422, detail=f"指标摘要图渲染失败：{type(exc).__name__}"
        )
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png")


@app.post("/api/assessment/matrix")
def assessment_matrix(
    assessment: AssessmentResult,
    user: CurrentUser,
    visible: str | None = Query(default=None),
    report_profile_id: str | None = Query(default=None),
) -> Response:
    """据评估结果渲染双重重要性矩阵 PNG（评分页/编辑台显示，与导出同一渲染源——所见即所得）。

    仅要求登录态，不绑定具体报告：渲染只读 assessment 派生图像，不做报告级授权检查。
    可选 ``visible`` 查询参数（逗号分隔 dual/impact/financial/non）为视图级过滤，仅交互预览使用；
    导出不传参，始终完整渲染。
    """
    from sustainability_desk.export.matrix_chart import (
        parse_visible_materialities,
        render_materiality_matrix,
    )

    try:
        visible_set = parse_visible_materialities(visible) if visible is not None else None
        package = knowledge_package_for_profile(
            report_profile_id or default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE)
        )
        png = render_materiality_matrix(
            assessment, package=package, visible_materialities=visible_set
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(content=png, media_type="image/png")


@app.get("/api/prompt-config")
def prompt_config(user: CurrentUser) -> dict:
    """可生成块清单与准则批注配置，供前端渲染生成入口；均从契约派生。

    可生成块同时纳入议题章节模板（topic_sections），使议题章节的生成块也能在工作台生成。
    """
    from sustainability_desk.contract.user_visible_disclosure_clause_annotations import (
        load_user_visible_disclosure_clause_annotations,
    )
    from sustainability_desk.contract.loader import load_package_contract
    from sustainability_desk.llm.topic_validate import validate_topic_templates_or_raise
    from sustainability_desk.planner import (
        load_topic_intake,
        load_topic_templates,
        with_topic_sections,
    )

    # Account-level configuration has no report yet: it describes the default package new
    # reports are created on.
    package = knowledge_package_for_profile(
        default_report_profile_id(DEFAULT_CUSTOMER_REPORT_TYPE)
    )
    report = load_package_contract(package)
    templates = load_topic_templates(package)
    intake = load_topic_intake(package)
    validate_topic_templates_or_raise(templates, intake, package=package)
    merged = with_topic_sections(report, templates)
    return {
        "blocks": generation_blocks(merged),
        "user_visible_disclosure_clause_annotations": [
            entry.model_dump()
            for entry in load_user_visible_disclosure_clause_annotations(package)
        ],
    }
