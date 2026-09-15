# ABOUTME: 将 PDF 页面、内容流文字运行和图片资源解析为无截断 ParsedMaterial。
# ABOUTME: 无法可靠恢复的视觉版面、图片语义和批注必须形成 ParseGap，不能伪装为完整覆盖。
# ABOUTME(en): Parses PDF pages, content-stream text runs and image resources into untruncated ParsedMaterial.
# ABOUTME(en): Layout, image semantics and annotations that cannot be recovered reliably must become ParseGaps.
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any
from uuid import UUID

import pypdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from sustainability_desk.material.intake.parse_coverage import (
    CapabilityCoverage,
    ParseCoverage,
    ParseGap,
)
from sustainability_desk.material.intake.parsed_material import (
    ParsedDocumentNode,
    ParsedImageNode,
    ParsedMaterial,
    ParsedNode,
    ParsedPageNode,
    ParsedTextNode,
    build_parsed_material,
    build_parsed_node,
)
from sustainability_desk.material.intake.parsed_material_locators import (
    DocumentRootLocator,
    EmbeddedImageLocator,
    PdfPageLocator,
    PdfTextBlockLocator,
)
from sustainability_desk.material.intake.scanned_pdf_ocr import ScannedPdfOcrError, ocr_pdf_pages

PDF_PARSER_PROFILE_ID = "pdf-content-stream@1"
PDF_NORMALIZATION_PROFILE_ID = "pdf-structure@1"
PDF_PARSER_FINGERPRINT = sha256(
    (
        f"pypdf:{pypdf.__version__};"
        f"profile:{PDF_PARSER_PROFILE_ID};"
        "visitor-text-runs;resource-inventory;scanned-page-ocr"
    ).encode("utf-8")
).hexdigest()


class PdfStructureParseError(ValueError):
    """PDF 容器无法建立最低限度结构时的确定性错误。"""


@dataclass(frozen=True)
class _TextRun:
    text: str
    font_name: str | None
    font_size_points: float | None


@dataclass(frozen=True)
class _PageInventory:
    image_resource_count: int | None
    form_xobject_count: int | None
    font_resource_count: int | None
    annotation_count: int | None
    resource_inventory_failed: bool
    annotation_inventory_failed: bool


def _utf8_safe(value: object) -> str:
    text = str(value).replace("\x00", " ")
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _resolve_pdf_object(value: Any) -> Any:
    get_object = getattr(value, "get_object", None)
    return get_object() if callable(get_object) else value


def _count_mapping(value: Any) -> int:
    resolved = _resolve_pdf_object(value)
    return len(resolved) if resolved is not None else 0


def _page_inventory(page: Any) -> _PageInventory:
    image_count: int | None = None
    form_count: int | None = None
    font_count: int | None = None
    resource_failed = False
    try:
        resources = _resolve_pdf_object(page.get_inherited("/Resources", {}))
        fonts = resources.get("/Font", {}) if resources else {}
        font_count = _count_mapping(fonts)
        xobjects = _resolve_pdf_object(resources.get("/XObject", {})) if resources else {}
        image_count = 0
        form_count = 0
        for reference in xobjects.values():
            resource = _resolve_pdf_object(reference)
            subtype = str(resource.get("/Subtype", ""))
            if subtype == "/Image":
                image_count += 1
            elif subtype == "/Form":
                form_count += 1
    except Exception:
        resource_failed = True

    annotation_count: int | None = None
    annotation_failed = False
    try:
        annotations = _resolve_pdf_object(page.get("/Annots", []))
        annotation_count = len(annotations) if annotations is not None else 0
    except Exception:
        annotation_failed = True

    return _PageInventory(
        image_resource_count=image_count,
        form_xobject_count=form_count,
        font_resource_count=font_count,
        annotation_count=annotation_count,
        resource_inventory_failed=resource_failed,
        annotation_inventory_failed=annotation_failed,
    )


def _font_name(font_dictionary: Any) -> str | None:
    if not font_dictionary:
        return None
    try:
        font = _resolve_pdf_object(font_dictionary)
        raw_name = font.get("/BaseFont")
    except Exception:
        return None
    if raw_name is None:
        return None
    name = _utf8_safe(raw_name)
    return name.removeprefix("/") or None


def _extract_text_runs(page: Any) -> tuple[str, list[_TextRun]]:
    runs: list[_TextRun] = []

    def visitor_text(
        text: str,
        _current_matrix: Any,
        _text_matrix: Any,
        font_dictionary: Any,
        font_size: Any,
    ) -> None:
        safe_text = _utf8_safe(text)
        if not safe_text:
            return
        try:
            numeric_size = float(font_size)
        except (TypeError, ValueError):
            numeric_size = 0
        run = _TextRun(
            text=safe_text,
            font_name=_font_name(font_dictionary),
            font_size_points=numeric_size if numeric_size > 0 else None,
        )
        if (
            runs
            and runs[-1].font_name == run.font_name
            and runs[-1].font_size_points == run.font_size_points
        ):
            previous = runs[-1]
            runs[-1] = _TextRun(
                text=f"{previous.text}{run.text}",
                font_name=previous.font_name,
                font_size_points=previous.font_size_points,
            )
        else:
            runs.append(run)

    extracted = _utf8_safe(page.extract_text(visitor_text=visitor_text) or "")
    return extracted, runs


def _enumerate_page_images(page: Any) -> tuple[list[Any], bool]:
    try:
        return list(page.images), False
    except Exception:
        return [], True


def parse_pdf_structure(
    data: bytes,
    *,
    source_id: UUID,
) -> ParsedMaterial:
    """解析完整 PDF 结构，并把所有不可靠能力显式记录为覆盖缺口。"""

    source_sha256 = sha256(data).hexdigest()
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise PdfStructureParseError("PDF 已加密，不能建立可审计解析树")
        page_count = len(reader.pages)
    except PdfStructureParseError:
        raise
    except (PdfReadError, ValueError, TypeError, OSError) as error:
        raise PdfStructureParseError("PDF 容器无法解析") from error
    if page_count == 0:
        raise PdfStructureParseError("PDF 不包含页面")

    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=source_sha256,
        parser_profile_id=PDF_PARSER_PROFILE_ID,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label=None,
    )
    nodes: list[ParsedNode] = [root]
    gaps: list[ParseGap] = []
    text_characters = 0
    text_pages_parsed = 0
    layout_pages_parsed = 0
    total_image_units = 0
    extracted_image_units = 0
    total_annotation_units = 0

    for page_number, page in enumerate(reader.pages, start=1):
        page_locator = PdfPageLocator(page=page_number)
        inventory = _page_inventory(page)
        image_files, image_enumeration_failed = _enumerate_page_images(page)
        direct_image_count = inventory.image_resource_count or 0
        page_image_units = max(direct_image_count, len(image_files))
        represented_image_count: int | None = page_image_units
        if inventory.image_resource_count is None and image_enumeration_failed:
            represented_image_count = None
        try:
            width_points = float(page.mediabox.width)
            height_points = float(page.mediabox.height)
            rotation_degrees = int(page.rotation or 0)
        except (TypeError, ValueError, AttributeError) as error:
            raise PdfStructureParseError(
                f"PDF 第 {page_number} 页尺寸或旋转信息无效"
            ) from error
        page_node = build_parsed_node(
            ParsedPageNode,
            source_sha256=source_sha256,
            parser_profile_id=PDF_PARSER_PROFILE_ID,
            locator=page_locator,
            parent_node_id=root.node_id,
            ordinal_path=(1, page_number),
            label=None,
            width_points=width_points,
            height_points=height_points,
            rotation_degrees=rotation_degrees,
            image_resource_count=represented_image_count,
            form_xobject_count=inventory.form_xobject_count,
            font_resource_count=inventory.font_resource_count,
            annotation_count=inventory.annotation_count,
        )
        nodes.append(page_node)

        if inventory.resource_inventory_failed:
            gaps.append(
                ParseGap(
                    code="pdf_resource_inventory_failed",
                    message=f"第 {page_number} 页资源字典无法完整盘点",
                    effect="negative_evidence_blocked",
                    locator=page_locator,
                )
            )
        if inventory.annotation_inventory_failed:
            gaps.append(
                ParseGap(
                    code="pdf_annotation_inventory_failed",
                    message=f"第 {page_number} 页批注清单无法完整盘点",
                    effect="negative_evidence_blocked",
                    locator=page_locator,
                )
            )
        elif inventory.annotation_count:
            total_annotation_units += inventory.annotation_count
            gaps.append(
                ParseGap(
                    code="pdf_annotations_unparsed",
                    message=(
                        f"第 {page_number} 页包含 "
                        f"{inventory.annotation_count} 个未解析批注"
                    ),
                    effect="negative_evidence_blocked",
                    locator=page_locator,
                )
            )

        text_extracted = False
        page_text = ""
        text_runs: list[_TextRun] = []
        try:
            page_text, text_runs = _extract_text_runs(page)
            text_extracted = True
            text_pages_parsed += 1
            text_characters += len(page_text)
        except Exception:
            gaps.append(
                ParseGap(
                    code="pdf_text_extraction_failed",
                    message=f"第 {page_number} 页文本内容流无法解析",
                    effect="negative_evidence_blocked",
                    locator=page_locator,
                )
            )

        if text_extracted and "".join(run.text for run in text_runs) != page_text:
            text_runs = (
                [_TextRun(page_text, None, None)]
                if page_text
                else []
            )
            gaps.append(
                ParseGap(
                    code="pdf_text_run_segmentation_unreliable",
                    message=f"第 {page_number} 页仅能保留完整页文本，无法可靠拆分文字运行",
                    effect="positive_evidence_only",
                    locator=page_locator,
                )
            )

        # 图片型（扫描件）页：内容流无文本但存在图片资源，触发本地 OCR 补全文字。
        # 真正空白、既无文本也无图片的页不触发 OCR，避免对空白分隔页做无意义识别。
        if text_extracted and not page_text and page_image_units > 0:
            ocr_results = ocr_pdf_pages(data, [page_number - 1])
            ocr_result = ocr_results.get(page_number - 1)
            if isinstance(ocr_result, ScannedPdfOcrError):
                gaps.append(
                    ParseGap(
                        code="pdf_scanned_page_ocr_failed",
                        message=(
                            f"第 {page_number} 页疑似扫描件，本地 OCR 未能提取文字："
                            f"{ocr_result}"
                        ),
                        effect="negative_evidence_blocked",
                        locator=page_locator,
                    )
                )
            elif ocr_result is not None and ocr_result.text.strip():
                ocr_text = ocr_result.text.strip()
                text_runs = [_TextRun(ocr_text, None, None)]
                page_text = ocr_text
                text_characters += len(ocr_text)
                gaps.append(
                    ParseGap(
                        code="pdf_scanned_page_ocr_applied",
                        message=f"第 {page_number} 页无原生文本层，已使用本地 OCR 识别文字",
                        effect="positive_evidence_only",
                        locator=page_locator,
                    )
                )
            else:
                gaps.append(
                    ParseGap(
                        code="pdf_scanned_page_ocr_empty",
                        message=f"第 {page_number} 页疑似扫描件，本地 OCR 未识别到文字",
                        effect="negative_evidence_blocked",
                        locator=page_locator,
                    )
                )

        child_ordinal = 1
        for block_index, run in enumerate(text_runs, start=1):
            block_locator = PdfTextBlockLocator(
                page=page_number,
                block_index=block_index,
            )
            nodes.append(
                build_parsed_node(
                    ParsedTextNode,
                    source_sha256=source_sha256,
                    parser_profile_id=PDF_PARSER_PROFILE_ID,
                    locator=block_locator,
                    parent_node_id=page_node.node_id,
                    ordinal_path=(1, page_number, child_ordinal),
                    kind="text_block",
                    text=run.text,
                    pdf_font_name=run.font_name,
                    pdf_font_size_points=run.font_size_points,
                )
            )
            child_ordinal += 1

        if page_text:
            gaps.append(
                ParseGap(
                    code="pdf_visual_layout_unverified",
                    message=(
                        f"第 {page_number} 页保留内容流顺序，但无法可靠恢复"
                        "每个文字运行的完整边界框与视觉阅读顺序"
                    ),
                    effect="positive_evidence_only",
                    locator=page_locator,
                )
            )
        elif text_extracted:
            layout_pages_parsed += 1

        if inventory.form_xobject_count:
            gaps.append(
                ParseGap(
                    code="pdf_form_xobject_layout_unverified",
                    message=(
                        f"第 {page_number} 页包含 "
                        f"{inventory.form_xobject_count} 个 Form XObject"
                    ),
                    effect="positive_evidence_only",
                    locator=page_locator,
                )
            )

        total_image_units += page_image_units
        if image_enumeration_failed:
            gaps.append(
                ParseGap(
                    code="pdf_image_inventory_failed",
                    message=f"第 {page_number} 页图片资源无法完整枚举",
                    effect="negative_evidence_blocked",
                    locator=page_locator,
                )
            )
        for image_index in range(1, page_image_units + 1):
            image_locator = EmbeddedImageLocator(
                container_kind="pdf",
                container_ref=f"page:{page_number}",
                image_index=image_index,
            )
            image_data: bytes | None = None
            if image_index <= len(image_files):
                candidate = getattr(image_files[image_index - 1], "data", None)
                if isinstance(candidate, bytes) and candidate:
                    image_data = candidate
            if image_data is not None:
                extracted_image_units += 1
                media_sha256 = sha256(image_data).hexdigest()
                media_extraction_status = "complete"
                gap_code = "pdf_image_semantics_unparsed"
                gap_message = (
                    f"第 {page_number} 页图片 {image_index} 已提取原始媒体，"
                    "但未解析图片语义"
                )
            else:
                media_sha256 = None
                media_extraction_status = "failed"
                gap_code = "pdf_image_resource_extraction_failed"
                gap_message = (
                    f"第 {page_number} 页图片 {image_index} 无法提取原始媒体"
                )
            nodes.append(
                build_parsed_node(
                    ParsedImageNode,
                    source_sha256=source_sha256,
                    parser_profile_id=PDF_PARSER_PROFILE_ID,
                    locator=image_locator,
                    parent_node_id=page_node.node_id,
                    ordinal_path=(1, page_number, child_ordinal),
                    media_sha256=media_sha256,
                    alt_text=None,
                    caption=None,
                    media_extraction_status=media_extraction_status,
                )
            )
            child_ordinal += 1
            gaps.append(
                ParseGap(
                    code=gap_code,
                    message=gap_message,
                    effect="negative_evidence_blocked",
                    locator=image_locator,
                )
            )

    source_units_total = page_count + total_image_units + total_annotation_units
    source_units_parsed = text_pages_parsed + extracted_image_units
    capabilities = (
        CapabilityCoverage(
            capability="text",
            source_unit_count=page_count,
            parsed_unit_count=text_pages_parsed,
        ),
        CapabilityCoverage(
            capability="images",
            source_unit_count=total_image_units,
            parsed_unit_count=extracted_image_units,
        ),
        CapabilityCoverage(
            capability="layout",
            source_unit_count=page_count,
            parsed_unit_count=layout_pages_parsed,
        ),
    )
    disposition = (
        "complete_for_declared_capabilities"
        if not gaps
        and source_units_parsed == source_units_total
        and all(capability.complete for capability in capabilities)
        else "incomplete_usable"
    )
    coverage = ParseCoverage(
        disposition=disposition,
        source_units_total=source_units_total,
        source_units_parsed=source_units_parsed,
        text_characters_parsed=text_characters,
        table_cells_parsed=0,
        capabilities=capabilities,
        gaps=tuple(gaps),
    )
    return build_parsed_material(
        source_id=source_id,
        source_sha256=source_sha256,
        document_kind="pdf",
        parser_profile_id=PDF_PARSER_PROFILE_ID,
        parser_fingerprint=PDF_PARSER_FINGERPRINT,
        normalization_profile_id=PDF_NORMALIZATION_PROFILE_ID,
        root_node_id=root.node_id,
        nodes=tuple(nodes),
        coverage=coverage,
    )
