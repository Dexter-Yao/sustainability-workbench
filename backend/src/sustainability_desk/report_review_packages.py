# ABOUTME: 从同一组资料、指标、映射、报告与运行合同派生客户批注、审阅稿资料处理说明页和内部审计包。
# ABOUTME: 客户合同结构性排除内部 trace 与存储信息；内部包保存可解析 trace 快照但不接收模型思维链。
# ABOUTME(en): Derives customer commentary, the review-draft material processing notice and the internal audit package.
# ABOUTME(en): The customer contract structurally excludes internal traces; the internal package takes no reasoning.
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.file_agent_contract import (
    FileAgentRunReceipt,
    FileDossier,
    FileMaterial,
    FileSourceRevision,
)
from sustainability_desk.material.intake.models import UserFileDeclarationRevision
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.material.mapping.snapshot import FrozenMappingPlan
from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.export.format_profile import DeliveryTexts, load_format_profile
from sustainability_desk.export.docx_renderer import DocumentRenderPlan
from sustainability_desk.contract.compiled_definition import (
    CompiledReportDefinition,
    load_compiled_report_definition,
)
from sustainability_desk.contract.block_provenance import ProvenanceBasis
from sustainability_desk.contract.certificate_facts import CERTIFICATE_TABLE_BLOCK_ID
from sustainability_desk.contract.disclosure_coverage import DisclosureCoverageReport
from sustainability_desk.contract.evidence_resolution import generation_evidence_keys
from sustainability_desk.contract.models import Block, Report
from sustainability_desk.quantitative_metrics import (
    quantitative_metric_display_label,
    quantitative_metric_value,
    quantitative_metrics_by_key,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"

type ReportArtifactKind = Literal["word", "review", "internal_audit"]
type InternalTraceStage = Literal[
    "file_agent",
    "image_agent",
    "mapping",
    "generation",
    "export",
]
type CustomerMaterialUsage = Literal[
    "adopted",
    "adopted_in_part",
    "not_adopted",
    "attention",
]


class ReviewPackageModel(BaseModel):
    """审阅包跨层合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportRevisionReference(ReviewPackageModel):
    """审阅包绑定的一次不可变 Report revision。"""

    report_id: UUID
    revision_id: UUID
    revision: int = Field(ge=1)
    content_fingerprint: str = Field(pattern=SHA256_PATTERN)
    created_at: datetime


class ReportArtifactReference(ReviewPackageModel):
    """内部可审计的交付物引用；客户投影只保留种类与文件名。"""

    artifact_id: UUID
    report_revision_id: UUID
    kind: ReportArtifactKind
    filename: str = Field(min_length=1, max_length=500)
    content_fingerprint: str = Field(pattern=SHA256_PATTERN)
    storage_ref: str = Field(min_length=1)


class InternalTraceReference(ReviewPackageModel):
    """一次模型或导出运行的可复现引用，不承载模型思维链。

    `storage_ref` 为 None 表示该轨迹在打包时不可用（外部轮转、清理、磁盘故障）。
    轨迹缺失是审计完备性的降级，不是业务失败：正文已经生成、交付物已经产出，
    不应因为一条引用取不到而让用户拿不到报告（否则全部块生成成功、
    Word 已落盘，整次生成仍会被判 failed）。缺失必须显式可见并告警，但不静默、不阻断。
    """

    stage: InternalTraceStage
    trace_id: str = Field(min_length=1, max_length=300)
    contract: str = Field(min_length=1, max_length=200)
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    output_fingerprint: str = Field(pattern=SHA256_PATTERN)
    storage_ref: str | None = Field(default=None, min_length=1)
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _validate_availability(self) -> "InternalTraceReference":
        if (self.storage_ref is None) == (self.unavailable_reason is None):
            raise ValueError(
                "轨迹引用必须恰好携带 storage_ref 或 unavailable_reason 之一"
            )
        return self


class ReportMaterialReviewInput(ReviewPackageModel):
    """一份资料在当前审阅输入中的冻结身份与用户声明。"""

    source_revision: FileSourceRevision
    filename: str = Field(min_length=1, max_length=500)
    declaration: UserFileDeclarationRevision

    @model_validator(mode="after")
    def _validate_declaration_revision(self) -> "ReportMaterialReviewInput":
        if self.declaration.revision != self.source_revision.declaration_revision:
            raise ValueError("资料声明 revision 与 File Agent source revision 不一致")
        return self


class BlockReviewLabel(ReviewPackageModel):
    """Block 内部身份到客户可理解标题的单向投影输入。"""

    block_id: str = Field(min_length=1, max_length=300)
    label: str = Field(min_length=1, max_length=300)


class LayoutImageReviewInput(ReviewPackageModel):
    """一张已放置素材图片的客户可读来源事实：上传文件名、用户说明与系统放置依据。

    放置依据只用稳定 code（识别类别）与契约范围标题表达；识别 Agent 的模型文本
    （placement_reason / summary）不进入本合同，也就不会进入批注。
    """

    asset_id: UUID
    block_id: str = Field(min_length=1, max_length=300)
    material_name: str = Field(min_length=1, max_length=500)
    user_description: str = Field(default="", max_length=1_000)
    asset_title: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=100)
    placement_scope_title: str = Field(min_length=1, max_length=300)


class ReportReviewSource(ReviewPackageModel):
    """生成两种审阅包的同源 typed 输入，不复制任何领域对象的所有权。"""

    report_revision: ReportRevisionReference
    report_title: str = Field(min_length=1, max_length=500)
    materials: tuple[ReportMaterialReviewInput, ...]
    dossiers: tuple[FileDossier, ...]
    block_decisions: tuple[BlockMaterialDecision, ...]
    mapping_plan: FrozenMappingPlan = Field(default_factory=FrozenMappingPlan)
    block_labels: tuple[BlockReviewLabel, ...]
    artifacts: tuple[ReportArtifactReference, ...]
    file_agent_receipts: tuple[FileAgentRunReceipt, ...]
    trace_references: tuple[InternalTraceReference, ...]
    #: 资料适用范围全部在本次报告之外时的说明，由执行范围能力表拥有，与资料处理页同一句。
    outside_scope_material_notice: str = Field(min_length=1, max_length=500)

    def outside_scope_dossier_ids(self) -> frozenset[UUID]:
        """相关、却没有路由到任何本次 Mapping scope 的 Dossier：资料只适用于本次报告未覆盖的范围。"""

        routed = {
            dossier_id
            for scope in self.mapping_plan.scopes
            for dossier_id in scope.dossier_ids
        }
        return frozenset(
            dossier_id
            for dossier_id in self.mapping_plan.candidate_dossier_ids
            if dossier_id not in routed
        )
    #: 本 revision 已放置的素材图片来源事实；批注据此把每幅素材图追溯到上传文件。
    layout_images: tuple[LayoutImageReviewInput, ...] = ()

    @model_validator(mode="after")
    def _validate_frozen_lineage(self) -> "ReportReviewSource":
        materials_by_source = {
            item.source_revision.source_id: item for item in self.materials
        }
        if len(materials_by_source) != len(self.materials):
            raise ValueError("资料审阅输入不得包含重复 source revision")

        dossier_ids = {item.dossier_id for item in self.dossiers}
        if len(dossier_ids) != len(self.dossiers):
            raise ValueError("资料审阅输入不得包含重复 FileDossier")
        if any(item.contract != "sustainability_desk.file_dossier.v7" for item in self.dossiers):
            raise ValueError("新审阅包只接受当前 v7 FileDossier")
        dossier_source_ids = {
            item.source_revision.source_id for item in self.dossiers
        }
        if len(dossier_source_ids) != len(self.dossiers):
            raise ValueError("同一冻结资料 revision 只能有一个当前 FileDossier")
        for dossier in self.dossiers:
            material = materials_by_source.get(dossier.source_revision.source_id)
            if material is None or material.source_revision != dossier.source_revision:
                raise ValueError("FileDossier 必须绑定当前冻结的资料与声明 revision")

        candidate_ids = {
            dossier.dossier_id
            for dossier in self.dossiers
            if dossier.candidate_for_mapping
        }
        if set(self.mapping_plan.candidate_dossier_ids) != candidate_ids:
            raise ValueError("冻结 Mapping plan 必须恰好反映当前可用 FileDossier")

        decision_block_ids = [item.block_id for item in self.block_decisions]
        if len(decision_block_ids) != len(set(decision_block_ids)):
            raise ValueError("BlockMaterialDecision 不得重复")
        dossier_materials: dict[UUID, FileMaterial] = {
            material.material_id: material
            for dossier in self.dossiers
            for material in dossier.materials
        }
        if len(dossier_materials) != sum(len(item.materials) for item in self.dossiers):
            raise ValueError("冻结 FileMaterial 身份不得重复")
        for decision in self.block_decisions:
            if set(decision.material_ids) - set(dossier_materials):
                raise ValueError("BlockMaterialDecision 引用了未知 FileMaterial")

        label_block_ids = [item.block_id for item in self.block_labels]
        if (
            len(label_block_ids) != len(set(label_block_ids))
            or set(label_block_ids) != set(decision_block_ids)
        ):
            raise ValueError("Block 标签必须恰好覆盖当前 BlockMaterialDecision")

        for artifact in self.artifacts:
            if artifact.report_revision_id != self.report_revision.revision_id:
                raise ValueError("产物必须绑定当前 Report revision")

        layout_asset_ids = [item.asset_id for item in self.layout_images]
        if len(layout_asset_ids) != len(set(layout_asset_ids)):
            raise ValueError("同一素材图片不得重复出现在审阅输入中")

        dossier_fingerprints = {
            (
                dossier.source_revision.source_id,
                dossier.dossier_fingerprint,
            )
            for dossier in self.dossiers
        }
        for receipt in self.file_agent_receipts:
            if receipt.source_revision.source_id not in materials_by_source:
                raise ValueError("File Agent receipt 引用了当前资料集之外的来源")
            if receipt.status == "completed" and (
                receipt.source_revision.source_id,
                receipt.dossier_fingerprint,
            ) not in dossier_fingerprints:
                raise ValueError("完成的 File Agent receipt 必须绑定当前 FileDossier")
        return self


class CustomerCommentarySource(ReviewPackageModel):
    """客户批注中的文件级已验证来源，不暴露内部定位或原文摘录。"""

    material_name: str


class CustomerCommentaryMetric(ReviewPackageModel):
    """批注中列出的一条用户已填写的定量指标：名称、数值、单位。

    带上数值是为了让客户在审阅正文时能就地校对；正文若含派生值（如比率、合计），
    客户也能据这些原始值自行核算。只投影用户实际填写的指标，不含内部 key 与口径备注。
    """

    metric_name: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=50)


class CustomerCommentaryImage(ReviewPackageModel):
    """一幅素材图片的客户可读来源：上传文件名、用户说明与系统放置依据。"""

    material_name: str = Field(min_length=1, max_length=500)
    user_description: str | None = Field(default=None, max_length=1_000)
    category_label: str | None = Field(default=None, max_length=100)
    placement_scope_title: str = Field(min_length=1, max_length=300)


class CustomerCommentaryEntry(ReviewPackageModel):
    """一个可见 Word 单元的客户可读说明。"""

    anchor_id: str = Field(min_length=1, max_length=300)
    unit_kind: Literal["paragraph", "list", "table", "image"]
    explanation: str = Field(min_length=1, max_length=2_000)
    basis: tuple[
        Literal[
            "structured_input",
            "validated_material",
            "quantitative_metric",
            "industry_disclosure_context",
            "deterministic_report_projection",
            "uploaded_layout_image",
        ],
        ...,
    ]
    sources: tuple[CustomerCommentarySource, ...] = ()
    #: 本单元实际消费、且用户已填写的定量指标，完整列出不截断——客户据此逐条校对正文数值。
    metrics: tuple[CustomerCommentaryMetric, ...] = ()
    #: 素材图片块内各幅图片的来源，按放置顺序。
    images: tuple[CustomerCommentaryImage, ...] = ()
    reading_notes: tuple[str, ...] = ()


class MaterialProcessingNoticeItem(ReviewPackageModel):
    """一份资料上的一条用户须留意事项，措辞与资料处理页逐字一致。"""

    message: str = Field(min_length=1, max_length=2_000)
    next_action: str = Field(min_length=1, max_length=1_000)


class MaterialProcessingNoticeFile(ReviewPackageModel):
    """按来源文件归组的须留意事项；只出现客户可读的文件名。"""

    material_name: str = Field(min_length=1, max_length=500)
    items: tuple[MaterialProcessingNoticeItem, ...] = Field(min_length=1)


class MaterialProcessingNotice(ReviewPackageModel):
    """审阅稿前置说明页的 machine contract。

    ``files`` 是模型核对用户资料后得出的、面向用户的资料事实（口径打架、时点超出报告期、
    引用了未提供的外部文件等），用户定稿前需要知道；它们不是内部不确定性，也不携带
    prompt、内部路径、判断代码、成本或 debug。与资料处理页同源同措辞，两处不得各自表述。
    """

    contract: Literal["sustainability_desk.material_processing_notice.v3"] = (
        "sustainability_desk.material_processing_notice.v3"
    )
    heading: str = Field(min_length=1, max_length=100)
    lead: str = Field(min_length=1, max_length=1_000)
    files_heading: str = Field(min_length=1, max_length=100)
    files_lead: str = Field(min_length=1, max_length=1_000)
    files: tuple[MaterialProcessingNoticeFile, ...] = Field(min_length=1)


class StandardsComplianceNoticeItem(ReviewPackageModel):
    """准则对照说明页上的一条事项；只承载业务语言，不含内部 key、路径与判断代码。"""

    #: 事项所属议题或报告部位的中文名称。
    scope_label: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2_000)
    #: 留意事项须给出下一步动作；信息性事项（准则允许的省略）无须动作。
    next_action: str | None = Field(default=None, max_length=1_000)


class StandardsComplianceNoticeGroup(ReviewPackageModel):
    """按性质归组的说明事项；组内条目顺序即渲染顺序。"""

    heading: str = Field(min_length=1, max_length=100)
    lead: str = Field(min_length=1, max_length=1_000)
    items: tuple[StandardsComplianceNoticeItem, ...] = Field(min_length=1)


class StandardsComplianceNotice(ReviewPackageModel):
    """审阅稿「准则对照说明」前置页的 machine contract。

    内容全部由 ``DisclosureCoverageReport`` 的稳定 code 经代码侧中文文案投影而来，
    不含 prompt、内部路径、requirement key 或判断代码。本页只陈述覆盖情况与留意事项，
    不构成鉴证意见或法律结论；正式稿不包含本页。
    """

    contract: Literal["sustainability_desk.standards_compliance_notice.v1"] = (
        "sustainability_desk.standards_compliance_notice.v1"
    )
    heading: str = Field(min_length=1, max_length=100)
    lead: str = Field(min_length=1, max_length=1_000)
    #: 覆盖概况一句话，避免逐条罗列淹没留意项。
    summary: str = Field(min_length=1, max_length=1_000)
    groups: tuple[StandardsComplianceNoticeGroup, ...] = ()


class CustomerCommentaryPackage(ReviewPackageModel):
    """批注 Word 的 machine contract；客户只接收它渲染出的自然语言 comments。"""

    contract: Literal["sustainability_desk.customer_commentary.v1"] = (
        "sustainability_desk.customer_commentary.v1"
    )
    report_title: str
    report_revision: int
    generated_at: datetime
    render_plan_fingerprint: str = Field(pattern=SHA256_PATTERN)
    overview: str = Field(min_length=1, max_length=2_000)
    entries: tuple[CustomerCommentaryEntry, ...]
    package_fingerprint: str = Field(pattern=SHA256_PATTERN)


class InternalExportReceipt(ReviewPackageModel):
    """确定性 Word 导出的完成凭证，不伪装为模型 trace。"""

    contract: Literal["sustainability_desk.internal_export_receipt.v1"] = (
        "sustainability_desk.internal_export_receipt.v1"
    )
    render_plan_fingerprint: str = Field(pattern=SHA256_PATTERN)
    normal_word_fingerprint: str = Field(pattern=SHA256_PATTERN)
    customer_word_fingerprint: str = Field(pattern=SHA256_PATTERN)
    customer_commentary_fingerprint: str = Field(pattern=SHA256_PATTERN)
    comment_entry_count: int = Field(ge=0)
    toc_finalized: Literal[True] = True


class InternalAuditPackage(ReviewPackageModel):
    """供产品方复盘的完整 typed 投影；原始 trace 由受限观测存储拥有。"""

    contract: Literal["sustainability_desk.internal_report_audit.v3"] = (
        "sustainability_desk.internal_report_audit.v3"
    )
    report_title: str
    report_revision: ReportRevisionReference
    materials: tuple[ReportMaterialReviewInput, ...]
    dossiers: tuple[FileDossier, ...]
    block_decisions: tuple[BlockMaterialDecision, ...]
    block_labels: tuple[BlockReviewLabel, ...]
    artifacts: tuple[ReportArtifactReference, ...]
    file_agent_receipts: tuple[FileAgentRunReceipt, ...]
    trace_references: tuple[InternalTraceReference, ...]
    mapping_plan: FrozenMappingPlan
    customer_commentary: CustomerCommentaryPackage
    export_receipt: InternalExportReceipt
    package_fingerprint: str = Field(pattern=SHA256_PATTERN)


def _fingerprint_payload(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()



# 未作为企业事实采用的资料，按稳定处置 code 给客户原因；模型文本（relevance_reason / decision.reason）不进入。
type MaterialNotAdoptedCode = Literal["not_relevant", "attention_items", "no_supporting_content"]


def _material_not_adopted_code(dossier: FileDossier) -> MaterialNotAdoptedCode:
    """一份已读取、相关范围在本次报告内、却没有被任何块采用的资料，其客户可读原因。"""

    if dossier.relevance == "not_relevant":
        return "not_relevant"
    if dossier.attention_items:
        return "attention_items"
    return "no_supporting_content"


def _customer_overview(source: ReportReviewSource, texts: DeliveryTexts) -> str:
    words = texts.overview
    if not source.materials:
        return words.no_materials
    dossier_by_material_id = {
        material.material_id: dossier
        for dossier in source.dossiers
        for material in dossier.materials
    }
    dossier_by_source_id = {
        dossier.source_revision.source_id: dossier for dossier in source.dossiers
    }
    used = {
        dossier_by_material_id[material_id].source_revision.source_id
        for decision in source.block_decisions
        for material_id in decision.material_ids
    }
    # 适用范围全在本次报告之外的资料单独说明：它不是「读了但没采用」，而是本次报告不覆盖。
    outside_scope = {
        dossier.source_revision.source_id
        for dossier in source.dossiers
        if dossier.dossier_id in source.outside_scope_dossier_ids()
    }
    adopted = [item.filename for item in source.materials if item.source_revision.source_id in used]
    outside = [
        item.filename
        for item in source.materials
        if item.source_revision.source_id in outside_scope
    ]
    not_adopted_by_code: dict[str, list[str]] = {}
    for item in source.materials:
        source_id = item.source_revision.source_id
        if source_id in used or source_id in outside_scope:
            continue
        dossier = dossier_by_source_id.get(source_id)
        if dossier is None:
            # 尚无 FileDossier（识别未完成）的资料不在本 revision 的事实来源之内，不下结论。
            continue
        not_adopted_by_code.setdefault(_material_not_adopted_code(dossier), []).append(item.filename)
    if adopted:
        text = words.materials_adopted
        text += words.adopted_list_template.format(names=words.adopted_name_separator.join(adopted))
    else:
        text = words.materials_read_not_adopted
    if outside:
        text += words.file_group_template.format(
            names=words.file_name_separator.join(outside),
            explanation=source.outside_scope_material_notice,
        )
    for code in ("attention_items", "no_supporting_content", "not_relevant"):
        names = not_adopted_by_code.get(code)
        if names:
            text += words.file_group_template.format(
                names=words.file_name_separator.join(names),
                explanation=words.not_adopted[code] + "。",
            )
    return text


def _blocks_by_id(report: Report) -> dict[str, Block]:
    """展开报告树，按 block id 建索引；批注需要据此解析该单元消费了哪些指标。"""

    index: dict[str, Block] = {}

    def walk(sections) -> None:
        for section in sections or ():
            for block in section.blocks or ():
                index[block.id] = block
            walk(section.children)

    walk(report.sections)
    return index


def _section_keys_by_block_id(report: Report) -> dict[str, frozenset[str]]:
    """每个 block 所在的全部祖先章节 key；批注覆盖政策按章节身份（而非标题文字）判定。"""

    index: dict[str, frozenset[str]] = {}

    def walk(sections, ancestors: tuple[str, ...]) -> None:
        for section in sections or ():
            path = (*ancestors, section.key)
            for block in section.blocks or ():
                index[block.id] = frozenset(path)
            walk(section.children, path)

    walk(report.sections, ())
    return index


# 批注覆盖政策：批注只出现在「系统做过判断」的单元上——模型撰写的正文，
# 以及需要交代出处的图片（素材图、指标摘要图、评估矩阵图）。模板固定文本与用户填写值的确定性投影
# 没有可说明的依据，逐段批注只会淹没真正需要复核的内容。
# 下列章节的正文单元整体不批注（图片单元仍按图片规则交代出处）：
# - about_report「关于本报告」：全部为模板文本与填写字段的确定性投影；
# - company_intro「关于公司」：模型只是把用户自述的公司简介整合改写，来源唯一且用户自知，
#   逐段标注「已采用资料：公司简介」没有复核价值。
COMMENTARY_EXEMPT_SECTION_KEYS: frozenset[str] = frozenset({"about_report", "company_intro"})


def _unit_label(unit_kind: str, texts: DeliveryTexts) -> str:
    """批注开头对本单元的称呼：段落／列表项／表格。"""

    labels = texts.unit_labels
    return {"paragraph": labels.paragraph, "list": labels.list, "table": labels.table}.get(
        unit_kind, labels.other
    )


def consumed_metrics(
    block: Block | None,
    report: Report,
    definition: "CompiledReportDefinition | None",
) -> tuple[CustomerCommentaryMetric, ...]:
    """该块实际消费、且用户确有填写值的定量指标（名称 + 数值 + 单位），完整不截断。

    经编译定义解析 selector——与生成侧 ``build_model_context`` 同一个 ``generation_evidence_keys``
    入口，因此批注声明的依据与模型当时实际看到的指标严格一致。``report_section`` 选择器必须靠
    definition 才能解析（无指标目录的议题会在无 definition 时抛错）。

    只认「已填写」：块声明消费的指标目录可能大部分为空，未填写的指标不得出现在批注里。
    显示名取 ``quantitative_metric_display_label``，不暴露 schema key。
    """

    if block is None or block.generation is None:
        return ()
    try:
        _intake_keys, metric_keys = generation_evidence_keys(
            block, report, report, definition
        )
    except (ValueError, KeyError):
        # 选择器无法解析不是批注的职责（批注宁可少说也不能错说），退回无指标依据。
        return ()
    catalog = quantitative_metrics_by_key(knowledge_package_of(report))
    metrics: list[CustomerCommentaryMetric] = []
    seen: set[str] = set()
    for key in metric_keys:
        value = quantitative_metric_value(report, key)
        if value is None:
            continue
        metric = catalog.get(key)
        if metric is None:
            continue
        name = quantitative_metric_display_label(metric)
        if name in seen:
            continue
        seen.add(name)
        unit = (metric.unit or "").strip() or None
        metrics.append(
            CustomerCommentaryMetric(metric_name=name, value=value, unit=unit)
        )
    return tuple(metrics)


def block_evidence_basis(
    block: Block,
    decision: BlockMaterialDecision | None,
    *,
    has_sources: bool,
    has_metrics: bool,
) -> tuple[ProvenanceBasis, ...]:
    """Single owner of the "why does this block read the way it does" rule.

    Shared by the customer commentary (review Word comments) and the block provenance
    projection so the two surfaces never disagree about a block's basis.
    """

    image = block.image
    if block.type == "image" and image is not None:
        if image.layoutAssetIds:
            return ("uploaded_layout_image",)
        if image.derivedVisualization is not None:
            return ("quantitative_metric", "deterministic_report_projection")
        return ("deterministic_report_projection",)
    if block.id == CERTIFICATE_TABLE_BLOCK_ID:
        return ("uploaded_layout_image",)
    if block.source != "ai":
        return ("deterministic_report_projection",)
    if has_sources:
        if has_metrics:
            return ("validated_material", "quantitative_metric", "structured_input")
        return ("validated_material", "structured_input")
    if decision is not None and decision.disposition == "needs_attention":
        return ("structured_input", "industry_disclosure_context")
    if has_metrics:
        return ("quantitative_metric", "structured_input")
    return ("structured_input", "industry_disclosure_context")


def _derived_metric_figure_entry(
    unit, block: Block, report: Report, texts: DeliveryTexts
) -> CustomerCommentaryEntry | None:
    """指标摘要图：逐条列出图中实际呈现的指标与填写值；没有任何已填写指标时该图不会渲染。"""

    spec = block.image.derivedVisualization
    catalog = quantitative_metrics_by_key(knowledge_package_of(report))
    metrics: list[CustomerCommentaryMetric] = []
    seen: set[str] = set()
    for key in spec.metricKeys:
        value = quantitative_metric_value(report, key)
        metric = catalog.get(key)
        if value is None or metric is None:
            continue
        name = quantitative_metric_display_label(metric)
        if name in seen:
            continue
        seen.add(name)
        metrics.append(
            CustomerCommentaryMetric(
                metric_name=name, value=value, unit=(metric.unit or "").strip() or None
            )
        )
    if not metrics:
        return None
    return CustomerCommentaryEntry(
        anchor_id=unit.anchor_id,
        unit_kind="image",
        explanation=texts.explanations.derived_metric_figure,
        basis=("quantitative_metric", "deterministic_report_projection"),
        metrics=tuple(metrics),
    )


def _assessment_figure_entry(unit, texts: DeliveryTexts) -> CustomerCommentaryEntry:
    """评估结果派生的图（双重重要性矩阵）：说明其由用户完成的评估确定性绘制。"""

    return CustomerCommentaryEntry(
        anchor_id=unit.anchor_id,
        unit_kind="image",
        explanation=texts.explanations.assessment_matrix,
        basis=("deterministic_report_projection",),
    )


def _layout_image_entry(
    unit,
    block: Block,
    images_by_block: dict[str, list[LayoutImageReviewInput]],
    texts: DeliveryTexts,
) -> CustomerCommentaryEntry:
    """素材图片块：逐幅列出上传文件名、用户说明与放置依据（识别类别稳定 code → 中文）。"""

    images_by_asset = {
        item.asset_id: item for item in images_by_block.get(block.id, ())
    }
    images: list[CustomerCommentaryImage] = []
    for asset_id in block.image.layoutAssetIds or ():
        item = images_by_asset.get(asset_id)
        if item is None:
            # 资产在放置与导出之间被移出；与渲染器同样跳过，不为它编造来源。
            continue
        images.append(
            CustomerCommentaryImage(
                material_name=item.material_name,
                user_description=item.user_description.strip() or None,
                category_label=(
                    texts.layout_image_categories.get(item.category)
                    if item.category
                    else None
                ),
                placement_scope_title=item.placement_scope_title,
            )
        )
    return CustomerCommentaryEntry(
        anchor_id=unit.anchor_id,
        unit_kind="image",
        explanation=texts.explanations.layout_image,
        basis=("uploaded_layout_image",),
        images=tuple(images),
    )


def build_customer_commentary_package(
    source: ReportReviewSource,
    render_plan: DocumentRenderPlan,
) -> CustomerCommentaryPackage:
    """从冻结谱系和最终可见 render plan 派生客户批注，不读取 Word 文本。"""

    materials_by_source = {item.source_revision.source_id: item for item in source.materials}
    dossier_by_material_id = {
        material.material_id: dossier
        for dossier in source.dossiers
        for material in dossier.materials
    }
    decisions_by_block = {item.block_id: item for item in source.block_decisions}
    images_by_block: dict[str, list[LayoutImageReviewInput]] = {}
    for item in source.layout_images:
        images_by_block.setdefault(item.block_id, []).append(item)
    # 指标值与块的消费声明都在冻结的 render plan report 里，无需另建 block→metric 冻结映射；
    # selector 经生成侧同一个编译定义解析，批注声明的依据与模型实际看到的指标一致。
    plan_report = render_plan.report
    texts = load_format_profile(knowledge_package_of(plan_report)).delivery_texts
    blocks_by_id = _blocks_by_id(plan_report)
    section_keys_by_block = _section_keys_by_block_id(plan_report)
    try:
        compiled_definition = load_compiled_report_definition(knowledge_package_of(plan_report))
    except Exception:  # noqa: BLE001 — 合同不可用时批注降级为不声明指标，不阻断交付
        compiled_definition = None
    entries: list[CustomerCommentaryEntry] = []
    for unit in render_plan.units:
        unit_block = blocks_by_id.get(unit.block_id)
        if unit_block is None:
            raise ValueError(f"渲染计划引用了报告中不存在的块：{unit.block_id}")
        unit_image = unit_block.image
        if unit.kind == "image" and unit_image is not None:
            # 图片单元的出处是领域事实（上传文件 / 生成期来源记录 / 填写的指标 / 评估结果），
            # 每幅实际渲染的图都交代出处，不走资料决定的通用措辞；章节豁免不适用于图片。
            if unit_image.layoutAssetIds:
                entries.append(_layout_image_entry(unit, unit_block, images_by_block, texts))
            elif unit_image.derivedVisualization is not None:
                derived = _derived_metric_figure_entry(unit, unit_block, plan_report, texts)
                if derived is not None:
                    entries.append(derived)
            elif unit_block.source == "assessment":
                entries.append(_assessment_figure_entry(unit, texts))
            # 其余图片单元（占位文字）是确定性投影，没有可说明的依据。
            continue
        if unit_block.id == CERTIFICATE_TABLE_BLOCK_ID:
            # 证书表虽声明 source=user_input，但表里的字来自模型对证书图片的识别，
            # 不是用户填写值的确定性投影——缺了批注，审阅稿会出现一张无出处的表，
            # 而它恰恰是最该被核对的一类内容（机构名、认证范围都可能读错）。
            entries.append(
                CustomerCommentaryEntry(
                    anchor_id=unit.anchor_id,
                    unit_kind=unit.kind,
                    basis=("uploaded_layout_image",),
                    explanation=texts.explanations.certificate_table,
                )
            )
            continue
        if unit_block.source != "ai":
            # 模板固定文本与用户填写值的确定性投影：没有系统判断，不批注。
            continue
        if section_keys_by_block.get(unit.block_id, frozenset()) & COMMENTARY_EXEMPT_SECTION_KEYS:
            continue
        label = _unit_label(unit.kind, texts)
        decision = decisions_by_block.get(unit.block_id)
        selected_materials = (
            tuple(
                dossier_by_material_id[material_id]
                for material_id in decision.material_ids
            )
            if decision is not None
            else ()
        )
        sources: list[CustomerCommentarySource] = []
        seen_source_names: set[str] = set()
        for dossier in selected_materials:
            material = materials_by_source[dossier.source_revision.source_id]
            if material.filename not in seen_source_names:
                sources.append(
                    CustomerCommentarySource(
                        material_name=material.filename,
                    )
                )
                seen_source_names.add(material.filename)
        # 该单元实际消费且用户已填写的定量指标：正文里的数值来自这里，批注必须如实说明，
        # 否则同一个指标值在表/图被说成「结构化数据投影」、在段落却被说成「未使用企业具体资料」。
        metrics = consumed_metrics(
            blocks_by_id.get(unit.block_id), plan_report, compiled_definition
        )
        words = texts.explanations
        basis = block_evidence_basis(
            unit_block,
            decision,
            has_sources=bool(selected_materials),
            has_metrics=bool(metrics),
        )
        if "validated_material" in basis:
            explanation = (
                words.from_materials_and_metrics.format(label=label)
                if "quantitative_metric" in basis
                else words.from_materials.format(label=label)
            )
        elif decision is not None and decision.disposition == "needs_attention":
            explanation = words.needs_attention.format(label=label)
        elif "quantitative_metric" in basis:
            explanation = words.from_metrics.format(label=label)
        else:
            explanation = words.without_materials.format(label=label)
        notes: tuple[str, ...] = ()
        if decision is not None and decision.disposition == "needs_attention":
            notes = (texts.reading_notes.needs_attention,)
        elif any(dossier.attention_items for dossier in source.dossiers) and selected_materials:
            notes = (texts.reading_notes.attention_items_present,)
        entries.append(
            CustomerCommentaryEntry(
                anchor_id=unit.anchor_id,
                unit_kind=unit.kind,
                explanation=explanation,
                basis=basis,
                sources=tuple(sources),
                # 只在批注确实声明指标依据时列出，避免表/图等确定性投影重复罗列。
                metrics=metrics if "quantitative_metric" in basis else (),
                reading_notes=notes,
            )
        )
    anchor_ids = [entry.anchor_id for entry in entries]
    if len(anchor_ids) != len(set(anchor_ids)) or not set(anchor_ids) <= render_plan.unit_anchor_ids:
        raise ValueError("客户批注只能锚定最终可见内容单元，且不得重复")
    plan_fingerprint = _fingerprint_payload(
        {
            "units": [
                {"anchor": item.anchor_id, "block": item.block_id, "kind": item.kind, "text": item.text}
                for item in render_plan.units
            ],
        }
    )
    payload: dict[str, object] = {
        "report_title": source.report_title,
        "report_revision": source.report_revision.revision,
        "generated_at": source.report_revision.created_at.isoformat(),
        "render_plan_fingerprint": plan_fingerprint,
        "overview": _customer_overview(source, texts),
        "entries": [item.model_dump(mode="json") for item in entries],
    }
    return CustomerCommentaryPackage(
        **payload,
        package_fingerprint=_fingerprint_payload(payload),
    )


def build_material_processing_notice(
    source: ReportReviewSource, *, texts: DeliveryTexts
) -> MaterialProcessingNotice | None:
    """从冻结谱系派生审阅稿前置说明页；无须留意事项时返回 None（不出页）。

    与 ``build_customer_commentary_package`` 读同一份 ``source.dossiers``，因此说明页与正文批注
    必然同源；条目文本原样取自 ``AttentionItem``，与资料处理页逐字一致，不在此重新措辞。
    """
    materials_by_source = {
        item.source_revision.source_id: item for item in source.materials
    }
    files: list[MaterialProcessingNoticeFile] = []
    for dossier in source.dossiers:
        if not dossier.attention_items:
            continue
        material = materials_by_source.get(dossier.source_revision.source_id)
        if material is None:
            raise ValueError("须留意事项引用了当前资料集之外的来源")
        files.append(
            MaterialProcessingNoticeFile(
                material_name=material.filename,
                items=tuple(
                    MaterialProcessingNoticeItem(
                        message=item.message,
                        next_action=item.next_action,
                    )
                    for item in dossier.attention_items
                ),
            )
        )
    if not files:
        return None
    return MaterialProcessingNotice(
        heading=texts.material_notice.heading,
        lead=texts.material_notice.lead,
        files_heading=texts.material_notice.files_heading,
        files_lead=texts.material_notice.files_lead,
        files=tuple(files),
    )


def render_customer_comment_texts(
    package: CustomerCommentaryPackage, texts: DeliveryTexts
) -> dict[str, str]:
    """把 typed 客户合同渲染为 Word 批注正文；不输出 Agent/内部字段。"""

    words = texts.comment_lines
    rendered: dict[str, str] = {}
    for entry in package.entries:
        lines = [entry.explanation]
        if entry.sources:
            # 说明句已以冒号引出资料清单，直接逐条列文件名。
            lines.extend(words.source_item.format(name=source.material_name) for source in entry.sources)
        for image in entry.images:
            line = words.image_item.format(name=image.material_name)
            if image.user_description:
                line += words.image_user_description.format(description=image.user_description)
            lines.append(line)
            lines.append(
                words.image_category_placement.format(
                    category=image.category_label, scope=image.placement_scope_title
                )
                if image.category_label
                else words.image_placement.format(scope=image.placement_scope_title)
            )
        if entry.metrics:
            # 完整列出、不截断：客户逐条校对正文数值，也据此核算正文中的派生值。
            # 图片单元的说明句已引出指标清单，不再加小标题。
            if entry.unit_kind != "image":
                lines.append(words.metrics_heading)
            lines.extend(
                words.metric_item.format(
                    name=metric.metric_name, value=metric.value, unit=metric.unit or ""
                )
                for metric in entry.metrics
            )
        lines.extend(entry.reading_notes)
        rendered[entry.anchor_id] = "\n".join(lines)
    return rendered


def render_customer_cover_comment(package: CustomerCommentaryPackage, texts: DeliveryTexts) -> str:
    """将全报告说明投影到封面报告主体名称，避免干扰正文第一段。"""

    return texts.comment_lines.cover_comment.format(overview=package.overview)


def build_internal_audit_package(
    source: ReportReviewSource,
    *,
    customer_commentary: CustomerCommentaryPackage,
    export_receipt: InternalExportReceipt,
) -> InternalAuditPackage:
    """保留完整 typed lineage 与 trace 引用，且不把运行正文复制进审计包。"""

    payload: dict[str, object] = {
        "report_title": source.report_title,
        "report_revision": source.report_revision.model_dump(mode="json"),
        "materials": [item.model_dump(mode="json") for item in source.materials],
        "dossiers": [item.model_dump(mode="json") for item in source.dossiers],
        "block_decisions": [
            item.model_dump(mode="json") for item in source.block_decisions
        ],
        "block_labels": [
            item.model_dump(mode="json") for item in source.block_labels
        ],
        "artifacts": [
            item.model_dump(mode="json") for item in source.artifacts
        ],
        "file_agent_receipts": [
            item.model_dump(mode="json")
            for item in source.file_agent_receipts
        ],
        "trace_references": [
            item.model_dump(mode="json") for item in source.trace_references
        ],
        "mapping_plan": source.mapping_plan.model_dump(mode="json"),
        "customer_commentary": customer_commentary.model_dump(mode="json"),
        "export_receipt": export_receipt.model_dump(mode="json"),
    }
    return InternalAuditPackage(
        **payload,
        package_fingerprint=_fingerprint_payload(payload),
    )


def _bullet_text(value: str) -> str:
    return value.replace("\n", " ").strip()


def render_internal_audit_markdown(package: InternalAuditPackage) -> str:
    """生成人员可读的内部索引；完整机器合同留在同目录 JSON。"""

    lines = [
        f"# {package.report_title}内部审计索引",
        "",
        f"- Report ID：{package.report_revision.report_id}",
        f"- Report revision：{package.report_revision.revision}",
        f"- Revision fingerprint：{package.report_revision.content_fingerprint}",
        f"- Package fingerprint：{package.package_fingerprint}",
        "",
        "## 资料与 FileDossier",
        "",
    ]
    dossiers_by_source = {
        item.source_revision.source_id: item for item in package.dossiers
    }
    for material in package.materials:
        dossier = dossiers_by_source.get(material.source_revision.source_id)
        lines.extend(
            [
                f"### {material.filename}",
                "",
                f"- Source ID：{material.source_revision.source_id}",
                f"- Declaration revision：{material.declaration.revision}",
                (
                    f"- Dossier fingerprint：{dossier.dossier_fingerprint}"
                    if dossier is not None
                    else "- Dossier：无"
                ),
            ]
        )
        if dossier is not None:
            lines.extend(
                [
                    f"- 文件相关性：{dossier.relevance}",
                    f"- 相关性理由：{_bullet_text(dossier.relevance_reason)}",
                ]
            )
            for file_material in dossier.materials:
                lines.extend(
                    [
                        f"- FileMaterial {file_material.material_id}："
                        f"scopes={','.join(file_material.applicable_scope_ids)}",
                        _bullet_text(file_material.content_markdown),
                    ]
                )
        lines.append("")

    lines.extend(["## FileMaterial 与 Block 决定", ""])
    materials_by_id = {
        material.material_id: material
        for dossier in package.dossiers
        for material in dossier.materials
    }
    for material in materials_by_id.values():
        lines.append(
            f"- Material {material.material_id}：{_bullet_text(material.content_markdown)}"
        )
    labels_by_block = {
        item.block_id: item.label for item in package.block_labels
    }
    for decision in package.block_decisions:
        lines.append(
            f"- Block {decision.block_id}（{labels_by_block[decision.block_id]}）："
            f"{decision.disposition}；Materials="
            f"{','.join(str(item) for item in decision.material_ids) or 'none'}"
        )

    lines.extend(["", "## 冻结 Mapping 计划", ""])
    if not package.mapping_plan.scopes:
        lines.append("- 本次没有需要执行 Mapping 的文件范围。")
    for scope in package.mapping_plan.scopes:
        lines.append(
            f"- Scope {scope.scope_id}：dossiers={','.join(str(item) for item in scope.dossier_ids)}；"
            f"blocks={','.join(scope.block_ids)}"
        )

    lines.extend(["", "## File Agent 运行收据", ""])
    for receipt in package.file_agent_receipts:
        lines.append(
            f"- Run {receipt.run_id}：{receipt.status}；"
            f"source={receipt.source_revision.source_id}；"
            f"trace={receipt.observation_run_id or 'none'}"
        )

    lines.extend(["", "## Trace 引用", ""])
    for trace in package.trace_references:
        location = trace.storage_ref or f"（不可用：{trace.unavailable_reason}）"
        lines.append(
            f"- {trace.stage} / {trace.trace_id} / {trace.contract} / {location}"
        )

    lines.extend(["", "## 客户批注投影", ""])
    lines.append(
        f"- 批注内容单元：{len(package.customer_commentary.entries)}；"
        f"render plan={package.customer_commentary.render_plan_fingerprint}"
    )

    lines.extend(["", "## Word 导出凭证", ""])
    lines.append(
        f"- 目录已最终化：{package.export_receipt.toc_finalized}；"
        f"批注单元：{package.export_receipt.comment_entry_count}；"
        f"普通 Word={package.export_receipt.normal_word_fingerprint}；"
        f"客户批注 Word={package.export_receipt.customer_word_fingerprint}"
    )

    lines.extend(["", "## 产物谱系", ""])
    for artifact in package.artifacts:
        lines.append(
            f"- {artifact.kind}：{artifact.filename}；"
            f"revision={artifact.report_revision_id}；"
            f"fingerprint={artifact.content_fingerprint}；"
            f"storage={artifact.storage_ref}"
        )
    return "\n".join(lines).rstrip() + "\n"




def build_standards_compliance_notice(
    coverage: DisclosureCoverageReport,
    *,
    package: KnowledgePackage,
) -> StandardsComplianceNotice:
    """把确定性覆盖判定投影为审阅稿说明页；措辞来自包格式 profile，标题来自议题注册表。"""
    from sustainability_desk.contract.topic_registry import all_report_sections

    words = load_format_profile(package).delivery_texts.standards_notice
    section_titles = {section.id: section.title for section in all_report_sections(package)}
    groups: list[StandardsComplianceNoticeGroup] = []

    attention: list[StandardsComplianceNoticeItem] = [
        StandardsComplianceNoticeItem(
            scope_label=section_titles.get(finding.reportSectionId, finding.reportSectionId),
            message=(
                words.omission_finding_template.format(title=finding.requirementTitle)
                if finding.requirementTitle
                else words.omission_finding_untitled
            ),
            next_action=words.omission_next_action,
        )
        for finding in coverage.attention_findings
    ]
    attention.extend(
        StandardsComplianceNoticeItem(
            scope_label=words.report_scope_label,
            message=obligation.userFacingNote
            or words.obligation_unmet_template.format(title=obligation.obligationTitle),
            next_action=words.obligation_next_action,
        )
        for obligation in coverage.attention_obligations
    )
    if attention:
        groups.append(
            StandardsComplianceNoticeGroup(
                heading=words.attention_heading,
                lead=words.attention_lead,
                items=tuple(attention),
            )
        )

    informational: list[StandardsComplianceNoticeItem] = []
    seen_rationales: set[tuple[str, str]] = set()
    for finding in coverage.findings:
        if finding.code not in ("requirement_excluded_by_design", "requirement_conditional_not_triggered"):
            continue
        rationale = words.exclusion_rationales.get(finding.exclusionRationaleCode or "")
        if rationale is None:
            continue
        scope_label = section_titles.get(finding.reportSectionId, finding.reportSectionId)
        if (scope_label, rationale) in seen_rationales:
            continue
        seen_rationales.add((scope_label, rationale))
        informational.append(
            StandardsComplianceNoticeItem(scope_label=scope_label, message=rationale)
        )
    pending_topics = sorted(
        {
            section_titles.get(finding.reportSectionId, finding.reportSectionId)
            for finding in coverage.findings
            if finding.code == "topic_requirements_pending"
        }
    )
    informational.extend(
        StandardsComplianceNoticeItem(scope_label=topic, message=words.pending_topic_message)
        for topic in pending_topics
    )
    if informational:
        groups.append(
            StandardsComplianceNoticeGroup(
                heading=words.exclusion_heading,
                lead=words.exclusion_lead,
                items=tuple(informational),
            )
        )

    return StandardsComplianceNotice(
        heading=words.heading,
        lead=words.lead,
        summary=words.summary_template.format(count=coverage.covered_requirement_count),
        groups=tuple(groups),
    )
