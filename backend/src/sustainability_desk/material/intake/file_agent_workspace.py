# ABOUTME: 为单个冻结原文件提供转换与完整读取两项只读能力，并记录可重放工具收据。
# ABOUTME: parser 只由 Agent 工具按需触发；PDF 不进入视觉模型，表格始终作为完整工作表返回。
# ABOUTME(en): Gives one frozen source file two read-only capabilities, conversion and complete reading.
# ABOUTME(en): Parsers fire only on Agent tool demand; PDFs never reach the vision model, tables stay whole sheets.
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid5

from sustainability_desk.material.intake.docx_structure import parse_docx_structure
from sustainability_desk.material.intake.file_agent_contract import (
    AttentionItem,
    ConvertedFileEntry,
    FileAgentContext,
    FileAgentProductTask,
    FileAgentRunCheckpoint,
    FileAgentToolObservation,
    FileAgentToolReceipt,
    FileAgentToolRequest,
    FileConversionManifest,
    FileDossier,
    FileDossierDraft,
    FileMaterial,
    FileSourceRevision,
    WorkspaceTextFile,
    file_dossier_fingerprint,
)
from sustainability_desk.material.intake.models import MaterialKind, UserFileDeclaration
from sustainability_desk.material.intake.parsed_material import (
    ParsedMaterial,
    ParsedPageNode,
    ParsedSheetNode,
    ParsedSheetRowNode,
    ParsedSlideNode,
    ParsedTableNode,
    ParsedTableRowNode,
    ParsedTextNode,
)
from sustainability_desk.material.intake.pdf_structure import parse_pdf_structure
from sustainability_desk.material.intake.pptx_structure import parse_pptx_structure
from sustainability_desk.material.intake.xlsx_structure import parse_xlsx_structure
from sustainability_desk.material.retrieval.chunks import StructuredDataPaginationPolicy
from sustainability_desk.material.retrieval.structured_markdown import (
    build_structured_markdown_projection,
)

AVAILABLE_TOOLS = ("convert_file", "read_file")
SUPPORTED_SUFFIXES: dict[str, MaterialKind] = {
    ".docx": "docx",
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}
WHOLE_OWNER_POLICY = StructuredDataPaginationPolicy(
    policy_id="file-agent-whole-owner@2",
    whole_owner_max_rows=10_000,
    transport_page_max_rows=10_000,
)


class FileAgentWorkspaceError(ValueError):
    """只读工作区合同、来源版本或工具边界失败。"""


def _fingerprint_model(value: object) -> str:
    payload = (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else value
    )
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class FileAgentWorkspace:
    """一个冻结原文件版本对应的单文件只读工作区。"""

    def __init__(self, *, source_bytes: bytes, context: FileAgentContext) -> None:
        self._source_bytes = source_bytes
        self.context = context
        self._parsed_material: ParsedMaterial | None = None
        self._converted_files: dict[str, str] = {}
        self._manifest: FileConversionManifest | None = None
        self._tool_receipts: list[FileAgentToolReceipt] = []
        self._read_paths: set[str] = set()

    @classmethod
    def open(
        cls,
        *,
        source_id: UUID,
        source_path: Path,
        declaration: UserFileDeclaration,
        product_task: FileAgentProductTask,
        declaration_revision: int = 1,
    ) -> "FileAgentWorkspace":
        """冻结当前原文件字节；初始化不调用 parser。"""

        if declaration.role != "semantic_material":
            raise FileAgentWorkspaceError("排版素材不得进入 File Agent 工作区")
        material_kind = SUPPORTED_SUFFIXES.get(source_path.suffix.lower())
        if material_kind is None:
            raise FileAgentWorkspaceError("File Agent 当前只接受 DOCX、PDF、PPTX 和 XLSX")
        source_bytes = source_path.read_bytes()
        if not source_bytes:
            raise FileAgentWorkspaceError("原文件不能为空")
        revision = FileSourceRevision(
            source_id=source_id,
            source_sha256=sha256(source_bytes).hexdigest(),
            declaration_revision=int(
                getattr(declaration, "revision", declaration_revision)
            ),
        )
        return cls(
            source_bytes=source_bytes,
            context=FileAgentContext(
                source_revision=revision,
                filename=source_path.name,
                material_kind=material_kind,
                size_bytes=len(source_bytes),
                declaration=declaration,
                product_task=product_task,
                available_tools=AVAILABLE_TOOLS,
            ),
        )

    @property
    def parsed_material(self) -> ParsedMaterial | None:
        return self._parsed_material

    @property
    def tool_receipts(self) -> tuple[FileAgentToolReceipt, ...]:
        return tuple(self._tool_receipts)

    def execute(self, request: FileAgentToolRequest) -> FileAgentToolObservation:
        """执行一个只读工具并记录输入、输出和 parser 指纹。"""

        observation = self._dispatch(request)
        parsed = self._parsed_material
        self._tool_receipts.append(
            FileAgentToolReceipt(
                sequence=len(self._tool_receipts) + 1,
                request=request,
                source_revision=self.context.source_revision,
                request_fingerprint=_fingerprint_model(request),
                output_fingerprint=_fingerprint_model(observation),
                parser_fingerprint=parsed.parser_fingerprint if parsed else None,
                parsed_material_fingerprint=(
                    parsed.content_fingerprint if parsed else None
                ),
            )
        )
        return observation

    def restore(
        self,
        checkpoint: FileAgentRunCheckpoint,
    ) -> tuple[FileAgentToolObservation, ...]:
        """在相同冻结来源上重放工具请求并核对输出。"""

        if checkpoint.source_revision != self.context.source_revision:
            raise FileAgentWorkspaceError("恢复点与当前冻结来源版本不一致")
        if checkpoint.product_task != self.context.product_task:
            raise FileAgentWorkspaceError("恢复点产品任务与当前运行不一致")
        observations: list[FileAgentToolObservation] = []
        for request, expected in zip(
            checkpoint.completed_requests,
            checkpoint.tool_receipts,
            strict=True,
        ):
            observation = self._dispatch(request)
            if _fingerprint_model(observation) != expected.output_fingerprint:
                raise FileAgentWorkspaceError("恢复重放的工具输出指纹发生变化")
            observations.append(observation)
        self._tool_receipts = list(checkpoint.tool_receipts)
        return tuple(observations)

    def finalize(self, draft: FileDossierDraft) -> FileDossier:
        """校验最小硬边界并把模型输出绑定到当前文件版本。"""

        if self._parsed_material is None or not self._read_paths:
            raise FileAgentWorkspaceError("提交 FileDossier 前必须转换并完整读取至少一个产物")
        scope_id_by_alias = {
            scope.alias: scope.scope_id
            for scope in self.context.product_task.material_scopes
        }
        materials: list[FileMaterial] = []
        for ordinal, material in enumerate(draft.materials, start=1):
            unknown = set(material.applicable_scope_aliases) - set(scope_id_by_alias)
            if unknown:
                raise FileAgentWorkspaceError(
                    f"资料内容超出当前报告范围：{sorted(unknown)}"
                )
            identity = "\n".join(
                (
                    self.context.source_revision.source_sha256,
                    ",".join(material.applicable_scope_aliases),
                    material.content_markdown,
                    str(ordinal),
                )
            )
            materials.append(
                FileMaterial(
                    material_id=uuid5(self.context.source_revision.source_id, identity),
                    applicable_scope_ids=tuple(
                        scope_id_by_alias[alias]
                        for alias in material.applicable_scope_aliases
                    ),
                    content_markdown=material.content_markdown,
                )
            )
        attention_items = tuple(
            AttentionItem(
                attention_id=uuid5(
                    self.context.source_revision.source_id,
                    f"{item.code}\n{item.message}\n{item.next_action}",
                ),
                code=item.code,
                message=item.message,
                next_action=item.next_action,
            )
            for item in draft.attention_items
        )
        fingerprint = file_dossier_fingerprint(
            source_revision=self.context.source_revision,
            relevance=draft.relevance,
            relevance_reason=draft.relevance_reason,
            materials=tuple(materials),
            attention_items=attention_items,
        )
        return FileDossier(
            source_revision=self.context.source_revision,
            relevance=draft.relevance,
            relevance_reason=draft.relevance_reason,
            materials=tuple(materials),
            attention_items=attention_items,
            dossier_fingerprint=fingerprint,
        )

    @staticmethod
    def _node_text(node: object) -> str | None:
        """从已解析的原始节点取得可逐字核验的短摘录来源。"""

        if isinstance(node, ParsedTextNode):
            return node.text
        if isinstance(node, (ParsedTableRowNode, ParsedSheetRowNode)):
            return " | ".join(cell.text for cell in node.cells).strip()
        return None

    def _dispatch(self, request: FileAgentToolRequest) -> FileAgentToolObservation:
        if request.tool_name == "convert_file":
            return self._convert_file()
        if request.tool_name == "read_file":
            assert request.path is not None
            return self._read_file(request.path)
        raise FileAgentWorkspaceError(f"未授权工具：{request.tool_name}")

    def _ensure_parsed(self) -> ParsedMaterial:
        if self._parsed_material is not None:
            return self._parsed_material
        source_id = self.context.source_revision.source_id
        if self.context.material_kind == "docx":
            parsed = parse_docx_structure(
                self._source_bytes,
                source_id=source_id,
                source_label=self.context.filename,
            )
        elif self.context.material_kind == "pdf":
            parsed = parse_pdf_structure(self._source_bytes, source_id=source_id)
        elif self.context.material_kind == "pptx":
            parsed = parse_pptx_structure(
                self._source_bytes,
                source_id=source_id,
                source_label=self.context.filename,
            )
        elif self.context.material_kind == "xlsx":
            parsed = parse_xlsx_structure(
                self._source_bytes,
                source_id=source_id,
                source_label=self.context.filename,
            )
        else:
            raise FileAgentWorkspaceError("当前文件没有获批准的 parser")
        if parsed.source_sha256 != self.context.source_revision.source_sha256:
            raise FileAgentWorkspaceError("parser 返回的原文件版本不一致")
        self._parsed_material = parsed
        return parsed

    def _convert_file(self) -> FileConversionManifest:
        if self._manifest is not None:
            return self._manifest
        parsed = self._ensure_parsed()
        converted: dict[str, str] = {}
        labels: dict[str, str] = {}
        if self.context.material_kind == "xlsx":
            for node in sorted(parsed.nodes, key=lambda item: item.ordinal_path):
                if not isinstance(node, ParsedSheetNode):
                    continue
                projection = build_structured_markdown_projection(
                    parsed,
                    owner_node_id=node.node_id,
                    pagination_policy=WHOLE_OWNER_POLICY,
                )
                path = f"derived/sheets/{len(converted) + 1:02d}.md"
                converted[path] = projection.markdown
                labels[path] = node.label or node.locator.sheet_name
        else:
            parts: list[str] = []
            included_owners: set[UUID] = set()
            pending_slide_marker_index: int | None = None
            for node in sorted(parsed.nodes, key=lambda item: item.ordinal_path):
                if isinstance(node, ParsedSlideNode):
                    if pending_slide_marker_index is not None:
                        parts.insert(
                            pending_slide_marker_index + 1,
                            "（本页为图片内容，未提取文字）",
                        )
                    slide_number = getattr(node.locator, "slide_number", None)
                    if slide_number is not None:
                        parts.append(f"## 第 {slide_number} 页")
                        pending_slide_marker_index = len(parts) - 1
                    else:
                        pending_slide_marker_index = None
                    continue
                if isinstance(node, ParsedPageNode):
                    page = getattr(node.locator, "page", None)
                    if page is not None:
                        parts.append(f"## 第 {page} 页")
                    continue
                if isinstance(node, ParsedTextNode) and node.text.strip():
                    if node.kind == "heading":
                        parts.append(f"{'#' * (node.heading_level or 1)} {node.text.strip()}")
                    elif node.kind == "list_item":
                        parts.append(f"- {node.text.strip()}")
                    elif node.locator.kind == "pptx_notes":
                        parts.append(f"备注：{node.text.strip()}")
                    else:
                        parts.append(node.text.strip())
                    pending_slide_marker_index = None
                elif isinstance(node, ParsedTableNode) and node.node_id not in included_owners:
                    projection = build_structured_markdown_projection(
                        parsed,
                        owner_node_id=node.node_id,
                        pagination_policy=WHOLE_OWNER_POLICY,
                    )
                    parts.append(projection.markdown)
                    included_owners.add(node.node_id)
                    pending_slide_marker_index = None
            if pending_slide_marker_index is not None:
                parts.insert(
                    pending_slide_marker_index + 1,
                    "（本页为图片内容，未提取文字）",
                )
            converted["derived/document.md"] = (
                "\n\n".join(parts) or "（parser 未提取到可读文本）"
            )
            labels["derived/document.md"] = self.context.filename
        if not converted:
            converted["derived/document.md"] = "（parser 未提取到可读文本）"
            labels["derived/document.md"] = self.context.filename
        self._converted_files = converted
        entries = tuple(
            ConvertedFileEntry(
                path=path,
                label=labels[path],
                kind="sheet" if "/sheets/" in path else "document",
                character_count=len(content),
            )
            for path, content in converted.items()
        )
        self._manifest = FileConversionManifest(
            files=entries,
            parser_profile_id=parsed.parser_profile_id,
            coverage=parsed.coverage.disposition,
            warnings=tuple(gap.message for gap in parsed.coverage.gaps),
        )
        return self._manifest

    def _read_file(self, path: str) -> WorkspaceTextFile:
        if self._manifest is None:
            raise FileAgentWorkspaceError("必须先调用 convert_file")
        content = self._converted_files.get(path)
        if content is None:
            raise FileAgentWorkspaceError("路径不属于当前文件的转换产物")
        self._read_paths.add(path)
        return WorkspaceTextFile(
            path=path,
            content=content,
        )
