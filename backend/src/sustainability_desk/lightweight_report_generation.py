# ABOUTME: 编排轻量版显式生成命令、完整 Report revision、Word 与双审阅包。
# ABOUTME: 仅经冻结资料快照和 Mapping 决定进入模型上下文；失败不会替换当前报告版本。
# ABOUTME(en): Orchestrates the explicit lightweight generation command, Report revisions, Word and two review packages.
# ABOUTME(en): Only the frozen material snapshot and Mapping decide model context; failure never replaces the version.
from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import zipfile
from uuid import UUID, uuid4

import asyncpg

from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    effective_report_scope,
    get_account_context_for_account,
    report_capabilities,
)
from sustainability_desk.accounts.entitlement_profiles import ReportScopeKind
from sustainability_desk.llm.model_registry import (
    DEFAULT_MODEL_ID,
    resolve_selected_model_id,
)
from sustainability_desk.accounts.report_execution_scope import EffectiveReportScope
from sustainability_desk.contract.report_generation import (
    CreateReportGenerationRequest,
    delivery_docx_filename,
)
from sustainability_desk.contract.compiled_definition import (
    COMPILED_SEMANTICS_VERSION,
    load_compiled_report_definition,
)
from sustainability_desk.contract.report_preparation import generation_preparation_blockers
from sustainability_desk.contract.structured_inputs import StructuredInputContext
from sustainability_desk.contract.disclosure_coverage import DisclosureCoverageReport
from sustainability_desk.diagnostics import diagnose_in_scope
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.report_profiles import require_report_profile
from sustainability_desk.contract.models import Report, Section
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stakeholder_engagement import (
    reconcile_stakeholder_engagement_profile,
)
from sustainability_desk.contract.section_titles import (
    display_title_is_stale,
    module_fingerprint,
)
from sustainability_desk.llm.derive import (
    COMPANY_BUSINESS_SUMMARY_KEY,
    company_business_summary_is_stale,
    company_profile_fingerprint,
    company_profile_text,
    derive_company_business_summary,
)
from sustainability_desk.llm.generate_module_titles import generate_report_module_titles
from sustainability_desk.contract.stored_report_state import (
    StoredCompanyBusinessSummary,
    StoredReportStateV4,
)
from sustainability_desk.contract.layout_asset_slots import (
    layout_asset_block_by_scope,
    layout_asset_slots,
)
from sustainability_desk.export.docx_renderer import (
    ResolvedEvidenceImage,
    build_document_render_plan,
    render_final_docx,
)
from sustainability_desk.export.figure_projection import FigureKind
from sustainability_desk.export.format_profile import load_format_profile
from sustainability_desk.export.normalize_template import normalize_template
from sustainability_desk.material.intake.image_agent_ai import (
    model_image_pixel_size,
    prepare_model_image,
)
from sustainability_desk.material.intake.storage import MaterialStorageClient
from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
from sustainability_desk.persistence.settings import persistence_settings
from sustainability_desk.llm.ai_observability import (
    SCHEMA_VERSION,
    ObservationRun,
    create_observation_run,
    observe_generation,
    locate_observation_trace,
    parse_observability_event,
)
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import (
    PipelineStageMissing,
    StageHandle,
    open_stage,
)
from sustainability_desk.llm.generate_all import (
    BlockMappedEvidence,
    blocks_for_report,
    generate_all,
)
from sustainability_desk.material.input_adapter import LightweightReportInputAdapter
from sustainability_desk.material.agent_pipeline import (
    synchronize_mapping_runs,
)
from sustainability_desk.material.workspace import (
    OUTSIDE_SCOPE_MATERIAL_NOTICE,
    active_binding_fingerprint,
    has_active_semantic_material,
    pending_file_description_count,
)
from sustainability_desk.material.intake.file_agent_contract import (
    FileDossier,
    FileMaterial,
    FileSourceRevision,
)
from sustainability_desk.material.mapping.decisions import (
    BlockMaterialDecision,
)
from sustainability_desk.material.mapping.snapshot import FrozenMappingPlan
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import material_intake as material_dal
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence import lightweight_report_generations as generation_dal
from sustainability_desk.persistence.section_generations import (
    apply_generation_results,
    unsuccessful_generation_results,
)
from sustainability_desk.report_review_packages import (
    BlockReviewLabel,
    InternalExportReceipt,
    InternalTraceReference,
    ReportArtifactReference,
    LayoutImageReviewInput,
    ReportMaterialReviewInput,
    ReportReviewSource,
    ReportRevisionReference,
    build_customer_commentary_package,
    build_material_processing_notice,
    build_standards_compliance_notice,
    build_internal_audit_package,
    render_customer_cover_comment,
    render_customer_comment_texts,
    render_internal_audit_markdown,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "backend" / "out" / "report_artifacts"
DEFAULT_REPORT_MODEL_ID = DEFAULT_MODEL_ID

logger = logging.getLogger(__name__)

# ---- 链路阶段声明（与使用处同址，导入即登记；spec 决策点 B）----
_GENERATION_SCOPES: tuple[ReportScopeKind, ...] = ("full_simplified",)

REPORT_GENERATION_STAGE = register_stage(
    Stage(
        id="report.generation",
        kind="orchestration",
        scopes=_GENERATION_SCOPES,
        unit_root=True,
    )
)
COMPANY_SUMMARY_STAGE = register_stage(
    Stage(id="generation.company_summary", kind="llm", scopes=_GENERATION_SCOPES)
)
GENERATION_BLOCKS_STAGE = register_stage(
    Stage(id="generation.blocks", kind="orchestration", scopes=_GENERATION_SCOPES)
)
STAKEHOLDER_RECONCILE_STAGE = register_stage(
    Stage(
        id="generation.stakeholder_engagement.reconcile",
        kind="deterministic",
        scopes=_GENERATION_SCOPES,
    )
)
MODULE_TITLES_STAGE = register_stage(
    Stage(id="generation.module_titles", kind="llm", scopes=_GENERATION_SCOPES)
)
EXPORT_GATE_STAGE = register_stage(
    Stage(id="delivery.export_gate", kind="deterministic", scopes=_GENERATION_SCOPES)
)
DELIVERY_RENDER_STAGE = register_stage(
    Stage(id="delivery.render", kind="orchestration", scopes=_GENERATION_SCOPES)
)
LAYOUT_IMAGES_STAGE = register_stage(
    Stage(id="delivery.layout_images.resolve", kind="tool", scopes=_GENERATION_SCOPES)
)
RENDER_PLAN_STAGE = register_stage(
    Stage(
        id="delivery.render_plan.build", kind="deterministic", scopes=_GENERATION_SCOPES
    )
)
DOCX_WORD_STAGE = register_stage(
    Stage(id="delivery.docx.word", kind="deterministic", scopes=_GENERATION_SCOPES)
)
DOCX_REVIEW_STAGE = register_stage(
    Stage(id="delivery.docx.review", kind="deterministic", scopes=_GENERATION_SCOPES)
)
INTERNAL_AUDIT_STAGE = register_stage(
    Stage(
        id="delivery.internal_audit.package",
        kind="deterministic",
        scopes=_GENERATION_SCOPES,
    )
)
GENERATION_COMMIT_STAGE = register_stage(
    Stage(id="generation.commit", kind="deterministic", scopes=_GENERATION_SCOPES)
)
REPORT_GENERATION_HARNESS_VERSION = "sustainability_desk.lightweight-generation-harness.v1"


def report_artifact_root() -> Path:
    """返回报告交付物的私有根目录；非本机环境必须由受限环境文件指定。"""

    configured = os.getenv("SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT")
    if not configured:
        return DEFAULT_ARTIFACT_ROOT
    root = Path(configured)
    if not root.is_absolute():
        raise ReportGenerationServiceError(
            "SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT 必须是绝对路径"
        )
    return root


class ReportGenerationServiceError(RuntimeError):
    """报告级生成命令不满足当前产品或运行边界。"""


class ReportGenerationInputNotReadyError(ReportGenerationServiceError):
    """最低输入缺失，或当前资料尚未形成可冻结快照。"""


class ReportGenerationMappingError(ReportGenerationServiceError):
    """Mapping 结果没有完整覆盖当前报告生成合同。"""


class ReportGenerationIncompleteError(ReportGenerationServiceError):
    """部分块多次尝试仍未成功；user_message 面向用户可行动，不暴露守卫与重试机制。"""

    def __init__(self, *, user_message: str, failed_block_ids: tuple[str, ...]) -> None:
        self.user_message = user_message
        self.failed_block_ids = failed_block_ids
        super().__init__(user_message)


def _report_section_titles_of_blocks(
    report: Report, block_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """块 → 所属议题/章节的用户可见标题（最近的带 reportSectionId 祖先；front 章取本节标题）。"""

    wanted = set(block_ids)
    titles: list[str] = []

    def walk(sections: list[Section], inherited_title: str | None) -> None:
        for section in sections:
            effective = section.title if section.reportSectionId else inherited_title
            own_blocks = list(section.blocks or [])
            if section.conciseDisclosure is not None:
                own_blocks.append(section.conciseDisclosure)
            if any(block.id in wanted for block in own_blocks):
                titles.append(effective or section.title)
            walk(section.children or [], effective)

    walk(report.sections, None)
    return tuple(dict.fromkeys(titles))


def _incomplete_generation_user_message(
    report: Report,
    failed: list[dict],
) -> str:
    """失败终态的用户可见说明：指出未完成的内容与可行动建议，不描述内部机制。"""

    failed_ids = tuple(str(item.get("blockId") or "") for item in failed)
    titles = _report_section_titles_of_blocks(report, failed_ids)
    listed = "、".join(f"「{title}」" for title in titles[:3])
    if len(titles) > 3:
        listed += f" 等 {len(titles)} 处"
    message = "本次报告未能完整生成"
    message += f"：{listed}的部分内容多次尝试仍未达到披露要求。" if listed else "。"
    if any(
        "missing_or_negative_statement" in (item.get("guardrailIssueKeys") or [])
        for item in failed
    ):
        message += (
            "请检查上述内容对应的填写：补充说明中「暂未建立相关制度」「尚未开展」类描述"
            "可改为只描述已有的日常做法，或留空（未填写的内容会按无资料方式生成），"
            "修改后重新生成。"
        )
    else:
        message += "可稍后重新生成；若多次出现，请联系我们协助处理。"
    message += "既有报告和交付物未被覆盖。"
    return message


def _fingerprint(value: object) -> str:
    payload = (
        value.model_dump(mode="json", by_alias=True)
        if hasattr(value, "model_dump")
        else value
    )
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _file_fingerprint(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _material_set_requires_confirmation(
    *,
    existing_workspace: material_dal.MaterialWorkspace | None,
    file_declarations: list[
        tuple[
            material_dal.MaterialSource,
            material_dal.ReportMaterialBinding,
            material_dal.UserFileDeclarationRevision,
        ]
    ],
    pending_file_description_count: int,
) -> bool:
    """派生前门"资料确认"blocker 是否应出现；与 pending_description 互斥共存。

    说明未齐时确认不可达，不重复指责；没有 workspace 或没有 active 语义资料
    （含零文件报告、只有排版素材的报告）都不需要确认；其余情况以重算指纹与已存储
    确认指纹比对。
    """

    if pending_file_description_count > 0:
        return False
    if existing_workspace is None:
        return False
    if not has_active_semantic_material(file_declarations):
        return False
    return (
        existing_workspace.material_set_confirmed_fingerprint
        != active_binding_fingerprint(file_declarations)
    )


def _unfinished_file_work_message(
    work: pipeline_dal.UnfinishedFileAgentWork,
) -> str:
    """按真实处境给出可操作指引：等待、重传，还是联系支持。

    合并成一句"请处理失败或仍在处理的资料"会让用户面对全部显示已处理的列表
    却不知道该做什么。
    """

    parts: list[str] = []
    if work.failed_count:
        parts.append(
            f"{work.failed_count} 份资料分析失败，请在资料页重新上传或将其移出报告"
        )
    if work.in_flight_count:
        parts.append(f"{work.in_flight_count} 份资料仍在分析中，请稍候再试")
    if work.never_enqueued_binding_ids:
        # 自愈后仍然存在，说明补入队没能建立运行——属于需要介入的异常。
        parts.append(
            f"{len(work.never_enqueued_binding_ids)} 份资料未能进入分析队列，"
            "请重新确认资料集；若反复出现请联系支持"
        )
    return "；".join(parts) + "。"


async def _reenqueue_missing_file_agent_runs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    binding_ids: tuple[UUID, ...],
) -> None:
    """为已确认却从未入队的语义资料补建 File Agent Run。

    入队幂等，重复调用不会产生额外模型调用；补入队失败不在此处 fail-loud，
    调用方会重读真实状态并据此给出面向用户的指引。
    """

    from sustainability_desk.material.agent_pipeline import (
        enqueue_file_agent_for_binding,
    )

    workspace = await material_dal.get_workspace_by_report(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if workspace is None:
        return
    for binding_id in binding_ids:
        try:
            await enqueue_file_agent_for_binding(
                pool,
                account_id=account_id,
                report_id=report_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "补入队 File Agent 失败 reportId=%s bindingId=%s",
                report_id,
                binding_id,
            )


async def _reenqueue_missing_image_agent_runs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    binding_ids: tuple[UUID, ...],
) -> None:
    """为说明已填却从未入队的排版素材补建 Image Agent Run。

    素材在说明保存时入队，不经资料集确认；若当时入队失败（只记日志、不阻断保存），
    生成前在此补齐。入队幂等，补入队失败不在此处 fail-loud——图片是排版增强，
    调用方只按仍在进行中的运行决定是否等待。
    """

    from sustainability_desk.material.agent_pipeline import (
        enqueue_image_agent_for_binding,
    )

    workspace = await material_dal.get_workspace_by_report(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if workspace is None:
        return
    for binding_id in binding_ids:
        try:
            await enqueue_image_agent_for_binding(
                pool,
                account_id=account_id,
                report_id=report_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "补入队 Image Agent 失败 reportId=%s bindingId=%s",
                report_id,
                binding_id,
            )


async def enqueue_report_generation(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    request: CreateReportGenerationRequest,
) -> UUID:
    """冻结当前资料版本并幂等建立一次显式生成或更新运行。"""

    execution_scope = await _current_generation_scope(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    report_snapshot = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        account_id,
        report_id,
    )
    if report_snapshot.state_seq != request.base_report_state_seq:
        raise generation_dal.ReportGenerationConflictError(
            "报告输入已变化，请刷新后重新生成"
        )
    profile = require_report_profile(report_snapshot.report_profile_id)
    report = execution_scope.project_report(
        build_report_revision(
            report_snapshot.state, package=execution_scope.knowledge_package
        )
    )
    existing_workspace = await material_dal.get_workspace_by_report(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    file_declarations = (
        await material_dal.list_report_file_declarations(
            pool,
            account_id=account_id,
            workspace_id=existing_workspace.id,
        )
        if existing_workspace is not None
        else []
    )
    pending_description_count = pending_file_description_count(file_declarations)
    material_set_requires_confirmation = _material_set_requires_confirmation(
        existing_workspace=existing_workspace,
        file_declarations=file_declarations,
        pending_file_description_count=pending_description_count,
    )
    preparation_blockers = generation_preparation_blockers(
        state=report_snapshot.state,
        profile=profile,
        report=report,
        # 定量信息不是生成门槛：留空按「尚未收集」在范围
        # 投影确定性补全，完整性校验对补全后的投影恒过，只作兜底。
        required_quantitative_metric_keys=None,
        pending_file_description_count=pending_description_count,
        material_set_requires_confirmation=material_set_requires_confirmation,
        # 闸一（design.md §7.3）：文件层无法解析的 active 文件必须先被重传或移出。
        unresolved_failed_file_count=sum(
            1
            for source, binding, _declaration in file_declarations
            if binding.status == "active" and source.status == "failed"
        ),
    )
    if preparation_blockers:
        raise ReportGenerationInputNotReadyError(
            "生成前请完成："
            f"{', '.join(blocker.label for blocker in preparation_blockers)}"
        )
    await _ensure_generation_workspace(
        pool,
        account_id=account_id,
        report_id=report_id,
        report_contract_version=report_snapshot.contract_version,
    )
    # 独立于确认标志的后门：即使确认逻辑有 bug 或被绕过，只要仍有 active 语义资料
    # 从未形成 succeeded/needs_attention 的 File Agent 结果，也一律拒绝生成；
    # 零文件报告没有 active 语义资料，不受影响。
    unfinished_files = await pipeline_dal.unfinished_file_agent_work(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    # 「已确认但从未入队」是产品自身的遗漏（确认先于入队落库时会造成），
    # 用户无从修复也无法从界面看出——就地补入队自愈，而不是让报告永久卡死。
    if unfinished_files.never_enqueued_binding_ids:
        await _reenqueue_missing_file_agent_runs(
            pool,
            account_id=account_id,
            report_id=report_id,
            binding_ids=unfinished_files.never_enqueued_binding_ids,
        )
        unfinished_files = await pipeline_dal.unfinished_file_agent_work(
            pool,
            account_id=account_id,
            report_id=report_id,
        )
    if unfinished_files.total:
        raise ReportGenerationInputNotReadyError(
            _unfinished_file_work_message(unfinished_files)
        )
    # 说明已填却从未入队的素材是产品自身的遗漏（说明保存时入队失败只记日志），
    # 生成前就地补入队，使图片能进入本次生成的放置。
    never_enqueued_images = await pipeline_dal.never_enqueued_image_agent_binding_ids(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if never_enqueued_images:
        await _reenqueue_missing_image_agent_runs(
            pool,
            account_id=account_id,
            report_id=report_id,
            binding_ids=never_enqueued_images,
        )
    # 素材图片识别只在 queued/running 时阻断；failed 不阻断——图片是排版增强,
    # 识别失败的素材跳过放置并在上传页提示,不构成语义正确性输入。
    unfinished_images = await pipeline_dal.unfinished_image_agent_run_count(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if unfinished_images:
        raise ReportGenerationInputNotReadyError(
            "素材图片识别仍在进行；请稍候完成后再生成。"
        )

    snapshot_id = await synchronize_mapping_runs(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if snapshot_id is None:
        # 已过资料闸却拿不到快照：资料与报告范围的匹配尚未建立，与"分析未完成"不同，
        # 不能复用同一句话误导用户去处理其实已处理好的文件。
        raise ReportGenerationInputNotReadyError(
            "资料与报告范围的匹配尚未建立，请稍候重试；若反复出现请重新确认资料集。"
        )
    material_snapshot = await pipeline_dal.get_material_set_snapshot(
        pool,
        account_id=account_id,
        report_id=report_id,
        snapshot_id=snapshot_id,
    )
    expected_block_ids = tuple(block.id for block in blocks_for_report(report))
    # 模型在**入队边界**定值：此后该运行的模型由队列行携带，worker 只执行不再选择。
    # 客户端给出的 id 必须是当前环境可选（凭据齐备）的注册条目，判据与 build_model 同源。
    model_id = resolve_selected_model_id(request.model_id)
    layout_asset_records = await layout_asset_dal.current_layout_asset_records(
        pool,
        report_id,
    )
    input_fingerprint = _fingerprint(
        {
            "reportState": report_snapshot.state.model_dump(
                mode="json",
                by_alias=True,
            ),
            "reportProfile": report_snapshot.report_profile_id,
            "reportScope": execution_scope.kind,
            "materialSet": material_snapshot.snapshot.input_fingerprint,
            "expectedBlocks": expected_block_ids,
            # 素材图片集是生成输入:图片增删、题注、识别类别或放置范围变化都
            # 使指纹变化,工作台据此出现"报告可更新"。
            "layoutAssetSet": [
                {
                    "assetId": str(record.asset_id),
                    "version": record.version,
                    "fingerprint": record.fingerprint,
                    "placementScopeId": record.placement_scope_id,
                    "category": record.category,
                    "caption": record.caption,
                }
                for record in layout_asset_records
            ],
            "harnessVersion": REPORT_GENERATION_HARNESS_VERSION,
            # 模型是生成输入：同一份输入换模型写出的正文并不相同，指纹必须随之变化，
            # 否则界面会把「换了模型」显示成无变化、不提示报告可更新。
            "modelId": model_id,
        }
    )
    run = await generation_dal.enqueue_generation(
        pool,
        run_id=uuid4(),
        account_id=account_id,
        report_id=report_id,
        material_set_snapshot_id=snapshot_id,
        base_report_state_seq=request.base_report_state_seq,
        input_fingerprint=input_fingerprint,
        idempotency_key=request.idempotency_key,
        model_id=model_id,
        expected_block_ids=expected_block_ids,
    )
    return run.run_id


async def _current_generation_scope(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> EffectiveReportScope:
    """在入队和 worker 提交前按当前 Grant 重新裁决报告生成范围。"""

    try:
        context = await get_account_context_for_account(pool, account_id)
        summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    except (AccountNotFoundError, AccountEntitlementError) as error:
        raise ReportGenerationServiceError("Account 权益状态异常") from error
    capabilities = report_capabilities(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )
    if not capabilities["can_generate"]:
        raise ReportGenerationServiceError("当前 Account 无权生成该报告")
    return effective_report_scope(
        context,
        created_under_profile_id=summary.created_under_profile_id,
        report_profile_id=summary.report_profile_id,
    )


async def _ensure_generation_workspace(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    report_contract_version: str,
) -> UUID:
    """确保显式生成也可从零文件状态进入同一资料快照主链。"""

    workspace = await material_dal.get_or_create_workspace(
        pool,
        account_id=account_id,
        report_id=report_id,
        adapter_id=LightweightReportInputAdapter.adapter_id,
        contract_version=report_contract_version,
    )
    return workspace.id


def _mapping_evidence(
    *,
    expected_block_ids: tuple[str, ...],
    results,
    mapping_plan: FrozenMappingPlan,
    dossiers: tuple[FileDossier, ...],
    scope_to_expected: bool = False,
) -> tuple[
    dict[str, BlockMappedEvidence],
    tuple[FileMaterial, ...],
    tuple[BlockMaterialDecision, ...],
]:
    """把冻结 Mapping 投影成逐块证据；覆盖不全或引用快照外材料即 fail-loud。

    ``scope_to_expected`` 供**整节重写**使用：冻结 plan 覆盖整份报告，而重写只要这一节，
    故把「plan 必须被完整覆盖」收窄到 plan ∩ 本节。两条 fail-loud 语义在节内不变——
    仍拒绝快照外 FileMaterial，仍拒绝本节内缺决定；放宽的只是「节外的块不关本次的事」。
    报告级生成保持默认值，覆盖校验仍按整份报告执行。
    """

    expected = set(expected_block_ids)
    decisions: dict[str, BlockMaterialDecision] = {}
    materials = {
        material.material_id: material
        for dossier in dossiers
        for material in dossier.materials
    }
    for result in results:
        for decision in result.block_decisions:
            if decision.block_id not in expected:
                continue
            if decision.block_id in decisions:
                raise ReportGenerationMappingError(
                    f"Block {decision.block_id} 存在重复 Mapping 决定"
                )
            decisions[decision.block_id] = decision
            for material_id in decision.material_ids:
                if material_id not in materials:
                    raise ReportGenerationMappingError(
                        f"Block {decision.block_id} 引用了快照外 FileMaterial"
                    )
    planned = set(mapping_plan.block_ids)
    if scope_to_expected:
        # 整节重写：冻结 plan 覆盖整份报告，本次只负责这一节。节外的块不在 expected 里，
        # 既不该被要求有决定，也不该被当成「plan 里有报告不存在的块」。
        planned &= expected
    if not planned.issubset(expected):
        unexpected = sorted(planned - expected)
        raise ReportGenerationMappingError(
            f"冻结 Mapping plan 包含当前报告不存在的 Block：{', '.join(unexpected)}"
        )
    if set(decisions) != planned:
        missing = sorted(planned - set(decisions))
        raise ReportGenerationMappingError(
            f"Mapping 尚未完整覆盖冻结 scope：{', '.join(missing)}"
        )
    mapped = {
        block_id: (
            BlockMappedEvidence(
                materials=tuple(
                    materials[material_id]
                    for material_id in decisions[block_id].material_ids
                ),
                decision=decisions[block_id],
                file_routing_disposition="mapping_decision",
            )
            if block_id in decisions
            else BlockMappedEvidence(
                file_routing_disposition="no_applicable_file_dossier"
            )
        )
        for block_id in expected_block_ids
    }
    selected_materials = tuple(
        materials[material_id]
        for decision in decisions.values()
        for material_id in decision.material_ids
    )
    return mapped, selected_materials, tuple(decisions.values())


@lru_cache(maxsize=None)
def _block_display_labels(package_id: str) -> dict[str, str]:
    """从编译契约派生 block → 用户可读标题;无标题的块回退最近有标题的祖先章节。"""

    definition = load_compiled_report_definition(load_knowledge_package(package_id))
    labels: dict[str, str] = {}
    for node_id, node in definition.nodes_by_id.items():
        if node.kind != "block":
            continue
        title = (node.title or "").strip()
        if not title or title == node.source_id:
            placement = definition.node_placements.get(node_id)
            title = ""
            if placement is not None:
                for ancestor_id in reversed(placement.ancestor_node_ids):
                    ancestor_title = (
                        definition.nodes_by_id[ancestor_id].title or ""
                    ).strip()
                    if ancestor_title:
                        title = ancestor_title
                        break
        if title:
            labels[node.source_id] = title
    return labels


def _compiled_block_review_labels(
    block_decisions: tuple[BlockMaterialDecision, ...],
    *,
    package: KnowledgePackage,
) -> tuple[BlockReviewLabel, ...]:
    """从报告合同投影客户标题；未知 Block 不得退回内部身份。"""

    definition = load_compiled_report_definition(package)
    labels: list[BlockReviewLabel] = []
    for decision in block_decisions:
        try:
            contract = definition.generation_for_block(decision.block_id)
            block_node = definition.nodes_by_id[contract.node_id]
            label = block_node.title.strip()
            if label == decision.block_id:
                placement = definition.node_placements[contract.node_id]
                label = next(
                    (
                        definition.nodes_by_id[node_id].title.strip()
                        for node_id in reversed(placement.ancestor_node_ids)
                        if definition.nodes_by_id[node_id].title.strip()
                    ),
                    "",
                )
        except KeyError as error:
            raise ReportGenerationMappingError(
                f"Block {decision.block_id} 缺少客户可见标题"
            ) from error
        if not label:
            raise ReportGenerationMappingError(
                f"Block {decision.block_id} 缺少客户可见标题"
            )
        labels.append(
            BlockReviewLabel(
                block_id=decision.block_id,
                label=label,
            )
        )
    return tuple(labels)


def _generation_trace_reference(
    *,
    lease: generation_dal.ReportGenerationLease,
    observation: ObservationRun,
    output_fingerprint: str,
) -> InternalTraceReference:
    """把本次生成 observation 投影为内部包可复盘引用。"""

    if (
        observation.runId != str(lease.run_id)
        or observation.reportId != str(lease.report_id)
        or observation.status != "succeeded"
        or not observation.path.is_file()
    ):
        raise ReportGenerationServiceError(
            "本次报告生成 observation 尚未形成有效完成记录"
        )
    return InternalTraceReference(
        stage="generation",
        trace_id=observation.traceId,
        contract=SCHEMA_VERSION,
        input_fingerprint=lease.input_fingerprint,
        output_fingerprint=output_fingerprint,
        storage_ref=str(observation.path),
    )


def _report_block_ids(report) -> frozenset[str]:
    """收集当前范围报告的全部 block id,用于放置时过滤已不在范围的承载位。"""

    ids: set[str] = set()

    def walk(sections) -> None:
        for section in sections:
            for block in section.blocks:
                ids.add(block.id)
            walk(section.children or [])

    walk(report.sections)
    return frozenset(ids)


def _apply_certificate_table(patched: dict, *, records, valid_block_ids: frozenset[str]) -> None:
    """把入口解析的证书事实收敛成集中承载表的数据行。

    证书是企业整体事实：一张 ISO 14001 天然横跨环境、能源、污染物、废弃物、水资源
    等多个议题，用户也可能为不同议题各上传一张同证书照片。清单按「名称+发证机构」
    归并，使每张证书在报告中只出现一行——这正是议题正文不再复述认证范围的前提。

    行由代码确定性生成，模型不参与；无证书时不写该块，表格无数据行即整章不可渲染。
    """

    from sustainability_desk.contract.certificate_facts import (
        CERTIFICATE_TABLE_BLOCK_ID,
        certificate_facts_from_records,
        certificate_table_rows,
    )

    if CERTIFICATE_TABLE_BLOCK_ID not in valid_block_ids:
        return
    facts = certificate_facts_from_records(records)
    if not facts:
        return
    tables = dict(patched.get("tableBlocks") or {})
    # 只投影 StoredTableCell 承认的字段：状态快照不接受 Plate 文本骨架
    # （stored_report_state.StoredTableCell 的 extra=forbid 会拒绝 children）。
    tables[CERTIFICATE_TABLE_BLOCK_ID] = {
        "children": [
            {
                "children": [
                    {"type": cell.type, "colKey": cell.colKey, "value": cell.value}
                    for cell in row.children
                ]
            }
            for row in certificate_table_rows(facts)
        ],
        "state": "ready",
    }
    patched["tableBlocks"] = tables


def _apply_layout_asset_placements(
    patched: dict,
    *,
    records,
    block_by_scope: dict[str, str],
    valid_block_ids: frozenset[str],
) -> None:
    """把识别完成的素材按 scope→承载块映射确定性写入 state.imageBlocks。

    scope 已不在当前报告范围(如权益收窄)的资产正常跳过,不是错误;
    records 已按 binding 建立时间排序,块内多图沿用该顺序。
    """

    image_blocks: dict[str, dict] = {}
    for record in records:
        scope_id = record.placement_scope_id
        block_id = block_by_scope.get(scope_id) if scope_id else None
        if block_id is None or block_id not in valid_block_ids:
            continue
        entry = image_blocks.setdefault(
            block_id, {"layoutAssetIds": [], "state": "ready"}
        )
        entry["layoutAssetIds"].append(str(record.asset_id))
    patched["imageBlocks"] = image_blocks


def _layout_image_width_cm(
    *,
    package: KnowledgePackage,
    width_px: int | None,
    height_px: int | None,
) -> float:
    """按宽高比的确定性宽度规则;模型不输出尺寸。参数归格式 profile。"""

    rules = load_format_profile(package).figures.aspect_ratio_rules
    if not width_px or not height_px:
        return rules.mid_cm
    aspect_ratio = width_px / height_px
    if aspect_ratio >= rules.wide_threshold:
        return rules.wide_cm
    if aspect_ratio >= rules.mid_threshold:
        return rules.mid_cm
    return min(rules.narrow_cap_cm, round(rules.narrow_scale_cm * aspect_ratio, 2))


async def resolve_layout_images(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    state: StoredReportStateV4,
    records,
    storage: MaterialStorageClient,
    package: KnowledgePackage,
) -> dict[str, tuple[ResolvedEvidenceImage, ...]]:
    """按 state.imageBlocks 逐资产解析图片字节:素材一律以归一化原图进报告。

    生成路径与导出路径共用本函数：二者都必须以权威 state 的放置事实为准，
    否则人工修订后的导出会与生成交付物在「有没有这张图」上分叉。
    """

    if not state.imageBlocks:
        return {}
    record_by_asset = {str(record.asset_id): record for record in records}
    workspace = await material_dal.get_workspace_by_report(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    resolved: dict[str, tuple[ResolvedEvidenceImage, ...]] = {}
    for block_id, stored in state.imageBlocks.items():
        images: list[ResolvedEvidenceImage] = []
        for asset_id in stored.layoutAssetIds:
            record = record_by_asset.get(str(asset_id))
            if record is None:
                # 资产在放置与导出之间被移出;跳过该图,导出不阻断。
                continue
            figure_kind: FigureKind = "evidence_image"
            source = await material_dal.get_source(
                pool,
                account_id=account_id,
                workspace_id=workspace.id,
                source_id=record.material_source_id,
            )
            raw = await storage.download(
                source.object_path,
                max_bytes=source.size_bytes + 1,
            )
            data = prepare_model_image(raw, media_type=source.media_type).data
            width_px, height_px = model_image_pixel_size(
                raw, media_type=source.media_type
            )
            images.append(
                ResolvedEvidenceImage(
                    data=data,
                    caption=record.caption,
                    alt_text=record.alt_text,
                    width_cm=_layout_image_width_cm(
                        package=package,
                        width_px=width_px,
                        height_px=height_px,
                    ),
                    kind=figure_kind,
                )
            )
        if images:
            resolved[block_id] = tuple(images)
    return resolved


async def _load_layout_image_review_inputs(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    state: StoredReportStateV4,
    package: KnowledgePackage,
) -> tuple[LayoutImageReviewInput, ...]:
    """按 state.imageBlocks 解析每幅已放置素材的客户可读来源：上传文件名、用户说明、识别类别与放置范围。

    只读稳定事实（文件名、用户声明原话、category code、契约范围标题）；识别 Agent 的模型文本不进入。
    资产在放置与导出之间被移出时跳过，与渲染器同一处置。
    """

    if not state.imageBlocks:
        return ()
    workspace = await material_dal.get_workspace_by_report(
        pool, account_id=account_id, report_id=report_id
    )
    if workspace is None:
        return ()
    records = await layout_asset_dal.current_layout_asset_records(pool, report_id)
    record_by_asset = {str(record.asset_id): record for record in records}
    declarations = await material_dal.list_report_file_declarations(
        pool, account_id=account_id, workspace_id=workspace.id
    )
    by_source: dict[UUID, tuple] = {}
    for source, binding, declaration in declarations:
        if binding.status == "active" or source.id not in by_source:
            by_source[source.id] = (source, declaration)
    scope_titles = {
        slot.scope_id: slot.scope_title
        for slot in layout_asset_slots(load_compiled_report_definition(package))
    }
    inputs: list[LayoutImageReviewInput] = []
    for block_id, stored in state.imageBlocks.items():
        for asset_id in stored.layoutAssetIds:
            record = record_by_asset.get(str(asset_id))
            if record is None or record.material_source_id not in by_source:
                continue
            source, declaration = by_source[record.material_source_id]
            inputs.append(
                LayoutImageReviewInput(
                    asset_id=asset_id,
                    block_id=block_id,
                    material_name=source.filename,
                    user_description=declaration.description,
                    asset_title=declaration.asset_title,
                    category=record.category,
                    placement_scope_title=(
                        scope_titles.get(record.placement_scope_id or "") or "本节"
                    ),
                )
            )
    return tuple(inputs)


def _image_agent_trace_references(
    receipts,
) -> tuple[InternalTraceReference, ...]:
    """把成功的 Image Agent 运行收敛为内部审计包的观测 trace 身份。"""

    references: list[InternalTraceReference] = []
    for receipt in receipts:
        if receipt.status != "completed":
            continue
        if not receipt.observation_run_id or not receipt.dossier_fingerprint:
            raise ReportGenerationServiceError(
                "完成的 Image Agent 运行缺少完整 trace 身份"
            )
        references.append(
            InternalTraceReference(
                stage="image_agent",
                trace_id=receipt.observation_run_id,
                contract=SCHEMA_VERSION,
                input_fingerprint=_fingerprint(receipt.source_revision),
                output_fingerprint=receipt.dossier_fingerprint,
                **_trace_availability(receipt.observation_run_id, stage="image_agent"),
            )
        )
    return tuple(references)


def _trace_availability(run_id: str, *, stage: str, report_id: object = "") -> dict[str, str]:
    """解析一条轨迹引用的可用性；缺失时降级为显式不可用，不阻断交付。

    轨迹是审计旁路证据。正文已生成、交付物已产出时，一条引用取不到不应让用户拿不到
    报告（否则全部块生成成功、Word 已落盘，整次生成仍会被判 failed）。
    缺失必须显式可见并记 warning——不静默，也不阻断。
    正常情况下轨迹不会缺失：写入根已收敛为唯一，且工作单元成功收尾时就地断言已落盘。
    """

    try:
        return {"storage_ref": str(locate_observation_trace(run_id))}
    except FileNotFoundError:
        logger.warning(
            "internal_audit_trace_unavailable stage=%s run_id=%s report_id=%s",
            stage,
            run_id,
            report_id,
        )
        return {"unavailable_reason": "轨迹在打包时不可读取"}


def _pipeline_trace_references(
    *,
    receipts,
    mapping_records,
    mapping_results,
) -> tuple[InternalTraceReference, ...]:
    """把已完成的 File/Mapping 运行收敛为可复制的完整观测 trace 身份。"""

    references: list[InternalTraceReference] = []
    for receipt in receipts:
        if receipt.status != "completed":
            continue
        if not receipt.observation_run_id or not receipt.dossier_fingerprint:
            raise ReportGenerationServiceError(
                "完成的 File Agent 运行缺少完整 trace 身份"
            )
        references.append(
            InternalTraceReference(
                stage="file_agent",
                trace_id=receipt.observation_run_id,
                contract=SCHEMA_VERSION,
                input_fingerprint=_fingerprint(receipt.source_revision),
                output_fingerprint=receipt.dossier_fingerprint,
                **_trace_availability(receipt.observation_run_id, stage="file_agent"),
            )
        )
    result_by_scope = {item.scope_id: item for item in mapping_results}
    for record in mapping_records:
        result = result_by_scope.get(record.scope_id)
        if result is None:
            raise ReportGenerationServiceError("Mapping trace 缺少同 scope 结果")
        references.append(
            InternalTraceReference(
                stage="mapping",
                trace_id=record.observation_run_id,
                contract=SCHEMA_VERSION,
                input_fingerprint=record.input_fingerprint,
                output_fingerprint=_fingerprint(result),
                **_trace_availability(record.observation_run_id, stage="mapping"),
            )
        )
    return tuple(references)


def _write_internal_audit_zip(
    path: Path,
    *,
    internal_json: str,
    internal_markdown: str,
    customer_commentary_json: str,
    trace_references: tuple[InternalTraceReference, ...],
    report_id: UUID,
) -> None:
    """将完整、严格可解析的运行 trace 快照写入受限内部审计包。"""

    manifest: list[dict[str, object]] = []
    trace_keys = [(item.stage, item.trace_id) for item in trace_references]
    if len(trace_keys) != len(set(trace_keys)):
        raise ReportGenerationServiceError("内部审计 trace 不得重复")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("internal-audit.json", internal_json)
        archive.writestr("internal-audit.md", internal_markdown)
        archive.writestr("review-commentary.json", customer_commentary_json)
        for reference in trace_references:
            if reference.storage_ref is None:
                # 引用已在解析边界降级为不可用，并已记 warning；审计包如实记录该事实，
                # 不因一条旁路证据缺失而让用户拿不到已经生成好的报告。
                manifest.append(
                    {
                        "stage": reference.stage,
                        "traceId": reference.trace_id,
                        "available": False,
                        "unavailableReason": reference.unavailable_reason,
                    }
                )
                continue
            trace_path = Path(reference.storage_ref)
            if not trace_path.is_file():
                logger.warning(
                    "internal_audit_trace_vanished stage=%s run_id=%s path=%s",
                    reference.stage,
                    reference.trace_id,
                    trace_path,
                )
                manifest.append(
                    {
                        "stage": reference.stage,
                        "traceId": reference.trace_id,
                        "available": False,
                        "unavailableReason": "轨迹在打包时已不可读取",
                    }
                )
                continue
            raw = trace_path.read_text(encoding="utf-8")
            lines = [line for line in raw.splitlines() if line.strip()]
            if not lines:
                # 空文件与文件缺失同类：都是证据取不到，不是业务事实错误。
                logger.warning(
                    "internal_audit_trace_empty stage=%s run_id=%s",
                    reference.stage,
                    reference.trace_id,
                )
                manifest.append(
                    {
                        "stage": reference.stage,
                        "traceId": reference.trace_id,
                        "available": False,
                        "unavailableReason": "轨迹为空",
                    }
                )
                continue
            events = [parse_observability_event(line) for line in lines]
            if any(event.reportId != str(report_id) for event in events):
                raise ReportGenerationServiceError(
                    f"内部审计 trace 报告身份不一致：{reference.trace_id}"
                )
            arcname = f"traces/{reference.stage}/{reference.trace_id}.jsonl"
            archive.writestr(arcname, raw)
            manifest.append(
                {
                    "stage": reference.stage,
                    "traceId": reference.trace_id,
                    "contract": reference.contract,
                    "archivePath": arcname,
                    "sha256": sha256(raw.encode("utf-8")).hexdigest(),
                    "bytes": len(raw.encode("utf-8")),
                    "eventCount": len(events),
                    "parseStatus": "verified",
                }
            )
        archive.writestr(
            "traces/manifest.json",
            json.dumps({"entries": manifest}, ensure_ascii=False, indent=2) + "\n",
        )


async def _build_artifacts(
    pool: asyncpg.Pool,
    *,
    lease: generation_dal.ReportGenerationLease,
    planned_revision: generation_dal.PlannedReportRevision,
    report_title: str,
    state: StoredReportStateV4,
    content_fingerprint: str,
    snapshot,
    mapping_results,
    block_decisions: tuple[BlockMaterialDecision, ...],
    generation_observation: ObservationRun,
    artifact_root: Path,
    execution_scope: EffectiveReportScope,
    trace_id: str,
    render_stage: StageHandle,
    resolved_layout_images: dict[str, tuple[ResolvedEvidenceImage, ...]] | None = None,
    image_agent_receipts: tuple = (),
    deliverable_report: Report | None = None,
    disclosure_coverage: "DisclosureCoverageReport | None" = None,
) -> tuple[generation_dal.ReportArtifactWrite, ...]:
    revision_dir = (
        artifact_root / str(lease.report_id) / str(planned_revision.revision_id)
    )
    revision_dir.mkdir(parents=True, exist_ok=False)

    shell_path = revision_dir / "render-shell.docx"
    delivery_generated_at = datetime.now(timezone.utc)
    company_registered_name = state.fields.get("company_registered_name")
    if not isinstance(company_registered_name, str):
        raise ReportGenerationServiceError("报告缺少可用于交付文件名的公司注册名称")
    # 包取自执行范围而非 state：StoredReportStateV4 不带 knowledgePackageId，
    # 且交付文件名要在 revision_report 装配之前算出。
    filename_variants = load_format_profile(
        execution_scope.knowledge_package
    ).labels.delivery_filename_variants
    try:
        word_filename = delivery_docx_filename(
            company_registered_name=company_registered_name,
            variant=filename_variants.word,
            generated_at=delivery_generated_at,
        )
        review_filename = delivery_docx_filename(
            company_registered_name=company_registered_name,
            variant=filename_variants.review,
            generated_at=delivery_generated_at,
        )
    except ValueError as error:
        raise ReportGenerationServiceError(str(error)) from error
    word_path = revision_dir / word_filename
    # 交付物报告由调用方按执行范围一次装配，渲染与渲染计划共用同一份，避免重复全量装配。
    revision_report = (
        deliverable_report
        if deliverable_report is not None
        else execution_scope.prepare_deliverable_report(
            build_report_revision(state, package=execution_scope.knowledge_package)
        )
    )
    render_package = knowledge_package_of(revision_report)
    render_format_profile = load_format_profile(render_package)
    with open_stage(
        RENDER_PLAN_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=render_stage,
    ) as plan_stage:
        render_plan = build_document_render_plan(revision_report)
        plan_stage.set_attribute("sustainability_desk.render_unit_count", len(render_plan.units))
    with open_stage(
        DOCX_WORD_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=render_stage,
    ):
        normalize_template(
            render_package.base_template_path, shell_path, profile=render_format_profile
        )
        render_final_docx(
            revision_report,
            shell_path,
            word_path,
            render_plan=render_plan,
            resolved_images=resolved_layout_images,
        )
        shell_path.unlink()

    word_artifact_id = uuid4()
    word_ref = ReportArtifactReference(
        artifact_id=word_artifact_id,
        report_revision_id=planned_revision.revision_id,
        kind="word",
        filename=word_path.name,
        content_fingerprint=_file_fingerprint(word_path),
        storage_ref=str(word_path.relative_to(artifact_root)),
    )
    customer_word_artifact_id = uuid4()
    customer_path = revision_dir / review_filename
    customer_ref = ReportArtifactReference(
        artifact_id=customer_word_artifact_id,
        report_revision_id=planned_revision.revision_id,
        kind="review",
        filename=customer_path.name,
        content_fingerprint="0" * 64,
        storage_ref=str(customer_path.relative_to(artifact_root)),
    )
    dossier_ids = tuple(member.dossier_id for member in snapshot.members)
    dossier_records = await pipeline_dal.load_dossiers(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        dossier_ids=dossier_ids,
    )
    receipts = await pipeline_dal.load_file_agent_receipts(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        dossier_ids=dossier_ids,
    )
    mapping_trace_records = await pipeline_dal.load_mapping_trace_records(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=snapshot.snapshot_id,
        scope_ids=tuple(scope.scope_id for scope in snapshot.mapping_plan.scopes),
    )
    review_source = ReportReviewSource(
        report_revision=ReportRevisionReference(
            report_id=lease.report_id,
            revision_id=planned_revision.revision_id,
            revision=planned_revision.revision,
            content_fingerprint=content_fingerprint,
            created_at=delivery_generated_at,
        ),
        report_title=report_title,
        materials=tuple(
            ReportMaterialReviewInput(
                source_revision=FileSourceRevision(
                    source_id=record.source_id,
                    source_sha256=record.dossier.source_revision.source_sha256,
                    declaration_revision=record.declaration.revision,
                ),
                filename=record.filename,
                declaration=record.declaration,
            )
            for record in dossier_records
        ),
        dossiers=tuple(record.dossier for record in dossier_records),
        block_decisions=block_decisions,
        mapping_plan=snapshot.mapping_plan,
        block_labels=_compiled_block_review_labels(
            block_decisions, package=knowledge_package_of(revision_report)
        ),
        artifacts=(word_ref, customer_ref),
        outside_scope_material_notice=OUTSIDE_SCOPE_MATERIAL_NOTICE,
        file_agent_receipts=receipts,
        trace_references=(
            *_pipeline_trace_references(
                receipts=receipts,
                mapping_records=mapping_trace_records,
                mapping_results=mapping_results,
            ),
            *_image_agent_trace_references(image_agent_receipts),
            _generation_trace_reference(
                lease=lease,
                observation=generation_observation,
                output_fingerprint=content_fingerprint,
            ),
        ),
        layout_images=await _load_layout_image_review_inputs(
            pool,
            account_id=lease.account_id,
            report_id=lease.report_id,
            state=state,
            package=render_package,
        ),
    )
    customer = build_customer_commentary_package(review_source, render_plan)
    # 与批注读同一份冻结 dossiers：说明页与正文批注同源，无须留意事项时为 None（不出页）。
    processing_notice = build_material_processing_notice(
        review_source, texts=render_format_profile.delivery_texts
    )
    # 准则对照说明页读导出闸同一份覆盖判定，保证判定一次、闸与交付同源。
    compliance_notice = (
        build_standards_compliance_notice(disclosure_coverage, package=render_package)
        if disclosure_coverage is not None
        else None
    )
    with open_stage(
        DOCX_REVIEW_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=render_stage,
    ) as review_stage:
        customer_shell_path = revision_dir / "render-comment-shell.docx"
        normalize_template(
            render_package.base_template_path,
            customer_shell_path,
            profile=render_format_profile,
        )
        render_final_docx(
            revision_report,
            customer_shell_path,
            customer_path,
            render_plan=render_plan,
            resolved_images=resolved_layout_images,
            comment_text_by_anchor=render_customer_comment_texts(
                customer, render_format_profile.delivery_texts
            ),
            delivery_variant="review",
            review_generated_at=customer.generated_at,
            cover_comment_text=render_customer_cover_comment(
                customer, render_format_profile.delivery_texts
            ),
            material_processing_notice=processing_notice,
            standards_compliance_notice=compliance_notice,
        )
        customer_shell_path.unlink()
        review_stage.set_attribute(
            "sustainability_desk.comment_entry_count", len(customer.entries)
        )
        included = compliance_notice is not None
        review_stage.set_attribute("sustainability_desk.compliance_notice_included", included)
        review_stage.set_attribute(
            "sustainability_desk.compliance_notice_item_count",
            sum(len(group.items) for group in compliance_notice.groups) if included else 0,
        )
    customer_ref = customer_ref.model_copy(
        update={"content_fingerprint": _file_fingerprint(customer_path)}
    )
    review_source = review_source.model_copy(
        update={"artifacts": (word_ref, customer_ref)}
    )
    internal = build_internal_audit_package(
        review_source,
        customer_commentary=customer,
        export_receipt=InternalExportReceipt(
            render_plan_fingerprint=customer.render_plan_fingerprint,
            normal_word_fingerprint=word_ref.content_fingerprint,
            customer_word_fingerprint=customer_ref.content_fingerprint,
            customer_commentary_fingerprint=customer.package_fingerprint,
            comment_entry_count=len(customer.entries),
        ),
    )

    internal_path = revision_dir / "内部审计包.zip"
    with open_stage(
        INTERNAL_AUDIT_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=render_stage,
    ) as audit_stage:
        _write_internal_audit_zip(
            internal_path,
            internal_json=internal.model_dump_json(indent=2),
            internal_markdown=render_internal_audit_markdown(internal),
            customer_commentary_json=customer.model_dump_json(indent=2),
            trace_references=review_source.trace_references,
            report_id=lease.report_id,
        )
        audit_stage.set_attribute(
            "sustainability_desk.trace_reference_count", len(review_source.trace_references)
        )
    return (
        generation_dal.ReportArtifactWrite(
            artifact_id=word_artifact_id,
            kind="word",
            filename=word_path.name,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content_fingerprint=word_ref.content_fingerprint,
            storage_ref=word_ref.storage_ref,
        ),
        generation_dal.ReportArtifactWrite(
            artifact_id=uuid4(),
            kind="review",
            filename=customer_path.name,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content_fingerprint=customer_ref.content_fingerprint,
            storage_ref=customer_ref.storage_ref,
        ),
        generation_dal.ReportArtifactWrite(
            artifact_id=uuid4(),
            kind="internal_audit",
            filename=internal_path.name,
            media_type="application/zip",
            content_fingerprint=_file_fingerprint(internal_path),
            storage_ref=str(internal_path.relative_to(artifact_root)),
        ),
    )


@dataclass(frozen=True)
class _GenerationInputs:
    """一次生成运行的已解析输入。

    把 lease 这一低结构领取记录，在生成开始前解析成携带业务判断的领域对象：
    权益范围已确定、资料快照已冻结、Mapping 证据已按 block 归集、报告已按范围投影。
    下游只消费本对象，不再回头查库或重算范围（Parse-First）。
    """

    execution_scope: EffectiveReportScope
    report_snapshot: reports_dal.LockedLightweightReportState
    material_snapshot: pipeline_dal.MaterialSetSnapshotRecord
    mapping_results: tuple[pipeline_dal.ValidatedMappingResult, ...]
    report: Report
    mapped_evidence: dict[str, BlockMappedEvidence]
    block_decisions: tuple[BlockMaterialDecision, ...]


async def resolve_section_mapped_evidence(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    expected_block_ids: tuple[str, ...],
) -> dict[str, BlockMappedEvidence] | None:
    """为整节重写装配冻结 Mapping 证据；尚无资料快照时返回 None。

    与报告级生成消费同一条装配链（快照 → 该快照的 Mapping 结果 → dossier →
    `_mapping_evidence`），只把覆盖校验收窄到本节。**不得**退化成「拿不到就当没有资料」：
    证据门控块在缺决定时会被判受控省略，而那会静默覆盖既有正文——调用方必须据
    `None` 拒绝重写，而不是继续。

    返回 `None` 只表示「本报告还没有资料快照」（零文件报告即如此）；快照存在而 Mapping
    不完整时仍由 `_mapping_evidence` fail-loud。
    """

    snapshot = await pipeline_dal.latest_material_set_snapshot(
        pool,
        account_id=account_id,
        report_id=report_id,
    )
    if snapshot is None:
        return None
    mapping_results = await pipeline_dal.current_mapping_results(
        pool,
        account_id=account_id,
        report_id=report_id,
        snapshot_id=snapshot.snapshot.snapshot_id,
    )
    dossier_records = await pipeline_dal.load_dossiers(
        pool,
        account_id=account_id,
        report_id=report_id,
        dossier_ids=tuple(member.dossier_id for member in snapshot.snapshot.members),
    )
    mapped, _selected, _decisions = _mapping_evidence(
        expected_block_ids=expected_block_ids,
        results=mapping_results,
        mapping_plan=snapshot.snapshot.mapping_plan,
        dossiers=tuple(record.dossier for record in dossier_records),
        scope_to_expected=True,
    )
    return mapped


async def _resolve_generation_inputs(
    pool: asyncpg.Pool,
    *,
    lease: generation_dal.ReportGenerationLease,
) -> _GenerationInputs:
    """把领取到的 lease 解析为可直接生成的输入；任一前提不成立即当场失败。"""

    execution_scope = await _current_generation_scope(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
    )
    report_snapshot = await reports_dal.get_lightweight_v4_snapshot(
        pool,
        lease.account_id,
        lease.report_id,
    )
    if report_snapshot.state_seq != lease.base_report_state_seq:
        raise generation_dal.ReportGenerationConflictError("报告输入在生成期间发生变化")
    material_snapshot = await pipeline_dal.get_material_set_snapshot(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=lease.material_set_snapshot_id,
    )
    mapping_results = await pipeline_dal.current_mapping_results(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        snapshot_id=lease.material_set_snapshot_id,
    )
    dossier_records = await pipeline_dal.load_dossiers(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
        dossier_ids=tuple(
            member.dossier_id for member in material_snapshot.snapshot.members
        ),
    )
    mapped, _selected_materials, block_decisions = _mapping_evidence(
        expected_block_ids=lease.expected_block_ids,
        results=mapping_results,
        mapping_plan=material_snapshot.snapshot.mapping_plan,
        dossiers=tuple(record.dossier for record in dossier_records),
    )
    report = execution_scope.project_report(
        build_report_revision(
            report_snapshot.state, package=execution_scope.knowledge_package
        )
    )
    if (
        tuple(block.id for block in blocks_for_report(report))
        != lease.expected_block_ids
    ):
        raise generation_dal.ReportGenerationConflictError(
            "报告权益范围已变化，请基于当前范围重新发起生成"
        )
    return _GenerationInputs(
        execution_scope=execution_scope,
        report_snapshot=report_snapshot,
        material_snapshot=material_snapshot,
        mapping_results=mapping_results,
        report=report,
        mapped_evidence=mapped,
        block_decisions=block_decisions,
    )


async def process_one_report_generation(
    pool: asyncpg.Pool,
    *,
    worker_id: str,
    model_id: str | None = None,
    artifact_root: Path | None = None,
    report_id: UUID | None = None,
    storage: MaterialStorageClient | None = None,
) -> bool:
    """领取一份报告级运行；仅完整正文和交付物成功后原子提交 revision。

    模型取自租约（入队时定值），而非本进程的环境变量：否则同一运行被不同环境的
    worker 领取时会用不同模型执行，而队列行与观测里记的又是另一个值。
    `model_id` 只作显式覆盖，供受控实验与单测使用。
    """

    resolved_artifact_root = artifact_root or report_artifact_root()

    lease = await generation_dal.claim_generation(
        pool,
        worker_id=worker_id,
        report_id=report_id,
    )
    if lease is None:
        return False
    resolved_model_id = model_id or lease.model_id
    # 报告级 traceId 复用 lease.run_id：它已是本次生成的唯一标识，内部审计包
    # 也按此 id 归集 trace（_generation_trace_reference）。不另造并行标识。
    trace_id = str(lease.run_id)
    # 根阶段横跨正文生成、导出闸与交付渲染，生命周期由 ExitStack 持有；
    # 它在 try 正常结束或异常退出时统一收束，异常状态由 open_stage 自行记录。
    stage_scope = ExitStack()
    try:
        with stage_scope:
            inputs = await _resolve_generation_inputs(pool, lease=lease)
            execution_scope = inputs.execution_scope
            report_stage = stage_scope.enter_context(
                open_stage(
                    REPORT_GENERATION_STAGE,
                    trace_id=trace_id,
                    report_id=str(lease.report_id),
                    scope=execution_scope.kind,
                    **{"sustainability_desk.block_count": len(lease.expected_block_ids)},
                )
            )
            return await _run_report_generation(
                pool,
                lease=lease,
                inputs=inputs,
                model_id=resolved_model_id,
                storage=storage,
                resolved_artifact_root=resolved_artifact_root,
                trace_id=trace_id,
                report_stage=report_stage,
            )
    except Exception as error:  # noqa: BLE001 - 报告级失败必须形成用户可见终态
        # 失败根因必须留在服务端日志：span 按内容边界只记异常类型，没有堆栈
        # 会让跨环境失败无从定位。
        logger.exception("报告生成失败（run %s）：%s", lease.run_id, type(error).__name__)
        await generation_dal.fail_generation(
            pool,
            lease=lease,
            failure_code=type(error).__name__,
            user_message=(
                error.user_message
                if isinstance(error, ReportGenerationIncompleteError)
                else "本次报告未能完整生成，既有报告和交付物未被覆盖。"
            ),
            action_required=isinstance(
                error,
                (
                    ReportGenerationIncompleteError,
                    ReportGenerationMappingError,
                    generation_dal.ReportGenerationConflictError,
                ),
            ),
        )
    return True


async def _ensure_company_business_summary(
    report: Report,
    state: StoredReportStateV4,
    *,
    model_id: str,
    observation,
) -> StoredCompanyBusinessSummary | None:
    """确保本次生成前公司业务摘要就绪；返回需写回状态的新派生结果，无需重算时返回 None。

    是否需要派生、是否已过期都由 `llm/derive` 单点判定（本函数不复制同名规则）。
    派生值同时写入在途 Report，使各块的 <report_subject> 当轮即可引用。
    """
    profile = company_profile_text(report)
    stored = state.companyBusinessSummary
    if not company_business_summary_is_stale(profile, stored, package=knowledge_package_of(report)):
        if stored is not None and stored.text:
            _apply_company_business_summary(report, stored.text)
        return None
    summary_text = await derive_company_business_summary(
        report, model_id=model_id, observation=observation
    )
    if not summary_text:
        return None
    _apply_company_business_summary(report, summary_text)
    return StoredCompanyBusinessSummary(
        text=summary_text,
        sourceFingerprint=company_profile_fingerprint(profile),
    )


def _apply_company_business_summary(report: Report, summary: str) -> None:
    """把派生摘要写入在途 Report 的派生字段，供本次各块的报告主体引用。"""
    field = report.fields.get(COMPANY_BUSINESS_SUMMARY_KEY)
    if field is not None:
        field.value = summary


async def _run_report_generation(
    pool: asyncpg.Pool,
    *,
    lease: generation_dal.ReportGenerationLease,
    inputs: _GenerationInputs,
    model_id: str,
    storage: MaterialStorageClient | None,
    resolved_artifact_root: Path,
    trace_id: str,
    report_stage: StageHandle,
) -> bool:
    """在已开启的报告级阶段内执行生成、导出闸与交付；失败向上抛给统一终态处理。"""

    execution_scope = inputs.execution_scope
    report_snapshot = inputs.report_snapshot
    material_snapshot = inputs.material_snapshot
    mapping_results = inputs.mapping_results
    report = inputs.report
    mapped = inputs.mapped_evidence
    block_decisions = inputs.block_decisions
    observation = create_observation_run(
        REPORT_GENERATION_STAGE,
        model_id=model_id,
        workload_kind="product_generation",
        report_id=str(lease.report_id),
        block_id="report",
        run_id=str(lease.run_id),
        user_id=str(lease.account_id),
        contract_version=report_snapshot.contract_version,
    )

    async def started(block_id: str) -> None:
        await generation_dal.append_block_event(
            pool,
            lease=lease,
            block_id=block_id,
            completed=False,
            display_label=_block_display_labels(execution_scope.knowledge_package.id).get(block_id),
        )

    async def completed(block_id: str, result: dict) -> None:
        await generation_dal.append_block_event(
            pool,
            lease=lease,
            block_id=block_id,
            completed=True,
            result=result,
            display_label=_block_display_labels(execution_scope.knowledge_package.id).get(block_id),
        )

    # 上下文工程步骤0：公司业务摘要供每个块的 <report_subject> 统一引用，须先于块生成算出。
    # 仅在简介长于目标长度且来源已变（或从未派生）时调用模型；结果与来源指纹同体写回状态。
    with open_stage(
        COMPANY_SUMMARY_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=report_stage,
    ) as summary_stage:
        company_summary = await _ensure_company_business_summary(
            report,
            report_snapshot.state,
            model_id=model_id,
            observation=observation,
        )
        # 该步骤是条件触发：未过期时直接复用已存摘要，不调用模型。
        # 记录本次是否真的派生，使「跳过」与「执行」在轨迹中可区分。
        summary_stage.set_attribute(
            "sustainability_desk.summary_derived", company_summary is not None
        )
    # 素材图片集只读一次，供生成后按承载位放置。
    layout_records = await layout_asset_dal.current_layout_asset_records(
        pool,
        lease.report_id,
    )
    with open_stage(
        GENERATION_BLOCKS_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=report_stage,
    ):
        with observe_generation(observation):
            results = await generate_all(
                report,
                block_ids=frozenset(lease.expected_block_ids),
                n=1,
                model_id=model_id,
                observation=observation,
                empty_table_policy="omit",
                on_block_started=started,
                on_block_completed=completed,
                mapped_evidence_by_block=mapped,
            )
    failed_results = unsuccessful_generation_results(
        results,
        allow_contract_omissions=True,
        package=execution_scope.knowledge_package,
    )
    if failed_results:
        # 在原子投影前给出用户可行动的失败说明；apply 内部的同判定保持最后防线。
        raise ReportGenerationIncompleteError(
            user_message=_incomplete_generation_user_message(report, failed_results),
            failed_block_ids=tuple(
                str(item.get("blockId") or "") for item in failed_results
            ),
        )
    patched = apply_generation_results(
        report_snapshot.state.model_dump(mode="json", by_alias=True),
        lease.expected_block_ids,
        results,
        package=execution_scope.knowledge_package,
        allow_contract_omissions=True,
    )
    if company_summary is not None:
        patched["companyBusinessSummary"] = company_summary.model_dump(
            mode="json", by_alias=True
        )
    _apply_certificate_table(
        patched,
        records=layout_records,
        valid_block_ids=_report_block_ids(report),
    )
    _apply_layout_asset_placements(
        patched,
        records=layout_records,
        block_by_scope=layout_asset_block_by_scope(
            load_compiled_report_definition(execution_scope.knowledge_package)
        ),
        valid_block_ids=_report_block_ids(report),
    )
    next_state = StoredReportStateV4.model_validate(patched)
    # 权威修订报告在本函数内只允许构建两次:一次供导出就绪补齐判定,
    # 一次在状态收敛后供导出闸与交付渲染共用(build_report_revision 全量
    # 装配约 150ms,重复重建是纯浪费)。
    revision = build_report_revision(next_state, package=execution_scope.knowledge_package)
    state_amended = False
    if execution_scope.includes_stakeholder_engagement:
        # 利益相关方沟通档案在产品流中由工作台首访落库;headless 首次生成
        # (从未打开工作台)时用同一生产函数落默认档案,否则导出闸的
        # "议题未分配沟通对象"必然阻断,整轮生成额度被白白烧掉。
        if next_state.stakeholderEngagement is None:
            with open_stage(
                STAKEHOLDER_RECONCILE_STAGE,
                trace_id=trace_id,
                report_id=str(lease.report_id),
                scope=execution_scope.kind,
                parent=report_stage,
            ):
                patched["stakeholderEngagement"] = (
                    reconcile_stakeholder_engagement_profile(revision).model_dump(
                        mode="json", by_alias=True
                    )
                )
            state_amended = True
    # 模块标题指纹依赖本次刚生成的 H4 配对标题;若仍要求用户回工作台手动
    # 刷新,批量生成会被自己的产出恒久阻断导出。批量运行在导出闸前用同一
    # 生产函数补齐过期模块标题(仅过期时一次报告级调用),手动入口不变。
    # 与利益相关方档案无隶属关系,独立成块;H4 新鲜度按本次生成范围裁定。
    module_sections = {
        section.reportModuleId: section
        for section in revision.sections
        if section.reportModuleId is not None
    }
    if any(
        display_title_is_stale(section, revision)
        for section in module_sections.values()
    ):
        with open_stage(
            MODULE_TITLES_STAGE,
            trace_id=trace_id,
            report_id=str(lease.report_id),
            scope=execution_scope.kind,
            parent=report_stage,
        ):
            generated_titles = await generate_report_module_titles(
                revision,
                model_id=model_id,
                observation=observation,
                generation_scope_section_ids=(
                    execution_scope.allowed_report_section_ids
                ),
            )
        section_titles = dict(patched.get("sectionTitles") or {})
        for item in generated_titles.modules:
            module_section = module_sections[item.reportModuleId]
            section_titles[module_section.key] = {
                "text": item.displayTitle,
                "origin": "generated",
                "inputFingerprint": module_fingerprint(module_section, revision),
            }
        patched["sectionTitles"] = section_titles
        state_amended = True
    if state_amended:
        next_state = StoredReportStateV4.model_validate(patched)
        revision = build_report_revision(next_state, package=execution_scope.knowledge_package)
    content_fingerprint = _fingerprint(next_state)
    planned_revision = await generation_dal.plan_next_revision(
        pool,
        lease=lease,
    )
    completion_scope = await _current_generation_scope(
        pool,
        account_id=lease.account_id,
        report_id=lease.report_id,
    )
    if completion_scope.kind != execution_scope.kind:
        raise generation_dal.ReportGenerationConflictError(
            "报告权益范围已变化，本次生成不会提交"
        )
    # 交付物与工作台导出共用同一道导出闸：生成后的报告存在阻断级问题时，
    # 正文照常保存（可在工作台修复），但不产出任何客户可见 Word 交付物。
    # 门禁按当前执行范围声明语义：试用不要求重要性评分、定量目录收敛到
    # 试用白名单、模块 H1 不进入独立气候章交付物故豁免其标题新鲜度。
    projected_revision = completion_scope.project_report(revision)
    with open_stage(
        EXPORT_GATE_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=completion_scope.kind,
        parent=report_stage,
    ) as gate_stage:
        export_diag = diagnose_in_scope(
            projected_revision,
            scope=completion_scope,
            stored_state=next_state,
            structured_input_context=StructuredInputContext(
                reportId=lease.report_id,
                contractVersion=report_snapshot.contract_version,
                compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
            ),
        )
        export_blocking_messages = tuple(
            issue.message for issue in export_diag.issues if issue.level == "block"
        )
        # 阻断原因只记 issue code，不记 message：message 含报告正文片段，
        # 按 spec §5.3 内容边界不得进入 span。
        gate_stage.set_attribute(
            "sustainability_desk.export_blocked", bool(export_blocking_messages)
        )
        gate_stage.set_attribute(
            "sustainability_desk.export_issue_codes",
            sorted(
                {issue.code for issue in export_diag.issues if issue.level == "block"}
            ),
        )
        # 准则披露覆盖判定在轻量版不阻断，但必须留痕：
        # trace 要能直答「这次交付为何带 N 条留意项」。
        if export_diag.coverage is not None:
            gate_stage.set_attribute(
                "sustainability_desk.coverage_finding_codes",
                list(export_diag.coverage.finding_codes()),
            )
            gate_stage.set_attribute(
                "sustainability_desk.coverage_findings_total",
                len(export_diag.coverage.attention_findings)
                + len(export_diag.coverage.attention_obligations),
            )
    if export_blocking_messages:
        artifacts: tuple[generation_dal.ReportArtifactWrite, ...] = ()
    else:
        with open_stage(
            DELIVERY_RENDER_STAGE,
            trace_id=trace_id,
            report_id=str(lease.report_id),
            scope=completion_scope.kind,
            parent=report_stage,
        ) as render_stage:
            if next_state.imageBlocks:
                material_storage = storage or MaterialStorageClient(
                    persistence_settings()
                )
                with open_stage(
                    LAYOUT_IMAGES_STAGE,
                    trace_id=trace_id,
                    report_id=str(lease.report_id),
                    scope=completion_scope.kind,
                    parent=render_stage,
                ):
                    resolved_layout_images = await resolve_layout_images(
                        pool,
                        account_id=lease.account_id,
                        report_id=lease.report_id,
                        state=next_state,
                        records=layout_records,
                        storage=material_storage,
                        package=execution_scope.knowledge_package,
                    )
            else:
                resolved_layout_images = {}
            image_agent_receipts = await pipeline_dal.load_image_agent_receipts(
                pool,
                account_id=lease.account_id,
                report_id=lease.report_id,
            )
            artifacts = await _build_artifacts(
                pool,
                lease=lease,
                planned_revision=planned_revision,
                report_title=report_snapshot.title,
                state=next_state,
                content_fingerprint=content_fingerprint,
                snapshot=material_snapshot.snapshot,
                mapping_results=mapping_results,
                block_decisions=block_decisions,
                generation_observation=observation,
                artifact_root=resolved_artifact_root,
                execution_scope=completion_scope,
                trace_id=trace_id,
                render_stage=render_stage,
                resolved_layout_images=resolved_layout_images,
                image_agent_receipts=image_agent_receipts,
                deliverable_report=completion_scope.prepare_deliverable_report(
                    revision
                ),
                disclosure_coverage=export_diag.coverage,
            )
            render_stage.set_attribute("sustainability_desk.artifact_count", len(artifacts))
    # 收束断言（spec §3.5）：逐块 span 的期望集合从报告契约派生（与 DB
    # _success_check 的 expected_block_ids 同源）。span 事实缺失说明观测链
    # 或生成编排偏航，宁可整轮失败也不产出一份无法归因的报告。
    recorded_block_ids = {
        str(attrs.get("sustainability_desk.block_id", ""))
        for stage_id, attrs in report_stage.executed_stage_facts
        if stage_id == "generation.block"
    }
    missing_block_spans = sorted(set(lease.expected_block_ids) - recorded_block_ids)
    if missing_block_spans:
        raise PipelineStageMissing(
            "以下块在本轮生成中没有留下阶段事实：" + ", ".join(missing_block_spans)
        )
    with open_stage(
        GENERATION_COMMIT_STAGE,
        trace_id=trace_id,
        report_id=str(lease.report_id),
        scope=execution_scope.kind,
        parent=report_stage,
        **{"sustainability_desk.artifact_count": len(artifacts)},
    ):
        await generation_dal.complete_generation(
            pool,
            lease=lease,
            planned_revision=planned_revision,
            state=next_state,
            content_fingerprint=content_fingerprint,
            block_results=tuple(results),
            artifacts=artifacts,
            package=execution_scope.knowledge_package,
            export_blocking_issues=export_blocking_messages,
        )
