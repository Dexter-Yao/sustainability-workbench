# ABOUTME: 验证 PDF 结构解析无页数或正文截断，并显式暴露图片、注释与版面风险。
# ABOUTME: 测试同时约束节点定位稳定、空白页覆盖、扫描页 OCR 触发与降级，以及原生内容不得伪装成来源标题。
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text

from sustainability_desk.material.intake.parsed_material import (
    ParsedImageNode,
    ParsedPageNode,
    ParsedTextNode,
)
from sustainability_desk.material.intake.parsed_material_locators import (
    PdfPageLocator,
    PdfTextBlockLocator,
)
from sustainability_desk.material.intake.pdf_structure import parse_pdf_structure
from sustainability_desk.material.intake.scanned_pdf_ocr import OcrPageText, ScannedPdfOcrError


def _escape_pdf_text(value: str) -> bytes:
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("ascii")
    )


def _text_pdf(page_texts: list[str]) -> bytes:
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_refs: list[str] = []
    for page_index, text in enumerate(page_texts):
        page_object_number = len(objects) + 1
        content_object_number = page_object_number + 1
        page_refs.append(f"{page_object_number} 0 R")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {content_object_number} 0 R >>"
            ).encode("ascii")
        )
        if text:
            stream = (
                b"BT /F1 12 Tf 40 740 Td ("
                + _escape_pdf_text(text)
                + b") Tj ET"
            )
        else:
            stream = b""
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    objects[1] = (
        f"<< /Type /Pages /Count {len(page_refs)} /Kids "
        f"[{' '.join(page_refs)}] >>"
    ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _add_image_and_annotation(data: bytes) -> bytes:
    image_buffer = BytesIO()
    Image.new("RGB", (24, 24), color=(20, 120, 80)).save(
        image_buffer,
        format="PDF",
    )
    image_page = PdfReader(BytesIO(image_buffer.getvalue())).pages[0]
    writer = PdfWriter(clone_from=BytesIO(data))
    writer.pages[0].merge_page(image_page)
    writer.add_annotation(
        0,
        Text(rect=(10, 10, 30, 30), text="需要复核的批注"),
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_parser_keeps_all_fifty_pages_and_stable_content_stream_locators() -> None:
    data = _text_pdf([f"Page {page}" for page in range(1, 51)])

    first = parse_pdf_structure(data, source_id=uuid4())
    second = parse_pdf_structure(data, source_id=uuid4())
    pages = [node for node in first.nodes if isinstance(node, ParsedPageNode)]
    blocks = [node for node in first.nodes if isinstance(node, ParsedTextNode)]

    assert len(pages) == 50
    assert len(blocks) == 50
    assert [page.locator for page in pages] == [
        PdfPageLocator(page=page) for page in range(1, 51)
    ]
    assert [block.locator for block in blocks] == [
        PdfTextBlockLocator(page=page, block_index=1)
        for page in range(1, 51)
    ]
    assert [node.node_id for node in first.nodes] == [
        node.node_id for node in second.nodes
    ]
    assert first.status == "complete_with_gaps"
    assert {
        gap.code for gap in first.coverage.gaps
    } == {"pdf_visual_layout_unverified"}


def test_pdf_parser_does_not_truncate_a_page_larger_than_twenty_thousand_chars() -> None:
    text = "A" * 25_500

    parsed = parse_pdf_structure(_text_pdf([text]), source_id=uuid4())
    blocks = [node for node in parsed.nodes if isinstance(node, ParsedTextNode)]

    assert "".join(block.text for block in blocks) == text
    assert parsed.coverage.text_characters_parsed == len(text)
    assert all(block.kind == "text_block" for block in blocks)


def test_pdf_parser_coalesces_adjacent_runs_with_the_same_font_without_text_loss() -> None:
    data = _text_pdf(["consecutive text run"])

    parsed = parse_pdf_structure(data, source_id=uuid4())
    blocks = [node for node in parsed.nodes if isinstance(node, ParsedTextNode)]

    assert "".join(block.text for block in blocks) == "consecutive text run"
    assert len(blocks) == 1


def test_pdf_image_and_annotation_are_modeled_without_claiming_complete_coverage() -> None:
    data = _add_image_and_annotation(_text_pdf(["Text and image"]))

    parsed = parse_pdf_structure(data, source_id=uuid4())
    images = [node for node in parsed.nodes if isinstance(node, ParsedImageNode)]
    gap_codes = {gap.code for gap in parsed.coverage.gaps}

    assert len(images) == 1
    assert images[0].media_sha256 is not None
    assert images[0].media_extraction_status == "complete"
    page = next(node for node in parsed.nodes if isinstance(node, ParsedPageNode))
    assert page.image_resource_count == 1
    assert page.annotation_count == 1
    assert "pdf_image_semantics_unparsed" in gap_codes
    assert "pdf_annotations_unparsed" in gap_codes
    assert parsed.status == "complete_with_gaps"
    assert parsed.coverage.allows_negative_evidence is False


def test_blank_and_mixed_pages_have_explicit_text_coverage_without_fake_blocks() -> None:
    data = _text_pdf(["", "Only the second page has text", ""])

    parsed = parse_pdf_structure(data, source_id=uuid4())
    pages = [node for node in parsed.nodes if isinstance(node, ParsedPageNode)]
    blocks = [node for node in parsed.nodes if isinstance(node, ParsedTextNode)]
    text_coverage = next(
        capability
        for capability in parsed.coverage.capabilities
        if capability.capability == "text"
    )

    assert len(pages) == 3
    assert [block.text for block in blocks] == ["Only the second page has text"]
    assert text_coverage.source_unit_count == 3
    assert text_coverage.parsed_unit_count == 3
    assert parsed.status == "complete_with_gaps"
    assert {
        gap.code for gap in parsed.coverage.gaps
    } == {"pdf_visual_layout_unverified"}
    layout_coverage = next(
        capability
        for capability in parsed.coverage.capabilities
        if capability.capability == "layout"
    )
    assert layout_coverage.source_unit_count == 3
    assert layout_coverage.parsed_unit_count == 2


def test_fully_blank_pdf_can_be_complete_for_declared_capabilities() -> None:
    parsed = parse_pdf_structure(_text_pdf(["", ""]), source_id=uuid4())

    assert parsed.status == "complete"
    assert parsed.coverage.gaps == ()
    assert parsed.coverage.allows_negative_evidence is True


def test_scanned_page_without_image_does_not_trigger_ocr() -> None:
    """真正空白、无图片资源的页不得触发 OCR 子进程调用。"""
    data = _text_pdf(["", "second page has text"])

    with patch(
        "sustainability_desk.material.intake.pdf_structure.ocr_pdf_pages"
    ) as mock_ocr:
        parsed = parse_pdf_structure(data, source_id=uuid4())

    mock_ocr.assert_not_called()
    assert parsed.status == "complete_with_gaps"
    assert "pdf_scanned_page_ocr_applied" not in {
        gap.code for gap in parsed.coverage.gaps
    }


def test_scanned_page_with_image_and_no_text_triggers_ocr_and_merges_text_node() -> None:
    """无文本层但含图片资源的页必须触发 OCR，并把识别文字并入解析树的文本节点。"""
    data = _add_image_and_annotation(_text_pdf(["", "second page has native text"]))

    with patch(
        "sustainability_desk.material.intake.pdf_structure.ocr_pdf_pages"
    ) as mock_ocr:
        mock_ocr.return_value = {
            0: OcrPageText(page_number=1, text="识别出的扫描文字", mean_confidence=0.98)
        }
        parsed = parse_pdf_structure(data, source_id=uuid4())

    mock_ocr.assert_called_once_with(data, [0])
    gap_codes = {gap.code for gap in parsed.coverage.gaps}
    assert "pdf_scanned_page_ocr_applied" in gap_codes
    assert "pdf_text_extraction_failed" not in gap_codes
    blocks = [
        node
        for node in parsed.nodes
        if isinstance(node, ParsedTextNode) and node.locator.page == 1
    ]
    assert len(blocks) == 1
    assert blocks[0].text == "识别出的扫描文字"
    assert parsed.coverage.text_characters_parsed == len(
        "识别出的扫描文字second page has native text"
    )


def test_scanned_page_ocr_failure_keeps_negative_evidence_blocked_gap() -> None:
    """OCR 子进程失败或超时必须保留“无法提取文字”缺口语义，不得伪装为已解析。"""
    data = _add_image_and_annotation(_text_pdf([""]))

    with patch(
        "sustainability_desk.material.intake.pdf_structure.ocr_pdf_pages"
    ) as mock_ocr:
        mock_ocr.return_value = {0: ScannedPdfOcrError("OCR 子进程超时")}
        parsed = parse_pdf_structure(data, source_id=uuid4())

    gap_codes = {gap.code for gap in parsed.coverage.gaps}
    assert "pdf_scanned_page_ocr_failed" in gap_codes
    failed_gap = next(
        gap for gap in parsed.coverage.gaps if gap.code == "pdf_scanned_page_ocr_failed"
    )
    assert failed_gap.effect == "negative_evidence_blocked"
    assert parsed.coverage.allows_negative_evidence is False
    blocks = [node for node in parsed.nodes if isinstance(node, ParsedTextNode)]
    assert blocks == []


def test_scanned_page_ocr_returns_no_text_keeps_negative_evidence_blocked_gap() -> None:
    """OCR 成功运行但未识别到任何文字时，同样不得当作完整覆盖。"""
    data = _add_image_and_annotation(_text_pdf([""]))

    with patch(
        "sustainability_desk.material.intake.pdf_structure.ocr_pdf_pages"
    ) as mock_ocr:
        mock_ocr.return_value = {
            0: OcrPageText(page_number=1, text="", mean_confidence=None)
        }
        parsed = parse_pdf_structure(data, source_id=uuid4())

    gap_codes = {gap.code for gap in parsed.coverage.gaps}
    assert "pdf_scanned_page_ocr_empty" in gap_codes
    empty_gap = next(
        gap for gap in parsed.coverage.gaps if gap.code == "pdf_scanned_page_ocr_empty"
    )
    assert empty_gap.effect == "negative_evidence_blocked"
