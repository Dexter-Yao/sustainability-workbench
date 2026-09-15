# ABOUTME: 资料工作区、规范化资料、证据定位、提案状态及队列租约的类型化合同。
# ABOUTME: workspace.state 是对话与人机确认的唯一工作状态；material_events 仅追加审计，不复制状态所有权。
# ABOUTME(en): Typed contracts for workspace, normalized material, evidence locators, proposals and queue leases.
# ABOUTME(en): workspace.state is the only working state; material_events is append-only audit, not a second owner.
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

type MaterialKind = Literal["pdf", "docx", "xlsx", "pptx", "png", "jpeg", "webp"]
type MaterialScopeKind = Literal["profile", "topics", "uncertain", "report"]
type MaterialProcessingRoute = Literal[
    "native_docx",
    "native_xlsx",
    "native_pdf_text",
    "native_pptx",
]
type MaterialSourceStatus = Literal[
    "uploading",
    "queued",
    "processing",
    "ready",
    "needs_attention",
    "failed",
    "deleted",
]
type TargetKind = Literal["lightweight_intake"]
type ProposalStatus = Literal["proposed", "accepted", "rejected", "applied", "stale"]
type MaterialFactStatus = Literal[
    "candidate", "confirmed", "conflicted", "rejected", "stale"
]
type MaterialFactConfirmationMethod = Literal["deterministic", "user"]
type AssertionBasis = Literal["material_evidence", "user_assertion"]
type PrimaryInputMode = Literal["materials", "questions"]
type MaterialIngressStatus = Literal["accepted", "reused", "rejected"]
type MaterialIngressReasonCode = Literal[
    "admitted",
    "duplicate_reused",
    "duplicate_declaration_conflict",
    "binding_removed",
    "file_rejected",
    "storage_failed",
    "upload_failed",
]
type MaterialSourceReviewPosture = Literal["reviewed_accepted", "excluded_by_user"]
type ReportFileRole = Literal["semantic_material", "layout_asset"]
type ReportMaterialBindingStatus = Literal["active", "removed", "superseded"]
MAX_MATERIAL_FILENAME_LENGTH = 500
REPORT_FILE_DESCRIPTION_MIN_CHARS = 10
REPORT_FILE_DESCRIPTION_MAX_CHARS = 140
REPORT_FILE_ASSET_TITLE_MAX_CHARS = 100


class StrictModel(BaseModel):
    """资料域所有跨层合同的共同严格边界。"""

    model_config = ConfigDict(extra="forbid")


class UserFileDeclaration(StrictModel):
    """用户对一份原文件的权威说明，不推断资料是否最终被报告采用。

    description 与 layout_asset 的 asset_title 允许为空串，表示用户选择先上传、
    后补充说明；一旦非空，仍必须满足 10–140 字（说明）或 1–140 字（素材标题）的
    权威长度约束。空说明不是故障态，是"待补充"这一合法用户分支。
    """

    description: str = Field(max_length=REPORT_FILE_DESCRIPTION_MAX_CHARS)
    role: ReportFileRole
    topic_tags: list[str] = Field(min_length=1, max_length=24)
    asset_title: str | None = Field(
        default=None,
        max_length=REPORT_FILE_ASSET_TITLE_MAX_CHARS,
    )

    @model_validator(mode="after")
    def _validate_role_specific_fields(self) -> "UserFileDeclaration":
        self.description = self.description.strip()
        self.topic_tags = [tag.strip() for tag in self.topic_tags]
        if self.description and (
            len(self.description) < REPORT_FILE_DESCRIPTION_MIN_CHARS
        ):
            raise ValueError(
                f"文件说明需为空（待补充）或至少 {REPORT_FILE_DESCRIPTION_MIN_CHARS} 字"
            )
        if not all(self.topic_tags) or len(self.topic_tags) != len(set(self.topic_tags)):
            raise ValueError("文件标签不能为空或重复")
        if self.role == "semantic_material" and self.asset_title is not None:
            raise ValueError("语义资料不得填写排版素材标题")
        if self.asset_title is not None:
            self.asset_title = self.asset_title.strip() or None
        return self


class UserFileDeclarationRevision(UserFileDeclaration):
    """一项不可变的用户文件声明修订；当前声明由 Binding 的最高 revision 派生。"""

    revision_id: UUID
    binding_id: UUID
    revision: int = Field(ge=1)
    declared_at: datetime

    def matches(self, declaration: UserFileDeclaration) -> bool:
        """比较业务声明正文，不把修订身份误当作用户意图。"""

        return (
            self.description == declaration.description
            and self.role == declaration.role
            and self.topic_tags == declaration.topic_tags
            and self.asset_title == declaration.asset_title
        )


class ReportMaterialBinding(StrictModel):
    """物理 Source 与一份报告的可恢复成员关系，不拥有文件字节或声明正文。"""

    binding_id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    source_id: UUID
    status: ReportMaterialBindingStatus = "active"
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None
    superseded_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_status_timestamps(self) -> "ReportMaterialBinding":
        if (self.status == "removed") != (self.removed_at is not None):
            raise ValueError("removed Binding 必须且只能具有 removed_at")
        if (self.status == "superseded") != (self.superseded_at is not None):
            raise ValueError("superseded Binding 必须且只能具有 superseded_at")
        return self


class ReportFileTopicTag(StrictModel):
    """用户可选的文件主题标签；标签值由服务端领域目录而非前端枚举提供。"""

    id: str = Field(min_length=1, max_length=300)
    label: str = Field(min_length=1, max_length=300)
    kind: Literal["auxiliary", "report_area", "report_section"]


class ReportFileIngressPolicy(StrictModel):
    """报告文件入口的唯一公开准入策略，前端只能投影不可自行复制。"""

    max_files_per_report: int = Field(ge=1)
    max_file_bytes: int = Field(ge=1)
    max_pdf_pages: int = Field(ge=1)
    description_min_chars: int = Field(ge=1)
    description_max_chars: int = Field(ge=1)
    asset_title_max_chars: int = Field(ge=1)
    semantic_material_kinds: list[MaterialKind]
    layout_asset_kinds: list[MaterialKind]
    semantic_material_extensions: list[str]
    layout_asset_extensions: list[str]
    topic_tags: list[ReportFileTopicTag]

    @model_validator(mode="after")
    def _validate_public_limits(self) -> "ReportFileIngressPolicy":
        if self.description_max_chars < self.description_min_chars:
            raise ValueError("文件说明上限不得小于下限")
        for extension in [
            *self.semantic_material_extensions,
            *self.layout_asset_extensions,
        ]:
            if not extension.startswith(".") or extension != extension.lower():
                raise ValueError("公开文件扩展名必须是小写且以点号开头")
        return self


class ValidatedMaterialFile(StrictModel):
    filename: str = Field(min_length=1, max_length=MAX_MATERIAL_FILENAME_LENGTH)
    kind: MaterialKind
    media_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_page_count: int | None = Field(default=None, ge=1)
    quality_flags: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def requires_attention(self) -> bool:
        return bool(self.quality_flags)


class MaterialIngressDecision(StrictModel):
    """持久化准入事实；不保存易过期展示文案。"""

    receipt_id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    filename: str = Field(
        min_length=1,
        max_length=MAX_MATERIAL_FILENAME_LENGTH,
    )
    status: MaterialIngressStatus
    reason_code: MaterialIngressReasonCode
    source_id: UUID | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _identity_matches_status(self) -> "MaterialIngressDecision":
        if self.status in {"accepted", "reused"}:
            if self.source_id is None or self.sha256 is None:
                raise ValueError("已接纳或复用的准入收据必须绑定 Source 与 SHA-256")
        elif self.reason_code not in {
            "duplicate_declaration_conflict",
            "binding_removed",
            "file_rejected",
            "storage_failed",
            "upload_failed",
        }:
            raise ValueError("拒绝收据必须使用拒绝类原因")
        if self.status == "accepted" and self.reason_code != "admitted":
            raise ValueError("接纳收据原因必须为 admitted")
        if self.status == "reused" and self.reason_code != "duplicate_reused":
            raise ValueError("复用收据原因必须为 duplicate_reused")
        return self


class MaterialIngressReceipt(MaterialIngressDecision):
    """由准入事实和当前 Source 状态派生的人类可见收据。"""

    message: str = Field(min_length=1, max_length=1_000)
    next_action: str = Field(min_length=1, max_length=1_000)


class MaterialSourceReviewDecision(StrictModel):
    """对当前规范化解析结果的可选人类决定；解析指纹变化后自然失效。"""

    decision_id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    normalized_material_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: MaterialSourceReviewPosture
    actor: Literal["user", "operator"]
    reason: str = Field(min_length=1, max_length=1_000)


class PdfPageLocator(StrictModel):
    kind: Literal["pdf_page"] = "pdf_page"
    page: int = Field(ge=1)


class DocxParagraphLocator(StrictModel):
    kind: Literal["docx_paragraph"] = "docx_paragraph"
    paragraph_index: int = Field(ge=1)


class DocxTableLocator(StrictModel):
    kind: Literal["docx_table"] = "docx_table"
    table_index: int = Field(ge=1)
    row_start: int = Field(ge=1)
    row_end: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered_rows(self) -> "DocxTableLocator":
        if self.row_end < self.row_start:
            raise ValueError("DOCX 表格行范围无效")
        return self


class XlsxRangeLocator(StrictModel):
    kind: Literal["xlsx_range"] = "xlsx_range"
    sheet_name: str
    cell_range: str


class PptxSlideLocator(StrictModel):
    kind: Literal["pptx_slide"] = "pptx_slide"
    slide: int = Field(ge=1)


class ImageRegionLocator(StrictModel):
    kind: Literal["image_region"] = "image_region"
    region_label: str = "整张图片"
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def _complete_bounding_box(self) -> "ImageRegionLocator":
        values = (self.x, self.y, self.width, self.height)
        if any(value is not None for value in values) and any(
            value is None for value in values
        ):
            raise ValueError("图片区域坐标必须完整提供")
        if self.x is not None and self.width is not None and self.x + self.width > 1:
            raise ValueError("图片区域横向范围超出图片")
        if self.y is not None and self.height is not None and self.y + self.height > 1:
            raise ValueError("图片区域纵向范围超出图片")
        return self


type SourceLocator = Annotated[
    PdfPageLocator
    | DocxParagraphLocator
    | DocxTableLocator
    | XlsxRangeLocator
    | PptxSlideLocator
    | ImageRegionLocator,
    Field(discriminator="kind"),
]


class TextFragment(StrictModel):
    fragment_id: str
    kind: Literal["text"] = "text"
    text: str
    locator: SourceLocator


class TableFragment(StrictModel):
    fragment_id: str
    kind: Literal["table"] = "table"
    rows: list[list[str]]
    locator: SourceLocator

    @computed_field
    @property
    def text(self) -> str:
        """仅供人类界面和模型上下文投影，不作为表格事实的独立所有者。"""
        return "\n".join(" | ".join(row) for row in self.rows)


class ImageObservation(StrictModel):
    fragment_id: str
    kind: Literal["image_observation"] = "image_observation"
    description: str
    locator: ImageRegionLocator
    confidence: float | None = Field(default=None, ge=0, le=1)


type NormalizedFragment = Annotated[
    TextFragment | TableFragment | ImageObservation,
    Field(discriminator="kind"),
]


class ProcessingStep(StrictModel):
    step: Literal["validated", "routed", "parsed", "vision_extracted", "normalized"]
    processor: Literal["deterministic", "agent"]
    status: Literal["succeeded", "warning", "failed"]
    parser: str | None = None
    model: str | None = None
    route: MaterialProcessingRoute | None = None
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    quality_flags: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    message: str = ""

    @model_validator(mode="after")
    def _processor_identity_and_time(self) -> "ProcessingStep":
        if self.processor == "deterministic" and not self.parser:
            raise ValueError("确定性处理步骤必须记录 parser")
        if self.processor == "agent" and not self.model:
            raise ValueError("Agent 处理步骤必须记录 model")
        if self.step == "routed" and self.route is None:
            raise ValueError("路由处理步骤必须记录 route")
        if self.step != "routed" and self.route is not None:
            raise ValueError("只有路由处理步骤可以记录 route")
        if self.status != "failed" and self.completed_at is None:
            raise ValueError("已结束的处理步骤必须记录 completed_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("处理步骤完成时间不得早于开始时间")
        return self


class NormalizedMaterial(StrictModel):
    source_id: UUID
    source_label: str
    summary: str
    fragments: list[NormalizedFragment]
    processing_steps: list[ProcessingStep]
    warnings: list[str] = Field(default_factory=list)

    def render_text(self) -> str:
        """生成 Markdown 无关的纯文本人类投影；证据真相仍为 typed fragments。"""
        rendered: list[str] = []
        for fragment in self.fragments:
            if isinstance(fragment, ImageObservation):
                rendered.append(fragment.description)
            else:
                rendered.append(fragment.text)
        return "\n".join(rendered)


class EvidenceRef(StrictModel):
    source_id: UUID
    source_label: str
    fragment_id: str
    locator: SourceLocator


class MaterialFactClaimDraft(StrictModel):
    """模型可提出的证据声明；它不是已确认企业事实。"""

    semantic_key: str
    value: str | list[str]
    supplement: str | None = None
    effective_period: str | None = None
    rationale: str
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class MaterialFactClaim(MaterialFactClaimDraft):
    """报告级事实声明；只有 confirmed 状态可以支撑 Report 输入提案。"""

    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    basis: AssertionBasis = "material_evidence"
    fact_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    status: MaterialFactStatus = "candidate"
    confirmation_method: MaterialFactConfirmationMethod | None = None
    fingerprint: str
    stale_reason: str | None = None

    @classmethod
    def from_draft(
        cls,
        draft: MaterialFactClaimDraft,
        *,
        status: MaterialFactStatus = "candidate",
        confirmation_method: MaterialFactConfirmationMethod | None = None,
    ) -> "MaterialFactClaim":
        """用稳定业务载荷生成事实指纹；证据 locator 不成为语义身份。"""
        import hashlib
        import json

        payload = json.dumps(
            {
                "semanticKey": draft.semantic_key,
                "value": draft.value,
                "supplement": draft.supplement,
                "effectivePeriod": draft.effective_period,
                "evidence": sorted(
                    (str(item.source_id), item.fragment_id)
                    for item in draft.evidence_refs
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            **draft.model_dump(),
            status=status,
            confirmation_method=confirmation_method,
            fingerprint=hashlib.sha256(payload).hexdigest(),
        )

    @model_validator(mode="after")
    def _confirmation_matches_status(self) -> "MaterialFactClaim":
        if self.status == "confirmed" and self.confirmation_method is None:
            raise ValueError("已确认事实必须记录确认方式")
        if self.status != "confirmed" and self.confirmation_method is not None:
            raise ValueError("未确认事实不得记录确认方式")
        if self.status == "stale" and not (self.stale_reason or "").strip():
            raise ValueError("失效事实必须说明原因")
        if self.basis == "user_assertion":
            if self.evidence_refs:
                raise ValueError("用户直接断言不得沿用资料证据")
            if self.status not in {"confirmed", "conflicted", "rejected", "stale"}:
                raise ValueError(
                    "用户直接断言只能处于已确认、冲突待裁决、已拒绝或已失效状态"
                )
            if self.status == "confirmed" and self.confirmation_method != "user":
                raise ValueError("有效的用户直接断言必须由用户确认")
        elif not self.evidence_refs:
            raise ValueError("资料事实必须保留证据引用")
        return self


class MaterialGap(StrictModel):
    gap_id: UUID = Field(default_factory=uuid4)
    category: Literal["unreadable", "missing", "ambiguous", "conflict", "unsupported"]
    description: str
    blocking: bool = False
    target_handle: str | None = None
    effective_period: str | None = None
    fact_claim_ids: list[UUID] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    scope_kind: MaterialScopeKind = "report"
    report_section_ids: list[str] = Field(default_factory=list)
    status: Literal["open", "resolved", "dismissed", "stale"] = "open"
    fingerprint: str = ""

    @model_validator(mode="after")
    def _derive_fingerprint(self) -> "MaterialGap":
        if self.fingerprint:
            return self
        import hashlib
        import json

        payload = json.dumps(
            {
                "category": self.category,
                "targetHandle": self.target_handle,
                "effectivePeriod": self.effective_period,
                "factClaimIds": sorted(str(item) for item in self.fact_claim_ids),
                "scopeKind": self.scope_kind,
                "reportSectionIds": sorted(self.report_section_ids),
                "evidence": sorted(
                    (str(item.source_id), item.fragment_id)
                    for item in self.evidence_refs
                ),
                "description": self.description.strip(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self


class ClarificationOption(StrictModel):
    value: str
    label: str
    description: str | None = None


class ClarificationRequest(StrictModel):
    request_id: UUID = Field(default_factory=uuid4)
    question: str
    reason: str
    gap_ids: list[UUID] = Field(default_factory=list)
    options: list[ClarificationOption] = Field(default_factory=list)
    allow_free_text: bool = True
    status: Literal["open", "answered", "dismissed"] = "open"
    answer: str | None = None
    scope_kind: MaterialScopeKind = "report"
    report_section_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _answered_has_content(self) -> "ClarificationRequest":
        if not self.options and not self.allow_free_text:
            raise ValueError("澄清请求必须提供选项或允许自由文本")
        if self.status == "answered" and not (self.answer or "").strip():
            raise ValueError("已回答的澄清请求必须保存答案")
        return self


class InputProposalDraft(StrictModel):
    """模型可提出的内容；权威指纹、ID 与状态由确定性应用层补齐。"""

    target_handle: str
    proposed_answer: str | list[str]
    supplement: str | None = None
    rationale: str
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    fact_claim_ids: list[UUID] = Field(min_length=1)


class InputProposal(InputProposalDraft):
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    basis: AssertionBasis = "material_evidence"
    proposal_id: UUID = Field(default_factory=uuid4)
    status: ProposalStatus = "proposed"
    target_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_value_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_value_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale_reason: str | None = None

    @model_validator(mode="after")
    def _basis_matches_evidence(self) -> "InputProposal":
        if self.basis == "user_assertion" and self.evidence_refs:
            raise ValueError("用户直接断言提案不得沿用资料证据")
        if self.basis == "material_evidence" and not self.evidence_refs:
            raise ValueError("资料证据提案必须保留证据引用")
        return self


class ConversationTurn(StrictModel):
    turn_id: UUID = Field(default_factory=uuid4)
    role: Literal["user", "assistant"]
    content: str
    scope_kind: MaterialScopeKind = "report"
    report_section_ids: list[str] = Field(default_factory=list)


class WorkspaceState(StrictModel):
    """material_workspaces.state 的唯一 JSON 合同。"""

    version: Literal[1] = 1
    turns: list[ConversationTurn] = Field(default_factory=list)
    proposals: list[InputProposal] = Field(default_factory=list)
    gaps: list[MaterialGap] = Field(default_factory=list)
    clarifications: list[ClarificationRequest] = Field(default_factory=list)
    facts: list[MaterialFactClaim] = Field(default_factory=list)
    topic_primary_input_modes: dict[str, PrimaryInputMode] = Field(
        default_factory=dict
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_report_primary_input_mode(cls, data: object) -> object:
        """丢弃已迁走的 report_primary_input_mode（已提升为报告级事实）。

        StrictModel 禁止额外字段，而存量行的 state JSON 仍带着这个键——不丢弃会让
        既有工作区一律解析失败（准备投影 500）。它已由
        StoredReportStateV4.meta.primaryInputMode 拥有，此处只做入口清洗，
        不回写、不作为真相源。
        """
        if isinstance(data, dict) and "report_primary_input_mode" in data:
            data = {
                key: value
                for key, value in data.items()
                if key != "report_primary_input_mode"
            }
        return data


class MaterialWorkspace(StrictModel):
    id: UUID
    account_id: UUID
    report_id: UUID
    adapter_id: str
    contract_version: str
    status: Literal["active", "completed", "archived"]
    state: WorkspaceState
    state_seq: int = Field(ge=1)
    material_set_confirmed_at: datetime | None = None
    material_set_confirmed_fingerprint: str | None = None


class MaterialSource(StrictModel):
    """持久化资料来源投影；仅 worker/DAL 使用，不得直接放入模型上下文。"""

    id: UUID
    workspace_id: UUID
    account_id: UUID
    source_label: str = Field(
        min_length=1,
        max_length=MAX_MATERIAL_FILENAME_LENGTH,
    )
    filename: str = Field(
        min_length=1,
        max_length=MAX_MATERIAL_FILENAME_LENGTH,
    )
    object_path: str
    kind: MaterialKind
    media_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: MaterialSourceStatus
    scope_kind: Literal["profile", "topics", "uncertain"] = "uncertain"
    report_section_ids: list[str] = Field(default_factory=list)
    normalized_material: NormalizedMaterial | None = None
    has_normalized_material: bool = False
    normalized_fragment_count: int = Field(default=0, ge=0)
    normalized_fragment_kinds: list[
        Literal["text", "table", "image_observation"]
    ] = Field(default_factory=list)
    processing_steps: list[ProcessingStep] = Field(default_factory=list)
    error: MaterialProcessingError | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def normalized_material_fingerprint(self) -> str | None:
        """返回当前规范化审阅载荷指纹；唯一算法由 provenance 模块拥有。"""

        if self.normalized_material is None:
            return None
        from sustainability_desk.material.intake.provenance import (
            normalized_material_review_fingerprint,
        )

        return normalized_material_review_fingerprint(
            self.normalized_material,
            self.processing_steps,
        )


class MaterialSourceDeletionTarget(StrictModel):
    """删除流程只读取对象路径和生命周期状态，不消费清洗正文。"""

    object_path: str
    status: MaterialSourceStatus
    error: MaterialProcessingError | None = None


class MaterialProcessingError(StrictModel):
    code: str
    failure_stage: Literal[
        "upload", "validation", "storage", "parse", "extraction", "normalization"
    ]
    reason: str
    next_action: str
    retryable: bool = False

    @property
    def can_retry_manually(self) -> bool:
        """判断操作员修复运行环境后是否可以重放同一份已存档资料。"""

        return self.retryable or self.failure_stage in {
            "parse", "extraction", "normalization",
        }


class MaterialSnapshot(StrictModel):
    workspace: MaterialWorkspace
    sources: list[MaterialSource]
    ingress_decisions: list[MaterialIngressDecision] = Field(default_factory=list)
    review_decisions: dict[UUID, MaterialSourceReviewDecision] = Field(
        default_factory=dict
    )
    projection_seq: int = Field(default=1, ge=1)


class WorkspaceMutationResult(StrictModel):
    state_seq: int = Field(ge=1)
