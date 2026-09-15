# ABOUTME: 报告级资料工作区的应用服务，拥有共享来源生命周期及按 Adapter 分离的用户可见投影。
# ABOUTME: 轻量版才可原子写入 intakeItems；P3 仅投影来源与提取状态，不读取或写入 StoredReportStateV4。
# ABOUTME(en): Report-scoped material workspace service, owning source lifecycle and per-Adapter projections.
# ABOUTME(en): Only lightweight may atomically write intakeItems; P3 projects state, never touching StoredReportStateV4.
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import os
from typing import TYPE_CHECKING, Iterable, Literal
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from sustainability_desk.persistence.lightweight_report_generations import (
        ReportGenerationRunRecord,
    )

import asyncpg
from fastapi import UploadFile

from sustainability_desk.contract.report_preparation import project_report_preparation
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.report_profiles import require_report_profile
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.material.input_adapter import (
    LightweightReportInputAdapter,
    UnknownMaterialTargetError,
)
from sustainability_desk.material.intake.files import (
    MAX_FILE_BYTES,
    MAX_PDF_PAGES,
    MaterialFileError,
    validate_material_file,
)
from sustainability_desk.material.intake.models import (
    ClarificationRequest,
    InputProposal,
    MaterialFactClaim,
    MaterialIngressDecision,
    MaterialIngressReceipt,
    MaterialProcessingError,
    MaterialSnapshot,
    ProcessingStep,
    MaterialSourceReviewDecision,
    MaterialWorkspace,
    ReportFileIngressPolicy,
    ReportFileTopicTag,
    ReportMaterialBinding,
    UserFileDeclaration,
    UserFileDeclarationRevision,
    ValidatedMaterialFile,
    MaterialSource,
    MaterialSourceDeletionTarget,
    WorkspaceState,
    MAX_MATERIAL_FILENAME_LENGTH,
    REPORT_FILE_ASSET_TITLE_MAX_CHARS,
    REPORT_FILE_DESCRIPTION_MAX_CHARS,
    REPORT_FILE_DESCRIPTION_MIN_CHARS,
)
from sustainability_desk.material.intake.parsers import MaterialParseError
from sustainability_desk.material.intake.routing import route_material_source
from sustainability_desk.material.intake.storage import (
    MaterialStorageClient,
    MaterialStorageError,
)
from sustainability_desk.persistence import material_intake as material_dal
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.persistence.settings import persistence_settings

ScopeKind = Literal["profile", "topics", "uncertain", "report"]

REPORT_FILE_MAX_COUNT = 30
# 资料适用范围全部落在本次报告之外时的用户可见说明；资料处理页与审阅稿同一句。
# File Agent 目录按完整报告给出，这类资料保留真实适用范围、只是不进入本次报告。
OUTSIDE_SCOPE_MATERIAL_NOTICE = "资料与本次报告未纳入的议题相关，本次未采用。"
REPORT_FILE_SEMANTIC_EXTENSION_KINDS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
}
REPORT_FILE_LAYOUT_ASSET_EXTENSION_KINDS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".pdf": "pdf",
}
# 排版素材声明为 PDF 时仅接受单页；多页文档须以语义资料上传。同一扩展名两种 role 由前端声明区分，
# 后端只在用户/前端已声明 role=layout_asset 时对页数收紧校验。
LAYOUT_ASSET_PDF_MAX_PAGES = 1
REPORT_FILE_SEMANTIC_KINDS = frozenset(
    REPORT_FILE_SEMANTIC_EXTENSION_KINDS.values()
)
REPORT_FILE_LAYOUT_ASSET_KINDS = frozenset(
    REPORT_FILE_LAYOUT_ASSET_EXTENSION_KINDS.values()
)
REPORT_FILE_AUXILIARY_TAGS = (
    ("company_and_report_basics", "企业及报告基本信息"),
    ("esg_quantitative_information", "ESG 定量信息"),
    ("comprehensive", "综合"),
    ("uncertain", "暂不确定"),
)
# 前四章报告区域标签：id 必须与 mapping 装配的 report-area:{source_id} 中 source_id 一致
# （material_mapping/scope.py 的 _scope_identity），使用户归属意图能对齐 File Agent 的 scope 目录。
REPORT_FILE_REPORT_AREA_TAGS = (
    ("company_intro", "关于公司"),
    ("governance", "公司治理"),
    ("sustainability_mgmt", "可持续发展治理"),
)


logger = logging.getLogger("sustainability_desk.material_workspace")

# 上传失败原因是用户可见的处理结论（design.md §7.3），与 next_action 同属面向用户的文案。
# 它曾写入 `str(error)`，把存储层与数据库的原始文本经 200 投影的 error_message /
# parse_failure_reason 送到界面：Supabase Storage 的错误体含 `{account_id}/{workspace_id}/
# {source_id}.pdf` 这样的三段内部 UUID 对象路径，asyncpg 的错误则含表名与唯一约束名。
# 故障细节只进日志；用户看到的是按故障类型派生的稳定结论。
_STORAGE_FAILURE_REASON = "文件未能可靠保存"
_UPLOAD_FAILURE_REASON = "文件登记未能完成"


def _log_upload_failure(
    *,
    stage: str,
    workspace_id: UUID,
    source_id: UUID,
    error: BaseException,
) -> None:
    """把上传失败的内部细节留在服务端，供排查；不进任何用户可见投影。"""

    logger.warning(
        "material upload failed stage=%s workspace_id=%s source_id=%s error=%r",
        stage,
        workspace_id,
        source_id,
        error,
    )


def active_binding_fingerprint(
    sources: list[tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]],
) -> str:
    """对当前 active 语义资料集合计算资料集确认指纹；集合为空时是固定值，不是异常。

    确认指纹只描述语义资料集：排版素材按单文件说明即时入队 Image Agent，不参与确认，
    其增删与说明修订不得使已确认的语义资料集失效。
    与 material_agent_pipeline_service._fingerprint 同惯例（canonical JSON + sha256），
    但输入范畴不同：这里只覆盖 bindingId、source sha256、declarationRevisionId 三元组，
    不含单文件 File Agent 的完整 context，供资料工作区与生成入队两处共用同一比对口径。
    """

    members = sorted(
        (
            {
                "bindingId": str(binding.binding_id),
                "sourceSha256": source.sha256,
                "declarationRevisionId": str(declaration.revision_id),
            }
            for source, binding, declaration in sources
            if binding.status == "active" and declaration.role == "semantic_material"
        ),
        key=lambda member: member["bindingId"],
    )
    return sha256(
        json.dumps(
            members,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def pending_file_description_count(
    sources: Iterable[tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]],
) -> int:
    """统计 active 文件中说明仍为空的数量；语义资料与排版素材同级计入，共同守卫生成资格。"""

    return sum(
        1
        for _source, binding, declaration in sources
        if binding.status == "active" and not declaration.description.strip()
    )


def has_active_semantic_material(
    sources: Iterable[tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]],
) -> bool:
    """是否存在需要资料集确认的 active 语义资料；只有排版素材的报告不需要确认。"""

    return any(
        binding.status == "active" and declaration.role == "semantic_material"
        for _source, binding, declaration in sources
    )


def report_update_available_since_last_success(
    *,
    report_state_seq: int,
    latest_success: "ReportGenerationRunRecord | None",
    latest_snapshot_id: UUID | None,
) -> bool:
    """「报告可更新」= 自上次成功生成以来输入发生变化：报告状态推进，或当前资料快照
    与生成时使用的不一致（含从无到有、从有到无）。从未有资料快照且状态未变时不得
    恒真——纯直填账户不应一直显示「更新报告」。"""
    if latest_success is None:
        return False
    if report_state_seq > (latest_success.result_report_state_seq or 0):
        return True
    return latest_success.material_set_snapshot_id != latest_snapshot_id


def material_ingress_max_concurrency() -> int:
    """批内有界并发；上限 10 防止配置错误放大内存占用。"""

    raw = os.getenv("SUSTAINABILITY_DESK_MATERIAL_INGRESS_MAX_CONCURRENCY", "2")
    try:
        return max(1, min(10, int(raw)))
    except ValueError as error:
        raise RuntimeError("资料准入并发配置必须是 1 至 10 的整数") from error


class MaterialRequestError(ValueError):
    """用户输入不满足资料工作区合同。"""


class MaterialConflictError(RuntimeError):
    """工作区、题定义或目标题值已在别处变化。"""


class MaterialNotFoundError(RuntimeError):
    """资料对象不存在或不属于当前报告。"""


class MaterialAccessDeniedError(RuntimeError):
    """当前 Account 不得访问指定范围。"""


class MaterialServiceUnavailableError(RuntimeError):
    """私有对象存储暂时无法完成所请求操作。"""


class MaterialWorkspaceService:
    """一份报告的资料工作区门面；所有公开方法均返回同一 snapshot 投影。"""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        account_id: UUID,
        report_id: UUID,
        report_contract_version: str,
        knowledge_package: KnowledgePackage,
        allowed_report_section_ids: frozenset[str],
        required_quantitative_metric_keys: frozenset[str] | None = None,
        storage: MaterialStorageClient | None = None,
    ) -> None:
        self.pool = pool
        self.account_id = account_id
        self.report_id = report_id
        self.report_contract_version = report_contract_version
        self.knowledge_package = knowledge_package
        self.allowed_report_section_ids = allowed_report_section_ids
        self.required_quantitative_metric_keys = required_quantitative_metric_keys
        self.adapter = LightweightReportInputAdapter(knowledge_package)
        self.workspace_adapter_id = self.adapter.adapter_id
        self._storage = storage

    def _storage_client(self) -> MaterialStorageClient:
        if self._storage is None:
            try:
                self._storage = MaterialStorageClient(persistence_settings())
            except MaterialStorageError as error:
                raise MaterialServiceUnavailableError(str(error)) from error
        return self._storage

    async def _workspace(self):
        try:
            return await material_dal.get_or_create_workspace(
                self.pool,
                account_id=self.account_id,
                report_id=self.report_id,
                adapter_id=self.workspace_adapter_id,
                contract_version=self.report_contract_version,
            )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("报告资料工作区不存在") from error

    async def _enqueue_file_agent(
        self,
        *,
        workspace_id: UUID,
        binding_id: UUID,
    ) -> None:
        """把当前语义 Binding 交给新 File Agent 队列；排版素材会被调度器忽略。"""

        from sustainability_desk.material.agent_pipeline import (
            enqueue_file_agent_for_binding,
        )

        await enqueue_file_agent_for_binding(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
            workspace_id=workspace_id,
            binding_id=binding_id,
        )

    async def _enqueue_image_agent(
        self,
        *,
        workspace_id: UUID,
        binding_id: UUID,
    ) -> None:
        """把当前排版素材 Binding 交给新 Image Agent 队列；语义资料会被调度器忽略。"""

        from sustainability_desk.material.agent_pipeline import (
            enqueue_image_agent_for_binding,
        )

        await enqueue_image_agent_for_binding(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
            workspace_id=workspace_id,
            binding_id=binding_id,
        )

    async def _synchronize_mapping_runs(self) -> None:
        """资料成员变化后冻结新 snapshot 并调度受影响的 Mapping。"""

        from sustainability_desk.material.agent_pipeline import (
            synchronize_mapping_runs,
        )

        await synchronize_mapping_runs(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )

    def _validate_scope(
        self, scope_kind: ScopeKind, report_section_ids: tuple[str, ...]
    ) -> None:
        if len(report_section_ids) != len(set(report_section_ids)):
            raise MaterialRequestError("议题范围不得重复")
        if scope_kind == "topics" and not report_section_ids:
            raise MaterialRequestError("议题资料必须至少选择一个议题")
        if scope_kind != "topics" and report_section_ids:
            raise MaterialRequestError("仅议题资料可以指定报告议题")
        unknown = set(report_section_ids) - self.allowed_report_section_ids
        if unknown:
            raise MaterialAccessDeniedError(f"当前报告不能访问议题：{sorted(unknown)}")

    async def _typed_snapshot(
        self, *, include_source_content: bool = True
    ) -> MaterialSnapshot:
        workspace = await self._workspace()
        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction(
                    isolation="repeatable_read", readonly=True
                ):
                    return await material_dal.get_snapshot(
                        connection,
                        account_id=self.account_id,
                        workspace_id=workspace.id,
                        include_source_content=include_source_content,
                    )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("报告资料工作区不存在") from error

    async def get_snapshot(self) -> dict:
        workspace = await self._workspace()
        async with self.pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                snapshot = await material_dal.get_snapshot(
                    connection,
                    account_id=self.account_id,
                    workspace_id=workspace.id,
                    include_source_content=False,
                )
                report = await reports_dal.get_state(
                    connection, self.account_id, self.report_id
                )
        return self._project_snapshot(
            snapshot,
            report.state,
            report_state_seq=report.state_seq,
        )

    async def get_existing_scope_summaries(self) -> list[dict]:
        """只读投影现有工作区摘要；报告尚未建立工作区时返回空列表。"""
        workspace = await material_dal.get_workspace_by_report(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )
        if workspace is None:
            return []
        async with self.pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                snapshot = await material_dal.get_snapshot(
                    connection,
                    account_id=self.account_id,
                    workspace_id=workspace.id,
                    include_source_content=False,
                )
                report = await reports_dal.get_state(
                    connection, self.account_id, self.report_id
                )
        return self._project_snapshot(
            snapshot,
            report.state,
            report_state_seq=report.state_seq,
        )["scope_summaries"]

    async def get_source_content(self, source_id: UUID) -> dict:
        """按需返回单份清洗内容；高频 workspace snapshot 不携带全文。"""
        workspace = await self._workspace()
        try:
            source = await material_dal.get_source(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                source_id=source_id,
            )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("资料不存在") from error
        if source.status == "deleted":
            raise MaterialNotFoundError("资料不存在")
        projected = self._project_source(source, include_content=True)
        return {
            "source_id": projected["id"],
            "normalized_material": projected["normalized_material"],
        }

    async def upload_sources(
        self,
        files: list[UploadFile],
        *,
        scope_kind: Literal["profile", "topics", "uncertain"],
        report_section_ids: tuple[str, ...],
    ) -> dict:
        self._validate_scope(scope_kind, report_section_ids)
        if not 1 <= len(files) <= 10:
            raise MaterialRequestError("每批必须上传 1 至 10 份资料")
        workspace = await self._workspace()
        batch_id = uuid4()
        queue: asyncio.Queue[UploadFile] = asyncio.Queue()
        for upload in files:
            queue.put_nowait(upload)

        async def consume() -> None:
            while True:
                try:
                    upload = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await self._upload_one(
                        upload,
                        workspace_id=workspace.id,
                        batch_id=batch_id,
                        scope_kind=scope_kind,
                        report_section_ids=report_section_ids,
                    )
                finally:
                    queue.task_done()

        await asyncio.gather(
            *(consume() for _ in range(min(material_ingress_max_concurrency(), len(files))))
        )
        projected = await self.get_snapshot()
        return projected

    @staticmethod
    def report_file_ingress_policy(package: KnowledgePackage) -> ReportFileIngressPolicy:
        """从资料准入常量和议题合同派生唯一的用户可见文件策略。"""

        contract = load_topic_contract(package)
        topic_tags = [
            *[
                ReportFileTopicTag(id=tag_id, label=label, kind="auxiliary")
                for tag_id, label in REPORT_FILE_AUXILIARY_TAGS
            ],
            *[
                ReportFileTopicTag(id=tag_id, label=label, kind="report_area")
                for tag_id, label in REPORT_FILE_REPORT_AREA_TAGS
            ],
            *[
                ReportFileTopicTag(
                    id=section.id,
                    label=section.title,
                    kind="report_section",
                )
                for section in sorted(
                    contract.source.reportSections,
                    key=lambda section: (
                        contract.reportModulesById[section.reportModuleId].order,
                        section.order,
                    ),
                )
            ],
        ]
        return ReportFileIngressPolicy(
            max_files_per_report=REPORT_FILE_MAX_COUNT,
            max_file_bytes=MAX_FILE_BYTES,
            max_pdf_pages=MAX_PDF_PAGES,
            description_min_chars=REPORT_FILE_DESCRIPTION_MIN_CHARS,
            description_max_chars=REPORT_FILE_DESCRIPTION_MAX_CHARS,
            asset_title_max_chars=REPORT_FILE_ASSET_TITLE_MAX_CHARS,
            semantic_material_kinds=sorted(REPORT_FILE_SEMANTIC_KINDS),
            layout_asset_kinds=sorted(REPORT_FILE_LAYOUT_ASSET_KINDS),
            semantic_material_extensions=list(
                REPORT_FILE_SEMANTIC_EXTENSION_KINDS
            ),
            layout_asset_extensions=list(REPORT_FILE_LAYOUT_ASSET_EXTENSION_KINDS),
            topic_tags=topic_tags,
        )

    def _validate_report_file_declaration(
        self,
        declaration: UserFileDeclaration,
        file: ValidatedMaterialFile,
    ) -> None:
        self.validate_report_file_declaration_for_policy(
            declaration,
            file,
            self.report_file_ingress_policy(self.knowledge_package),
        )

    @staticmethod
    def validate_report_file_declaration_for_policy(
        declaration: UserFileDeclaration,
        file: ValidatedMaterialFile,
        policy: ReportFileIngressPolicy,
    ) -> None:
        """按已投影的资料准入策略校验一份文件声明。"""

        available_tags = {tag.id for tag in policy.topic_tags}
        unknown = set(declaration.topic_tags) - available_tags
        if unknown:
            raise MaterialRequestError(f"文件标签不存在：{sorted(unknown)}")
        if "uncertain" in declaration.topic_tags and len(declaration.topic_tags) > 1:
            raise MaterialRequestError("“暂不确定”不能与其他资料标签同时选择")
        allowed_kinds = (
            set(policy.semantic_material_kinds)
            if declaration.role == "semantic_material"
            else set(policy.layout_asset_kinds)
        )
        if file.kind not in allowed_kinds:
            label = "语义资料" if declaration.role == "semantic_material" else "排版素材"
            raise MaterialRequestError(
                f"{label}不支持 {file.kind.upper()} 格式"
            )
        if (
            declaration.role == "layout_asset"
            and file.kind == "pdf"
            and (file.pdf_page_count or 0) > LAYOUT_ASSET_PDF_MAX_PAGES
        ):
            raise MaterialRequestError(
                f"排版素材仅接受单页 PDF（当前 {file.pdf_page_count} 页）；"
                "多页文档请以语义资料上传"
            )

    @staticmethod
    def _active_binding_fingerprint(
        sources: list[tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]],
    ) -> str:
        return active_binding_fingerprint(sources)

    def _material_set_confirmation_projection(
        self,
        *,
        workspace: MaterialWorkspace,
        sources: list[tuple[MaterialSource, ReportMaterialBinding, UserFileDeclarationRevision]],
        pending_description_count: int,
    ) -> dict:
        """派生资料集确认状态；失效不落库，读取时对当前 active 语义资料集重算比对。"""

        # 缺说明先于"是否需要确认"判定：只有排版素材且说明未填的报告同样停在 draft，
        # 不得因为没有语义资料就被判成无需处理。
        if pending_description_count > 0:
            status = "pending_description"
        elif not has_active_semantic_material(sources):
            status = "not_required"
        elif (
            workspace.material_set_confirmed_fingerprint is not None
            and workspace.material_set_confirmed_fingerprint
            == self._active_binding_fingerprint(sources)
        ):
            status = "confirmed"
        else:
            status = "required"
        return {
            "status": status,
            "confirmed_at": (
                workspace.material_set_confirmed_at.isoformat()
                if status == "confirmed" and workspace.material_set_confirmed_at is not None
                else None
            ),
            "pending_description_count": pending_description_count,
        }

    async def get_report_file_intake(self) -> dict:
        """返回准备中心所需的文件准入投影，不泄露旧工作台的用途或范围语义。"""

        workspace = await self._workspace()
        sources = await material_dal.list_report_file_declarations(
            self.pool,
            account_id=self.account_id,
            workspace_id=workspace.id,
        )
        snapshot = await self._typed_snapshot(include_source_content=False)
        sources_by_id = {source.id: source for source in snapshot.sources}
        from sustainability_desk.persistence.material_agent_pipeline import (
            list_current_file_agent_runs,
        )

        current_runs = {
            item.binding_id: item
            for item in await list_current_file_agent_runs(
                self.pool,
                account_id=self.account_id,
                report_id=self.report_id,
            )
        }

        from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
        from sustainability_desk.persistence.material_agent_pipeline import (
            latest_material_set_snapshot,
            list_current_image_agent_runs,
        )

        # 资料是否进入本次报告以冻结 Mapping plan 为准（与审阅稿说明同源），不在投影里
        # 重新装配范围：相关 Dossier 若是快照成员却未路由到任何 scope，即其适用范围
        # 全部在本次报告之外。快照尚未形成（处理中）时不下结论。
        latest_snapshot = await latest_material_set_snapshot(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )
        snapshot_dossier_ids: set[UUID] = set()
        routed_dossier_ids: set[UUID] = set()
        if latest_snapshot is not None:
            snapshot_dossier_ids = {
                member.dossier_id for member in latest_snapshot.snapshot.members
            }
            routed_dossier_ids = {
                dossier_id
                for scope in latest_snapshot.snapshot.mapping_plan.scopes
                for dossier_id in scope.dossier_ids
            }

        def report_scope(dossier) -> str | None:
            if dossier.relevance != "relevant" or dossier.dossier_id not in snapshot_dossier_ids:
                return None
            return "within_report" if dossier.dossier_id in routed_dossier_ids else "outside_report"

        current_image_runs = {
            item.binding_id: item
            for item in await list_current_image_agent_runs(
                self.pool,
                account_id=self.account_id,
                report_id=self.report_id,
            )
        }
        layout_assets_by_source = {
            record.material_source_id: record
            for record in await layout_asset_dal.list_layout_assets_for_report(
                self.pool,
                self.report_id,
            )
        }

        def image_analysis(binding, declaration, source):
            if declaration.role != "layout_asset":
                return None
            run = current_image_runs.get(binding.binding_id)
            if run is None:
                return None
            asset = layout_assets_by_source.get(source.id)
            if run.status != "succeeded" or asset is None:
                return {"status": run.status}
            return {
                "status": run.status,
                "asset_id": str(asset.asset_id),
                "caption": asset.caption,
                "category": asset.category,
                "placement_scope_id": asset.placement_scope_id,
                # 证书事实回给用户核对：识别结论会进报告正文与成果章，用户有权看见并更正。
                "certificate_fact": asset.certificate_fact,
            }

        def parse_conclusion(source, binding, declaration) -> tuple[str | None, str | None]:
            """文件级处理结论（design.md §7.3 两道闸）：(parse_status, parse_failure_reason)。

            failed 只覆盖文件层机械事实（加密、损坏、无法解析、超页数——准入/解析失败），
            用户解法只有重新上传或移出，存在即阻断生成（闸一）；ok_with_attention 是内容层
            软待确认（闸二），不阻断；Agent 终态失败保持既有「资料暂不可用」语义（§3.5，
            不阻断），由 file_analysis/image_analysis.status 表达，本结论返回 None。
            """

            if source.status == "failed":
                reason = source.error.reason if source.error else "文件无法解析，请重新上传可读的版本。"
                return "failed", reason
            file_run = current_runs.get(binding.binding_id) if declaration.role == "semantic_material" else None
            image_run = (
                current_image_runs.get(binding.binding_id)
                if declaration.role == "layout_asset"
                else None
            )
            run_status = file_run.status if file_run else (image_run.status if image_run else None)
            if run_status == "needs_attention":
                return "ok_with_attention", None
            if run_status == "succeeded":
                if file_run and file_run.dossier and file_run.dossier.attention_items:
                    return "ok_with_attention", None
                return "ok", None
            return None, None

        def file_analysis(binding, declaration):
            if declaration.role != "semantic_material":
                return None
            run = current_runs.get(binding.binding_id)
            if run is None:
                return None
            dossier = run.dossier
            scope_conclusion = report_scope(dossier) if dossier is not None else None
            return {
                "status": run.status,
                "dossier": (
                    {
                        "relevance": dossier.relevance,
                        "relevance_reason": dossier.relevance_reason,
                        "applicable_scope_count": len(
                            {
                                scope_id
                                for material in dossier.materials
                                for scope_id in material.applicable_scope_ids
                            }
                        ),
                        "attention_items": [
                            {
                                "message": item.message,
                                "next_action": item.next_action,
                            }
                            for item in dossier.attention_items
                        ],
                        "report_scope": scope_conclusion,
                        "report_scope_notice": (
                            OUTSIDE_SCOPE_MATERIAL_NOTICE
                            if scope_conclusion == "outside_report"
                            else None
                        ),
                    }
                    if dossier is not None
                    else None
                ),
            }

        # 投影序号取本投影全部数据行的最大落库时间(微秒纪元):文件改名、说明修订、
        # 移出/恢复、资料集确认、File/Image Agent 状态推进都会推进它;
        # 前端据此丢弃乱序到达的旧响应,不作并发写校验。
        row_timestamps = [
            timestamp
            for source, binding, declaration in sources
            for timestamp in (
                source.created_at,
                source.updated_at,
                binding.updated_at,
                declaration.declared_at,
            )
            if timestamp is not None
        ]
        if workspace.material_set_confirmed_at is not None:
            row_timestamps.append(workspace.material_set_confirmed_at)
        row_timestamps.extend(run.updated_at for run in current_runs.values())
        row_timestamps.extend(run.updated_at for run in current_image_runs.values())
        row_timestamps.extend(
            record.updated_at for record in layout_assets_by_source.values()
        )
        latest_row_at = max(row_timestamps, default=None)
        projection_seq = (
            max(1, int(latest_row_at.timestamp() * 1_000_000))
            if latest_row_at is not None
            else 1
        )

        file_intake = {
            "report_id": str(self.report_id),
            "projection_seq": projection_seq,
            "policy": self.report_file_ingress_policy(self.knowledge_package).model_dump(mode="json"),
            "active_file_count": sum(
                binding.status == "active"
                and source.status not in {"failed", "deleted"}
                for source, binding, _declaration in sources
            ),
            "sources": [
                {
                    "binding_id": str(binding.binding_id),
                    "source_id": str(source.id),
                    "binding_status": binding.status,
                    "filename": source.filename,
                    "source_label": source.source_label,
                    "content_type": source.media_type,
                    "size_bytes": source.size_bytes,
                    "sha256": source.sha256,
                    "declaration": declaration.model_dump(mode="json"),
                    "admission_status": "failed" if source.status == "failed" else "admitted",
                    "error_message": source.error.reason if source.error else None,
                    "file_analysis": file_analysis(binding, declaration),
                    "image_analysis": image_analysis(binding, declaration, source),
                    "parse_status": (conclusion := parse_conclusion(source, binding, declaration))[0],
                    "parse_failure_reason": conclusion[1],
                    "created_at": source.created_at.isoformat(),
                    "updated_at": source.updated_at.isoformat(),
                }
                for source, binding, declaration in sources
            ],
            "ingress_receipts": [
                self._project_ingress_receipt(decision, sources_by_id)
                for decision in snapshot.ingress_decisions
            ],
        }
        pending_description_count = pending_file_description_count(sources)
        file_intake["material_set_confirmation"] = self._material_set_confirmation_projection(
            workspace=workspace,
            sources=sources,
            pending_description_count=pending_description_count,
        )
        # 批次级阶段（design.md §7.3）：读派生，不落库。未确认为 draft；已确认或无需确认
        # （没有语义资料）时按当前 Agent 运行判定 processing/reviewed——排版素材不经确认
        # 即入队，只有素材的报告也会有进行中的 Image Agent 运行。
        active_bindings = {
            binding.binding_id
            for _source, binding, _declaration in sources
            if binding.status == "active"
        }
        runs_in_flight = any(
            run.status in {"queued", "running"}
            for run in (*current_runs.values(), *current_image_runs.values())
            if run.binding_id in active_bindings
        )
        confirmation_status = file_intake["material_set_confirmation"]["status"]
        if confirmation_status in {"confirmed", "not_required"}:
            file_intake["phase"] = "processing" if runs_in_flight else "reviewed"
        else:
            file_intake["phase"] = "draft"
        return file_intake

    async def get_report_preparation(self) -> dict:
        """返回轻量版四类并行输入与最低生成资格的唯一公共投影。"""

        report = await reports_dal.get_lightweight_v4_snapshot(
            self.pool,
            self.account_id,
            self.report_id,
        )
        await self._workspace()
        file_intake = await self.get_report_file_intake()
        from sustainability_desk.persistence.material_agent_pipeline import (
            latest_material_set_snapshot,
            material_pipeline_status,
        )
        from sustainability_desk.persistence.lightweight_report_generations import (
            latest_successful_generation,
        )

        pipeline_status = await material_pipeline_status(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )
        latest_snapshot = await latest_material_set_snapshot(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )
        latest_success = await latest_successful_generation(
            self.pool,
            account_id=self.account_id,
            report_id=self.report_id,
        )
        report_update_available = report_update_available_since_last_success(
            report_state_seq=report.state_seq,
            latest_success=latest_success,
            latest_snapshot_id=(
                latest_snapshot.snapshot.snapshot_id if latest_snapshot else None
            ),
        )
        primary_input_mode = (
            report.state.meta.primaryInputMode if report.state.meta else None
        )
        # 问答路径的排版素材在议题信息页上传，缺说明的入口随之不同：只有当缺说明的
        # 全是素材时才指向该页；混有语义资料时资料页是唯一能补齐全部说明的入口。
        pending_description_roles = {
            entry["declaration"]["role"]
            for entry in file_intake["sources"]
            if entry["binding_status"] == "active"
            and not (entry["declaration"].get("description") or "").strip()
        }
        pending_description_href = (
            "/intake/questions"
            if primary_input_mode == "questions"
            and pending_description_roles == {"layout_asset"}
            else "/materials"
        )
        projection = project_report_preparation(
            report_id=self.report_id,
            report_state_seq=report.state_seq,
            state=report.state,
            profile=require_report_profile(report.report_profile_id),
            active_file_count=int(file_intake["active_file_count"]),
            processing_file_count=(
                pipeline_status.file_queued_or_running
                + pipeline_status.image_queued_or_running
            ),
            processing_mapping_scope_count=(
                pipeline_status.mapping_queued_or_running
            ),
            attention_item_count=(
                pipeline_status.needs_attention + pipeline_status.failed
            ),
            report_update_available=report_update_available,
            required_quantitative_metric_keys=self.required_quantitative_metric_keys,
            pending_file_description_count=int(
                file_intake["material_set_confirmation"]["pending_description_count"]
            ),
            material_set_requires_confirmation=(
                file_intake["material_set_confirmation"]["status"] == "required"
            ),
            unresolved_failed_file_count=sum(
                1
                for entry in file_intake["sources"]
                if entry["binding_status"] == "active"
                and entry["parse_status"] == "failed"
            ),
            primary_input_mode=primary_input_mode,
            pending_description_href=pending_description_href,
        )
        return projection.model_dump(mode="json")

    async def upload_report_files(
        self,
        files: list[UploadFile],
        *,
        declarations: tuple[UserFileDeclaration, ...],
    ) -> dict:
        """接纳准备中心文件；只保存原件和用户声明，绝不启动旧预处理或视觉路由。"""

        if not files:
            raise MaterialRequestError("至少选择一份文件")
        if len(files) != len(declarations):
            raise MaterialRequestError("每份文件必须对应一条用户说明")
        workspace = await self._workspace()
        batch_id = uuid4()
        receipts: list[MaterialIngressDecision] = []
        queue: asyncio.Queue[tuple[UploadFile, UserFileDeclaration]] = asyncio.Queue()
        for item in zip(files, declarations, strict=True):
            queue.put_nowait(item)

        async def consume() -> None:
            while True:
                try:
                    upload, declaration = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    receipt = await self._upload_report_file(
                        upload,
                        declaration=declaration,
                        workspace_id=workspace.id,
                        batch_id=batch_id,
                    )
                    receipts.append(receipt)
                finally:
                    queue.task_done()

        await asyncio.gather(
            *(consume() for _ in range(min(material_ingress_max_concurrency(), len(files))))
        )
        await material_dal.record_ingress_decisions(
            self.pool,
            account_id=self.account_id,
            workspace_id=workspace.id,
            decisions=tuple(receipts),
        )
        return await self.get_report_file_intake()

    async def _upload_report_file(
        self,
        upload: UploadFile,
        *,
        declaration: UserFileDeclaration,
        workspace_id: UUID,
        batch_id: UUID,
    ) -> MaterialIngressDecision:
        filename = upload.filename or "未命名文件"
        try:
            data = await upload.read(MAX_FILE_BYTES + 1)
            validated = await asyncio.to_thread(
                validate_material_file,
                filename=filename,
                content_type=upload.content_type or "application/octet-stream",
                data=data,
            )
            self._validate_report_file_declaration(declaration, validated)
        except (MaterialFileError, MaterialParseError, MaterialRequestError):
            return self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="file_rejected",
            )
        object_path = self._storage_client().object_path(
            self.account_id, workspace_id, uuid4(), validated.kind
        )
        try:
            source, binding, reused = await material_dal.reserve_report_file_upload(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                source_label=validated.filename,
                object_path=object_path,
                file=validated,
                declaration=declaration,
                max_files_per_report=REPORT_FILE_MAX_COUNT,
            )
        except (
            material_dal.ReportFileCapacityError,
            material_dal.ReportFileSourceConflictError,
        ):
            return self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="file_rejected",
            )
        except material_dal.ReportFileDeclarationConflictError:
            return self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="duplicate_declaration_conflict",
            )
        except material_dal.ReportMaterialBindingStateError:
            return self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="binding_removed",
            )
        if reused:
            return self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="reused",
                reason_code="duplicate_reused",
                source_id=source.id,
                sha256=source.sha256,
            )
        try:
            await self._storage_client().upload(object_path, data, validated.media_type)
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="accepted",
                reason_code="admitted",
                source_id=source.id,
                sha256=source.sha256,
            )
            await material_dal.finalize_source_upload(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                source_id=source.id,
                ingress_decision=decision,
            )
            return decision
        except MaterialStorageError as error:
            _log_upload_failure(
                stage="storage",
                workspace_id=workspace_id,
                source_id=source.id,
                error=error,
            )
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="storage_failed",
                source_id=source.id,
                sha256=source.sha256,
            )
            await self._mark_upload_failed(
                workspace_id,
                source.id,
                stage="storage",
                reason=_STORAGE_FAILURE_REASON,
                retryable=False,
                ingress_decision=decision,
            )
            return decision

    async def update_report_file_declaration(
        self,
        binding_id: UUID,
        *,
        declaration: UserFileDeclaration,
        expected_revision: int,
    ) -> dict:
        """更新用户声明后返回同一报告文件投影。"""

        workspace = await self._workspace()
        try:
            records = await material_dal.list_report_file_declarations(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
            )
            record = next(
                (
                    item
                    for item in records
                    if item[1].binding_id == binding_id
                ),
                None,
            )
            if record is None:
                raise material_dal.MaterialOwnershipError(str(binding_id))
            source, binding, _current_declaration = record
            if binding.status != "active":
                raise material_dal.ReportMaterialBindingStateError(
                    "只有 active Binding 可以编辑声明"
                )
            self._validate_report_file_declaration(
                declaration,
                ValidatedMaterialFile(
                    filename=source.filename,
                    kind=source.kind,
                    media_type=source.media_type,
                    size_bytes=source.size_bytes,
                    sha256=source.sha256,
                ),
            )
            await material_dal.update_report_file_declaration(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
                declaration=declaration,
                expected_revision=expected_revision,
            )
        except (
            material_dal.MaterialStateConflictError,
            material_dal.ReportMaterialBindingStateError,
        ) as error:
            raise MaterialConflictError(str(error)) from error
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("文件不存在") from error
        if declaration.role == "layout_asset" and declaration.description.strip():
            await self._enqueue_image_agent_after_description(
                workspace_id=workspace.id,
                binding_id=binding_id,
            )
        return await self._autostart_material_processing()

    async def _enqueue_image_agent_after_description(
        self,
        *,
        workspace_id: UUID,
        binding_id: UUID,
    ) -> None:
        """排版素材说明保存成功即入队图片识别，与语义资料集确认解耦。

        素材说明是 Image Agent 的输入，不是确认指纹的成员：问答路径没有「资料集确认」
        步骤，若仍经 confirm_material_set 入队，素材会因语义说明未齐或根本没有确认动作
        而永远不被识别。入队幂等；入队失败只记日志，不得让用户已保存的说明连带失败——
        确认流程与生成前自愈会再次尝试。
        """

        try:
            await self._enqueue_image_agent(
                workspace_id=workspace_id,
                binding_id=binding_id,
            )
        except Exception:
            logger.exception(
                "排版素材说明保存后入队 Image Agent 失败 report_id=%s binding_id=%s",
                self.report_id,
                binding_id,
            )

    async def _autostart_material_processing(self) -> dict:
        """说明补齐即自动入队解析，用户无需再点一次「开始处理」。

        解析输入含文件说明（进 input_fingerprint），因此触发点必须是**说明补齐后**而非上传时：
        上传即入队会先用空说明跑一遍，用户随后填写说明必然改变指纹并令整批重跑，白烧一次模型调用。

        复用 ``confirm_material_set`` 而非另开一条入队路径：它已承载"说明未补齐则拒绝、入队成功后
        才落指纹"的完整语义，且幂等——未变化的文件命中既有 run，不产生新的模型调用。
        自动入队失败不得吃掉用户已保存的说明：吞掉异常返回投影，用户仍可经「下一步：资料处理」重试。
        """

        try:
            return await self.confirm_material_set()
        except (MaterialConflictError, MaterialRequestError):
            # 说明尚未补齐（或并发改动使指纹失效）是正常分支，不是故障：保持 draft 形态等用户填完。
            return await self.get_report_file_intake()

    async def update_report_file_source_label(
        self,
        binding_id: UUID,
        *,
        source_label: str,
    ) -> dict:
        """更新文件展示名;不产生声明 Revision,不影响确认指纹与分析结果。"""

        normalized = source_label.strip()
        if not normalized or len(normalized) > 140:
            raise MaterialRequestError("文件名须为 1-140 字")
        workspace = await self._workspace()
        try:
            await material_dal.update_report_file_source_label(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
                source_label=normalized,
            )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("文件不存在") from error
        return await self.get_report_file_intake()

    async def _owned_layout_asset(self, asset_id: UUID):
        from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal

        record = next(
            (
                item
                for item in await layout_asset_dal.list_layout_assets_for_report(
                    self.pool,
                    self.report_id,
                )
                if item.asset_id == asset_id
            ),
            None,
        )
        if record is None:
            raise MaterialNotFoundError("素材图片不存在")
        return record

    async def get_layout_asset_image(self, asset_id: UUID) -> tuple[bytes, str]:
        """返回归一化原图字节,与 Word 导出同一图源。"""

        from sustainability_desk.material.intake.image_agent_ai import prepare_model_image

        record = await self._owned_layout_asset(asset_id)
        source = await material_dal.get_source(
            self.pool,
            account_id=self.account_id,
            workspace_id=(await self._workspace()).id,
            source_id=record.material_source_id,
        )
        raw = await self._storage_client().download(
            source.object_path,
            max_bytes=source.size_bytes + 1,
        )
        normalized = prepare_model_image(raw, media_type=source.media_type)
        return normalized.data, normalized.media_type

    async def update_layout_asset_caption(
        self,
        asset_id: UUID,
        *,
        caption: str,
    ) -> dict:
        """用户改写题注;归属转为用户,后续识别重跑不再覆盖。"""

        from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal

        normalized = caption.strip()
        if not normalized or len(normalized) > 50:
            raise MaterialRequestError("题注须为 1-50 字")
        await self._owned_layout_asset(asset_id)
        await layout_asset_dal.update_layout_asset_caption(
            self.pool,
            report_id=self.report_id,
            asset_id=asset_id,
            caption=normalized,
        )
        return await self.get_report_file_intake()

    async def update_layout_asset_certificate_fact(
        self,
        asset_id: UUID,
        *,
        certificate_fact: dict,
    ) -> dict:
        """用户更正证书事实；归属转为用户，后续识别重跑不再覆盖。

        名称是唯一必填——它是集中承载表的行标识，空名称无法成行。其余字段允许留空，
        用户可能就是不想披露发证机构或范围。
        """

        from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal

        name = str(certificate_fact.get("certificate_name") or "").strip()
        if not name:
            raise MaterialRequestError("证书名称不能为空")
        await self._owned_layout_asset(asset_id)
        await layout_asset_dal.update_layout_asset_certificate_fact(
            self.pool,
            report_id=self.report_id,
            asset_id=asset_id,
            certificate_fact=certificate_fact,
        )
        return await self.get_report_file_intake()

    async def remove_report_file(self, binding_id: UUID) -> dict:
        """把文件移出当前报告，保留物理对象、声明历史与审计事件。"""

        workspace = await self._workspace()
        try:
            await material_dal.remove_report_material_binding(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
            )
        except material_dal.ReportMaterialBindingStateError as error:
            raise MaterialConflictError(str(error)) from error
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("文件 Binding 不存在") from error
        return await self.get_report_file_intake()

    async def restore_report_file(self, binding_id: UUID) -> dict:
        """恢复被移出的文件；服务端重新执行容量裁决。"""

        workspace = await self._workspace()
        try:
            await material_dal.restore_report_material_binding(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                binding_id=binding_id,
                max_files_per_report=REPORT_FILE_MAX_COUNT,
            )
        except (
            material_dal.ReportMaterialBindingStateError,
            material_dal.ReportFileCapacityError,
        ) as error:
            raise MaterialConflictError(str(error)) from error
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("文件 Binding 不存在") from error
        return await self.get_report_file_intake()

    async def confirm_material_set(self) -> dict:
        """用户显式确认资料集齐备；全部 active 资料入队成功后才落确认指纹。

        幂等键天然带来增量语义：未变化的文件命中既有 succeeded run，不会产生新的模型调用；
        末尾统一调用 synchronize_mapping_runs 覆盖"全部已 succeeded 但缺 Mapping"的场景。

        **确认指纹必须后写**：它是"入队确实完成"的证据，不是承诺。先落指纹再入队会在
        入队中途失败时留下不可自愈的脏状态——指纹已存在使前端不再要求确认，而文件从未
        入队，生成闸永远判定"资料分析尚未完成"。入队幂等，
        失败后用户重试安全；指纹缺失只是要求再确认一次，不丢数据。
        """

        workspace = await self._workspace()
        sources = await material_dal.list_report_file_declarations(
            self.pool,
            account_id=self.account_id,
            workspace_id=workspace.id,
        )
        pending_description_count = pending_file_description_count(sources)
        if pending_description_count > 0:
            raise MaterialConflictError(
                f"还有 {pending_description_count} 份文件待补充说明，无法确认资料集"
            )
        fingerprint = self._active_binding_fingerprint(sources)
        for source, binding, declaration in sources:
            if binding.status != "active":
                continue
            if declaration.role == "semantic_material":
                await self._enqueue_file_agent(
                    workspace_id=workspace.id,
                    binding_id=binding.binding_id,
                )
            elif declaration.role == "layout_asset":
                await self._enqueue_image_agent(
                    workspace_id=workspace.id,
                    binding_id=binding.binding_id,
                )
        await material_dal.record_material_set_confirmation(
            self.pool,
            account_id=self.account_id,
            workspace_id=workspace.id,
            fingerprint=fingerprint,
            confirmed_at=datetime.now(timezone.utc),
        )
        await self._synchronize_mapping_runs()
        return await self.get_report_file_intake()

    async def _upload_one(
        self,
        upload: UploadFile,
        *,
        workspace_id: UUID,
        batch_id: UUID,
        scope_kind: Literal["profile", "topics", "uncertain"],
        report_section_ids: tuple[str, ...],
    ) -> None:
        """处理一个文件；调用方固定并发数，因此每个 worker 最多持有一份文件字节。"""

        filename = upload.filename or "未命名文件"
        try:
            data = await upload.read(MAX_FILE_BYTES + 1)
            validated, route_step = await asyncio.to_thread(
                self._validate_and_route_upload,
                filename,
                upload.content_type or "application/octet-stream",
                data,
            )
        except (MaterialFileError, MaterialParseError):
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="file_rejected",
            )
            await material_dal.record_ingress_decisions(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                decisions=(decision,),
            )
            return

        object_path = self._storage_client().object_path(
            self.account_id, workspace_id, uuid4(), validated.kind
        )
        try:
            source = await material_dal.reserve_source_upload(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                source_label=validated.filename,
                object_path=object_path,
                file=validated,
                scope_kind=scope_kind,
                report_section_ids=report_section_ids,
                route_step=route_step,
            )
        except material_dal.MaterialDuplicateSourceError:
            existing = await material_dal.get_active_source_by_sha256(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                sha256=validated.sha256,
            )
            if existing is None:
                raise MaterialConflictError("重复资料的现有 Source 无法读取")
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="reused",
                reason_code="duplicate_reused",
                source_id=existing.id,
                sha256=existing.sha256,
            )
            await material_dal.reuse_source_and_record_ingress(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                sha256=existing.sha256,
                decision=decision,
            )
            return

        try:
            await self._storage_client().upload(
                object_path, data, validated.media_type
            )
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="accepted",
                reason_code="admitted",
                source_id=source.id,
                sha256=source.sha256,
            )
            await material_dal.finalize_source_upload(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                source_id=source.id,
                ingress_decision=decision,
            )
        except MaterialStorageError as error:
            _log_upload_failure(
                stage="storage",
                workspace_id=workspace_id,
                source_id=source.id,
                error=error,
            )
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="storage_failed",
                source_id=source.id,
                sha256=source.sha256,
            )
            await self._mark_upload_failed(
                workspace_id,
                source.id,
                stage="storage",
                reason=_STORAGE_FAILURE_REASON,
                retryable=False,
                ingress_decision=decision,
            )
        except Exception as error:
            # 兜底分支覆盖数据库写入等非存储故障；asyncpg 的错误文本含表名与约束名，
            # 只进日志。
            _log_upload_failure(
                stage="upload",
                workspace_id=workspace_id,
                source_id=source.id,
                error=error,
            )
            decision = self._ingress_decision(
                batch_id=batch_id,
                filename=filename,
                status="rejected",
                reason_code="upload_failed",
                source_id=source.id,
                sha256=source.sha256,
            )
            await self._mark_upload_failed(
                workspace_id,
                source.id,
                stage="upload",
                reason=_UPLOAD_FAILURE_REASON,
                retryable=True,
                ingress_decision=decision,
            )

    def _validate_and_route_upload(
        self,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> tuple[ValidatedMaterialFile, ProcessingStep]:
        validated = validate_material_file(
            filename=filename,
            content_type=content_type,
            data=data,
        )
        route_step = self._route_source(
            validated.kind,
            validated.sha256,
            data,
            pdf_page_count=validated.pdf_page_count,
        )
        return validated, route_step

    async def _mark_upload_failed(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        stage: Literal["storage", "upload"],
        reason: str,
        retryable: bool,
        ingress_decision: MaterialIngressDecision | None = None,
    ) -> None:
        failure_stage = "storage" if stage == "storage" else "upload"
        try:
            await material_dal.fail_source_upload(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                source_id=source_id,
                error=MaterialProcessingError(
                    code="source_upload_failed",
                    failure_stage=failure_stage,
                    reason=reason,
                    next_action=(
                        "对象未可靠写入，请删除该失败记录后重新上传"
                        if not retryable
                        else "请重试该资料；若持续失败，请删除后重新上传"
                    ),
                    retryable=retryable,
                ),
                ingress_decision=ingress_decision,
            )
        except material_dal.MaterialOwnershipError:
            return

    @staticmethod
    def _route_source(
        kind: str,
        sha256: str,
        data: bytes,
        *,
        pdf_page_count: int | None = None,
    ) -> ProcessingStep:
        now = datetime.now(timezone.utc)
        decision = route_material_source(
            kind=kind,
            data=data,
            pdf_page_count=pdf_page_count,
        )
        return ProcessingStep(
            step="routed",
            processor="deterministic",
            status="succeeded",
            parser=decision.parser,
            route=decision.route,
            input_fingerprint=sha256,
            output_fingerprint=sha256,
            started_at=now,
            completed_at=now,
            message=decision.message,
        )

    @staticmethod
    def _ingress_decision(
        *,
        batch_id: UUID,
        filename: str,
        status: Literal["accepted", "reused", "rejected"],
        reason_code: Literal[
            "admitted",
            "duplicate_reused",
            "duplicate_declaration_conflict",
            "binding_removed",
            "file_rejected",
            "storage_failed",
            "upload_failed",
        ],
        source_id: UUID | None = None,
        sha256: str | None = None,
    ) -> MaterialIngressDecision:
        return MaterialIngressDecision(
            batch_id=batch_id,
            filename=filename[:MAX_MATERIAL_FILENAME_LENGTH],
            status=status,
            reason_code=reason_code,
            source_id=source_id,
            sha256=sha256,
        )

    async def update_source_metadata(
        self,
        source_id: UUID,
        *,
        scope_kind: ScopeKind,
        report_section_ids: tuple[str, ...],
    ) -> dict:
        if scope_kind == "report":
            raise MaterialRequestError("文件分类不支持全报告范围")
        self._validate_scope(scope_kind, report_section_ids)
        workspace = await self._workspace()
        try:
            await material_dal.update_source_metadata(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                source_id=source_id,
                scope_kind=scope_kind,
                report_section_ids=report_section_ids,
            )
        except material_dal.MaterialStateConflictError as error:
            raise MaterialConflictError(str(error)) from error
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("资料不存在") from error

    async def record_source_review_decision(
        self,
        source_id: UUID,
        *,
        decision: Literal["reviewed_accepted", "excluded_by_user"],
        actor: Literal["user", "operator"],
        reason: str,
        expected_normalized_material_fingerprint: str,
    ) -> dict:
        """把人类裁决绑定到当前解析输出；后续重解析会使旧裁决失效。"""

        workspace = await self._workspace()
        review_decision = MaterialSourceReviewDecision(
            source_id=source_id,
            normalized_material_fingerprint=expected_normalized_material_fingerprint,
            decision=decision,
            actor=actor,
            reason=reason,
        )
        try:
            await material_dal.record_source_review_decision(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                decision=review_decision,
            )
        except (
            material_dal.MaterialOwnershipError,
            material_dal.MaterialStateConflictError,
        ) as error:
            raise MaterialConflictError("资料状态已变化，请刷新后重试") from error
        return await self.get_snapshot()

    async def delete_source(self, source_id: UUID) -> dict:
        workspace = await self._workspace()
        try:
            source = await material_dal.get_source_deletion_target(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                source_id=source_id,
            )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("资料不存在") from error
        if source.status == "deleted":
            return await self.get_snapshot()
        try:
            if not self._storage_rejected_before_object_write(source):
                await self._delete_or_ignore_missing(source.object_path)
        except MaterialStorageError as error:
            raise MaterialServiceUnavailableError(
                "原文件删除失败，系统未把资料标记为已删除；请稍后重试"
            ) from error
        try:
            await material_dal.delete(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace.id,
                source_id=source_id,
            )
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("资料不存在") from error
        except asyncpg.PostgresError as error:
            raise MaterialServiceUnavailableError(
                "原文件已删除，但资料状态同步失败；请再次删除以完成同步"
            ) from error
        return await self.get_snapshot()

    @staticmethod
    def _storage_rejected_before_object_write(source: MaterialSourceDeletionTarget) -> bool:
        """识别已由 Storage 明确拒绝、从未创建主对象的失败上传。"""

        return (
            source.status == "failed"
            and source.error is not None
            and source.error.failure_stage == "storage"
            and "invalid_mime_type" in source.error.reason
        )

    async def _delete_or_ignore_missing(self, object_path: str) -> None:
        try:
            await self._storage_client().delete(object_path)
        except MaterialStorageError as error:
            if "HTTP 404" not in str(error):
                raise

    async def update_topic_primary_input_mode(
        self,
        report_section_id: str,
        *,
        primary_input_mode: Literal["materials", "questions"],
        base_workspace_state_seq: int,
    ) -> dict:
        """保存议题的首选收集路径；另一条路径仍可作为补充，不改写既有输入。"""
        if report_section_id not in self.allowed_report_section_ids:
            raise MaterialAccessDeniedError("当前报告不能访问该议题")
        snapshot = await self._typed_snapshot()
        if snapshot.workspace.state_seq != base_workspace_state_seq:
            raise MaterialConflictError("资料工作区已在别处更新，请刷新后重试")
        modes = dict(snapshot.workspace.state.topic_primary_input_modes)
        modes[report_section_id] = primary_input_mode
        state = snapshot.workspace.state.model_copy(
            update={"topic_primary_input_modes": modes}
        )
        await self._commit_workspace_mutation(
            workspace_id=snapshot.workspace.id,
            base_state_seq=base_workspace_state_seq,
            state=state,
            event_type="topic_primary_input_mode_updated",
            payload={
                "reportSectionId": report_section_id,
                "primaryInputMode": primary_input_mode,
            },
        )
        return await self.get_snapshot()

    async def update_report_primary_input_mode(
        self,
        *,
        primary_input_mode: Literal["materials", "questions"],
        base_report_state_seq: int,
    ) -> dict:
        """保存报告级主输入路径（资料解析 / 直接回答问题）。

        只改分步流编排，不清空、不迁移任何已填输入：两条路径的事实
        （intakeItems 与资料证据轨）在生成侧本就允许任一为空。

        落在报告状态而非资料工作区：生成闸与导出闸都按它裁定议题义务是否阻断，
        两闸必须读同一侧事实，否则出现"生成得了却导不出"。
        """
        report = await reports_dal.get_state(
            self.pool, self.account_id, self.report_id
        )
        if report.state_seq != base_report_state_seq:
            raise MaterialConflictError("报告已在别处更新，请刷新后重试")
        state = dict(report.state)
        meta = dict(state.get("meta") or {})
        meta["primaryInputMode"] = primary_input_mode
        state["meta"] = meta
        try:
            await reports_dal.put_state(
                self.pool,
                self.account_id,
                self.report_id,
                state,
                base_report_state_seq,
                # 本端点是 primaryInputMode 的唯一写入器；声明后锁内保全放行这一个
                # 字段，其余服务端事实仍按 generic 语义原样往返。
                writes=frozenset({"meta.primaryInputMode"}),
            )
        except reports_dal.StateConflictError as exc:
            raise MaterialConflictError("报告已在别处更新，请刷新后重试") from exc
        return await self.get_snapshot()

    async def _commit_workspace_mutation(
        self,
        *,
        workspace_id: UUID,
        base_state_seq: int,
        state: WorkspaceState,
        event_type: str,
        payload: dict,
    ) -> int:
        """把状态 CAS 与审计事件作为一个数据库事实提交；无后台任务入队副作用。"""
        try:
            result = await material_dal.mutate_workspace(
                self.pool,
                account_id=self.account_id,
                workspace_id=workspace_id,
                base_state_seq=base_state_seq,
                state=state,
                actor="user",
                event_type=event_type,
                event_payload=payload,
            )
        except material_dal.MaterialStateConflictError as error:
            raise MaterialConflictError(
                "资料工作区已在别处更新，请刷新后重试"
            ) from error
        except material_dal.MaterialOwnershipError as error:
            raise MaterialNotFoundError("资料工作区不存在") from error
        return result.state_seq

    def _project_snapshot(
        self,
        snapshot: MaterialSnapshot,
        report_state: dict,
        *,
        report_state_seq: int = 1,
    ) -> dict:
        state = snapshot.workspace.state
        raw_items = report_state.get("intakeItems") or {}
        projected_proposals = [
            self._project_proposal(proposal, raw_items) for proposal in state.proposals
        ]
        projected_gaps = [self._project_gap(gap) for gap in state.gaps]
        projected_facts = [self._project_fact(fact) for fact in state.facts]
        sources = [
            self._project_source(
                source,
                review_decision=snapshot.review_decisions.get(source.id),
            )
            for source in snapshot.sources
            if source.status != "deleted"
        ]
        sources_by_id = {source.id: source for source in snapshot.sources}
        return {
            "id": str(snapshot.workspace.id),
            "report_id": str(snapshot.workspace.report_id),
            "adapter_id": snapshot.workspace.adapter_id,
            "contract_version": snapshot.workspace.contract_version,
            "state_seq": snapshot.workspace.state_seq,
            "projection_seq": snapshot.projection_seq,
            "report_state_seq": report_state_seq,
            "sources": sources,
            "messages": [
                {
                    "id": str(turn.turn_id),
                    "role": turn.role,
                    "content": turn.content,
                    "scope_id": self._scope_id(
                        turn.scope_kind, turn.report_section_ids
                    ),
                    "created_at": "",
                }
                for turn in state.turns
            ],
            "clarifications": [
                self._project_clarification(item) for item in state.clarifications
            ],
            "proposals": projected_proposals,
            "facts": projected_facts,
            "gaps": projected_gaps,
            "topic_primary_input_modes": state.topic_primary_input_modes,
            # 报告级填报方式落在报告状态（与生成闸、导出闸同源）；
            # 此处只做投影转发，资料工作区不再持有该事实。
            "report_primary_input_mode": (
                (report_state.get("meta") or {}).get("primaryInputMode")
            ),
            "scope_summaries": self._scope_summaries(
                sources, projected_proposals, projected_gaps
            ),
            "ingress_receipts": [
                self._project_ingress_receipt(decision, sources_by_id)
                for decision in snapshot.ingress_decisions
            ],
        }

    def _project_source(
        self,
        source: MaterialSource,
        *,
        include_content: bool = False,
        review_decision: MaterialSourceReviewDecision | None = None,
    ) -> dict:
        material = source.normalized_material
        segments: list[dict] = []
        if material is not None:
            for fragment in material.fragments:
                item = {
                    "id": fragment.fragment_id,
                    "kind": fragment.kind,
                    "locator": fragment.locator.model_dump(mode="json"),
                    "quality_flags": [],
                }
                if fragment.kind == "table":
                    item["markdown"] = fragment.text
                elif fragment.kind == "image_observation":
                    item["text"] = fragment.description
                else:
                    item["text"] = fragment.text
                segments.append(item)
        fragment_count = source.normalized_fragment_count
        fragment_kinds = source.normalized_fragment_kinds
        if material is not None:
            fragment_count = len(material.fragments)
            fragment_kinds = sorted({fragment.kind for fragment in material.fragments})
        parse_status = (
            "failed" if source.status == "failed" else
            "available" if source.has_normalized_material else
            "not_started"
        )
        parse_summary = (
            "解析或提取未完成；请查看失败原因和下一步。"
            if parse_status == "failed"
            else f"已取得 {fragment_count} 个可定位片段（{'、'.join(fragment_kinds) or '无'}）。"
            if parse_status == "available"
            else "尚未取得可用解析结果。"
        )
        current_review_decision = (
            review_decision
            if review_decision is not None
            and review_decision.normalized_material_fingerprint
            == source.normalized_material_fingerprint
            else None
        )
        return {
            "id": str(source.id),
            "filename": source.filename,
            "content_type": source.media_type,
            "size_bytes": source.size_bytes,
            "sha256": source.sha256,
            "scope": {
                "kind": source.scope_kind,
                "report_section_ids": source.report_section_ids,
            },
            "content_availability": (
                "available"
                if material is not None or source.has_normalized_material
                else "not_extracted"
            ),
            "status": source.status,
            "error_stage": source.error.failure_stage if source.error else None,
            "error_message": source.error.reason if source.error else None,
            "error_next_action": source.error.next_action if source.error else None,
            "can_retry": bool(source.error and source.error.can_retry_manually),
            "parse_result": {
                "status": parse_status,
                "fragment_count": fragment_count,
                "fragment_kinds": fragment_kinds,
                "summary": parse_summary,
            },
            "normalized_material_fingerprint": (
                source.normalized_material_fingerprint
            ),
            "normalized_material": (
                {
                    "segments": segments,
                    "review_markdown": material.render_text(),
                    "quality_flags": material.warnings,
                }
                if material is not None and include_content
                else None
            ),
            "processing_steps": [
                {
                    "id": f"{source.id}:{index}",
                    "stage": step.step,
                    "method": step.parser or step.model or step.processor,
                    "model": step.model,
                    "route": step.route,
                    "status": step.status,
                    "quality_flags": step.quality_flags,
                    "created_at": step.started_at.isoformat(),
                }
                for index, step in enumerate(source.processing_steps)
            ],
            "current_review_decision": (
                {
                    "decision": current_review_decision.decision,
                    "reason": (
                        current_review_decision.reason
                        if current_review_decision.actor == "user"
                        else None
                    ),
                }
                if current_review_decision is not None
                else None
            ),
            "created_at": source.created_at.isoformat() if source.created_at else "",
            "updated_at": source.updated_at.isoformat() if source.updated_at else "",
        }

    @staticmethod
    def _project_ingress_receipt(
        decision: MaterialIngressDecision,
        sources_by_id: dict[UUID, MaterialSource],
    ) -> dict:
        """由持久准入事实与当前 Source 状态派生展示文案。"""

        source = (
            sources_by_id.get(decision.source_id)
            if decision.source_id is not None
            else None
        )
        if decision.status == "accepted":
            status = source.status if source is not None else "不可用"
            message = f"资料已接纳；当前处理状态：{status}。"
            next_action = "等待解析完成或按当前状态处理。"
        elif decision.status == "reused":
            status = source.status if source is not None else "不可用"
            message = f"已复用内容相同的既有资料；当前处理状态：{status}。"
            next_action = "无需重复上传。"
        elif decision.reason_code == "file_rejected":
            message = "文件未通过准入校验。"
            next_action = "请按当前文件格式、大小和文件名要求修正后重新上传。"
        elif decision.reason_code == "duplicate_declaration_conflict":
            message = "内容相同的文件已存在，但本次文件说明不同。"
            next_action = "请编辑既有文件说明；系统不会用重复上传静默覆盖声明。"
        elif decision.reason_code == "binding_removed":
            message = "内容相同的文件已被移出当前报告。"
            next_action = "请在已移出文件中显式恢复，不要重复上传。"
        else:
            message = "资料未完成可靠写入。"
            next_action = "请检查当前 Source 状态后重试。"
        return MaterialIngressReceipt(
            **decision.model_dump(mode="python"),
            message=message,
            next_action=next_action,
        ).model_dump(mode="json")

    def _project_proposal(self, proposal: InputProposal, raw_items: dict) -> dict:
        current = raw_items.get(proposal.target_handle) or {}
        if not isinstance(current, dict):
            current = {}
        current_answer = current.get("answer")
        current_supplement = current.get("supplement")
        current_fingerprint = self.adapter.fingerprint(
            current_answer, current_supplement
        )
        status = proposal.status
        stale_reason = proposal.stale_reason
        try:
            target = self.adapter.target(proposal.target_handle)
            definition_matches = (
                self.adapter.target_fingerprint(proposal.target_handle)
                == proposal.target_fingerprint
            )
        except UnknownMaterialTargetError:
            target = None
            definition_matches = False
        expected = (
            proposal.proposed_value_fingerprint
            if proposal.status == "applied"
            else proposal.current_value_fingerprint
        )
        if proposal.status in {"accepted", "applied"} and (
            not definition_matches or current_fingerprint != expected
        ):
            status = "stale"
            stale_reason = (
                "用户后续修改" if proposal.status == "applied" else "目标题当前值已变化"
            )
        scope_id = target.scope_id if target else "report"
        return {
            "id": str(proposal.proposal_id),
            "scope_id": scope_id,
            "report_section_id": None if scope_id == "profile" else scope_id,
            "target_key": proposal.target_handle,
            "target_label": target.prompt if target else proposal.target_handle,
            "target_kind": target.kind if target else "text",
            "target_options": list(target.options) if target else [],
            "target_option_groups": [
                group.model_dump(mode="json")
                for group in (target.option_groups if target else ())
            ],
            "question": target.prompt if target else None,
            "current_answer": current_answer,
            "current_supplement": current_supplement,
            "proposed_answer": proposal.proposed_answer,
            "proposed_supplement": proposal.supplement,
            "basis": proposal.basis,
            "explanation": proposal.rationale,
            "evidence_refs": [
                {
                    "source_id": str(evidence.source_id),
                    "source_name": evidence.source_label,
                    "segment_id": evidence.fragment_id,
                    "locator": evidence.locator.model_dump(mode="json"),
                }
                for evidence in proposal.evidence_refs
            ],
            "fact_claim_ids": [str(item) for item in proposal.fact_claim_ids],
            "processing_summary": "证据已完成格式校验、解析与类型化清洗",
            "status": status,
            "stale_reason": stale_reason,
            "target_value_fingerprint": current_fingerprint,
        }

    def _project_fact(self, fact: MaterialFactClaim) -> dict:
        try:
            target = self.adapter.target(fact.semantic_key)
            scope_id = target.scope_id
            label = target.prompt
        except UnknownMaterialTargetError:
            scope_id = "report"
            label = fact.semantic_key
        return {
            "id": str(fact.fact_id),
            "semantic_key": fact.semantic_key,
            "label": label,
            "scope_id": scope_id,
            "report_section_id": None if scope_id == "profile" else scope_id,
            "value": fact.value,
            "supplement": fact.supplement,
            "effective_period": fact.effective_period,
            "rationale": fact.rationale,
            "basis": fact.basis,
            "evidence_refs": [
                {
                    "source_id": str(item.source_id),
                    "source_name": item.source_label,
                    "segment_id": item.fragment_id,
                    "locator": item.locator.model_dump(mode="json"),
                }
                for item in fact.evidence_refs
            ],
            "status": fact.status,
            "confirmation_method": fact.confirmation_method,
            "version": fact.version,
            "stale_reason": fact.stale_reason,
        }

    def _gap_scope(self, target_handle: str | None) -> str:
        if not target_handle:
            return "report"
        try:
            return self.adapter.target(target_handle).scope_id
        except UnknownMaterialTargetError:
            return "report"

    @staticmethod
    def _scope_id(scope_kind: str, report_section_ids: list[str]) -> str:
        if scope_kind == "topics" and len(report_section_ids) == 1:
            return report_section_ids[0]
        return scope_kind

    def _project_gap(self, gap) -> dict:
        kind = {
            "missing": "missing",
            "conflict": "conflict",
            "unreadable": "unparseable",
            "unsupported": "unparseable",
            "ambiguous": "needs_judgment",
        }[gap.category]
        scope_id = (
            self._gap_scope(gap.target_handle)
            if gap.target_handle
            else self._scope_id(gap.scope_kind, gap.report_section_ids)
        )
        return {
            "id": str(gap.gap_id),
            "scope_id": scope_id,
            "report_section_id": None
            if scope_id in {"profile", "report"}
            else scope_id,
            "kind": kind,
            "title": "资料缺口" if gap.category == "missing" else "资料需要处理",
            "description": gap.description,
            "source_ids": [str(item.source_id) for item in gap.evidence_refs],
            "status": gap.status,
        }

    def _project_clarification(self, request: ClarificationRequest) -> dict:
        return {
            "id": str(request.request_id),
            "scope_id": self._scope_id(request.scope_kind, request.report_section_ids),
            "question": request.question,
            "options": [item.model_dump(mode="json") for item in request.options],
            "allow_free_text": request.allow_free_text,
            "status": request.status,
            "answer": request.answer,
            "created_at": "",
        }

    def _scope_summaries(
        self, sources: list[dict], proposals: list[dict], gaps: list[dict]
    ) -> list[dict]:
        source_counts: Counter[str] = Counter()
        ready_counts: Counter[str] = Counter()
        for source in sources:
            scope = source["scope"]
            scope_ids = (
                scope["report_section_ids"]
                if scope["kind"] == "topics"
                else [scope["kind"]]
            )
            for scope_id in scope_ids:
                source_counts[scope_id] += 1
                if source["status"] == "ready":
                    ready_counts[scope_id] += 1
        pending = Counter(
            item["scope_id"] for item in proposals if item["status"] == "proposed"
        )
        accepted = Counter(
            item["scope_id"] for item in proposals if item["status"] == "accepted"
        )
        gap_counts = Counter(
            item["scope_id"] for item in gaps if item["status"] == "open"
        )
        registry = load_topic_contract(self.knowledge_package).reportSectionsById
        scope_ids = {"profile", *source_counts, *pending, *accepted, *gap_counts}
        return [
            {
                "scope_id": scope_id,
                "label": (
                    "基础信息"
                    if scope_id == "profile"
                    else registry[scope_id].title
                    if scope_id in registry
                    else dict(REPORT_FILE_REPORT_AREA_TAGS)[scope_id]
                    if scope_id in dict(REPORT_FILE_REPORT_AREA_TAGS)
                    else "待分类资料"
                    if scope_id == "uncertain"
                    else "全报告资料"
                ),
                "report_section_id": scope_id if scope_id in registry else None,
                "source_count": source_counts[scope_id],
                "ready_count": ready_counts[scope_id],
                "pending_proposal_count": pending[scope_id],
                "accepted_proposal_count": accepted[scope_id],
                "gap_count": gap_counts[scope_id],
            }
            for scope_id in sorted(
                scope_ids, key=lambda value: (value != "profile", value)
            )
        ]
