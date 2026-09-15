# ABOUTME: 自有 Word 导出基底的唯一生成器——从空白文档按 word_zh 格式 profile 构造版心、样式、目录控件与脚注部件。
# ABOUTME: 产物 backend/data/export/base_template.docx 入库；渲染器只借用其样式、分节属性与目录控件，正文全部由契约生成。
# ABOUTME(en): Sole generator of the owned Word export base template — builds page area, styles, the TOC field control
# ABOUTME(en): and footnotes part from a blank document per the word_zh format profile. The docx product is checked in.
"""导出基底不再来自任何外部模板文件。

渲染前 `docx_renderer._prepare_shell` 会清空基底正文、只保留分节属性与目录内容控件，
因此基底需要且只需要提供：A4 版心、正文/标题/目录/题注/脚注/批注样式、一个带
TOC 域的目录控件，以及承载分隔线的 footnotes 部件。这些全部由本模块用 python-docx
从空白文档构造，再经 `normalize_template` 做与运行时相同的样式归正。

用法（在 backend/ 下）：
    uv run python -m sustainability_desk.export.base_template
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, Twips

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    all_knowledge_package_ids,
    load_knowledge_package,
)
from sustainability_desk.contract.language import word_language_tag
from sustainability_desk.export.format_profile import WordFormatProfile, load_format_profile
from sustainability_desk.export.toc import TOC_FIELD_INSTRUCTION
# 目录条目的右对齐点线制表位（版心 16cm 内略收，与页码列对齐）。
_TOC_TAB_POSITION_TWIPS = 8494
# 页眉页脚距页边：与正文版心分离，页脚署名行不挤压正文。
_HEADER_DISTANCE_CM = 0.2
_FOOTER_DISTANCE_CM = 0.5

_FOOTNOTES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f"<w:footnotes {nsdecls('w')}>"
    '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>'
    "<w:r><w:separator/></w:r></w:p></w:footnote>"
    '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>'
    "<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
    "</w:footnotes>"
)
_FOOTNOTES_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)


def _configure_page(doc, profile) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    margins = profile.page.body_margins_cm
    section.top_margin = Cm(margins.top)
    section.bottom_margin = Cm(margins.bottom)
    section.left_margin = Cm(margins.left)
    section.right_margin = Cm(margins.right)
    section.header_distance = Cm(_HEADER_DISTANCE_CM)
    section.footer_distance = Cm(_FOOTER_DISTANCE_CM)


def _configure_defaults(doc, profile: WordFormatProfile) -> None:
    """文档默认语言取包语言的 Word 标签；正文字号取 profile。字体族由 normalize_template 统一归正。"""

    doc_defaults = doc.styles.element.find(qn("w:docDefaults"))
    rpr = doc_defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    tag = word_language_tag(profile.language)
    lang.set(qn("w:val"), tag)
    lang.set(qn("w:eastAsia"), tag)
    normal = doc.styles["Normal"]
    normal.font.size = Pt(profile.body.font_size_pt)
    normal.paragraph_format.widow_control = True


def _add_paragraph_style(
    doc,
    name: str,
    style_id: str,
    *,
    size_pt: float | None = None,
    space_after_pt: float | None = None,
    single_line: bool = False,
    left_indent_twips: int | None = None,
    right_dot_tab: bool = False,
):
    style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.style_id = style_id
    style.base_style = doc.styles["Normal"]
    style.next_paragraph_style = doc.styles["Normal"]
    style.unhide_when_used = True
    style.quick_style = True
    fmt = style.paragraph_format
    if size_pt is not None:
        style.font.size = Pt(size_pt)
    if space_after_pt is not None:
        fmt.space_after = Pt(space_after_pt)
    if single_line:
        fmt.line_spacing = 1.0
    if left_indent_twips is not None:
        fmt.left_indent = Twips(left_indent_twips)
    if right_dot_tab:
        fmt.tab_stops.add_tab_stop(
            Twips(_TOC_TAB_POSITION_TWIPS), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )
    return style


def _add_character_style(doc, name: str, style_id: str, *, superscript: bool = False, size_pt: float | None = None):
    style = doc.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
    style.style_id = style_id
    style.unhide_when_used = True
    if superscript:
        style.font.superscript = True
    if size_pt is not None:
        style.font.size = Pt(size_pt)
    return style


def _add_styles(doc, profile) -> None:
    """渲染器按 styleId `TOC{n}` 写目录条目，脚注与批注按样式名解析；四者默认模板都没有。"""

    _add_paragraph_style(doc, "toc 1", "TOC1", right_dot_tab=True)
    _add_paragraph_style(doc, "toc 2", "TOC2", left_indent_twips=440, right_dot_tab=True)
    _add_paragraph_style(doc, "toc 3", "TOC3", left_indent_twips=840, right_dot_tab=True)
    _add_paragraph_style(doc, "toc 4", "TOC4", left_indent_twips=1240, right_dot_tab=True)
    _add_paragraph_style(
        doc,
        "footnote text",
        "FootnoteText",
        size_pt=profile.footnotes.font_size_pt,
        space_after_pt=0,
        single_line=True,
    )
    _add_character_style(doc, "footnote reference", "FootnoteReference", superscript=True)
    _add_paragraph_style(doc, "annotation text", "CommentText", size_pt=10.5, single_line=True)
    _add_character_style(doc, "annotation reference", "CommentReference", size_pt=10.5)


def _append_toc_control(doc, profile: WordFormatProfile) -> None:
    """目录内容控件：标题段 + TOC 域。渲染期会在域范围内重建条目并由版式引擎回写页码。"""

    heading_font = profile.headings.east_asia_font
    sdt = parse_xml(
        f"<w:sdt {nsdecls('w')}>"
        "<w:sdtPr><w:docPartObj><w:docPartGallery w:val=\"Table of Contents\"/>"
        "<w:docPartUnique/></w:docPartObj></w:sdtPr>"
        "<w:sdtContent>"
        "<w:p><w:pPr><w:keepNext/><w:spacing w:before=\"240\" w:after=\"240\"/><w:jc w:val=\"center\"/></w:pPr>"
        f"<w:r><w:rPr><w:rFonts w:ascii=\"{heading_font}\" w:eastAsia=\"{heading_font}\" w:hAnsi=\"{heading_font}\"/><w:b/><w:sz w:val=\"32\"/></w:rPr>"
        f"<w:t>{profile.labels.toc_title}</w:t></w:r></w:p>"
        "<w:p><w:pPr><w:pStyle w:val=\"TOC1\"/></w:pPr>"
        "<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>"
        f"<w:r><w:instrText xml:space=\"preserve\">{TOC_FIELD_INSTRUCTION}</w:instrText></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>"
        f"<w:r><w:t>{profile.labels.toc_placeholder}</w:t></w:r></w:p>"
        "<w:p><w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )
    body = doc.element.body
    body.find(qn("w:sectPr")).addprevious(sdt)


def _attach_footnotes_part(doc) -> None:
    """footnotes 部件承载分隔线条目（id -1 / 0）；正文脚注由 export/footnotes.py 在渲染期追加。"""

    part = Part(
        PackURI("/word/footnotes.xml"),
        _FOOTNOTES_CONTENT_TYPE,
        _FOOTNOTES_XML.encode("utf-8"),
        doc.part.package,
    )
    doc.part.relate_to(part, RT.FOOTNOTES)


def build_base_template(package: KnowledgePackage, dst: Path | None = None) -> Path:
    """Generate and normalise a package's export base template; output is deterministic apart from rsids."""

    from sustainability_desk.export.normalize_template import normalize_template

    profile = load_format_profile(package)
    target = dst or package.base_template_path
    doc = Document()
    _configure_page(doc, profile)
    _configure_defaults(doc, profile)
    _add_styles(doc, profile)
    _append_toc_control(doc, profile)
    _attach_footnotes_part(doc)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    normalize_template(target, target, profile=profile)
    return target


def main() -> None:
    for package_id in all_knowledge_package_ids():
        path = build_base_template(load_knowledge_package(package_id))
        print(f"export base template written: {path}")


if __name__ == "__main__":
    main()
