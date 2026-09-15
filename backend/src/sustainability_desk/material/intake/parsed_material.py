# ABOUTME: 定义结构化 parser 的无截断、可定位、可验证 typed 输出及其稳定身份。
# ABOUTME: 它是 File Agent 可调用的一类工具产物，不是统一前置状态，也不垄断其他工具观察。
# ABOUTME(en): Defines the untruncated, locatable, verifiable typed parser output and its stable identity.
# ABOUTME(en): It is one tool product the File Agent may call, not a prerequisite state, and monopolizes no observation.
from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Literal, TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.parse_coverage import ParseCoverage
from sustainability_desk.material.intake.parsed_material_locators import ParsedNodeLocator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
EMPTY_SHA256 = "0" * 64

type ParsedDocumentKind = Literal["pdf", "docx", "xlsx", "pptx", "image"]
type ParsedMaterialStatus = Literal["complete", "complete_with_gaps", "failed"]
type ParsedTextKind = Literal["heading", "paragraph", "list_item", "text_block"]
type ParsedCellValueKind = Literal[
    "text",
    "number",
    "boolean",
    "date",
    "blank",
    "error",
    "formula",
]
type ParsedMediaExtractionStatus = Literal[
    "not_attempted",
    "complete",
    "failed",
]
type SheetState = Literal["visible", "hidden", "veryHidden"]
type TableRowHeightRule = Literal["auto", "at_least", "exact"]


class ParsedMaterialModel(BaseModel):
    """规范化解析域的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ParsedCell(ParsedMaterialModel):
    """表格单元格的结构化原始值。"""

    column_index: int = Field(ge=1)
    text: str
    value_kind: ParsedCellValueKind = "text"
    cell_reference: str | None = None
    formula: str | None = None
    cached_value: str | int | float | bool | None = None
    native_data_type: str | None = None
    number_format: str | None = None
    merged_anchor: str | None = None
    merged_range: str | None = None
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    hidden_row: bool = False
    hidden_column: bool = False

    @model_validator(mode="after")
    def _validate_formula(self) -> "ParsedCell":
        if self.value_kind == "formula" and not self.formula:
            raise ValueError("公式单元格必须保留公式表达式")
        if self.value_kind != "formula" and self.formula is not None:
            raise ValueError("非公式单元格不得携带公式表达式")
        return self


class ParsedNodeModel(ParsedMaterialModel):
    """所有解析节点共享的身份、树位置和内容指纹。"""

    node_id: UUID
    parent_node_id: UUID | None
    ordinal_path: tuple[int, ...] = Field(min_length=1)
    locator: ParsedNodeLocator
    content_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_ordinal_path(self) -> "ParsedNodeModel":
        if any(part < 1 for part in self.ordinal_path):
            raise ValueError("节点顺序路径只能包含正整数")
        return self


class ParsedDocumentNode(ParsedNodeModel):
    """规范化解析树的唯一根节点。"""

    kind: Literal["document"] = "document"
    label: str | None = None


class ParsedSectionNode(ParsedNodeModel):
    """源文件显式章节容器。"""

    kind: Literal["section"] = "section"
    label: str | None = None


class ParsedPageNode(ParsedNodeModel):
    """PDF 页容器。"""

    kind: Literal["page"] = "page"
    label: str | None = None
    width_points: float = Field(gt=0)
    height_points: float = Field(gt=0)
    rotation_degrees: int
    image_resource_count: int | None = Field(default=None, ge=0)
    form_xobject_count: int | None = Field(default=None, ge=0)
    font_resource_count: int | None = Field(default=None, ge=0)
    annotation_count: int | None = Field(default=None, ge=0)


class ParsedSlideNode(ParsedNodeModel):
    """PPTX 幻灯片容器。"""

    kind: Literal["slide"] = "slide"
    label: str | None = None


def _xlsx_column_name(column_index: int) -> str:
    letters = ""
    remaining = column_index
    while remaining:
        remaining, remainder = divmod(remaining - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xlsx_column_index(column_name: str) -> int:
    index = 0
    for character in column_name:
        index = index * 26 + ord(character) - 64
    return index


class ParsedSheetNode(ParsedNodeModel):
    """XLSX 工作表整体；单元格事实仍由成员行节点唯一持有。"""

    kind: Literal["sheet"] = "sheet"
    label: str | None = None
    sheet_state: SheetState = "visible"
    cell_range: str | None
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)
    row_node_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def _validate_derived_extent(self) -> "ParsedSheetNode":
        if self.row_count != len(self.row_node_ids):
            raise ValueError("工作表行数必须与成员行节点数量一致")
        if self.column_count == 0:
            if self.cell_range is not None or self.cell_count != 0:
                raise ValueError("无有效列的工作表不得声明单元格范围或数量")
            return self
        if self.row_count == 0:
            raise ValueError("存在有效列的工作表必须至少包含一行")
        if self.cell_count != self.row_count * self.column_count:
            raise ValueError("工作表单元格数量必须由行列数量派生")
        expected_range = (
            f"A1:{_xlsx_column_name(self.column_count)}{self.row_count}"
        )
        if self.cell_range != expected_range:
            raise ValueError("工作表范围必须由有效行列边界派生")
        return self


class ParsedTextNode(ParsedNodeModel):
    """源结构中的完整文本节点，不施加字符上限。"""

    kind: ParsedTextKind
    text: str = Field(min_length=1)
    style_id: str | None = None
    style_name: str | None = None
    outline_level: int | None = Field(default=None, ge=0, le=9)
    heading_level: int | None = Field(default=None, ge=1, le=9)
    pdf_font_name: str | None = None
    pdf_font_size_points: float | None = Field(default=None, gt=0)
    list_num_id: int | None = Field(default=None, ge=0)
    list_ilvl: int | None = Field(default=None, ge=0)
    list_num_format: str | None = None

    @model_validator(mode="after")
    def _validate_text_kind_fields(self) -> "ParsedTextNode":
        if self.kind == "heading" and self.heading_level is None:
            raise ValueError("标题节点必须提供 heading_level")
        if self.kind != "heading" and self.heading_level is not None:
            raise ValueError("非标题节点不得提供 heading_level")
        list_fields = (self.list_num_id, self.list_ilvl, self.list_num_format)
        if self.kind == "list_item" and any(value is None for value in list_fields):
            raise ValueError("列表项节点必须提供 num_id、ilvl 和 numFmt")
        if self.kind != "list_item" and any(
            value is not None for value in list_fields
        ):
            raise ValueError("非列表项节点不得携带列表编号字段")
        return self


class ParsedTableNode(ParsedNodeModel):
    """表格容器；表头只通过行节点身份引用。"""

    kind: Literal["table"] = "table"
    column_count: int = Field(ge=1)
    header_row_node_ids: tuple[UUID, ...] = ()
    title: str | None = None


class ParsedTableRowNode(ParsedNodeModel):
    """表格中的单行原始单元格事实。"""

    kind: Literal["table_row"] = "table_row"
    is_header: bool
    cells: tuple[ParsedCell, ...] = Field(min_length=1)
    repeat_as_header: bool = False
    cannot_split: bool = False
    height_twips: int | None = Field(default=None, ge=0)
    height_rule: TableRowHeightRule | None = None

    @model_validator(mode="after")
    def _validate_cell_columns(self) -> "ParsedTableRowNode":
        columns = [cell.column_index for cell in self.cells]
        if len(columns) != len(set(columns)):
            raise ValueError("表格行内单元格列序号不得重复")
        if columns != sorted(columns):
            raise ValueError("表格行内单元格必须按列序号排列")
        return self


class ParsedSheetRowNode(ParsedNodeModel):
    """XLSX 原始行，允许完整保留空行与隐藏状态。"""

    kind: Literal["sheet_row"] = "sheet_row"
    row_index: int = Field(ge=1)
    hidden: bool = False
    height_points: float | None = Field(default=None, ge=0)
    cells: tuple[ParsedCell, ...] = ()

    @model_validator(mode="after")
    def _validate_cell_columns(self) -> "ParsedSheetRowNode":
        columns = [cell.column_index for cell in self.cells]
        if len(columns) != len(set(columns)):
            raise ValueError("工作表行内单元格列序号不得重复")
        if columns != sorted(columns):
            raise ValueError("工作表行内单元格必须按列序号排列")
        return self


class ParsedNamedRangeNode(ParsedNodeModel):
    """XLSX 名称定义及其原生定义表达式。"""

    kind: Literal["named_range"] = "named_range"
    name: str = Field(min_length=1)
    scope_sheet_name: str | None = None
    definition: str = Field(min_length=1)


class ParsedChartNode(ParsedNodeModel):
    """XLSX 图表结构及其数据源范围引用。"""

    kind: Literal["chart"] = "chart"
    chart_type: str = Field(min_length=1)
    title: str | None = None
    source_ranges: tuple[str, ...] = ()


class ParsedImageNode(ParsedNodeModel):
    """图片媒体的确定性提取结果；视觉语义由独立 Observation owner 持有。"""

    kind: Literal["image"] = "image"
    media_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    alt_text: str | None = None
    caption: str | None = None
    media_extraction_status: ParsedMediaExtractionStatus = "not_attempted"

    @model_validator(mode="after")
    def _validate_media_extraction(self) -> "ParsedImageNode":
        if self.media_extraction_status == "complete" and self.media_sha256 is None:
            raise ValueError("媒体提取完成时必须保留媒体 SHA-256")
        if self.media_extraction_status != "complete" and self.media_sha256 is not None:
            raise ValueError("未完成媒体提取时不得携带媒体 SHA-256")
        return self


type ParsedNode = Annotated[
    ParsedDocumentNode
    | ParsedSectionNode
    | ParsedPageNode
    | ParsedSlideNode
    | ParsedSheetNode
    | ParsedTextNode
    | ParsedTableNode
    | ParsedTableRowNode
    | ParsedSheetRowNode
    | ParsedNamedRangeNode
    | ParsedChartNode
    | ParsedImageNode,
    Field(discriminator="kind"),
]

ParsedNodeType = TypeVar("ParsedNodeType", bound=ParsedNodeModel)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_parsed_node_id(
    *,
    source_sha256: str,
    parser_profile_id: str,
    locator: ParsedNodeLocator,
) -> UUID:
    """按源内容、解析配置和源位置生成稳定节点身份。"""

    identity = _canonical_json(
        {
            "source_sha256": source_sha256,
            "parser_profile_id": parser_profile_id,
            "locator": locator.model_dump(mode="json"),
        }
    )
    return uuid5(NAMESPACE_URL, f"sustainability_desk.parsed-node:{identity}")


def parsed_node_content_fingerprint(node: ParsedNodeModel) -> str:
    """对节点完整结构和内容生成确定性 SHA-256 指纹。"""

    payload = node.model_dump(
        mode="json",
        exclude={"node_id", "content_fingerprint"},
    )
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_parsed_node(
    node_type: type[ParsedNodeType],
    *,
    source_sha256: str,
    parser_profile_id: str,
    locator: ParsedNodeLocator,
    **fields: object,
) -> ParsedNodeType:
    """构造带稳定身份和完整内容指纹的解析节点。"""

    node = node_type(
        node_id=stable_parsed_node_id(
            source_sha256=source_sha256,
            parser_profile_id=parser_profile_id,
            locator=locator,
        ),
        locator=locator,
        content_fingerprint=EMPTY_SHA256,
        **fields,
    )
    identified = node.model_copy(
        update={"content_fingerprint": parsed_node_content_fingerprint(node)}
    )
    return cast(ParsedNodeType, identified)


def parsed_material_content_fingerprint(
    *,
    source_sha256: str,
    parser_profile_id: str,
    parser_fingerprint: str,
    normalization_profile_id: str,
    root_node_id: UUID,
    nodes: tuple[ParsedNode, ...],
    coverage: ParseCoverage,
) -> str:
    """对有序解析树、解析器身份和覆盖率结论生成确定性指纹。"""

    ordered_nodes = sorted(nodes, key=lambda node: node.ordinal_path)
    payload = {
        "source_sha256": source_sha256,
        "parser_profile_id": parser_profile_id,
        "parser_fingerprint": parser_fingerprint,
        "normalization_profile_id": normalization_profile_id,
        "root_node_id": str(root_node_id),
        "nodes": [
            {
                "node_id": str(node.node_id),
                "content_fingerprint": node.content_fingerprint,
            }
            for node in ordered_nodes
        ],
        "coverage": coverage.model_dump(mode="json"),
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class ParsedMaterial(ParsedMaterialModel):
    """单个源文件在指定解析配置下的规范化、可审计解析结果。"""

    parsed_material_id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    document_kind: ParsedDocumentKind
    parser_profile_id: str = Field(min_length=1)
    parser_fingerprint: str = Field(pattern=SHA256_PATTERN)
    normalization_profile_id: str = Field(min_length=1)
    root_node_id: UUID
    status: ParsedMaterialStatus
    nodes: tuple[ParsedNode, ...] = Field(min_length=1)
    content_fingerprint: str = Field(pattern=SHA256_PATTERN)
    coverage: ParseCoverage

    @model_validator(mode="after")
    def _validate_tree_and_fingerprints(self) -> "ParsedMaterial":
        nodes_by_id = {node.node_id: node for node in self.nodes}
        if len(nodes_by_id) != len(self.nodes):
            raise ValueError("解析树节点身份不得重复")
        ordinal_paths = [node.ordinal_path for node in self.nodes]
        if len(ordinal_paths) != len(set(ordinal_paths)):
            raise ValueError("解析树节点顺序路径不得重复")

        root = nodes_by_id.get(self.root_node_id)
        if root is None or root.kind != "document":
            raise ValueError("root_node_id 必须指向文档根节点")
        if root.parent_node_id is not None:
            raise ValueError("文档根节点不得存在父节点")

        for node in self.nodes:
            expected_id = stable_parsed_node_id(
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=node.locator,
            )
            if node.node_id != expected_id:
                raise ValueError(f"节点 {node.node_id} 的稳定身份无效")
            if node.content_fingerprint != parsed_node_content_fingerprint(node):
                raise ValueError(f"节点 {node.node_id} 的内容指纹无效")
            if node.node_id == self.root_node_id:
                continue
            if node.parent_node_id is None:
                raise ValueError(f"非根节点 {node.node_id} 必须存在父节点")
            parent = nodes_by_id.get(node.parent_node_id)
            if parent is None:
                raise ValueError(f"节点 {node.node_id} 引用了不存在的父节点")
            if node.ordinal_path[:-1] != parent.ordinal_path:
                raise ValueError(f"节点 {node.node_id} 的顺序路径不属于其父节点")

        for node in self.nodes:
            if isinstance(node, ParsedSheetNode):
                self._validate_sheet(node, nodes_by_id)
            elif isinstance(node, ParsedTableNode):
                self._validate_table(node, nodes_by_id)
            elif isinstance(node, ParsedTableRowNode):
                if not isinstance(nodes_by_id.get(node.parent_node_id), ParsedTableNode):
                    raise ValueError("表格行父节点必须是表格")
            elif isinstance(node, ParsedSheetRowNode):
                if not isinstance(nodes_by_id.get(node.parent_node_id), ParsedSheetNode):
                    raise ValueError("工作表行父节点必须是工作表")
                if node.locator.kind != "xlsx_row":
                    raise ValueError("工作表行必须使用 XlsxRowLocator")

        expected_status: ParsedMaterialStatus
        if self.coverage.disposition == "complete_for_declared_capabilities":
            expected_status = "complete"
        elif self.coverage.disposition == "incomplete_usable":
            expected_status = "complete_with_gaps"
        else:
            expected_status = "failed"
        if self.status != expected_status:
            raise ValueError("解析状态必须由覆盖率 disposition 派生")

        expected_fingerprint = parsed_material_content_fingerprint(
            source_sha256=self.source_sha256,
            parser_profile_id=self.parser_profile_id,
            parser_fingerprint=self.parser_fingerprint,
            normalization_profile_id=self.normalization_profile_id,
            root_node_id=self.root_node_id,
            nodes=self.nodes,
            coverage=self.coverage,
        )
        if self.content_fingerprint != expected_fingerprint:
            raise ValueError("ParsedMaterial 内容指纹无效")
        return self

    @staticmethod
    def _validate_sheet(
        sheet: ParsedSheetNode,
        nodes_by_id: dict[UUID, ParsedNode],
    ) -> None:
        if sheet.locator.kind != "xlsx_sheet":
            raise ValueError("工作表节点必须使用 XlsxSheetLocator")
        if len(sheet.row_node_ids) != len(set(sheet.row_node_ids)):
            raise ValueError("工作表成员行引用不得重复")
        member_rows: list[ParsedSheetRowNode] = []
        for row_node_id in sheet.row_node_ids:
            row = nodes_by_id.get(row_node_id)
            if not isinstance(row, ParsedSheetRowNode):
                raise ValueError("工作表成员引用必须指向工作表行节点")
            if row.parent_node_id != sheet.node_id:
                raise ValueError("工作表成员行必须由本工作表持有")
            member_rows.append(row)

        direct_rows = sorted(
            (
                node
                for node in nodes_by_id.values()
                if isinstance(node, ParsedSheetRowNode)
                and node.parent_node_id == sheet.node_id
            ),
            key=lambda row: row.row_index,
        )
        if tuple(row.node_id for row in direct_rows) != sheet.row_node_ids:
            raise ValueError("工作表必须完整引用全部直属行节点并保持原始顺序")
        if [row.row_index for row in member_rows] != list(
            range(1, sheet.row_count + 1)
        ):
            raise ValueError("工作表成员行必须完整覆盖声明的连续行范围")
        if sum(len(row.cells) for row in member_rows) != sheet.cell_count:
            raise ValueError("工作表单元格数量必须等于成员行单元格总数")
        for row in member_rows:
            if len(row.cells) != sheet.column_count:
                raise ValueError("工作表行单元格数量必须与工作表列数一致")
            if [cell.column_index for cell in row.cells] != list(
                range(1, sheet.column_count + 1)
            ):
                raise ValueError("工作表行必须完整覆盖工作表声明的连续列范围")
            if row.locator.kind != "xlsx_row":
                raise ValueError("工作表行必须使用 XlsxRowLocator")
            if row.locator.sheet_name != sheet.locator.sheet_name:
                raise ValueError("工作表行定位器必须属于其工作表")
            if row.locator.row_index != row.row_index:
                raise ValueError("工作表行索引必须与定位器一致")
            expected_references = [
                f"{_xlsx_column_name(column_index)}{row.row_index}"
                for column_index in range(1, sheet.column_count + 1)
            ]
            if [cell.cell_reference for cell in row.cells] != expected_references:
                raise ValueError("工作表单元格引用必须完整匹配其行列位置")

    @staticmethod
    def _validate_table(
        table: ParsedTableNode,
        nodes_by_id: dict[UUID, ParsedNode],
    ) -> None:
        if table.locator.kind == "xlsx_table":
            parent = nodes_by_id.get(table.parent_node_id)
            if not isinstance(parent, ParsedSheetNode):
                raise ValueError("XLSX 定义表必须由工作表持有")
            if table.locator.sheet_name != parent.locator.sheet_name:
                raise ValueError("XLSX 定义表定位器必须属于其工作表")
            first, last = table.locator.cell_range.split(":")
            first_column = "".join(filter(str.isalpha, first))
            last_column = "".join(filter(str.isalpha, last))
            first_row = int("".join(filter(str.isdigit, first)))
            last_row = int("".join(filter(str.isdigit, last)))
            first_column_index = _xlsx_column_index(first_column)
            last_column_index = _xlsx_column_index(last_column)
            if table.column_count != last_column_index - first_column_index + 1:
                raise ValueError("XLSX 定义表列数必须由其源范围派生")
            if (
                first_row < 1
                or first_column_index < 1
                or last_row > parent.row_count
                or last_column_index > parent.column_count
            ):
                raise ValueError("XLSX 定义表范围不得超出其工作表")
        header_ids = set(table.header_row_node_ids)
        if len(header_ids) != len(table.header_row_node_ids):
            raise ValueError("表格表头行引用不得重复")
        for header_id in table.header_row_node_ids:
            header = nodes_by_id.get(header_id)
            if not isinstance(header, ParsedTableRowNode):
                raise ValueError("表格表头引用必须指向表格行节点")
            if header.parent_node_id != table.node_id or not header.is_header:
                raise ValueError("表格表头引用必须指向本表的表头行")
        rows = [
            node
            for node in nodes_by_id.values()
            if isinstance(node, ParsedTableRowNode)
            and node.parent_node_id == table.node_id
        ]
        for row in rows:
            if len(row.cells) != table.column_count:
                raise ValueError("表格行单元格数量必须与表格列数一致")
            if any(cell.column_index > table.column_count for cell in row.cells):
                raise ValueError("表格行单元格列序号超出表格列数")


def build_parsed_material(
    *,
    source_id: UUID,
    source_sha256: str,
    document_kind: ParsedDocumentKind,
    parser_profile_id: str,
    parser_fingerprint: str,
    normalization_profile_id: str,
    root_node_id: UUID,
    nodes: tuple[ParsedNode, ...],
    coverage: ParseCoverage,
    parsed_material_id: UUID | None = None,
) -> ParsedMaterial:
    """由解析树和覆盖率构造自校验的 ParsedMaterial。"""

    if coverage.disposition == "complete_for_declared_capabilities":
        status: ParsedMaterialStatus = "complete"
    elif coverage.disposition == "incomplete_usable":
        status = "complete_with_gaps"
    else:
        status = "failed"
    content_fingerprint = parsed_material_content_fingerprint(
        source_sha256=source_sha256,
        parser_profile_id=parser_profile_id,
        parser_fingerprint=parser_fingerprint,
        normalization_profile_id=normalization_profile_id,
        root_node_id=root_node_id,
        nodes=nodes,
        coverage=coverage,
    )
    fields: dict[str, object] = {
        "source_id": source_id,
        "source_sha256": source_sha256,
        "document_kind": document_kind,
        "parser_profile_id": parser_profile_id,
        "parser_fingerprint": parser_fingerprint,
        "normalization_profile_id": normalization_profile_id,
        "root_node_id": root_node_id,
        "status": status,
        "nodes": nodes,
        "content_fingerprint": content_fingerprint,
        "coverage": coverage,
    }
    if parsed_material_id is not None:
        fields["parsed_material_id"] = parsed_material_id
    return ParsedMaterial.model_validate(fields)
