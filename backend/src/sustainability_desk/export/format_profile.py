# ABOUTME(en): Typed parse boundary for a knowledge package's Word format profile — the package's
# ABOUTME(en): format_profile.yaml is the only parameter SSOT; renderer and normalizer consume these frozen models only.
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

import yaml
from docx.shared import RGBColor
from pydantic import BaseModel, ConfigDict, StringConstraints

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)
from sustainability_desk.contract.language import Language


def rgb(hex_value: str) -> RGBColor:
    """把 profile 中的六位十六进制色值转为 docx RGBColor。"""

    value = hex_value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"非法色值：{hex_value}")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThemeColors(_ProfileModel):
    primary: str
    note_red: str
    caption_gray: str
    cover_gray: str
    placeholder_gray: str


class Margins(_ProfileModel):
    top: float
    bottom: float
    left: float
    right: float


class PageLayout(_ProfileModel):
    size: Literal["A4"]
    body_margins_cm: Margins
    cover_margins_cm: Margins


class NumberingPolicy(_ProfileModel):
    # chapter_cn: 第N章 / 一、 / （一） / 1.   decimal: 1 / 1.1 / 1.1.1 (unnumbered chapters' subtree unnumbered)
    section_scheme: Literal["chapter_cn", "decimal"]
    unnumbered_chapter_keys: tuple[str, ...]
    figure_numbering: Literal["sequential_whole_document"]
    appendix_numbering: Literal["appendix_letter"]
    number_caption_separator: str
    # Between the kind label and the number: "" for 表1, " " for Table 1.
    label_number_separator: str = ""
    count_only_rendered: bool


class CaptionRules(_ProfileModel):
    figure_position: Literal["below"]
    table_position: Literal["above"]
    font_size_pt: float
    color: str
    no_trailing_period: bool
    source_note_font_size_pt: float
    table_note_font_size_pt: float
    table_note_italic: bool


class FootnoteRules(_ProfileModel):
    """脚注版式（GB/T 1.1-2020 §10.4.4）。分隔细实线与编号由 Word 母版承载，不在此声明。"""

    text_style_name: str       # 母版脚注正文段落样式名；按名解析 styleId，不硬编码 id
    reference_style_name: str  # 母版脚注引用字符样式名（上标）
    font_size_pt: float


class HeadingStyle(_ProfileModel):
    """Heading font family; sizes and colors are normalised by normalize_template."""

    east_asia_font: str


class MetricTableHeaders(_ProfileModel):
    """Column headers of the derived metric summary table figure."""

    metric: str
    value: str
    unit: str


class DeliveryFilenameVariants(_ProfileModel):
    """Filename infix that tells the formal deliverable from the review deliverable."""

    word: str
    review: str


class DeliveryLabels(_ProfileModel):
    """Fixed words the renderer prints into the Word deliverable, in the package language."""

    toc_title: str
    toc_placeholder: str
    page_number_prefix: str
    page_number_suffix: str
    table_note_prefix: str
    figure_label: str
    table_label: str
    appendix_number_prefix: str
    reporting_period_template: str  # {year}
    document_title_template: str  # {year} {title}
    generated_at_template: str  # {timestamp}
    image_placeholder_template: str  # {text}
    derived_figure_failed: str
    default_table_unit_text: str
    default_image_unit_text: str
    metric_year_template: str  # {year}; year caption of derived metric figures
    metric_year_fallback: str  # caption when the report year is unknown
    metric_table_headers: MetricTableHeaders
    delivery_filename_variants: DeliveryFilenameVariants


class BodyStyle(_ProfileModel):
    east_asia_font: str
    font_size_pt: float
    line_spacing_multiple: float
    space_after_pt: float
    first_line_indent_chars: int
    first_line_indent_twips: int


class CellMargins(_ProfileModel):
    top: int
    start: int
    bottom: int
    end: int


class ThreeLineBorders(_ProfileModel):
    outer_size_pt: float
    outer_color: str
    inner_h_size_pt: float
    inner_h_color: str
    vertical_edges: Literal["nil"]


class TableStyle(_ProfileModel):
    cell_font_size_pt: float
    header_font_size_pt: float
    header_bold: bool
    header_color: str
    cell_east_asia_font: str
    cell_line_spacing: float
    cell_space_before_pt: float
    cell_space_after_pt: float
    cell_margins_dxa: CellMargins
    three_line: ThreeLineBorders
    first_column_narrow_ratio: float
    repeat_header_row: bool
    keep_row_together: bool
    fixed_layout: bool
    caption_space_pt: float


class FigureWidths(_ProfileModel):
    evidence_default: float
    derived_metric_summary: float
    materiality_matrix: float


class AspectRatioRules(_ProfileModel):
    wide_threshold: float
    mid_threshold: float
    wide_cm: float
    mid_cm: float
    narrow_scale_cm: float
    narrow_cap_cm: float


_HexColor = Annotated[str, StringConstraints(pattern=r"^[0-9A-Fa-f]{6}$")]


class FigureLayout(_ProfileModel):
    placeholder_color: str
    widths_cm: FigureWidths
    aspect_ratio_rules: AspectRatioRules


class ListStyle(_ProfileModel):
    bullet_char: str
    ordered_level_text: str
    indent_left_dxa: int
    hanging_dxa: int
    supported_levels: int


class FooterStyle(_ProfileModel):
    east_asia_font: str
    color: str
    standard_font_size_pt: float
    review_font_size_pt: float
    timestamp_format: str
    timezone: str
    provider_name: str
    review_prefix_standard: str
    # 为空则署名行不显示联系方式段。
    review_contact: str = ""
    # 开源仓库地址，随署名行进入两种交付物；为空则不显示该段。
    repository_url: str = ""
    cover_and_toc_footer: Literal["attribution_only"]


class CoverFullReport(_ProfileModel):
    logo_width_cm: float
    logo_space_before_pt: int
    logo_space_after_pt: int
    standard_spacer_before_pt: int
    company_space_before_review_pt: int
    company_space_before_standard_pt: int
    company_space_after_pt: int
    company_font_size_pt: int
    title_text: str
    title_font_size_pt: int
    title_space_after_pt: int
    period_font_size_pt: int
    period_space_after_pt: int
    ai_disclosure_text: str
    ai_disclosure_font_size_pt: float
    ai_disclosure_space_before_pt: int





class MaterialProcessingNoticeStyle(_ProfileModel):
    """审阅稿前置说明页版式；标题不进多级编号，故不占章号也不进目录。"""

    # 条目清单版式：段内行距须小于条目间距，续行才不会被读成独立条目。
    line_spacing_multiple: float
    heading_font_size_pt: float
    heading_space_after_pt: int
    lead_font_size_pt: float
    lead_space_after_pt: int
    file_name_font_size_pt: float
    file_name_space_before_pt: int
    file_name_space_after_pt: int
    item_font_size_pt: float
    item_space_after_pt: int
    next_action_font_size_pt: float
    next_action_space_after_pt: int
    next_action_label: str
    next_action_indent_chars: int


class OverviewTexts(_ProfileModel):
    no_materials: str
    materials_adopted: str
    adopted_list_template: str  # {names}
    adopted_name_separator: str
    materials_read_not_adopted: str
    file_group_template: str  # {names} {explanation}
    file_name_separator: str
    not_adopted: dict[str, str]  # MaterialNotAdoptedCode -> explanation


class UnitLabels(_ProfileModel):
    paragraph: str
    list: str
    table: str
    other: str


class ExplanationTexts(_ProfileModel):
    layout_image: str
    certificate_table: str
    derived_metric_figure: str
    assessment_matrix: str
    from_materials: str  # {label}
    from_materials_and_metrics: str  # {label}
    needs_attention: str  # {label}
    from_metrics: str  # {label}
    without_materials: str  # {label}


class ReadingNoteTexts(_ProfileModel):
    needs_attention: str
    attention_items_present: str


class CommentLineTexts(_ProfileModel):
    source_item: str  # {name}
    image_item: str  # {name}
    image_user_description: str  # {description}
    image_category_placement: str  # {category} {scope}
    image_placement: str  # {scope}
    metrics_heading: str
    metric_item: str  # {name} {value} {unit}
    cover_comment: str  # {overview}


class MaterialNoticeTexts(_ProfileModel):
    heading: str
    lead: str
    files_heading: str
    files_lead: str


class StandardsNoticeTexts(_ProfileModel):
    heading: str
    lead: str
    attention_heading: str
    attention_lead: str
    exclusion_heading: str
    exclusion_lead: str
    omission_finding_template: str  # {title}
    omission_finding_untitled: str
    omission_next_action: str
    report_scope_label: str
    obligation_unmet_template: str  # {title}
    obligation_next_action: str
    pending_topic_message: str
    summary_template: str  # {count}
    exclusion_rationales: dict[str, str]  # exclusionRationaleCode -> user-facing rationale


class DeliveryTexts(_ProfileModel):
    """User-facing wording of the review deliverable (cover comment, block comments, notice pages).

    The facts behind each sentence are computed in report_review_packages.py; this profile only
    owns how they are said in the package language.
    """

    overview: OverviewTexts
    unit_labels: UnitLabels
    explanations: ExplanationTexts
    reading_notes: ReadingNoteTexts
    comment_lines: CommentLineTexts
    layout_image_categories: dict[str, str]  # image category code -> reader label
    material_notice: MaterialNoticeTexts
    standards_notice: StandardsNoticeTexts


class TocPolicy(_ProfileModel):
    max_heading_level: int
    field_instruction: str
    page_numbers: Literal["frozen_by_layout_engine"]


class WordFormatProfile(_ProfileModel):
    """One package's Word format parameters; profile_id/version feed delivery fingerprints."""

    profile_id: str
    profile_version: int
    language: Language
    scope: str
    theme: ThemeColors
    page: PageLayout
    numbering: NumberingPolicy
    captions: CaptionRules
    footnotes: FootnoteRules
    body: BodyStyle
    headings: HeadingStyle
    labels: DeliveryLabels
    tables: TableStyle
    figures: FigureLayout
    lists: ListStyle
    footer: FooterStyle
    cover_full_report: CoverFullReport
    material_processing_notice: MaterialProcessingNoticeStyle
    delivery_texts: DeliveryTexts
    toc: TocPolicy


@lru_cache(maxsize=None)
def _load_format_profile(package_id: str) -> WordFormatProfile:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.format_profile_path.read_text(encoding="utf-8"))
    profile = WordFormatProfile.model_validate(raw)
    if profile.profile_id != package.id:
        raise ValueError(
            f"format profile id {profile.profile_id!r} does not match package {package.id!r}"
        )
    if profile.language != package.language:
        raise ValueError(
            f"format profile language {profile.language!r} does not match package {package.language!r}"
        )
    return profile


def load_format_profile(package: KnowledgePackage) -> WordFormatProfile:
    """Strictly parse a package's Word format profile; unknown and missing fields are rejected."""

    return _load_format_profile(package.id)
