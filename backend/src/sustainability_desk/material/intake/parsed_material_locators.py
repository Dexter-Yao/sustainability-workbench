# ABOUTME: 定义规范化解析节点可复现的源位置合同。
# ABOUTME: 定位器只表达原文件结构位置，不承载正文、推断事实或展示副本。
# ABOUTME(en): Defines the reproducible source-position contract for normalized parsed nodes.
# ABOUTME(en): Locators express structural position only, carrying no body text, inferred facts or display copies.
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type DocumentPart = Literal["body", "header", "footer"]
type HeaderFooterType = Literal["default", "first", "even"]
type EmbeddedImageContainerKind = Literal["docx", "pdf", "xlsx", "pptx", "image"]


class ParsedLocatorModel(BaseModel):
    """所有解析节点定位器的严格不可变边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentRootLocator(ParsedLocatorModel):
    """文件根节点。"""

    kind: Literal["document_root"] = "document_root"


class DocxParagraphLocator(ParsedLocatorModel):
    """DOCX 正文流中的段落位置。"""

    kind: Literal["docx_paragraph"] = "docx_paragraph"
    part: DocumentPart
    section_index: int | None = Field(default=None, ge=1)
    header_footer_type: HeaderFooterType | None = None
    block_index: int = Field(ge=1)
    paragraph_index: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_story_identity(self) -> "DocxParagraphLocator":
        _validate_docx_story_identity(
            part=self.part,
            section_index=self.section_index,
            header_footer_type=self.header_footer_type,
        )
        return self


class DocxTableLocator(ParsedLocatorModel):
    """DOCX 正文流中的表格位置。"""

    kind: Literal["docx_table"] = "docx_table"
    part: DocumentPart
    section_index: int | None = Field(default=None, ge=1)
    header_footer_type: HeaderFooterType | None = None
    block_index: int = Field(ge=1)
    table_index: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_story_identity(self) -> "DocxTableLocator":
        _validate_docx_story_identity(
            part=self.part,
            section_index=self.section_index,
            header_footer_type=self.header_footer_type,
        )
        return self


class DocxTableRowLocator(ParsedLocatorModel):
    """DOCX 表格中的单行位置。"""

    kind: Literal["docx_table_row"] = "docx_table_row"
    part: DocumentPart
    section_index: int | None = Field(default=None, ge=1)
    header_footer_type: HeaderFooterType | None = None
    table_index: int = Field(ge=1)
    row_index: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_story_identity(self) -> "DocxTableRowLocator":
        _validate_docx_story_identity(
            part=self.part,
            section_index=self.section_index,
            header_footer_type=self.header_footer_type,
        )
        return self


class DocxStoryLocator(ParsedLocatorModel):
    """DOCX 页眉或页脚故事容器的稳定身份。"""

    kind: Literal["docx_story"] = "docx_story"
    part: Literal["header", "footer"]
    section_index: int = Field(ge=1)
    header_footer_type: HeaderFooterType


class PdfPageLocator(ParsedLocatorModel):
    """PDF 页容器位置。"""

    kind: Literal["pdf_page"] = "pdf_page"
    page: int = Field(ge=1)


class PdfTextBlockLocator(ParsedLocatorModel):
    """PDF 页内文本块位置，可附带归一化边界框。"""

    kind: Literal["pdf_text_block"] = "pdf_text_block"
    page: int = Field(ge=1)
    block_index: int = Field(ge=1)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def _validate_bounding_box(self) -> "PdfTextBlockLocator":
        coordinates = (self.x, self.y, self.width, self.height)
        if any(value is not None for value in coordinates) and any(
            value is None for value in coordinates
        ):
            raise ValueError("PDF 文本块边界框必须完整提供")
        if self.x is not None and self.width is not None and self.x + self.width > 1:
            raise ValueError("PDF 文本块横向范围超出页面")
        if (
            self.y is not None
            and self.height is not None
            and self.y + self.height > 1
        ):
            raise ValueError("PDF 文本块纵向范围超出页面")
        return self


class PptxSlideLocator(ParsedLocatorModel):
    """PPTX 幻灯片容器位置。"""

    kind: Literal["pptx_slide"] = "pptx_slide"
    slide_number: int = Field(ge=1)


class PptxShapeLocator(ParsedLocatorModel):
    """PPTX 幻灯片内形状文本位置，按阅读顺序（top, left）编号。"""

    kind: Literal["pptx_shape"] = "pptx_shape"
    slide_number: int = Field(ge=1)
    shape_index: int = Field(ge=1)


class PptxTableLocator(ParsedLocatorModel):
    """PPTX 幻灯片内表格位置。"""

    kind: Literal["pptx_table"] = "pptx_table"
    slide_number: int = Field(ge=1)
    shape_index: int = Field(ge=1)


class PptxTableRowLocator(ParsedLocatorModel):
    """PPTX 幻灯片内表格中的单行位置。"""

    kind: Literal["pptx_table_row"] = "pptx_table_row"
    slide_number: int = Field(ge=1)
    shape_index: int = Field(ge=1)
    row_index: int = Field(ge=1)


class PptxNotesLocator(ParsedLocatorModel):
    """PPTX 幻灯片演讲者备注位置。"""

    kind: Literal["pptx_notes"] = "pptx_notes"
    slide_number: int = Field(ge=1)


class XlsxSheetLocator(ParsedLocatorModel):
    """XLSX 工作表容器位置。"""

    kind: Literal["xlsx_sheet"] = "xlsx_sheet"
    sheet_name: str = Field(min_length=1)
    sheet_index: int = Field(ge=1)


class XlsxRowLocator(ParsedLocatorModel):
    """XLSX 工作表中的原始行位置。"""

    kind: Literal["xlsx_row"] = "xlsx_row"
    sheet_name: str = Field(min_length=1)
    row_index: int = Field(ge=1)


class XlsxCellLocator(ParsedLocatorModel):
    """XLSX 工作表中的单元格位置。"""

    kind: Literal["xlsx_cell"] = "xlsx_cell"
    sheet_name: str = Field(min_length=1)
    cell_reference: str = Field(min_length=1)


class XlsxTableLocator(ParsedLocatorModel):
    """XLSX 定义表及其范围。"""

    kind: Literal["xlsx_table"] = "xlsx_table"
    sheet_name: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    cell_range: str = Field(min_length=1)


class XlsxNamedRangeLocator(ParsedLocatorModel):
    """XLSX 名称定义及其作用域。"""

    kind: Literal["xlsx_named_range"] = "xlsx_named_range"
    name: str = Field(min_length=1)
    scope_sheet_name: str | None = None
    definition_index: int = Field(default=1, ge=1)


class XlsxChartLocator(ParsedLocatorModel):
    """XLSX 工作表中的图表位置。"""

    kind: Literal["xlsx_chart"] = "xlsx_chart"
    sheet_name: str = Field(min_length=1)
    chart_index: int = Field(ge=1)
    chart_name: str | None = None


class EmbeddedImageLocator(ParsedLocatorModel):
    """嵌入图片在其宿主结构中的位置。"""

    kind: Literal["embedded_image"] = "embedded_image"
    container_kind: EmbeddedImageContainerKind
    container_ref: str = Field(min_length=1)
    image_index: int = Field(ge=1)


type DocumentObjectKind = Literal[
    "textbox",
    "footnote",
    "content_control",
    "revision",
]
type DocumentObjectHostLocator = (
    DocxParagraphLocator
    | DocxTableLocator
    | DocxTableRowLocator
    | PdfPageLocator
    | PdfTextBlockLocator
    | XlsxSheetLocator
    | XlsxRowLocator
    | XlsxCellLocator
)


class DocumentObjectLocator(ParsedLocatorModel):
    """解析缺口对象及其宿主源位置。"""

    kind: Literal["document_object"] = "document_object"
    object_kind: DocumentObjectKind
    host_locator: DocumentObjectHostLocator
    object_index: int = Field(ge=1)
    object_reference: str | None = None


type ParsedNodeLocator = Annotated[
    DocumentRootLocator
    | DocxParagraphLocator
    | DocxTableLocator
    | DocxTableRowLocator
    | DocxStoryLocator
    | PdfPageLocator
    | PdfTextBlockLocator
    | PptxSlideLocator
    | PptxShapeLocator
    | PptxTableLocator
    | PptxTableRowLocator
    | PptxNotesLocator
    | XlsxSheetLocator
    | XlsxRowLocator
    | XlsxCellLocator
    | XlsxTableLocator
    | XlsxNamedRangeLocator
    | XlsxChartLocator
    | EmbeddedImageLocator
    | DocumentObjectLocator,
    Field(discriminator="kind"),
]


def _validate_docx_story_identity(
    *,
    part: DocumentPart,
    section_index: int | None,
    header_footer_type: HeaderFooterType | None,
) -> None:
    if part == "body":
        if section_index is not None or header_footer_type is not None:
            raise ValueError("DOCX 正文位置不得携带页眉页脚身份")
        return
    if section_index is None or header_footer_type is None:
        raise ValueError("DOCX 页眉页脚位置必须提供节序号和类型")
