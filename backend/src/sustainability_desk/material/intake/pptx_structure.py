# ABOUTME: 将 PPTX 幻灯片按阅读顺序解析为无截断、可定位的 ParsedMaterial。
# ABOUTME: 只覆盖形状文本、表格与演讲者备注；动画、母版继承样式和 OLE 对象登记为显式缺口，不做 OCR/LLM。
# ABOUTME(en): Parses PPTX slides in reading order into untruncated, locatable ParsedMaterial.
# ABOUTME(en): Covers shape text, tables and notes only; animation, master styles and OLE objects are explicit gaps.
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pptx
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.exc import PackageNotFoundError

from sustainability_desk.material.intake.parse_coverage import (
    CapabilityCoverage,
    ParseCoverage,
    ParseGap,
)
from sustainability_desk.material.intake.parsed_material import (
    ParsedCell,
    ParsedDocumentNode,
    ParsedImageNode,
    ParsedMaterial,
    ParsedNode,
    ParsedSlideNode,
    ParsedTableNode,
    ParsedTableRowNode,
    ParsedTextNode,
    build_parsed_material,
    build_parsed_node,
)
from sustainability_desk.material.intake.parsed_material_locators import (
    DocumentRootLocator,
    EmbeddedImageLocator,
    PptxNotesLocator,
    PptxShapeLocator,
    PptxSlideLocator,
    PptxTableLocator,
    PptxTableRowLocator,
)

PPTX_PARSER_PROFILE_ID = "pptx-structural@1"
PPTX_NORMALIZATION_PROFILE_ID = "pptx-reading-order@1"
PPTX_PARSER_FINGERPRINT = sha256(
    (
        f"python-pptx:{pptx.__version__};"
        f"profile:{PPTX_PARSER_PROFILE_ID};"
        "reading-order-top-left;tables;notes;no-ocr"
    ).encode("utf-8")
).hexdigest()


class PptxStructureParseError(ValueError):
    """PPTX 容器无法建立最低限度结构时的确定性错误。"""


def _shape_reading_order_key(shape: object) -> tuple[int, int]:
    """按视觉阅读顺序排序：先纵坐标（top）后横坐标（left）。"""

    top = getattr(shape, "top", None)
    left = getattr(shape, "left", None)
    return (int(top) if top is not None else 0, int(left) if left is not None else 0)


def parse_pptx_structure(
    data: bytes,
    *,
    source_id: UUID,
    source_label: str | None = None,
) -> ParsedMaterial:
    """按阅读顺序解析 PPTX 幻灯片结构；不做 OCR/LLM，仅确定性提取。"""

    source_sha256 = sha256(data).hexdigest()
    try:
        presentation = Presentation(BytesIO(data))
    except (PackageNotFoundError, KeyError, ValueError, OSError) as error:
        raise PptxStructureParseError("PPTX 容器无法解析") from error

    slides = list(presentation.slides)
    if not slides:
        raise PptxStructureParseError("PPTX 不包含幻灯片")

    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=source_sha256,
        parser_profile_id=PPTX_PARSER_PROFILE_ID,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label=source_label,
    )
    nodes: list[ParsedNode] = [root]
    gaps: list[ParseGap] = []
    text_characters = 0
    table_cells = 0
    text_shape_units_total = 0
    text_shape_units_parsed = 0
    table_units_total = 0
    table_units_parsed = 0
    image_units_total = 0
    image_units_parsed = 0

    for slide_number, slide in enumerate(slides, start=1):
        slide_locator = PptxSlideLocator(slide_number=slide_number)
        slide_node = build_parsed_node(
            ParsedSlideNode,
            source_sha256=source_sha256,
            parser_profile_id=PPTX_PARSER_PROFILE_ID,
            locator=slide_locator,
            parent_node_id=root.node_id,
            ordinal_path=(1, slide_number),
            label=None,
        )
        nodes.append(slide_node)

        ordered_shapes = sorted(
            enumerate(slide.shapes, start=1),
            key=lambda item: _shape_reading_order_key(item[1]),
        )
        child_ordinal = 1
        slide_has_text = False

        for shape_index, shape in ordered_shapes:
            if getattr(shape, "has_table", False):
                table_units_total += 1
                table = shape.table
                column_count = len(table.columns)
                if column_count < 1:
                    gaps.append(
                        ParseGap(
                            code="pptx_table_without_columns",
                            message=f"第 {slide_number} 页表格无法确定列数",
                            effect="negative_evidence_blocked",
                            locator=PptxTableLocator(
                                slide_number=slide_number, shape_index=shape_index
                            ),
                        )
                    )
                    child_ordinal += 1
                    continue
                table_units_parsed += 1
                table_locator = PptxTableLocator(
                    slide_number=slide_number, shape_index=shape_index
                )
                table_node = build_parsed_node(
                    ParsedTableNode,
                    source_sha256=source_sha256,
                    parser_profile_id=PPTX_PARSER_PROFILE_ID,
                    locator=table_locator,
                    parent_node_id=slide_node.node_id,
                    ordinal_path=(1, slide_number, child_ordinal),
                    column_count=column_count,
                    header_row_node_ids=(),
                )
                nodes.append(table_node)
                for row_index, row in enumerate(table.rows, start=1):
                    cells = tuple(
                        ParsedCell(
                            column_index=column_index,
                            text=" ".join((cell.text or "").split()),
                        )
                        for column_index, cell in enumerate(row.cells, start=1)
                    )
                    table_cells += len(cells)
                    row_node = build_parsed_node(
                        ParsedTableRowNode,
                        source_sha256=source_sha256,
                        parser_profile_id=PPTX_PARSER_PROFILE_ID,
                        locator=PptxTableRowLocator(
                            slide_number=slide_number,
                            shape_index=shape_index,
                            row_index=row_index,
                        ),
                        parent_node_id=table_node.node_id,
                        ordinal_path=(1, slide_number, child_ordinal, row_index),
                        is_header=False,
                        cells=cells,
                    )
                    nodes.append(row_node)
                slide_has_text = True
                child_ordinal += 1
                continue

            if getattr(shape, "has_text_frame", False):
                text_shape_units_total += 1
                raw_text = "\n".join(
                    paragraph_text
                    for paragraph in shape.text_frame.paragraphs
                    if (
                        paragraph_text := "".join(
                            run.text for run in paragraph.runs
                        )
                    )
                )
                text = raw_text.strip()
                if text:
                    text_shape_units_parsed += 1
                    text_characters += len(text)
                    text_node = build_parsed_node(
                        ParsedTextNode,
                        source_sha256=source_sha256,
                        parser_profile_id=PPTX_PARSER_PROFILE_ID,
                        locator=PptxShapeLocator(
                            slide_number=slide_number, shape_index=shape_index
                        ),
                        parent_node_id=slide_node.node_id,
                        ordinal_path=(1, slide_number, child_ordinal),
                        kind="text_block",
                        text=text,
                    )
                    nodes.append(text_node)
                    slide_has_text = True
                    child_ordinal += 1
                continue

            if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE:
                image_units_total += 1
                image_locator = EmbeddedImageLocator(
                    container_kind="pptx",
                    container_ref=f"slide:{slide_number}",
                    image_index=shape_index,
                )
                media_sha256: str | None = None
                media_extraction_status = "failed"
                try:
                    media = shape.image.blob
                except Exception:
                    media = None
                if media:
                    media_sha256 = sha256(media).hexdigest()
                    media_extraction_status = "complete"
                    image_units_parsed += 1
                image_node = build_parsed_node(
                    ParsedImageNode,
                    source_sha256=source_sha256,
                    parser_profile_id=PPTX_PARSER_PROFILE_ID,
                    locator=image_locator,
                    parent_node_id=slide_node.node_id,
                    ordinal_path=(1, slide_number, child_ordinal),
                    media_sha256=media_sha256,
                    alt_text=None,
                    caption=None,
                    media_extraction_status=media_extraction_status,
                )
                nodes.append(image_node)
                gaps.append(
                    ParseGap(
                        code="pptx_image_semantics_unparsed",
                        message=(
                            f"第 {slide_number} 页图片 {shape_index} 已提取原始媒体（如可用），"
                            "但未解析图片语义，也未执行 OCR"
                        ),
                        effect="negative_evidence_blocked",
                        locator=image_locator,
                    )
                )
                child_ordinal += 1
                continue

            # 其余形状（如图表、SmartArt、OLE 嵌入对象、连接线等）未建模；
            # 显式登记缺口，不静默丢弃，也不伪装为完整覆盖。
            gaps.append(
                ParseGap(
                    code="pptx_shape_semantics_not_modeled",
                    message=(
                        f"第 {slide_number} 页形状 {shape_index}"
                        f"（{getattr(shape, 'shape_type', '未知类型')}）未建模，"
                        "可能包含图表、SmartArt、OLE 嵌入对象或动画"
                    ),
                    effect="negative_evidence_blocked",
                    locator=slide_locator,
                )
            )
            child_ordinal += 1

        if not slide_has_text:
            gaps.append(
                ParseGap(
                    code="pptx_slide_without_extractable_text",
                    message=f"第 {slide_number} 页未提取到可读文本或表格，可能为纯图片页",
                    effect="positive_evidence_only",
                    locator=slide_locator,
                )
            )

        if getattr(slide, "has_notes_slide", False):
            notes_text = "\n".join(
                paragraph_text
                for paragraph in slide.notes_slide.notes_text_frame.paragraphs
                if (
                    paragraph_text := "".join(
                        run.text for run in paragraph.runs
                    )
                )
            ).strip()
            if notes_text:
                text_characters += len(notes_text)
                notes_node = build_parsed_node(
                    ParsedTextNode,
                    source_sha256=source_sha256,
                    parser_profile_id=PPTX_PARSER_PROFILE_ID,
                    locator=PptxNotesLocator(slide_number=slide_number),
                    parent_node_id=slide_node.node_id,
                    ordinal_path=(1, slide_number, child_ordinal),
                    kind="text_block",
                    text=notes_text,
                )
                nodes.append(notes_node)

    capabilities = (
        CapabilityCoverage(
            capability="text",
            source_unit_count=text_shape_units_total,
            parsed_unit_count=text_shape_units_parsed,
        ),
        CapabilityCoverage(
            capability="tables",
            source_unit_count=table_units_total,
            parsed_unit_count=table_units_parsed,
        ),
        CapabilityCoverage(
            capability="images",
            source_unit_count=image_units_total,
            parsed_unit_count=image_units_parsed,
        ),
    )
    source_units_total = text_shape_units_total + table_units_total + image_units_total
    source_units_parsed = text_shape_units_parsed + table_units_parsed + image_units_parsed
    disposition = (
        "complete_for_declared_capabilities"
        if not gaps and source_units_parsed == source_units_total
        else "incomplete_usable"
    )
    coverage = ParseCoverage(
        disposition=disposition,
        source_units_total=source_units_total,
        source_units_parsed=source_units_parsed,
        text_characters_parsed=text_characters,
        table_cells_parsed=table_cells,
        capabilities=capabilities,
        gaps=tuple(gaps),
    )
    return build_parsed_material(
        source_id=source_id,
        source_sha256=source_sha256,
        document_kind="pptx",
        parser_profile_id=PPTX_PARSER_PROFILE_ID,
        parser_fingerprint=PPTX_PARSER_FINGERPRINT,
        normalization_profile_id=PPTX_NORMALIZATION_PROFILE_ID,
        root_node_id=root.node_id,
        nodes=tuple(nodes),
        coverage=coverage,
    )
