# ABOUTME: 验证 DOCX 结构解析的原序、无截断、合并单元格、媒体指纹与显式缺口。
# ABOUTME: 测试使用最小 OOXML fixture，避免 python-docx 高层集合掩盖真实 document body 顺序。
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sustainability_desk.material.intake.docx_structure import parse_docx_structure
from sustainability_desk.material.intake.parsed_material import (
    ParsedImageNode,
    ParsedSectionNode,
    ParsedTableNode,
    ParsedTableRowNode,
    ParsedTextNode,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def _docx(
    body: str,
    *,
    styles: str | None = None,
    numbering: str | None = None,
    relationships: str | None = None,
    extra_parts: dict[str, bytes | str] | None = None,
) -> bytes:
    document = (
        f'<w:document xmlns:w="{W}" xmlns:r="{R}" '
        f'xmlns:a="{A}" xmlns:wp="{WP}"><w:body>{body}</w:body></w:document>'
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
        if styles is not None:
            archive.writestr("word/styles.xml", styles)
        if numbering is not None:
            archive.writestr("word/numbering.xml", numbering)
        if relationships is not None:
            archive.writestr("word/_rels/document.xml.rels", relationships)
        for path, content in (extra_parts or {}).items():
            archive.writestr(path, content)
    return output.getvalue()


def _paragraph(text: str, properties: str = "") -> str:
    return f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_docx_preserves_long_text_and_body_child_order() -> None:
    long_text = "气候风险。" * 20_000
    styles = (
        f'<w:styles xmlns:w="{W}">'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="标题 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        "</w:style></w:styles>"
    )
    body = (
        _paragraph(
            "气候治理",
            '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>',
        )
        + _paragraph(long_text)
        + (
            "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
            "<w:tr><w:trPr><w:tblHeader/><w:cantSplit/>"
            '<w:trHeight w:val="360" w:hRule="exact"/></w:trPr>'
            "<w:tc><w:p><w:r><w:t>指标</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>数值</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
        )
        + _paragraph("表后正文")
        + "<w:sectPr/>"
    )

    parsed = parse_docx_structure(
        _docx(body, styles=styles),
        source_id=uuid4(),
        source_label="顺序测试",
    )

    body_nodes = [
        node
        for node in parsed.nodes
        if len(node.ordinal_path) == 2
        and not isinstance(node, ParsedSectionNode)
        and node.kind != "document"
    ]
    assert [node.kind for node in body_nodes] == [
        "heading",
        "paragraph",
        "table",
        "paragraph",
    ]
    heading = body_nodes[0]
    assert isinstance(heading, ParsedTextNode)
    assert heading.style_id == "Heading1"
    assert heading.style_name == "标题 1"
    assert heading.outline_level == 0
    assert heading.heading_level == 1
    assert isinstance(body_nodes[1], ParsedTextNode)
    assert body_nodes[1].text == long_text
    assert len(body_nodes[1].text) == len(long_text)
    table = body_nodes[2]
    assert isinstance(table, ParsedTableNode)
    row = next(
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTableRowNode)
    )
    assert table.header_row_node_ids == (row.node_id,)
    assert row.repeat_as_header is True
    assert row.cannot_split is True
    assert row.height_twips == 360
    assert row.height_rule == "exact"
    assert parsed.status == "complete"


def test_docx_preserves_list_identity_merge_metadata_and_embedded_media_sha() -> None:
    media = b"\x89PNG\r\n\x1a\nfixture-image"
    numbering = (
        f'<w:numbering xmlns:w="{W}">'
        '<w:abstractNum w:abstractNumId="7"><w:lvl w:ilvl="0">'
        '<w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="11"><w:abstractNumId w:val="7"/></w:num>'
        "</w:numbering>"
    )
    relationships = (
        f'<Relationships xmlns="{PR}"><Relationship Id="rImg" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/image1.png"/></Relationships>'
    )
    body = (
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="11"/></w:numPr></w:pPr>'
        "<w:r><w:t>供应链尽责管理</w:t></w:r></w:p>"
        "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
        "<w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>'
        "</w:tcPr><w:p><w:r><w:t>合并指标</w:t></w:r></w:p></w:tc>"
        "</w:tr><w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr>'
        "<w:p/></w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:drawing><wp:inline>"
        '<wp:docPr id="1" name="证据图片" descr="排放设施"/>'
        '<a:graphic><a:graphicData><a:blip r:embed="rImg"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        "<w:sectPr/>"
    )

    parsed = parse_docx_structure(
        _docx(
            body,
            numbering=numbering,
            relationships=relationships,
            extra_parts={"word/media/image1.png": media},
        ),
        source_id=uuid4(),
    )

    list_item = next(
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode) and node.kind == "list_item"
    )
    assert (list_item.list_num_id, list_item.list_ilvl, list_item.list_num_format) == (
        11,
        0,
        "bullet",
    )
    rows = [
        node for node in parsed.nodes if isinstance(node, ParsedTableRowNode)
    ]
    anchor = rows[0].cells[0]
    assert anchor.merged_anchor == "R1C1"
    assert anchor.merged_range == "R1C1:R2C2"
    assert anchor.row_span == 2
    assert anchor.column_span == 2
    for row in rows:
        assert len(row.cells) == 2
        assert all(cell.merged_anchor == "R1C1" for cell in row.cells)
        assert all(cell.merged_range == "R1C1:R2C2" for cell in row.cells)
    image = next(
        node for node in parsed.nodes if isinstance(node, ParsedImageNode)
    )
    assert image.media_sha256 == sha256(media).hexdigest()
    assert image.alt_text == "排放设施"
    assert image.media_extraction_status == "complete"
    assert image.parent_node_id is not None
    assert {gap.code for gap in parsed.coverage.gaps} == {
        "docx_image_semantics_unparsed"
    }
    image_coverage = next(
        capability
        for capability in parsed.coverage.capabilities
        if capability.capability == "images"
    )
    assert image_coverage.source_unit_count == 1
    assert image_coverage.parsed_unit_count == 1
    assert image_coverage.complete is True
    assert parsed.status == "complete_with_gaps"
    assert parsed.coverage.allows_negative_evidence is False


def test_docx_keeps_header_footer_as_independent_story_and_registers_gaps() -> None:
    relationships = (
        f'<Relationships xmlns="{PR}">'
        '<Relationship Id="rHeader" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
        'Target="header1.xml"/>'
        '<Relationship Id="rFooter" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
        'Target="footer1.xml"/></Relationships>'
    )
    body = (
        "<w:sdt><w:sdtContent>"
        + _paragraph("控件内正文")
        + "</w:sdtContent></w:sdt>"
        '<w:p><w:ins w:id="4" w:author="审核人"><w:r><w:t>新增披露</w:t>'
        "</w:r></w:ins><w:r><w:footnoteReference w:id=\"2\"/></w:r>"
        "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>文本框事实</w:t>"
        "</w:r></w:p></w:txbxContent></w:pict></w:r></w:p>"
        '<w:sectPr><w:headerReference w:type="default" r:id="rHeader"/>'
        '<w:footerReference w:type="first" r:id="rFooter"/></w:sectPr>'
    )
    header = (
        f'<w:hdr xmlns:w="{W}" xmlns:r="{R}">'
        + _paragraph("可持续发展报告")
        + "</w:hdr>"
    )
    footer = (
        f'<w:ftr xmlns:w="{W}" xmlns:r="{R}">'
        + _paragraph("报告期 2025")
        + "</w:ftr>"
    )
    footnotes = (
        f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="2">'
        + _paragraph("脚注中的补充证据")
        + "</w:footnote></w:footnotes>"
    )

    parsed = parse_docx_structure(
        _docx(
            body,
            relationships=relationships,
            extra_parts={
                "word/header1.xml": header,
                "word/footer1.xml": footer,
                "word/footnotes.xml": footnotes,
            },
        ),
        source_id=uuid4(),
    )

    stories = [
        node
        for node in parsed.nodes
        if isinstance(node, ParsedSectionNode)
        and node.locator.kind == "docx_story"
    ]
    assert len(stories) == 2
    story = next(node for node in stories if node.locator.part == "header")
    assert story.locator.kind == "docx_story"
    assert story.locator.part == "header"
    header_text = next(
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode) and node.parent_node_id == story.node_id
    )
    assert header_text.text == "可持续发展报告"
    assert header_text.locator.part == "header"
    assert header_text.locator.section_index == 1
    assert header_text.locator.header_footer_type == "default"
    footer_story = next(node for node in stories if node.locator.part == "footer")
    footer_text = next(
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode)
        and node.parent_node_id == footer_story.node_id
    )
    assert footer_text.text == "报告期 2025"
    assert footer_text.locator.header_footer_type == "first"
    extracted_object_text = {
        node.text
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode) and node.kind == "text_block"
    }
    assert "文本框事实" in extracted_object_text
    assert "脚注中的补充证据" in extracted_object_text
    gap_codes = {gap.code for gap in parsed.coverage.gaps}
    assert {
        "docx_content_control_semantics_not_modeled",
        "docx_revision_semantics_not_modeled",
        "docx_textbox_layout_unmodeled",
    } <= gap_codes
    assert "docx_footnote_not_extracted" not in gap_codes
    assert all(gap.locator is not None for gap in parsed.coverage.gaps)
    assert parsed.status == "complete_with_gaps"
    assert parsed.coverage.allows_negative_evidence is False


def test_docx_missing_image_bytes_are_failed_media_fact_and_explicit_gap() -> None:
    relationships = (
        f'<Relationships xmlns="{PR}"><Relationship Id="rMissing" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/missing.png"/></Relationships>'
    )
    body = (
        "<w:p><w:r><w:drawing><wp:inline>"
        '<wp:docPr id="1" name="缺失图片"/>'
        '<a:graphic><a:graphicData><a:blip r:embed="rMissing"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        "<w:sectPr/>"
    )

    parsed = parse_docx_structure(
        _docx(body, relationships=relationships),
        source_id=uuid4(),
    )

    image = next(
        node for node in parsed.nodes if isinstance(node, ParsedImageNode)
    )
    assert image.media_sha256 is None
    assert image.media_extraction_status == "failed"
    assert {gap.code for gap in parsed.coverage.gaps} == {
        "docx_image_part_missing"
    }
    assert parsed.status == "complete_with_gaps"


def test_docx_footnote_preserves_all_264_characters_as_located_text_nodes() -> None:
    footnote_text = "脚注证据" * 66
    assert len(footnote_text) == 264
    body = (
        '<w:p><w:r><w:t>正文引用</w:t></w:r>'
        '<w:r><w:footnoteReference w:id="11"/></w:r></w:p>'
        "<w:sectPr/>"
    )
    footnotes = (
        f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="11">'
        + (
            "<w:p><w:r><w:footnoteRef/></w:r>"
            f'<w:r><w:t xml:space="preserve"> {footnote_text[:132]}</w:t></w:r>'
            "</w:p>"
        )
        + _paragraph(footnote_text[132:])
        + "</w:footnote></w:footnotes>"
    )

    parsed = parse_docx_structure(
        _docx(
            body,
            extra_parts={"word/footnotes.xml": footnotes},
        ),
        source_id=uuid4(),
    )

    footnote_nodes = [
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode)
        and node.kind == "text_block"
        and node.locator.kind == "document_object"
        and node.locator.object_kind == "footnote"
    ]
    assert "".join(node.text for node in footnote_nodes) == footnote_text
    assert sum(len(node.text) for node in footnote_nodes) == 264
    assert all(node.parent_node_id is not None for node in footnote_nodes)
    assert parsed.status == "complete"


def test_docx_textbox_table_is_not_flattened_into_text_block() -> None:
    body = (
        "<w:p><w:r><w:pict><w:txbxContent>"
        + _paragraph("文本框段落")
        + (
            "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid><w:tr><w:tc>"
            + _paragraph("表格结构事实")
            + "</w:tc></w:tr></w:tbl>"
        )
        + "</w:txbxContent></w:pict></w:r></w:p><w:sectPr/>"
    )

    parsed = parse_docx_structure(_docx(body), source_id=uuid4())

    textbox_text = [
        node.text
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode)
        and node.kind == "text_block"
        and node.locator.kind == "document_object"
        and node.locator.object_kind == "textbox"
    ]
    assert textbox_text == ["文本框段落"]
    assert "表格结构事实" not in textbox_text
    assert {
        "docx_textbox_layout_unmodeled",
        "docx_textbox_table_structure_unmodeled",
    } <= {gap.code for gap in parsed.coverage.gaps}
