# ABOUTME: 定义单文件理解 Agent 的任务、候选相关性、只读工具、Dossier 与运行收据合同。
# ABOUTME: FileDossier 只追溯到冻结文件版本；实际报告采用由下游 Mapping Agent 决定。
# ABOUTME(en): Defines the single-file Agent contract: task, candidate relevance, read-only tools, Dossier, receipt.
# ABOUTME(en): A FileDossier traces only to the frozen file revision; adoption is decided by the Mapping Agent.
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.models import MaterialKind, UserFileDeclaration

SHA256_PATTERN = r"^[0-9a-f]{64}$"
type FileAgentToolName = Literal["convert_file", "read_file"]
type FileAgentRunStatus = Literal["completed", "suspended", "failed"]
type FileRelevance = Literal["relevant", "not_relevant"]


class FileAgentContractModel(BaseModel):
    """文件 Agent 跨层合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FileAgentProductTask(FileAgentContractModel):
    """文件理解所需的最小产品任务。"""

    objective: Literal[
        "判断当前文件是否应进入 ESG 报告资料映射候选池，并形成可供报告生成使用的资料内容"
    ] = "判断当前文件是否应进入 ESG 报告资料映射候选池，并形成可供报告生成使用的资料内容"
    report_id: UUID
    report_subject_name: str | None = Field(default=None, min_length=1, max_length=300)
    report_period_label: str | None = Field(default=None, min_length=1, max_length=100)
    scope_label: str = Field(default="轻量版完整路径 ESG 报告", min_length=1, max_length=100)
    material_scopes: tuple["FileMaterialScope", ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_report_coverage(self) -> "FileAgentProductTask":
        if not any(scope.within_report_scope for scope in self.material_scopes):
            raise ValueError("产品任务至少要有一个属于本次报告范围的 scope")
        return self

    def covered_scopes(self) -> tuple["FileMaterialScope", ...]:
        """本次报告实际覆盖的 scope；目录中其余 scope 只用于如实记录资料适用范围。"""

        return tuple(scope for scope in self.material_scopes if scope.within_report_scope)


class FileMaterialScope(FileAgentContractModel):
    """File Agent 可选择的既有报告 Mapping scope；不是第二套目录。

    目录按完整报告定义给出，`within_report_scope` 标记该 scope 是否进入本次报告
    （受权益范围或重要性评估收窄）。范围外 scope 仍可被资料选择，使资料的真实适用
    范围得以记录而不是被判为不相关；Mapping 只对范围内 scope 建任务。默认 True 使
    收窄前持久化的运行上下文保持原语义（当时目录里的每个 scope 都在范围内）。
    """

    alias: str = Field(min_length=1, max_length=100)
    scope_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    kind: Literal["report_area", "esg_topic"]
    within_report_scope: bool = True


class FileSourceRevision(FileAgentContractModel):
    """本次运行冻结的原文件与用户声明版本。"""

    source_id: UUID
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    declaration_revision: int = Field(ge=1)


class FileAgentContext(FileAgentContractModel):
    """模型可见的单文件任务边界。"""

    source_revision: FileSourceRevision
    filename: str = Field(min_length=1, max_length=500)
    material_kind: MaterialKind
    size_bytes: int = Field(gt=0)
    declaration: UserFileDeclaration
    product_task: FileAgentProductTask
    available_tools: tuple[FileAgentToolName, ...]


class AttentionItemDraft(FileAgentContractModel):
    """模型提出的一项用户可理解的待确认事项。"""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2_000)
    next_action: str = Field(min_length=1, max_length=1_000)


class AttentionItem(AttentionItemDraft):
    """绑定到当前文件版本的待确认事项。"""

    attention_id: UUID = Field(default_factory=uuid4)


class FileMaterialDraft(FileAgentContractModel):
    """模型提交的单文件资料单元；scope alias 只在本次 File Agent 运行有效。"""

    applicable_scope_aliases: tuple[str, ...] = Field(min_length=1)
    content_markdown: str = Field(min_length=1, max_length=12_000)

    @model_validator(mode="after")
    def _validate_scope_aliases(self) -> "FileMaterialDraft":
        if len(self.applicable_scope_aliases) != len(set(self.applicable_scope_aliases)):
            raise ValueError("同一资料单元不得重复关联 scope")
        return self


class FileMaterial(FileAgentContractModel):
    """冻结文件中可直接进入报告生成链的资料内容。"""

    material_id: UUID
    applicable_scope_ids: tuple[str, ...] = Field(min_length=1)
    content_markdown: str = Field(min_length=1, max_length=12_000)

    @model_validator(mode="after")
    def _validate_scope_ids(self) -> "FileMaterial":
        if len(self.applicable_scope_ids) != len(set(self.applicable_scope_ids)):
            raise ValueError("同一资料单元不得重复关联 scope")
        return self


class FileDossierDraft(FileAgentContractModel):
    """Harness 汇总语义工具操作后的文件级候选资料判断。"""

    contract: Literal["sustainability_desk.file_dossier_draft.v7"] = (
        "sustainability_desk.file_dossier_draft.v7"
    )
    relevance: FileRelevance
    relevance_reason: str = Field(min_length=1, max_length=2_000)
    materials: tuple[FileMaterialDraft, ...] = ()
    attention_items: tuple[AttentionItemDraft, ...] = ()

    @model_validator(mode="after")
    def _validate_relevance_shape(self) -> "FileDossierDraft":
        if self.relevance == "relevant" and not self.materials:
            raise ValueError("相关资料必须至少提供一条可用于报告的资料内容")
        if self.relevance == "not_relevant" and self.materials:
            raise ValueError("不相关资料不得提供可用于报告的资料内容")
        return self


class FileDossier(FileAgentContractModel):
    """一份冻结文件的候选相关性与高信号语义理解。"""

    contract: Literal[
        "sustainability_desk.file_dossier.v7",
    ] = "sustainability_desk.file_dossier.v7"
    dossier_id: UUID = Field(default_factory=uuid4)
    source_revision: FileSourceRevision
    relevance: FileRelevance
    relevance_reason: str = Field(min_length=1, max_length=2_000)
    materials: tuple[FileMaterial, ...] = ()
    attention_items: tuple[AttentionItem, ...] = ()
    dossier_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_dossier(self) -> "FileDossier":
        FileDossierDraft(
            relevance=self.relevance,
            relevance_reason=self.relevance_reason,
            materials=tuple(
                FileMaterialDraft(
                    applicable_scope_aliases=material.applicable_scope_ids,
                    content_markdown=material.content_markdown,
                )
                for material in self.materials
            ),
            attention_items=tuple(
                AttentionItemDraft(
                    code=item.code,
                    message=item.message,
                    next_action=item.next_action,
                )
                for item in self.attention_items
            ),
        )
        expected = file_dossier_fingerprint(
            source_revision=self.source_revision,
            relevance=self.relevance,
            relevance_reason=self.relevance_reason,
            materials=self.materials,
            attention_items=self.attention_items,
        )
        if self.dossier_fingerprint != expected:
            raise ValueError("FileDossier 内容指纹无效")
        return self

    @property
    def candidate_for_mapping(self) -> bool:
        """相关资料才进入 Mapping；这是候选准入而不是最终采用。"""

        return self.relevance == "relevant"


def file_dossier_fingerprint(
    *,
    source_revision: FileSourceRevision,
    relevance: FileRelevance,
    relevance_reason: str,
    materials: tuple[FileMaterial, ...],
    attention_items: tuple[AttentionItem, ...],
) -> str:
    """生成不依赖运行身份的 FileDossier 内容指纹。"""

    payload = {
        "sourceRevision": source_revision.model_dump(mode="json"),
        "relevance": relevance,
        "relevanceReason": relevance_reason,
        "materials": [item.model_dump(mode="json") for item in materials],
        "attentionItems": [
            {
                "code": item.code,
                "message": item.message,
                "nextAction": item.next_action,
            }
            for item in attention_items
        ],
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class FileAgentToolRequest(FileAgentContractModel):
    """Agent 自主选择的一个只读工具调用。"""

    tool_name: FileAgentToolName
    path: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _validate_arguments(self) -> "FileAgentToolRequest":
        if self.tool_name == "read_file" and self.path is None:
            raise ValueError("read_file 必须指定转换产物路径")
        if self.tool_name == "convert_file" and self.path is not None:
            raise ValueError("convert_file 不接受路径")
        return self


class ConvertedFileEntry(FileAgentContractModel):
    """一个可由 Agent 完整打开的只读 Markdown 产物。"""

    path: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    kind: Literal["document", "sheet"]
    character_count: int = Field(ge=0)


class FileConversionManifest(FileAgentContractModel):
    kind: Literal["conversion_manifest"] = "conversion_manifest"
    files: tuple[ConvertedFileEntry, ...] = Field(min_length=1)
    parser_profile_id: str = Field(min_length=1)
    coverage: Literal[
        "complete_for_declared_capabilities",
        "incomplete_usable",
        "failed",
    ]
    warnings: tuple[str, ...] = ()


class WorkspaceTextFile(FileAgentContractModel):
    """一次完整读取的解析文本。"""

    kind: Literal["workspace_text_file"] = "workspace_text_file"
    path: str = Field(min_length=1, max_length=500)
    content: str
    complete: Literal[True] = True


type FileAgentToolObservation = Annotated[
    FileConversionManifest | WorkspaceTextFile,
    Field(discriminator="kind"),
]


class FileAgentToolReceipt(FileAgentContractModel):
    receipt_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    request: FileAgentToolRequest
    source_revision: FileSourceRevision
    request_fingerprint: str = Field(pattern=SHA256_PATTERN)
    output_fingerprint: str = Field(pattern=SHA256_PATTERN)
    parser_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    parsed_material_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)


class FileAgentTraceEvent(FileAgentContractModel):
    event_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    occurred_at: datetime
    event_type: Literal[
        "context_prepared",
        "tool_completed",
        "dossier_validated",
        "run_suspended",
        "run_completed",
        "run_failed",
    ]
    tool_name: FileAgentToolName | None = None
    receipt_id: UUID | None = None
    detail_code: str = Field(min_length=1, max_length=100)


class FileAgentRunCheckpoint(FileAgentContractModel):
    """可持久化恢复点；工具结果由冻结请求重放。"""

    run_id: UUID
    source_revision: FileSourceRevision
    product_task: FileAgentProductTask
    completed_requests: tuple[FileAgentToolRequest, ...]
    tool_receipts: tuple[FileAgentToolReceipt, ...]
    next_tool_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_replay_chain(self) -> "FileAgentRunCheckpoint":
        if len(self.completed_requests) != len(self.tool_receipts):
            raise ValueError("恢复点工具请求与收据数量不一致")
        if [item.sequence for item in self.tool_receipts] != list(
            range(1, len(self.tool_receipts) + 1)
        ):
            raise ValueError("恢复点工具收据序号不连续")
        if self.next_tool_sequence != len(self.tool_receipts) + 1:
            raise ValueError("恢复点 next_tool_sequence 无效")
        return self


class FileAgentRunReceipt(FileAgentContractModel):
    run_id: UUID
    observation_run_id: str | None = None
    attempt: int = Field(ge=1)
    status: FileAgentRunStatus
    source_revision: FileSourceRevision
    started_at: datetime
    finished_at: datetime
    tool_receipts: tuple[FileAgentToolReceipt, ...]
    trace_events: tuple[FileAgentTraceEvent, ...]
    dossier_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    failure_code: str | None = None


class FileAgentRunResult(FileAgentContractModel):
    status: FileAgentRunStatus
    dossier: FileDossier | None
    checkpoint: FileAgentRunCheckpoint | None
    receipt: FileAgentRunReceipt

    @model_validator(mode="after")
    def _validate_terminal_shape(self) -> "FileAgentRunResult":
        if self.status == "completed":
            if self.dossier is None or self.checkpoint is not None:
                raise ValueError("完成运行必须只返回 FileDossier")
        elif self.status == "suspended":
            if self.dossier is not None or self.checkpoint is None:
                raise ValueError("暂停运行必须只返回恢复点")
        elif self.dossier is not None:
            raise ValueError("失败运行不得返回 FileDossier")
        return self
