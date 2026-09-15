# ABOUTME: 将 DOCX OOXML 按故事流原序解析为可定位、无截断的 ParsedMaterial 树。
# ABOUTME: 未完整建模的 Word 对象必须登记 ParseGap，禁止静默丢弃或伪装成完整覆盖。
# ABOUTME(en): Parses DOCX OOXML in story-flow order into a locatable, untruncated ParsedMaterial tree.
# ABOUTME(en): Word objects not fully modelled must register a ParseGap; silent dropping or faked coverage is banned.
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import json
import posixpath
import re
from typing import Literal
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from lxml import etree

from sustainability_desk.material.intake.parse_coverage import (
    CapabilityCoverage,
    ParseCapability,
    ParseCoverage,
    ParseGap,
)
from sustainability_desk.material.intake.parsed_material import (
    ParsedCell,
    ParsedDocumentNode,
    ParsedImageNode,
    ParsedMaterial,
    ParsedNode,
    ParsedSectionNode,
    ParsedTableNode,
    ParsedTableRowNode,
    ParsedTextNode,
    build_parsed_material,
    build_parsed_node,
)
from sustainability_desk.material.intake.parsed_material_locators import (
    DocumentObjectLocator,
    DocumentObjectHostLocator,
    DocumentObjectKind,
    DocumentRootLocator,
    DocxParagraphLocator,
    DocxStoryLocator,
    DocxTableLocator,
    DocxTableRowLocator,
    EmbeddedImageLocator,
    HeaderFooterType,
    ParsedNodeLocator,
)

PARSER_PROFILE_ID = "docx-structural@1"
NORMALIZATION_PROFILE_ID = "ooxml-preserve-text@1"
PARSER_FINGERPRINT = sha256(
    b"sustainability_desk.docx-structural@1:body-order,styles,lists,tables,stories,"
    b"media,image-semantic-gaps,textbox-text,footnotes"
).hexdigest()

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
V_NS = "urn:schemas-microsoft-com:vml"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "r": R_NS, "a": A_NS, "wp": WP_NS, "v": V_NS}

W_VAL = f"{{{W_NS}}}val"
W_TYPE = f"{{{W_NS}}}type"
R_ID = f"{{{R_NS}}}id"
R_EMBED = f"{{{R_NS}}}embed"
R_LINK = f"{{{R_NS}}}link"

type StoryPart = Literal["body", "header", "footer"]


class DocxStructureParseError(ValueError):
    """DOCX 容器或关键 OOXML 部件无法可靠解析。"""


@dataclass(frozen=True)
class _Relationship:
    target: str
    target_mode: str | None
    relationship_type: str


@dataclass(frozen=True)
class _Style:
    style_id: str
    name: str | None
    based_on: str | None
    outline_level: int | None
    num_id: int | None
    ilvl: int | None


@dataclass(frozen=True)
class _StoryIdentity:
    part: StoryPart
    section_index: int | None = None
    header_footer_type: HeaderFooterType | None = None


@dataclass
class _CoverageCounter:
    source: dict[ParseCapability, int] = field(default_factory=dict)
    parsed: dict[ParseCapability, int] = field(default_factory=dict)
    text_characters: int = 0
    table_cells: int = 0
    extra_source_units: int = 0
    gaps: list[ParseGap] = field(default_factory=list)

    def unit(self, capability: ParseCapability, *, parsed: bool) -> None:
        self.source[capability] = self.source.get(capability, 0) + 1
        if parsed:
            self.parsed[capability] = self.parsed.get(capability, 0) + 1

    def gap(
        self,
        *,
        code: str,
        message: str,
        locator: ParsedNodeLocator | None,
        capability: ParseCapability | None = None,
    ) -> None:
        if capability is None:
            self.extra_source_units += 1
        else:
            self.unit(capability, parsed=False)
        self.gaps.append(
            ParseGap(
                code=code,
                message=message,
                effect="negative_evidence_blocked",
                locator=locator,
            )
        )


@dataclass
class _TableRowDraft:
    locator: DocxTableRowLocator
    ordinal_path: tuple[int, ...]
    repeat_as_header: bool
    cannot_split: bool
    height_twips: int | None
    height_rule: Literal["auto", "at_least", "exact"] | None
    cells: list[ParsedCell]


@dataclass
class _Parser:
    archive: ZipFile
    source_id: UUID
    source_sha256: str
    source_label: str | None
    parser_profile_id: str
    normalization_profile_id: str
    nodes: list[ParsedNode] = field(default_factory=list)
    coverage: _CoverageCounter = field(default_factory=_CoverageCounter)
    paragraph_index: dict[_StoryIdentity, int] = field(default_factory=dict)
    table_index: dict[_StoryIdentity, int] = field(default_factory=dict)
    image_index: int = 0
    object_index: dict[tuple[str, str], int] = field(default_factory=dict)
    footnotes_by_id: dict[str, etree._Element] | None = None

    def parse(self) -> ParsedMaterial:
        document = self._xml("word/document.xml")
        styles = self._styles()
        numbering = self._numbering_formats()
        root = build_parsed_node(
            ParsedDocumentNode,
            source_sha256=self.source_sha256,
            parser_profile_id=self.parser_profile_id,
            locator=DocumentRootLocator(),
            parent_node_id=None,
            ordinal_path=(1,),
            label=self.source_label,
        )
        self.nodes.append(root)

        body = document.find("w:body", NS)
        if body is None:
            raise DocxStructureParseError("DOCX document.xml 缺少 w:body")
        body_relationships = self._relationships("word/document.xml")
        top_level_ordinal = self._parse_story_blocks(
            container=body,
            identity=_StoryIdentity(part="body"),
            part_path="word/document.xml",
            relationships=body_relationships,
            parent_node_id=root.node_id,
            parent_ordinal=(1,),
            first_ordinal=1,
            styles=styles,
            numbering=numbering,
        )
        top_level_ordinal = self._parse_header_footer_stories(
            body=body,
            document_relationships=body_relationships,
            root_node_id=root.node_id,
            first_ordinal=top_level_ordinal,
            styles=styles,
            numbering=numbering,
        )
        del top_level_ordinal

        capabilities = tuple(
            CapabilityCoverage(
                capability=capability,
                source_unit_count=count,
                parsed_unit_count=self.coverage.parsed.get(capability, 0),
            )
            for capability, count in sorted(self.coverage.source.items())
        )
        source_units_total = (
            sum(self.coverage.source.values()) + self.coverage.extra_source_units
        )
        source_units_parsed = sum(self.coverage.parsed.values())
        gaps = tuple(self.coverage.gaps)
        disposition = "incomplete_usable" if gaps else "complete_for_declared_capabilities"
        coverage = ParseCoverage(
            disposition=disposition,
            source_units_total=source_units_total,
            source_units_parsed=source_units_parsed,
            text_characters_parsed=self.coverage.text_characters,
            table_cells_parsed=self.coverage.table_cells,
            capabilities=capabilities,
            gaps=gaps,
        )
        typed_nodes = tuple(self.nodes)
        return build_parsed_material(
            source_id=self.source_id,
            source_sha256=self.source_sha256,
            document_kind="docx",
            parser_profile_id=self.parser_profile_id,
            parser_fingerprint=PARSER_FINGERPRINT,
            normalization_profile_id=self.normalization_profile_id,
            root_node_id=root.node_id,
            nodes=typed_nodes,
            coverage=coverage,
        )

    def _parse_story_blocks(
        self,
        *,
        container: etree._Element,
        identity: _StoryIdentity,
        part_path: str,
        relationships: dict[str, _Relationship],
        parent_node_id: UUID,
        parent_ordinal: tuple[int, ...],
        first_ordinal: int,
        styles: dict[str, _Style],
        numbering: dict[int, dict[int, str]],
    ) -> int:
        block_ordinal = first_ordinal
        block_index = 0
        for child in container:
            if child.tag == f"{{{W_NS}}}sectPr":
                continue
            if child.tag in {f"{{{W_NS}}}p", f"{{{W_NS}}}tbl"}:
                block_index += 1
                ordinal_path = (*parent_ordinal, block_ordinal)
                if child.tag == f"{{{W_NS}}}p":
                    self._parse_paragraph(
                        element=child,
                        identity=identity,
                        block_index=block_index,
                        part_path=part_path,
                        relationships=relationships,
                        parent_node_id=parent_node_id,
                        ordinal_path=ordinal_path,
                        styles=styles,
                        numbering=numbering,
                    )
                else:
                    self._parse_table(
                        element=child,
                        identity=identity,
                        block_index=block_index,
                        part_path=part_path,
                        relationships=relationships,
                        parent_node_id=parent_node_id,
                        ordinal_path=ordinal_path,
                        styles=styles,
                        numbering=numbering,
                    )
                block_ordinal += 1
                continue

            descendant_blocks = self._outermost_blocks(child)
            host = self._wrapper_host_locator(
                identity=identity,
                block_index=block_index + 1,
                first_block=descendant_blocks[0] if descendant_blocks else None,
            )
            object_kind = self._object_kind(child)
            if host is None:
                self.coverage.gap(
                    code=f"docx_{object_kind}_semantics_not_modeled",
                    message=f"DOCX {self._local_name(child)} 对象语义未完整建模",
                    locator=None,
                )
            else:
                self._object_gap(
                    object_kind=object_kind,
                    host=host,
                    code=f"docx_{object_kind}_semantics_not_modeled",
                    message=f"DOCX {self._local_name(child)} 对象语义未完整建模",
                )
            for descendant in descendant_blocks:
                block_index += 1
                ordinal_path = (*parent_ordinal, block_ordinal)
                if descendant.tag == f"{{{W_NS}}}p":
                    self._parse_paragraph(
                        element=descendant,
                        identity=identity,
                        block_index=block_index,
                        part_path=part_path,
                        relationships=relationships,
                        parent_node_id=parent_node_id,
                        ordinal_path=ordinal_path,
                        styles=styles,
                        numbering=numbering,
                    )
                else:
                    self._parse_table(
                        element=descendant,
                        identity=identity,
                        block_index=block_index,
                        part_path=part_path,
                        relationships=relationships,
                        parent_node_id=parent_node_id,
                        ordinal_path=ordinal_path,
                        styles=styles,
                        numbering=numbering,
                    )
                block_ordinal += 1
        return block_ordinal

    def _parse_paragraph(
        self,
        *,
        element: etree._Element,
        identity: _StoryIdentity,
        block_index: int,
        part_path: str,
        relationships: dict[str, _Relationship],
        parent_node_id: UUID,
        ordinal_path: tuple[int, ...],
        styles: dict[str, _Style],
        numbering: dict[int, dict[int, str]],
    ) -> None:
        paragraph_number = self.paragraph_index.get(identity, 0) + 1
        self.paragraph_index[identity] = paragraph_number
        locator = DocxParagraphLocator(
            part=identity.part,
            section_index=identity.section_index,
            header_footer_type=identity.header_footer_type,
            block_index=block_index,
            paragraph_index=paragraph_number,
        )
        text = self._paragraph_text(element)
        images = self._image_elements(element)

        style_id, style = self._paragraph_style(element, styles)
        outline_level = self._paragraph_outline_level(element, style)
        heading_level = (
            outline_level + 1
            if outline_level is not None and 0 <= outline_level <= 8
            else self._heading_level_from_style(style_id, style)
        )
        num_id, ilvl, num_format = self._paragraph_numbering(
            element, style, numbering
        )
        if num_id is not None and ilvl is not None and num_format is not None:
            kind = "list_item"
            heading_level = None
        elif heading_level is not None:
            kind = "heading"
        else:
            kind = "paragraph"

        paragraph_node: ParsedTextNode | None = None
        if text:
            self.coverage.unit("text", parsed=True)
            self.coverage.text_characters += len(text)
            paragraph_node = build_parsed_node(
                ParsedTextNode,
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=locator,
                parent_node_id=parent_node_id,
                ordinal_path=ordinal_path,
                kind=kind,
                text=text,
                style_id=style_id,
                style_name=style.name if style is not None else None,
                outline_level=outline_level,
                heading_level=heading_level,
                list_num_id=num_id if kind == "list_item" else None,
                list_ilvl=ilvl if kind == "list_item" else None,
                list_num_format=num_format if kind == "list_item" else None,
            )
            self.nodes.append(paragraph_node)

        self._register_complex_objects(element, locator)
        image_parent_id = (
            paragraph_node.node_id if paragraph_node is not None else parent_node_id
        )
        image_parent_ordinal = (
            paragraph_node.ordinal_path
            if paragraph_node is not None
            else ordinal_path[:-1]
        )
        next_child_ordinal = self._parse_textboxes(
            element=element,
            host_locator=locator,
            part_path=part_path,
            relationships=relationships,
            parent_node_id=image_parent_id,
            parent_ordinal=image_parent_ordinal,
            first_ordinal=1,
            styles=styles,
        )
        for local_index, image in enumerate(images, start=1):
            self._parse_image(
                element=image,
                host_locator=locator,
                container_suffix=None,
                part_path=part_path,
                relationships=relationships,
                parent_node_id=image_parent_id,
                ordinal_path=(
                    *image_parent_ordinal,
                    next_child_ordinal + local_index - 1,
                ),
            )
        next_child_ordinal += len(images)
        self._parse_footnotes(
            element=element,
            host_locator=locator,
            parent_node_id=image_parent_id,
            parent_ordinal=image_parent_ordinal,
            first_ordinal=next_child_ordinal,
            styles=styles,
        )

    def _parse_table(
        self,
        *,
        element: etree._Element,
        identity: _StoryIdentity,
        block_index: int,
        part_path: str,
        relationships: dict[str, _Relationship],
        parent_node_id: UUID,
        ordinal_path: tuple[int, ...],
        styles: dict[str, _Style],
        numbering: dict[int, dict[int, str]],
    ) -> None:
        table_number = self.table_index.get(identity, 0) + 1
        self.table_index[identity] = table_number
        locator = DocxTableLocator(
            part=identity.part,
            section_index=identity.section_index,
            header_footer_type=identity.header_footer_type,
            block_index=block_index,
            table_index=table_number,
        )
        rows = element.findall("w:tr", NS)
        column_count = self._table_column_count(element, rows)
        if column_count < 1:
            self.coverage.gap(
                code="docx_table_without_grid",
                message="DOCX 表格无法确定列数",
                locator=locator,
            )
            return

        self.coverage.unit("tables", parsed=True)
        table_node = build_parsed_node(
            ParsedTableNode,
            source_sha256=self.source_sha256,
            parser_profile_id=self.parser_profile_id,
            locator=locator,
            parent_node_id=parent_node_id,
            ordinal_path=ordinal_path,
            column_count=column_count,
            header_row_node_ids=(),
        )
        self.nodes.append(table_node)
        drafts = self._table_row_drafts(
            rows=rows,
            identity=identity,
            table_number=table_number,
            table_ordinal=ordinal_path,
            column_count=column_count,
        )
        self._apply_vertical_merge_metadata(drafts)
        row_nodes: list[ParsedTableRowNode] = []
        for row_index, (row_element, draft) in enumerate(
            zip(rows, drafts, strict=True), start=1
        ):
            row_node = build_parsed_node(
                ParsedTableRowNode,
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=draft.locator,
                parent_node_id=table_node.node_id,
                ordinal_path=draft.ordinal_path,
                is_header=draft.repeat_as_header,
                repeat_as_header=draft.repeat_as_header,
                cannot_split=draft.cannot_split,
                height_twips=draft.height_twips,
                height_rule=draft.height_rule,
                cells=tuple(draft.cells),
            )
            self.nodes.append(row_node)
            row_nodes.append(row_node)
            self.coverage.table_cells += len(draft.cells)
            self._register_complex_objects(row_element, draft.locator)
            images = self._image_elements(row_element)
            next_child_ordinal = self._parse_textboxes(
                element=row_element,
                host_locator=draft.locator,
                part_path=part_path,
                relationships=relationships,
                parent_node_id=row_node.node_id,
                parent_ordinal=row_node.ordinal_path,
                first_ordinal=1,
                styles=styles,
            )
            for image_index, image in enumerate(images, start=1):
                cell_number = self._image_cell_number(image, row_element)
                self._parse_image(
                    element=image,
                    host_locator=draft.locator,
                    container_suffix=f"cell:{cell_number}",
                    part_path=part_path,
                    relationships=relationships,
                    parent_node_id=row_node.node_id,
                    ordinal_path=(
                        *row_node.ordinal_path,
                        next_child_ordinal + image_index - 1,
                    ),
                )
            next_child_ordinal += len(images)
            self._parse_footnotes(
                element=row_element,
                host_locator=draft.locator,
                parent_node_id=row_node.node_id,
                parent_ordinal=row_node.ordinal_path,
                first_ordinal=next_child_ordinal,
                styles=styles,
            )
            nested_tables = row_element.xpath(".//w:tc//w:tbl", namespaces=NS)
            for nested_index, _nested in enumerate(nested_tables, start=1):
                self.coverage.gap(
                    code="docx_nested_table_not_structured",
                    message="单元格内嵌套表格已保留文本，但未建立独立表格树",
                    locator=DocumentObjectLocator(
                        object_kind="content_control",
                        host_locator=draft.locator,
                        object_index=nested_index,
                        object_reference=f"nested-table[{nested_index}]",
                    ),
                )

        header_ids = tuple(
            row.node_id for row in row_nodes if row.repeat_as_header
        )
        if header_ids:
            rebuilt = build_parsed_node(
                ParsedTableNode,
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=locator,
                parent_node_id=parent_node_id,
                ordinal_path=ordinal_path,
                column_count=column_count,
                header_row_node_ids=header_ids,
            )
            self.nodes[self.nodes.index(table_node)] = rebuilt

    def _table_row_drafts(
        self,
        *,
        rows: list[etree._Element],
        identity: _StoryIdentity,
        table_number: int,
        table_ordinal: tuple[int, ...],
        column_count: int,
    ) -> list[_TableRowDraft]:
        drafts: list[_TableRowDraft] = []
        active_vertical: dict[int, str] = {}
        for row_index, row in enumerate(rows, start=1):
            row_properties = row.find("w:trPr", NS)
            repeat_as_header = (
                row_properties is not None
                and row_properties.find("w:tblHeader", NS) is not None
            )
            cannot_split = (
                row_properties is not None
                and row_properties.find("w:cantSplit", NS) is not None
            )
            height_twips, height_rule = self._row_height(row_properties)
            grid_before = self._int_attribute(
                row_properties.find("w:gridBefore", NS)
                if row_properties is not None
                else None,
                default=0,
            )
            cells: list[ParsedCell | None] = [None] * column_count
            column = grid_before + 1
            for physical_cell in row.findall("w:tc", NS):
                span = max(
                    1,
                    self._int_attribute(
                        physical_cell.find("w:tcPr/w:gridSpan", NS), default=1
                    ),
                )
                text = self._cell_text(physical_cell)
                v_merge = physical_cell.find("w:tcPr/w:vMerge", NS)
                v_state = (
                    (v_merge.get(W_VAL) or "continue") if v_merge is not None else None
                )
                anchor_ref = f"R{row_index}C{column}"
                if v_state == "continue":
                    anchor_ref = active_vertical.get(column, anchor_ref)
                elif v_state == "restart":
                    for covered_column in range(
                        column, min(column + span, column_count + 1)
                    ):
                        active_vertical[covered_column] = anchor_ref
                else:
                    for covered_column in range(
                        column, min(column + span, column_count + 1)
                    ):
                        active_vertical.pop(covered_column, None)

                for offset in range(span):
                    target_column = column + offset
                    if target_column > column_count:
                        self.coverage.gap(
                            code="docx_table_cell_outside_grid",
                            message="DOCX 单元格跨度超出表格网格",
                            locator=DocxTableRowLocator(
                                part=identity.part,
                                section_index=identity.section_index,
                                header_footer_type=identity.header_footer_type,
                                table_index=table_number,
                                row_index=row_index,
                            ),
                        )
                        break
                    is_anchor_position = offset == 0 and v_state != "continue"
                    merged = span > 1 or v_state is not None
                    cells[target_column - 1] = ParsedCell(
                        column_index=target_column,
                        text=text if offset == 0 else "",
                        cell_reference=f"R{row_index}C{target_column}",
                        merged_anchor=anchor_ref if merged else None,
                        column_span=span if is_anchor_position else 1,
                    )
                column += span
            for column_index, cell in enumerate(cells, start=1):
                if cell is None:
                    cells[column_index - 1] = ParsedCell(
                        column_index=column_index,
                        text="",
                        value_kind="blank",
                        cell_reference=f"R{row_index}C{column_index}",
                    )
            drafts.append(
                _TableRowDraft(
                    locator=DocxTableRowLocator(
                        part=identity.part,
                        section_index=identity.section_index,
                        header_footer_type=identity.header_footer_type,
                        table_index=table_number,
                        row_index=row_index,
                    ),
                    ordinal_path=(*table_ordinal, row_index),
                    repeat_as_header=repeat_as_header,
                    cannot_split=cannot_split,
                    height_twips=height_twips,
                    height_rule=height_rule,
                    cells=[cell for cell in cells if cell is not None],
                )
            )
        return drafts

    def _apply_vertical_merge_metadata(self, drafts: list[_TableRowDraft]) -> None:
        members: dict[str, list[tuple[int, int]]] = {}
        for row_index, draft in enumerate(drafts, start=1):
            for cell in draft.cells:
                if cell.merged_anchor is not None:
                    members.setdefault(cell.merged_anchor, []).append(
                        (row_index, cell.column_index)
                    )
        for anchor_ref, positions in members.items():
            anchor_row, anchor_column = self._parse_cell_reference(anchor_ref)
            max_row = max(row for row, _column in positions)
            max_column = max(column for _row, column in positions)
            merged_range = (
                f"R{anchor_row}C{anchor_column}:R{max_row}C{max_column}"
            )
            for row, column in positions:
                cell = drafts[row - 1].cells[column - 1]
                updates: dict[str, object] = {"merged_range": merged_range}
                if row == anchor_row and column == anchor_column:
                    updates["row_span"] = max_row - anchor_row + 1
                    updates["column_span"] = max_column - anchor_column + 1
                drafts[row - 1].cells[column - 1] = cell.model_copy(update=updates)

    def _parse_header_footer_stories(
        self,
        *,
        body: etree._Element,
        document_relationships: dict[str, _Relationship],
        root_node_id: UUID,
        first_ordinal: int,
        styles: dict[str, _Style],
        numbering: dict[int, dict[int, str]],
    ) -> int:
        section_properties = body.xpath(".//w:sectPr", namespaces=NS)
        effective: dict[
            tuple[Literal["header", "footer"], HeaderFooterType], str
        ] = {}
        top_ordinal = first_ordinal
        for section_index, section in enumerate(section_properties, start=1):
            for part in ("header", "footer"):
                references = section.findall(f"w:{part}Reference", NS)
                for reference in references:
                    story_type = reference.get(W_TYPE, "default")
                    if story_type not in {"default", "first", "even"}:
                        self.coverage.gap(
                            code="docx_unknown_header_footer_type",
                            message=f"未知页眉页脚类型：{story_type}",
                            locator=None,
                        )
                        continue
                    relationship_id = reference.get(R_ID)
                    if relationship_id:
                        effective[(part, story_type)] = relationship_id
            for (part, story_type), relationship_id in sorted(effective.items()):
                relationship = document_relationships.get(relationship_id)
                story_locator = DocxStoryLocator(
                    part=part,
                    section_index=section_index,
                    header_footer_type=story_type,
                )
                self.coverage.unit("headers_footers", parsed=False)
                if relationship is None or relationship.target_mode == "External":
                    self.coverage.gap(
                        code="docx_header_footer_relationship_missing",
                        message="页眉页脚部件关系不存在或为外部目标",
                        locator=story_locator,
                    )
                    continue
                story_path = self._resolve_target(
                    "word/document.xml", relationship.target
                )
                try:
                    story_xml = self._xml(story_path)
                except DocxStructureParseError:
                    self.coverage.gap(
                        code="docx_header_footer_part_missing",
                        message=f"页眉页脚部件缺失：{story_path}",
                        locator=story_locator,
                    )
                    continue
                story_node = build_parsed_node(
                    ParsedSectionNode,
                    source_sha256=self.source_sha256,
                    parser_profile_id=self.parser_profile_id,
                    locator=story_locator,
                    parent_node_id=root_node_id,
                    ordinal_path=(1, top_ordinal),
                    label=f"第 {section_index} 节 {story_type} {part}",
                )
                self.nodes.append(story_node)
                self.coverage.parsed["headers_footers"] = (
                    self.coverage.parsed.get("headers_footers", 0) + 1
                )
                self._parse_story_blocks(
                    container=story_xml,
                    identity=_StoryIdentity(
                        part=part,
                        section_index=section_index,
                        header_footer_type=story_type,
                    ),
                    part_path=story_path,
                    relationships=self._relationships(story_path),
                    parent_node_id=story_node.node_id,
                    parent_ordinal=story_node.ordinal_path,
                    first_ordinal=1,
                    styles=styles,
                    numbering=numbering,
                )
                top_ordinal += 1
        return top_ordinal

    def _parse_image(
        self,
        *,
        element: etree._Element,
        host_locator: ParsedNodeLocator,
        container_suffix: str | None,
        part_path: str,
        relationships: dict[str, _Relationship],
        parent_node_id: UUID,
        ordinal_path: tuple[int, ...],
    ) -> None:
        self.image_index += 1
        relationship_id = element.get(R_EMBED) or element.get(R_ID)
        if relationship_id is None:
            relationship_id = element.get(R_LINK)
        host_ref = json.dumps(
            host_locator.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if container_suffix:
            host_ref = f"{host_ref}#{container_suffix}"
        locator = EmbeddedImageLocator(
            container_kind="docx",
            container_ref=host_ref,
            image_index=self.image_index,
        )
        relationship = relationships.get(relationship_id or "")
        media_sha: str | None = None
        media_extraction_status = "failed"
        if relationship is None:
            self.coverage.gap(
                code="docx_image_relationship_missing",
                message="嵌入图片缺少可解析的关系目标",
                locator=locator,
                capability="images",
            )
        elif relationship.target_mode == "External":
            self.coverage.gap(
                code="docx_external_image_not_embedded",
                message="外链图片未嵌入 DOCX，无法计算媒体指纹",
                locator=locator,
                capability="images",
            )
        else:
            media_path = self._resolve_target(part_path, relationship.target)
            try:
                media = self.archive.read(media_path)
            except KeyError:
                self.coverage.gap(
                    code="docx_image_part_missing",
                    message=f"嵌入图片部件缺失：{media_path}",
                    locator=locator,
                    capability="images",
                )
            else:
                media_sha = sha256(media).hexdigest()
                media_extraction_status = "complete"
                self.coverage.unit("images", parsed=True)
                self.coverage.gap(
                    code="docx_image_semantics_unparsed",
                    message=(
                        "图片媒体字节已提取，但图片中的文字、图表及视觉事实"
                        "尚未由独立视觉解析流程生成 Observation"
                    ),
                    locator=locator,
                )

        drawing = element
        doc_properties = drawing.xpath(
            "ancestor-or-self::*[self::w:drawing or self::w:pict]"
            "//wp:docPr[1]",
            namespaces=NS,
        )
        alt_text = None
        if doc_properties:
            alt_text = (
                doc_properties[0].get("descr")
                or doc_properties[0].get("title")
                or doc_properties[0].get("name")
            )
        image_node = build_parsed_node(
            ParsedImageNode,
            source_sha256=self.source_sha256,
            parser_profile_id=self.parser_profile_id,
            locator=locator,
            parent_node_id=parent_node_id,
            ordinal_path=ordinal_path,
            media_sha256=media_sha,
            alt_text=alt_text,
            caption=None,
            media_extraction_status=media_extraction_status,
        )
        self.nodes.append(image_node)

    def _parse_textboxes(
        self,
        *,
        element: etree._Element,
        host_locator: DocumentObjectHostLocator,
        part_path: str,
        relationships: dict[str, _Relationship],
        parent_node_id: UUID,
        parent_ordinal: tuple[int, ...],
        first_ordinal: int,
        styles: dict[str, _Style],
    ) -> int:
        next_ordinal = first_ordinal
        textboxes = element.xpath(".//w:txbxContent", namespaces=NS)
        for textbox_index, textbox in enumerate(textboxes, start=1):
            if self._has_ancestor(
                textbox, f"{{{W_NS}}}txbxContent", element
            ):
                continue
            container_locator = self._next_object_locator(
                object_kind="textbox",
                host=host_locator,
                reference=f"w:txbxContent[{textbox_index}]",
            )
            container_node = build_parsed_node(
                ParsedSectionNode,
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=container_locator,
                parent_node_id=parent_node_id,
                ordinal_path=(*parent_ordinal, next_ordinal),
                label=f"文本框 {textbox_index}",
            )
            self.nodes.append(container_node)
            self.coverage.gap(
                code="docx_textbox_layout_unmodeled",
                message=(
                    "文本框正文已确定性提取，但浮动位置、形状、层级及布局"
                    "尚未结构化"
                ),
                locator=container_locator,
            )
            child_ordinal = 1
            paragraph_index = 0
            for block in self._outermost_blocks(textbox):
                if block.tag == f"{{{W_NS}}}tbl":
                    table_locator = self._next_object_locator(
                        object_kind="textbox",
                        host=host_locator,
                        reference=(
                            f"w:txbxContent[{textbox_index}]/"
                            f"table[{child_ordinal}]"
                        ),
                    )
                    self.coverage.gap(
                        code="docx_textbox_table_structure_unmodeled",
                        message="文本框内表格未扁平化；其行列结构尚未解析",
                        locator=table_locator,
                    )
                    child_ordinal += 1
                    continue
                paragraph_index += 1
                text = self._paragraph_text(block)
                if not text:
                    continue
                text_locator = self._next_object_locator(
                    object_kind="textbox",
                    host=host_locator,
                    reference=(
                        f"w:txbxContent[{textbox_index}]/"
                        f"paragraph[{paragraph_index}]"
                    ),
                )
                style_id, style = self._paragraph_style(block, styles)
                outline_level = self._paragraph_outline_level(block, style)
                text_node = build_parsed_node(
                    ParsedTextNode,
                    source_sha256=self.source_sha256,
                    parser_profile_id=self.parser_profile_id,
                    locator=text_locator,
                    parent_node_id=container_node.node_id,
                    ordinal_path=(*container_node.ordinal_path, child_ordinal),
                    kind="text_block",
                    text=text,
                    style_id=style_id,
                    style_name=style.name if style is not None else None,
                    outline_level=outline_level,
                )
                self.nodes.append(text_node)
                self.coverage.unit("text", parsed=True)
                self.coverage.text_characters += len(text)
                child_ordinal += 1
            for image in self._image_elements(textbox):
                self._parse_image(
                    element=image,
                    host_locator=container_locator,
                    container_suffix=None,
                    part_path=part_path,
                    relationships=relationships,
                    parent_node_id=container_node.node_id,
                    ordinal_path=(*container_node.ordinal_path, child_ordinal),
                )
                child_ordinal += 1
            next_ordinal += 1
        return next_ordinal

    def _parse_footnotes(
        self,
        *,
        element: etree._Element,
        host_locator: DocumentObjectHostLocator,
        parent_node_id: UUID,
        parent_ordinal: tuple[int, ...],
        first_ordinal: int,
        styles: dict[str, _Style],
    ) -> int:
        next_ordinal = first_ordinal
        references = element.xpath(".//w:footnoteReference", namespaces=NS)
        if not references:
            return next_ordinal
        footnotes = self._load_footnotes()
        for reference_index, reference in enumerate(references, start=1):
            footnote_id = reference.get(f"{{{W_NS}}}id")
            if footnotes is None:
                self._object_gap(
                    object_kind="footnote",
                    host=host_locator,
                    code="docx_footnote_part_missing",
                    message="文档引用了脚注，但 word/footnotes.xml 不存在",
                    reference=footnote_id,
                )
                continue
            footnote = footnotes.get(footnote_id or "")
            if footnote is None:
                self._object_gap(
                    object_kind="footnote",
                    host=host_locator,
                    code="docx_footnote_id_missing",
                    message=f"脚注引用 {footnote_id!r} 在脚注部件中不存在",
                    reference=footnote_id,
                )
                continue
            container_locator = self._next_object_locator(
                object_kind="footnote",
                host=host_locator,
                reference=f"footnote[{footnote_id}]",
            )
            container_node = build_parsed_node(
                ParsedSectionNode,
                source_sha256=self.source_sha256,
                parser_profile_id=self.parser_profile_id,
                locator=container_locator,
                parent_node_id=parent_node_id,
                ordinal_path=(*parent_ordinal, next_ordinal),
                label=f"脚注 {footnote_id}",
            )
            self.nodes.append(container_node)
            child_ordinal = 1
            paragraph_index = 0
            for block in self._outermost_blocks(footnote):
                if block.tag == f"{{{W_NS}}}tbl":
                    table_locator = self._next_object_locator(
                        object_kind="footnote",
                        host=host_locator,
                        reference=(
                            f"footnote[{footnote_id}]/table[{child_ordinal}]"
                        ),
                    )
                    self.coverage.gap(
                        code="docx_footnote_table_structure_unmodeled",
                        message="脚注内表格未扁平化；其行列结构尚未解析",
                        locator=table_locator,
                    )
                    child_ordinal += 1
                    continue
                paragraph_index += 1
                text = self._footnote_paragraph_text(block)
                if not text:
                    continue
                text_locator = self._next_object_locator(
                    object_kind="footnote",
                    host=host_locator,
                    reference=(
                        f"footnote[{footnote_id}]/paragraph[{paragraph_index}]"
                    ),
                )
                style_id, style = self._paragraph_style(block, styles)
                outline_level = self._paragraph_outline_level(block, style)
                text_node = build_parsed_node(
                    ParsedTextNode,
                    source_sha256=self.source_sha256,
                    parser_profile_id=self.parser_profile_id,
                    locator=text_locator,
                    parent_node_id=container_node.node_id,
                    ordinal_path=(*container_node.ordinal_path, child_ordinal),
                    kind="text_block",
                    text=text,
                    style_id=style_id,
                    style_name=style.name if style is not None else None,
                    outline_level=outline_level,
                )
                self.nodes.append(text_node)
                self.coverage.unit("text", parsed=True)
                self.coverage.text_characters += len(text)
                child_ordinal += 1
            if footnote.xpath(".//w:txbxContent | .//w:sdt | .//w:ins | .//w:del", namespaces=NS):
                self.coverage.gap(
                    code="docx_footnote_nested_object_unmodeled",
                    message="脚注内存在尚未完整建模的文本框、内容控件或修订对象",
                    locator=container_locator,
                )
            footnote_relationships = self._relationships("word/footnotes.xml")
            for image in self._image_elements(footnote):
                self._parse_image(
                    element=image,
                    host_locator=container_locator,
                    container_suffix=None,
                    part_path="word/footnotes.xml",
                    relationships=footnote_relationships,
                    parent_node_id=container_node.node_id,
                    ordinal_path=(*container_node.ordinal_path, child_ordinal),
                )
                child_ordinal += 1
            next_ordinal += 1
        return next_ordinal

    def _load_footnotes(self) -> dict[str, etree._Element] | None:
        if self.footnotes_by_id is not None:
            return self.footnotes_by_id
        if "word/footnotes.xml" not in self.archive.namelist():
            return None
        root = self._xml("word/footnotes.xml")
        self.footnotes_by_id = {
            footnote_id: footnote
            for footnote in root.findall("w:footnote", NS)
            if (footnote_id := footnote.get(f"{{{W_NS}}}id")) is not None
        }
        return self.footnotes_by_id

    def _register_complex_objects(
        self,
        element: etree._Element,
        host_locator: DocumentObjectHostLocator,
    ) -> None:
        selectors = (
            (
                "content_control",
                ".//w:sdt",
                "docx_content_control_semantics_not_modeled",
                "内容控件内容可能已提取，但控件语义未建模",
                None,
            ),
            (
                "revision",
                ".//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo",
                "docx_revision_semantics_not_modeled",
                "修订文本可能已提取，但修订状态、作者和时间未建模",
                "revisions",
            ),
        )
        for object_kind, selector, code, message, capability in selectors:
            objects = element.xpath(selector, namespaces=NS)
            for item in objects:
                reference = (
                    item.get(W_VAL)
                    or item.get(f"{{{W_NS}}}id")
                    or self._local_name(item)
                )
                self._object_gap(
                    object_kind=object_kind,
                    host=host_locator,
                    code=code,
                    message=message,
                    reference=reference,
                    capability=capability,
                )
        comment_references = element.xpath(".//w:commentReference", namespaces=NS)
        for comment in comment_references:
            self._object_gap(
                object_kind="revision",
                host=host_locator,
                code="docx_comment_not_extracted",
                message="批注正文、作者和锚点范围未提取",
                reference=comment.get(f"{{{W_NS}}}id"),
                capability="comments",
            )

    def _object_gap(
        self,
        *,
        object_kind: DocumentObjectKind,
        host: DocumentObjectHostLocator,
        code: str,
        message: str,
        reference: str | None = None,
        capability: ParseCapability | None = None,
    ) -> None:
        locator = self._next_object_locator(
            object_kind=object_kind,
            host=host,
            reference=reference,
        )
        self.coverage.gap(
            code=code,
            message=message,
            locator=locator,
            capability=capability,
        )

    def _next_object_locator(
        self,
        *,
        object_kind: DocumentObjectKind,
        host: DocumentObjectHostLocator,
        reference: str | None,
    ) -> DocumentObjectLocator:
        key = (object_kind, json.dumps(host.model_dump(mode="json"), sort_keys=True))
        index = self.object_index.get(key, 0) + 1
        self.object_index[key] = index
        return DocumentObjectLocator(
            object_kind=object_kind,
            host_locator=host,
            object_index=index,
            object_reference=reference,
        )

    def _paragraph_text(self, paragraph: etree._Element) -> str:
        parts: list[str] = []
        for element in paragraph.iter():
            if self._has_ancestor(element, f"{{{W_NS}}}txbxContent", paragraph):
                continue
            if element.tag in {f"{{{W_NS}}}t", f"{{{W_NS}}}delText"}:
                parts.append(element.text or "")
            elif element.tag == f"{{{W_NS}}}tab":
                parts.append("\t")
            elif element.tag in {f"{{{W_NS}}}br", f"{{{W_NS}}}cr"}:
                parts.append("\n")
            elif element.tag in {
                f"{{{A_NS}}}blip",
                f"{{{V_NS}}}imagedata",
            }:
                parts.append("\ufffc")
            elif element.tag in {
                f"{{{W_NS}}}txbxContent",
                f"{{{W_NS}}}footnoteReference",
            }:
                parts.append("\ufffc")
        return "".join(parts)

    def _footnote_paragraph_text(self, paragraph: etree._Element) -> str:
        text = self._paragraph_text(paragraph)
        if (
            text.startswith(" ")
            and paragraph.find(".//w:footnoteRef", NS) is not None
        ):
            # Word 用 footnoteRef 后的一个空格分隔脚注编号与正文；编号不属于
            # 语义正文，规范化节点只移除这一枚确定性的排版分隔符。
            return text[1:]
        return text

    def _cell_text(self, cell: etree._Element) -> str:
        paragraphs = [
            paragraph
            for paragraph in cell.xpath(".//w:p", namespaces=NS)
            if self._nearest_ancestor(
                paragraph, f"{{{W_NS}}}tc"
            ) is cell
            and not self._has_ancestor(
                paragraph, f"{{{W_NS}}}txbxContent", cell
            )
        ]
        return "\n".join(
            text
            for paragraph in paragraphs
            if (text := self._paragraph_text(paragraph))
        )

    def _image_elements(self, element: etree._Element) -> list[etree._Element]:
        candidates = element.xpath(
            ".//a:blip[@r:embed or @r:link] | .//v:imagedata[@r:id]",
            namespaces=NS,
        )
        return [
            image
            for image in candidates
            if not self._has_ancestor(
                image, f"{{{W_NS}}}txbxContent", element
            )
        ]

    def _paragraph_style(
        self, paragraph: etree._Element, styles: dict[str, _Style]
    ) -> tuple[str | None, _Style | None]:
        style_element = paragraph.find("w:pPr/w:pStyle", NS)
        style_id = style_element.get(W_VAL) if style_element is not None else None
        return style_id, styles.get(style_id) if style_id is not None else None

    def _paragraph_outline_level(
        self, paragraph: etree._Element, style: _Style | None
    ) -> int | None:
        outline = paragraph.find("w:pPr/w:outlineLvl", NS)
        if outline is not None:
            return self._int_attribute(outline, default=9)
        return style.outline_level if style is not None else None

    def _paragraph_numbering(
        self,
        paragraph: etree._Element,
        style: _Style | None,
        numbering: dict[int, dict[int, str]],
    ) -> tuple[int | None, int | None, str | None]:
        num_id_element = paragraph.find("w:pPr/w:numPr/w:numId", NS)
        ilvl_element = paragraph.find("w:pPr/w:numPr/w:ilvl", NS)
        num_id = (
            self._int_attribute(num_id_element, default=0)
            if num_id_element is not None
            else style.num_id if style is not None else None
        )
        ilvl = (
            self._int_attribute(ilvl_element, default=0)
            if ilvl_element is not None
            else style.ilvl if style is not None else None
        )
        if num_id is None or ilvl is None:
            return None, None, None
        num_format = numbering.get(num_id, {}).get(ilvl)
        if num_format is None:
            self.coverage.gap(
                code="docx_numbering_definition_missing",
                message=f"列表 numId={num_id}, ilvl={ilvl} 缺少 numFmt 定义",
                locator=None,
            )
            return None, None, None
        return num_id, ilvl, num_format

    def _styles(self) -> dict[str, _Style]:
        if "word/styles.xml" not in self.archive.namelist():
            return {}
        root = self._xml("word/styles.xml")
        raw: dict[str, _Style] = {}
        for style in root.findall("w:style", NS):
            style_id = style.get(f"{{{W_NS}}}styleId")
            if not style_id:
                continue
            name = style.find("w:name", NS)
            based_on = style.find("w:basedOn", NS)
            outline = style.find("w:pPr/w:outlineLvl", NS)
            num_id = style.find("w:pPr/w:numPr/w:numId", NS)
            ilvl = style.find("w:pPr/w:numPr/w:ilvl", NS)
            raw[style_id] = _Style(
                style_id=style_id,
                name=name.get(W_VAL) if name is not None else None,
                based_on=based_on.get(W_VAL) if based_on is not None else None,
                outline_level=(
                    self._int_attribute(outline, default=9)
                    if outline is not None
                    else None
                ),
                num_id=(
                    self._int_attribute(num_id, default=0)
                    if num_id is not None
                    else None
                ),
                ilvl=(
                    self._int_attribute(ilvl, default=0)
                    if ilvl is not None
                    else None
                ),
            )

        resolved: dict[str, _Style] = {}

        def resolve(style_id: str, stack: set[str]) -> _Style:
            if style_id in resolved:
                return resolved[style_id]
            style = raw[style_id]
            if style.based_on and style.based_on in raw and style_id not in stack:
                parent = resolve(style.based_on, {*stack, style_id})
                style = _Style(
                    style_id=style.style_id,
                    name=style.name,
                    based_on=style.based_on,
                    outline_level=(
                        style.outline_level
                        if style.outline_level is not None
                        else parent.outline_level
                    ),
                    num_id=style.num_id if style.num_id is not None else parent.num_id,
                    ilvl=style.ilvl if style.ilvl is not None else parent.ilvl,
                )
            resolved[style_id] = style
            return style

        for style_id in raw:
            resolve(style_id, set())
        return resolved

    def _numbering_formats(self) -> dict[int, dict[int, str]]:
        if "word/numbering.xml" not in self.archive.namelist():
            return {}
        root = self._xml("word/numbering.xml")
        abstract_formats: dict[int, dict[int, str]] = {}
        for abstract in root.findall("w:abstractNum", NS):
            abstract_id = self._int_attribute_raw(
                abstract.get(f"{{{W_NS}}}abstractNumId"), default=-1
            )
            formats: dict[int, str] = {}
            for level in abstract.findall("w:lvl", NS):
                ilvl = self._int_attribute_raw(
                    level.get(f"{{{W_NS}}}ilvl"), default=0
                )
                num_format = level.find("w:numFmt", NS)
                if num_format is not None and num_format.get(W_VAL):
                    formats[ilvl] = num_format.get(W_VAL) or ""
            abstract_formats[abstract_id] = formats
        result: dict[int, dict[int, str]] = {}
        for num in root.findall("w:num", NS):
            num_id = self._int_attribute_raw(
                num.get(f"{{{W_NS}}}numId"), default=-1
            )
            abstract_id_element = num.find("w:abstractNumId", NS)
            if abstract_id_element is None:
                continue
            abstract_id = self._int_attribute(abstract_id_element, default=-1)
            result[num_id] = abstract_formats.get(abstract_id, {})
        return result

    def _relationships(self, part_path: str) -> dict[str, _Relationship]:
        directory, filename = posixpath.split(part_path)
        relationship_path = posixpath.join(
            directory, "_rels", f"{filename}.rels"
        )
        if relationship_path not in self.archive.namelist():
            return {}
        root = self._xml(relationship_path)
        relationships: dict[str, _Relationship] = {}
        for relationship in root.findall(f"{{{PKG_REL_NS}}}Relationship"):
            relationship_id = relationship.get("Id")
            target = relationship.get("Target")
            if relationship_id and target:
                relationships[relationship_id] = _Relationship(
                    target=target,
                    target_mode=relationship.get("TargetMode"),
                    relationship_type=relationship.get("Type", ""),
                )
        return relationships

    def _xml(self, path: str) -> etree._Element:
        try:
            payload = self.archive.read(path)
        except KeyError as error:
            raise DocxStructureParseError(f"DOCX 缺少必要部件：{path}") from error
        if b"<!DOCTYPE" in payload.upper():
            raise DocxStructureParseError(f"DOCX XML 不允许声明 DTD：{path}")
        try:
            return etree.fromstring(
                payload,
                parser=etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    load_dtd=False,
                    recover=False,
                    huge_tree=True,
                ),
            )
        except etree.XMLSyntaxError as error:
            raise DocxStructureParseError(f"DOCX XML 无法解析：{path}") from error

    @staticmethod
    def _resolve_target(part_path: str, target: str) -> str:
        base = posixpath.dirname(part_path)
        resolved = posixpath.normpath(posixpath.join(base, target))
        if resolved.startswith("../") or resolved.startswith("/"):
            raise DocxStructureParseError("DOCX 关系目标越出 OOXML 容器")
        return resolved

    @staticmethod
    def _table_column_count(
        table: etree._Element, rows: list[etree._Element]
    ) -> int:
        grid_count = len(table.findall("w:tblGrid/w:gridCol", NS))
        row_counts = []
        for row in rows:
            grid_before = _Parser._int_attribute(
                row.find("w:trPr/w:gridBefore", NS), default=0
            )
            grid_after = _Parser._int_attribute(
                row.find("w:trPr/w:gridAfter", NS), default=0
            )
            physical = sum(
                max(
                    1,
                    _Parser._int_attribute(
                        cell.find("w:tcPr/w:gridSpan", NS), default=1
                    ),
                )
                for cell in row.findall("w:tc", NS)
            )
            row_counts.append(grid_before + physical + grid_after)
        return max([grid_count, *row_counts], default=0)

    @staticmethod
    def _row_height(
        row_properties: etree._Element | None,
    ) -> tuple[int | None, Literal["auto", "at_least", "exact"] | None]:
        if row_properties is None:
            return None, None
        height = row_properties.find("w:trHeight", NS)
        if height is None:
            return None, None
        value = _Parser._int_attribute(height, default=0)
        rule = height.get(f"{{{W_NS}}}hRule")
        mapped = {"auto": "auto", "atLeast": "at_least", "exact": "exact"}.get(rule)
        return value, mapped

    @staticmethod
    def _heading_level_from_style(
        style_id: str | None, style: _Style | None
    ) -> int | None:
        candidates = [style_id, style.name if style is not None else None]
        for candidate in candidates:
            if not candidate:
                continue
            match = re.search(r"(?:heading|标题)\s*([1-9])$", candidate, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _image_cell_number(
        image: etree._Element, row: etree._Element
    ) -> int:
        cells = row.findall("w:tc", NS)
        ancestor = next(
            (
                candidate
                for candidate in image.iterancestors(f"{{{W_NS}}}tc")
                if candidate in cells
            ),
            None,
        )
        return cells.index(ancestor) + 1 if ancestor is not None else 1

    def _wrapper_host_locator(
        self,
        *,
        identity: _StoryIdentity,
        block_index: int,
        first_block: etree._Element | None,
    ) -> DocumentObjectHostLocator | None:
        if first_block is None:
            return None
        if first_block.tag == f"{{{W_NS}}}p":
            return DocxParagraphLocator(
                part=identity.part,
                section_index=identity.section_index,
                header_footer_type=identity.header_footer_type,
                block_index=block_index,
                paragraph_index=self.paragraph_index.get(identity, 0) + 1,
            )
        return DocxTableLocator(
            part=identity.part,
            section_index=identity.section_index,
            header_footer_type=identity.header_footer_type,
            block_index=block_index,
            table_index=self.table_index.get(identity, 0) + 1,
        )

    @staticmethod
    def _outermost_blocks(container: etree._Element) -> list[etree._Element]:
        blocks: list[etree._Element] = []
        block_tags = {f"{{{W_NS}}}p", f"{{{W_NS}}}tbl"}
        for candidate in container.xpath(".//w:p | .//w:tbl", namespaces=NS):
            ancestor = candidate.getparent()
            nested = False
            while ancestor is not None and ancestor is not container:
                if ancestor.tag in block_tags:
                    nested = True
                    break
                ancestor = ancestor.getparent()
            if not nested:
                blocks.append(candidate)
        return blocks

    @staticmethod
    def _object_kind(element: etree._Element) -> DocumentObjectKind:
        local = _Parser._local_name(element)
        if local == "sdt":
            return "content_control"
        if local in {"ins", "del", "moveFrom", "moveTo"}:
            return "revision"
        return "content_control"

    @staticmethod
    def _local_name(element: etree._Element) -> str:
        return etree.QName(element).localname

    @staticmethod
    def _has_ancestor(
        element: etree._Element,
        ancestor_tag: str,
        stop: etree._Element,
    ) -> bool:
        parent = element.getparent()
        while parent is not None and parent is not stop:
            if parent.tag == ancestor_tag:
                return True
            parent = parent.getparent()
        return False

    @staticmethod
    def _nearest_ancestor(
        element: etree._Element, ancestor_tag: str
    ) -> etree._Element | None:
        parent = element.getparent()
        while parent is not None:
            if parent.tag == ancestor_tag:
                return parent
            parent = parent.getparent()
        return None

    @staticmethod
    def _parse_cell_reference(reference: str) -> tuple[int, int]:
        match = re.fullmatch(r"R(\d+)C(\d+)", reference)
        if match is None:
            raise DocxStructureParseError(f"无效 DOCX 单元格引用：{reference}")
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _int_attribute(
        element: etree._Element | None, *, default: int
    ) -> int:
        if element is None:
            return default
        return _Parser._int_attribute_raw(element.get(W_VAL), default=default)

    @staticmethod
    def _int_attribute_raw(value: str | None, *, default: int) -> int:
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default


def parse_docx_structure(
    data: bytes,
    *,
    source_id: UUID,
    source_label: str | None = None,
    parser_profile_id: str = PARSER_PROFILE_ID,
    normalization_profile_id: str = NORMALIZATION_PROFILE_ID,
) -> ParsedMaterial:
    """按 OOXML 原序解析 DOCX，并返回带完整覆盖率与缺口的规范化解析树。"""

    source_sha256 = sha256(data).hexdigest()
    try:
        with ZipFile(BytesIO(data)) as archive:
            parser = _Parser(
                archive=archive,
                source_id=source_id,
                source_sha256=source_sha256,
                source_label=source_label,
                parser_profile_id=parser_profile_id,
                normalization_profile_id=normalization_profile_id,
            )
            return parser.parse()
    except (BadZipFile, RuntimeError) as error:
        raise DocxStructureParseError("DOCX 容器无法解析") from error
