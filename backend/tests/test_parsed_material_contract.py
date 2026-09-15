# ABOUTME: 验证规范化解析树的稳定身份、完整正文和覆盖率不变量。
# ABOUTME: 测试禁止把解析缺口或表格导航信息误表示为可下游消费的完整事实。
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.material.intake.parse_coverage import (
    CapabilityCoverage,
    ParseCoverage,
    ParseGap,
)
from sustainability_desk.material.intake.parsed_material import (
    ParsedCell,
    ParsedDocumentNode,
    ParsedImageNode,
    ParsedPageNode,
    ParsedSheetNode,
    ParsedSheetRowNode,
    ParsedMaterial,
    ParsedTableNode,
    ParsedTableRowNode,
    ParsedTextNode,
    build_parsed_material,
    build_parsed_node,
    stable_parsed_node_id,
)
from sustainability_desk.material.intake.parsed_material_locators import (
    DocumentRootLocator,
    DocumentObjectLocator,
    DocxParagraphLocator,
    DocxTableLocator,
    DocxTableRowLocator,
    EmbeddedImageLocator,
    PdfPageLocator,
    PdfTextBlockLocator,
    XlsxRowLocator,
    XlsxSheetLocator,
)

SOURCE_SHA = "1" * 64
PARSER_FINGERPRINT = "2" * 64
PARSER_PROFILE_ID = "docx-structural@1"


def _complete_coverage() -> ParseCoverage:
    return ParseCoverage(
        disposition="complete_for_declared_capabilities",
        source_units_total=4,
        source_units_parsed=4,
        text_characters_parsed=8,
        table_cells_parsed=4,
        capabilities=(
            CapabilityCoverage(
                capability="text",
                source_unit_count=2,
                parsed_unit_count=2,
            ),
            CapabilityCoverage(
                capability="tables",
                source_unit_count=2,
                parsed_unit_count=2,
            ),
        ),
    )


def test_stable_node_identity_depends_on_source_profile_and_locator_not_content() -> None:
    locator = DocxParagraphLocator(
        part="body",
        block_index=2,
        paragraph_index=2,
    )
    first = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=locator,
        parent_node_id=uuid4(),
        ordinal_path=(2,),
        kind="paragraph",
        text="原始正文",
    )
    second = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=locator,
        parent_node_id=first.parent_node_id,
        ordinal_path=(2,),
        kind="paragraph",
        text="正文内容发生变化",
    )

    assert first.node_id == second.node_id
    assert first.content_fingerprint != second.content_fingerprint


def test_parsed_material_preserves_full_text_and_validates_table_headers() -> None:
    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label="测试文档",
    )
    long_text = "气候风险与应对。" * 20_000
    paragraph = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxParagraphLocator(
            part="body",
            block_index=1,
            paragraph_index=1,
        ),
        parent_node_id=root.node_id,
        ordinal_path=(1, 1),
        kind="paragraph",
        text=long_text,
    )
    table = build_parsed_node(
        ParsedTableNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxTableLocator(
            part="body",
            block_index=2,
            table_index=1,
        ),
        parent_node_id=root.node_id,
        ordinal_path=(1, 2),
        column_count=2,
        header_row_node_ids=(),
    )
    header = build_parsed_node(
        ParsedTableRowNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxTableRowLocator(
            part="body",
            table_index=1,
            row_index=1,
        ),
        parent_node_id=table.node_id,
        ordinal_path=(1, 2, 1),
        is_header=True,
        cells=(
            ParsedCell(column_index=1, text="指标"),
            ParsedCell(column_index=2, text="数值"),
        ),
    )
    data_row = build_parsed_node(
        ParsedTableRowNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxTableRowLocator(
            part="body",
            table_index=1,
            row_index=2,
        ),
        parent_node_id=table.node_id,
        ordinal_path=(1, 2, 2),
        is_header=False,
        cells=(
            ParsedCell(column_index=1, text="温室气体排放"),
            ParsedCell(column_index=2, text="100"),
        ),
    )
    table = build_parsed_node(
        ParsedTableNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=table.locator,
        parent_node_id=root.node_id,
        ordinal_path=(1, 2),
        column_count=2,
        header_row_node_ids=(header.node_id,),
    )

    parsed = build_parsed_material(
        source_id=uuid4(),
        source_sha256=SOURCE_SHA,
        document_kind="docx",
        parser_profile_id=PARSER_PROFILE_ID,
        parser_fingerprint=PARSER_FINGERPRINT,
        normalization_profile_id="default@1",
        root_node_id=root.node_id,
        nodes=(root, paragraph, table, header, data_row),
        coverage=_complete_coverage(),
    )

    assert isinstance(parsed, ParsedMaterial)
    assert paragraph.text == long_text
    assert len(paragraph.text) > 20_000
    assert parsed.coverage.allows_negative_evidence is True


def test_incomplete_coverage_blocks_negative_evidence() -> None:
    coverage = ParseCoverage(
        disposition="incomplete_usable",
        source_units_total=10,
        source_units_parsed=9,
        text_characters_parsed=100,
        table_cells_parsed=0,
        capabilities=(
            CapabilityCoverage(
                capability="text",
                source_unit_count=10,
                parsed_unit_count=9,
            ),
        ),
        gaps=(
            ParseGap(
                code="encrypted_page",
                message="第 3 页无法提取文本",
                effect="negative_evidence_blocked",
            ),
        ),
    )

    assert coverage.allows_negative_evidence is False


def test_complete_coverage_rejects_declared_gap() -> None:
    with pytest.raises(ValidationError):
        ParseCoverage(
            disposition="complete_for_declared_capabilities",
            source_units_total=1,
            source_units_parsed=1,
            text_characters_parsed=0,
            table_cells_parsed=0,
            capabilities=(),
            gaps=(
                ParseGap(
                    code="missing_image_text",
                    message="图片未执行 OCR",
                    effect="positive_evidence_only",
                ),
            ),
        )


def test_header_footer_identity_prevents_stable_node_collisions() -> None:
    first_header = DocxParagraphLocator(
        part="header",
        section_index=1,
        header_footer_type="first",
        block_index=1,
        paragraph_index=1,
    )
    default_header = DocxParagraphLocator(
        part="header",
        section_index=1,
        header_footer_type="default",
        block_index=1,
        paragraph_index=1,
    )
    first = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=first_header,
        parent_node_id=uuid4(),
        ordinal_path=(1, 1),
        kind="paragraph",
        text="首页页眉",
        style_id="Header",
        style_name="页眉",
        outline_level=9,
    )
    default = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=default_header,
        parent_node_id=first.parent_node_id,
        ordinal_path=(1, 2),
        kind="paragraph",
        text="默认页眉",
    )

    assert first.node_id != default.node_id
    with pytest.raises(ValidationError):
        DocxParagraphLocator(
            part="footer",
            block_index=1,
            paragraph_index=1,
        )


def test_parse_gap_can_pinpoint_document_object_and_host() -> None:
    host = DocxParagraphLocator(
        part="body",
        block_index=3,
        paragraph_index=2,
    )
    gap = ParseGap(
        code="unsupported_textbox",
        message="文本框尚未解析",
        effect="negative_evidence_blocked",
        locator=DocumentObjectLocator(
            object_kind="textbox",
            host_locator=host,
            object_index=1,
            object_reference="w:txbxContent[1]",
        ),
    )

    assert gap.locator is not None
    assert gap.locator.host_locator == host


def test_xlsx_sheet_row_preserves_empty_hidden_rows_and_cell_native_metadata() -> None:
    row_locator = XlsxRowLocator(sheet_name="定量数据", row_index=1)
    row_node_id = stable_parsed_node_id(
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=row_locator,
    )
    sheet = build_parsed_node(
        ParsedSheetNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=XlsxSheetLocator(sheet_name="定量数据", sheet_index=1),
        parent_node_id=uuid4(),
        ordinal_path=(1, 1),
        label="定量数据",
        sheet_state="veryHidden",
        cell_range=None,
        row_count=1,
        column_count=0,
        cell_count=0,
        row_node_ids=(row_node_id,),
    )
    empty_row = build_parsed_node(
        ParsedSheetRowNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=row_locator,
        parent_node_id=sheet.node_id,
        ordinal_path=(1, 1, 1),
        row_index=1,
        hidden=True,
        cells=(),
    )
    formula_cell = ParsedCell(
        column_index=2,
        text="42",
        value_kind="formula",
        formula="=SUM(B2:B7)",
        cached_value=42,
        native_data_type="f",
        merged_anchor="B8",
        merged_range="B8:C9",
        row_span=2,
        column_span=2,
        hidden_row=True,
        hidden_column=False,
    )

    assert empty_row.hidden is True
    assert empty_row.cells == ()
    assert sheet.sheet_state == "veryHidden"
    assert formula_cell.native_data_type == "f"
    assert (formula_cell.row_span, formula_cell.column_span) == (2, 2)


def test_xlsx_sheet_owner_rejects_incomplete_member_cell_matrix() -> None:
    parser_profile_id = "xlsx-structural@1"
    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=parser_profile_id,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label="不完整工作表.xlsx",
    )
    row_locator = XlsxRowLocator(sheet_name="Sheet1", row_index=1)
    row_node_id = stable_parsed_node_id(
        source_sha256=SOURCE_SHA,
        parser_profile_id=parser_profile_id,
        locator=row_locator,
    )
    sheet = build_parsed_node(
        ParsedSheetNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=parser_profile_id,
        locator=XlsxSheetLocator(sheet_name="Sheet1", sheet_index=1),
        parent_node_id=root.node_id,
        ordinal_path=(1, 1),
        label="Sheet1",
        sheet_state="visible",
        cell_range="A1:B1",
        row_count=1,
        column_count=2,
        cell_count=2,
        row_node_ids=(row_node_id,),
    )
    incomplete_row = build_parsed_node(
        ParsedSheetRowNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=parser_profile_id,
        locator=row_locator,
        parent_node_id=sheet.node_id,
        ordinal_path=(1, 1, 1),
        row_index=1,
        cells=(
            ParsedCell(
                column_index=1,
                cell_reference="A1",
                text="仅一个单元格",
            ),
        ),
    )

    with pytest.raises(ValidationError, match="成员行单元格总数"):
        build_parsed_material(
            source_id=uuid4(),
            source_sha256=SOURCE_SHA,
            document_kind="xlsx",
            parser_profile_id=parser_profile_id,
            parser_fingerprint=PARSER_FINGERPRINT,
            normalization_profile_id="source-faithful@1",
            root_node_id=root.node_id,
            nodes=(root, sheet, incomplete_row),
            coverage=_complete_coverage(),
        )


def test_image_media_extraction_status_cannot_impersonate_visual_analysis() -> None:
    with pytest.raises(ValidationError):
        build_parsed_node(
            ParsedImageNode,
            source_sha256=SOURCE_SHA,
            parser_profile_id=PARSER_PROFILE_ID,
            locator=EmbeddedImageLocator(
                container_kind="docx",
                container_ref="body:block:1",
                image_index=1,
            ),
            parent_node_id=uuid4(),
            ordinal_path=(1, 1),
            media_sha256=SOURCE_SHA,
            media_extraction_status="not_attempted",
        )


def test_pdf_page_inventory_and_single_font_run_are_typed_source_facts() -> None:
    page = build_parsed_node(
        ParsedPageNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="pdf-content-stream@1",
        locator=PdfPageLocator(page=1),
        parent_node_id=uuid4(),
        ordinal_path=(1, 1),
        width_points=612,
        height_points=792,
        rotation_degrees=0,
        image_resource_count=2,
        form_xobject_count=1,
        font_resource_count=3,
        annotation_count=1,
    )
    block = build_parsed_node(
        ParsedTextNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="pdf-content-stream@1",
        locator=PdfTextBlockLocator(page=1, block_index=1),
        parent_node_id=page.node_id,
        ordinal_path=(1, 1, 1),
        kind="text_block",
        text="完整 PDF 文字运行",
        pdf_font_name="Helvetica",
        pdf_font_size_points=12,
    )

    assert page.image_resource_count == 2
    assert page.form_xobject_count == 1
    assert block.pdf_font_name == "Helvetica"
    assert block.pdf_font_size_points == 12
