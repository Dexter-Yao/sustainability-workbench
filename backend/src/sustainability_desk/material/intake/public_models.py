# ABOUTME: 资料工作区 HTTP 公共投影合同，统一约束 FastAPI 响应与前端生成类型。
# ABOUTME: 本文件只描述人类可见投影，不暴露对象路径、数据库行、完整清洗正文或内部任务 payload。
# ABOUTME(en): Public HTTP projection contract of the material workspace, binding FastAPI and frontend types.
# ABOUTME(en): Human-visible projections only: no object paths, database rows, full normalized text or task payloads.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from sustainability_desk.material.intake.models import (
    AssertionBasis,
    MaterialFactConfirmationMethod,
    MaterialFactStatus,
    MaterialIngressReceipt,
    MaterialSourceStatus,
    ProposalStatus,
    MaterialSourceReviewPosture,
    ReportFileIngressPolicy,
    UserFileDeclaration,
    UserFileDeclarationRevision,
    PrimaryInputMode,
    SourceLocator,
    StrictModel,
)


class MaterialSourceReviewProjection(StrictModel):
    """客户安全的当前复核结果；内部身份、指纹和操作员理由不出边界。"""

    decision: MaterialSourceReviewPosture
    reason: str | None = Field(default=None, min_length=1, max_length=1_000)


class MaterialScopeProjection(StrictModel):
    kind: Literal["profile", "topics", "uncertain", "report"]
    report_section_ids: list[str]


class MaterialProcessingStepProjection(StrictModel):
    id: str
    stage: str
    method: str | None = None
    model: str | None = None
    route: str | None = None
    status: str
    quality_flags: list[str]
    created_at: str


class NormalizedSegmentProjection(StrictModel):
    id: str
    kind: Literal["text", "table", "image_observation"]
    locator: SourceLocator
    text: str | None = None
    markdown: str | None = None
    quality_flags: list[str]


class NormalizedMaterialProjection(StrictModel):
    segments: list[NormalizedSegmentProjection]
    review_markdown: str
    quality_flags: list[str]


class MaterialParseResultProjection(StrictModel):
    """单份资料的脱敏 parse-first 结果摘要，不携带清洗正文或对象路径。"""

    status: Literal["not_started", "available", "failed"]
    fragment_count: int = Field(ge=0)
    fragment_kinds: list[Literal["text", "table", "image_observation"]]
    summary: str


class MaterialSourceProjection(StrictModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    scope: MaterialScopeProjection
    content_availability: Literal["available", "not_extracted"]
    status: MaterialSourceStatus
    error_stage: str | None = None
    error_message: str | None = None
    error_next_action: str | None = None
    can_retry: bool
    parse_result: MaterialParseResultProjection
    normalized_material_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    normalized_material: NormalizedMaterialProjection | None = None
    processing_steps: list[MaterialProcessingStepProjection]
    current_review_decision: MaterialSourceReviewProjection | None = None
    created_at: str
    updated_at: str


class MaterialMessageProjection(StrictModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    scope_id: str
    created_at: str


class MaterialEvidenceProjection(StrictModel):
    source_id: UUID
    source_name: str
    segment_id: str
    locator: SourceLocator
    excerpt: str | None = None


class MaterialOptionGroupProjection(StrictModel):
    key: str
    label: str
    options: list[str]
    min_selections: int = Field(ge=0)


class MaterialProposalProjection(StrictModel):
    id: UUID
    scope_id: str
    report_section_id: str | None = None
    target_key: str
    target_label: str
    target_kind: Literal["text", "single_select", "multi_select"]
    target_options: list[str]
    target_option_groups: list[MaterialOptionGroupProjection]
    question: str | None = None
    current_answer: str | list[str] | None = None
    current_supplement: str | None = None
    proposed_answer: str | list[str]
    proposed_supplement: str | None = None
    basis: AssertionBasis
    explanation: str
    evidence_refs: list[MaterialEvidenceProjection]
    fact_claim_ids: list[UUID]
    processing_summary: str
    status: ProposalStatus
    stale_reason: str | None = None
    target_value_fingerprint: str


class MaterialFactProjection(StrictModel):
    id: UUID
    semantic_key: str
    label: str
    scope_id: str
    report_section_id: str | None = None
    value: str | list[str]
    supplement: str | None = None
    effective_period: str | None = None
    rationale: str
    basis: AssertionBasis
    evidence_refs: list[MaterialEvidenceProjection]
    status: MaterialFactStatus
    confirmation_method: MaterialFactConfirmationMethod | None = None
    version: int = Field(ge=1)
    stale_reason: str | None = None


class MaterialGapProjection(StrictModel):
    id: UUID
    scope_id: str
    report_section_id: str | None = None
    kind: Literal["missing", "conflict", "unparseable", "needs_judgment"]
    title: str
    description: str
    source_ids: list[UUID]
    status: Literal["open", "resolved", "dismissed", "stale"]


class ClarificationOptionProjection(StrictModel):
    value: str
    label: str
    description: str | None = None


class MaterialClarificationProjection(StrictModel):
    id: UUID
    scope_id: str
    question: str
    options: list[ClarificationOptionProjection]
    allow_free_text: bool
    status: Literal["open", "answered", "dismissed"]
    answer: str | None = None
    created_at: str


class MaterialScopeSummaryProjection(StrictModel):
    scope_id: str
    label: str
    report_section_id: str | None = None
    source_count: int = Field(ge=0)
    ready_count: int = Field(ge=0)
    pending_proposal_count: int = Field(ge=0)
    accepted_proposal_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)


class MaterialWorkspaceProjection(StrictModel):
    id: UUID
    report_id: UUID
    adapter_id: str
    contract_version: str
    state_seq: int = Field(ge=1)
    projection_seq: int = Field(ge=1)
    report_state_seq: int = Field(ge=1)
    sources: list[MaterialSourceProjection]
    messages: list[MaterialMessageProjection]
    clarifications: list[MaterialClarificationProjection]
    proposals: list[MaterialProposalProjection]
    facts: list[MaterialFactProjection]
    gaps: list[MaterialGapProjection]
    topic_primary_input_modes: dict[str, PrimaryInputMode]
    report_primary_input_mode: PrimaryInputMode | None = None
    scope_summaries: list[MaterialScopeSummaryProjection]
    ingress_receipts: list[MaterialIngressReceipt] = Field(default_factory=list)


class MaterialSourceContentProjection(StrictModel):
    source_id: UUID
    normalized_material: NormalizedMaterialProjection | None


class CertificateFactProjection(StrictModel):
    """证书事实的用户可见投影；字段与入口解析同名，供资料处理页核对与更正。"""

    certificate_name: str = ""
    issuer: str | None = None
    covered_scope: str | None = None
    holder_name: str | None = None
    unreadable_fields: tuple[str, ...] = ()


class ReportFileImageAnalysisProjection(StrictModel):
    """排版素材的图片识别生命周期与受限资产视图；题注/替代文本归资产 owner。"""

    status: Literal["queued", "running", "succeeded", "failed", "superseded"]
    asset_id: UUID | None = None
    caption: str | None = None
    category: str | None = None
    placement_scope_id: str | None = None
    # 证书类素材解析出的事实；供用户在资料处理页核对与更正，非证书为 None。
    certificate_fact: CertificateFactProjection | None = None


class ReportFileSourceProjection(StrictModel):
    """轻量版准备中心使用的文件投影，不暴露旧资料工作区的用途、范围或解析正文。"""

    binding_id: UUID
    source_id: UUID
    binding_status: Literal["active", "removed", "superseded"]
    filename: str
    source_label: str | None = None
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    declaration: UserFileDeclarationRevision
    admission_status: Literal["admitted", "failed"]
    error_message: str | None = Field(default=None, min_length=1, max_length=1_000)
    file_analysis: ReportFileAnalysisProjection | None = None
    image_analysis: ReportFileImageAnalysisProjection | None = None
    # 文件级处理结论（design.md §7.3 两道闸）：failed=闸一硬阻断（文件层机械事实），
    # ok_with_attention=闸二软待确认（内容层），ok=已处理；None 表示尚无结论（未提交或处理中）。
    parse_status: Literal["ok", "failed", "ok_with_attention"] | None = None
    parse_failure_reason: str | None = Field(default=None, min_length=1, max_length=1_000)
    created_at: str
    updated_at: str


class ReportFileAttentionProjection(StrictModel):
    """一项面向上传者的资料澄清提示，不暴露内部判断代码。"""

    message: str = Field(min_length=1, max_length=2_000)
    next_action: str = Field(min_length=1, max_length=1_000)


class ReportFileDossierProjection(StrictModel):
    """FileDossier 的客户可见投影，保持文件级来源边界。"""

    relevance: Literal["relevant", "not_relevant"]
    relevance_reason: str = Field(min_length=1, max_length=2_000)
    applicable_scope_count: int = Field(ge=0)
    attention_items: list[ReportFileAttentionProjection] = Field(
        default_factory=list
    )
    # 相关资料相对本次报告范围的结论，由冻结 Mapping plan 派生：within_report 表示至少一条
    # 资料路由到本次 Mapping scope；outside_report 表示适用范围全在本次报告之外（资料保留，
    # 只是不进入本次报告）。None 表示不相关或尚未形成快照。说明文案由执行范围拥有。
    report_scope: Literal["within_report", "outside_report"] | None = None
    report_scope_notice: str | None = Field(default=None, min_length=1, max_length=500)


class ReportFileAnalysisProjection(StrictModel):
    """当前文件的 File Agent 生命周期与受限 Dossier 视图。"""

    status: Literal[
        "queued",
        "running",
        "succeeded",
        "needs_attention",
        "failed",
        "superseded",
    ]
    dossier: ReportFileDossierProjection | None = None


class MaterialSetConfirmationProjection(StrictModel):
    """资料集确认状态；确认后才对 active 语义资料入队 File Agent。"""

    status: Literal["not_required", "pending_description", "required", "confirmed"]
    confirmed_at: str | None = None
    pending_description_count: int = Field(ge=0)


class ReportFileIntakeProjection(StrictModel):
    """报告准备中心的文件准入 SSOT 投影。"""

    report_id: UUID
    # 由本投影全部数据行的落库时间派生的单调序号(微秒纪元);
    # 前端据此丢弃乱序到达的旧快照响应,不得回传或用于并发写校验。
    projection_seq: int = Field(ge=1)
    policy: ReportFileIngressPolicy
    active_file_count: int = Field(ge=0)
    sources: list[ReportFileSourceProjection]
    ingress_receipts: list[MaterialIngressReceipt] = Field(default_factory=list)
    material_set_confirmation: MaterialSetConfirmationProjection
    # 批次级阶段（design.md §7.3 三阶段模型）：draft=上传与说明可编辑、processing=已提交
    # 正在逐份处理、reviewed=已有逐份结论（含零文件路径）。读取时由确认状态与当前
    # Agent 运行派生，不落库、不新增状态机；/materials/processing 页面形态由它决定。
    phase: Literal["draft", "processing", "reviewed"] = "draft"


class MaterialApiContracts(StrictModel):
    """前端生成类型使用的资料 API 合同集合；不作为业务请求载荷。"""

    workspace: MaterialWorkspaceProjection
    source_content: MaterialSourceContentProjection
    file_declaration: UserFileDeclaration
    report_file_intake: ReportFileIntakeProjection
