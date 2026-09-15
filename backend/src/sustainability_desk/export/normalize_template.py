# ABOUTME: 把导出基底按 word_zh 格式 profile 归正：标题去自动编号、字体/字号/间距/主题色、目录层级与字段刷新设置。
# ABOUTME: 基底本身由 export/base_template.py 生成；本模块只做幂等的样式归正，不再依赖任何外部模板正文。
# ABOUTME(en): Normalizes the export base template to the word_zh format profile: heading auto-numbering removal, fonts,
# ABOUTME(en): sizes, spacing, theme colors, TOC levels and field refresh. Idempotent style normalization only.
import re
import shutil
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from sustainability_desk.export.format_profile import WordFormatProfile, rgb
from sustainability_desk.export.toc import TOC_OUTLINE_SWITCH




def _set_font(style, name: str) -> None:
    """设置样式的中文(eastAsia)与西文/数字(ascii/hAnsi/cs)字体为同一字体；并清除主题字体引用。

    等线常来自主题 minorHAnsi——仅设显式字体不够，须移除 *Theme 属性，显式字体才生效。
    """
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:eastAsia", "w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), name)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if qn(attr) in rfonts.attrib:
            del rfonts.attrib[qn(attr)]


def _fix_default_font(doc: Document, name: str) -> None:
    """把文档默认字体(docDefaults)设为正文字体并清主题引用——未被样式覆盖的 run 也默认该字体。"""
    dd = doc.styles.element.find(qn("w:docDefaults"))
    if dd is None:
        return
    rprd = dd.find(qn("w:rPrDefault"))
    if rprd is None:
        return
    rpr = rprd.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        rprd.append(rpr)
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:eastAsia", "w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), name)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if qn(attr) in rfonts.attrib:
            del rfonts.attrib[qn(attr)]


def _fix_fonts(doc: Document, profile: WordFormatProfile) -> None:
    """正文/列表用 profile 的正文字体（含数字、英文），标题用 profile 的标题字体（格式标准 §2）。"""
    _fix_default_font(doc, profile.body.east_asia_font)
    for name in ("Normal", "List Paragraph"):
        try:
            _set_font(doc.styles[name], profile.body.east_asia_font)
        except KeyError:
            pass
    for name in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        try:
            _set_font(doc.styles[name], profile.headings.east_asia_font)
        except KeyError:
            pass


# 段落间距/行距规范（before/after 单位 pt；line 为倍数，None 表示不改）。
_SPACING = {
    "Normal": (None, 6, 1.5),  # 正文：1.5 倍行距、段后 6pt
    "Heading 1": (24, 12, 1.5),  # 章：段前 24 / 段后 12
    "Heading 2": (18, 6, 1.5),  # 节：段前 18 / 段后 6
    "Heading 3": (12, 6, 1.5),  # 子节：段前 12 / 段后 6
    "Heading 4": (9, 3, 1.5),  # 支柱内子主题：紧凑但保持标题间距
    "toc 1": (6, 0, None),  # 目录章：段前 6、段后 0（与节统一，消除不匀间隙）
    "toc 2": (0, 0, None),  # 目录节：紧凑
    "toc 3": (0, 0, None),  # 目录支柱：紧凑
    "toc 4": (0, 0, None),  # 目录子主题：紧凑
    "List Paragraph": (None, 6, 1.5),  # 列表项：与正文一致 1.5 倍行距
}


def _fix_spacing(doc: Document) -> None:
    """正文行距与各级标题/目录的段前段后间距规范（格式标准 §2）。"""
    for name, (before, after, line) in _SPACING.items():
        try:
            pf = doc.styles[name].paragraph_format
        except KeyError:
            continue
        if before is not None:
            pf.space_before = Pt(before)
        if after is not None:
            pf.space_after = Pt(after)
        if line is not None:
            pf.line_spacing = line


# 标题字号归正（格式标准 §1：16/14/12/12pt）；主题色取格式 profile primary。
_HEADING_FONT_SIZE_PT = {
    "Heading 1": 16,
    "Heading 2": 14,
    "Heading 3": 12,
    "Heading 4": 12,
}


def _fix_heading_colors_and_sizes(doc: Document, profile: WordFormatProfile) -> None:
    """标题主题色统一到格式 profile 主色并归正字号（格式标准 §1、§2）。"""

    primary = rgb(profile.theme.primary)
    for name, size_pt in _HEADING_FONT_SIZE_PT.items():
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        style.font.size = Pt(size_pt)
        style.font.color.rgb = primary
        color_elem = style.element.get_or_add_rPr().find(qn("w:color"))
        if color_elem is not None and qn("w:themeColor") in color_elem.attrib:
            del color_elem.attrib[qn("w:themeColor")]


def _fix_heading_styles(doc: Document) -> None:
    """标题样式归正（格式标准 §1）：去自动编号 numPr、左对齐、清列表缩进；保留大纲级别。

    根治"1.1 一、报告范围"双重编号——标题编号全部由 section_number 渲染期
    确定性字面量输出（第N章 / 一、 / （一） / 1.），不绑 Word 自动多级编号。
    """
    for name in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        ppr = style._element.get_or_add_pPr()
        for np in ppr.findall(qn("w:numPr")):
            ppr.remove(np)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        style.paragraph_format.left_indent = Pt(0)
        style.paragraph_format.first_line_indent = Pt(0)



def _fix_toc_and_settings(path: Path) -> None:
    """把目录层级统一到报告模块与议题，并禁用打开时的全域刷新。

    目录页码由最终版式阶段写回 ``PAGEREF`` 的展示缓存。交付件是冻结
    revision，不能要求 Word 在用户打开时更新字段；该设置会触发“可能
    引用了其他文件”的通用安全提示。
    """
    with zipfile.ZipFile(path) as z:
        contents = {n: z.read(n) for n in z.namelist()}

    doc_xml = contents["word/document.xml"].decode("utf-8")
    doc_xml = re.sub(r'TOC \\o "1-\d"', lambda _: TOC_OUTLINE_SWITCH, doc_xml)
    contents["word/document.xml"] = doc_xml.encode("utf-8")

    settings = contents.get("word/settings.xml", b"").decode("utf-8")
    if settings:
        settings = re.sub(r"<w:updateFields\b[^>]*/>", "", settings)
        contents["word/settings.xml"] = settings.encode("utf-8")

    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in contents.items():
            z.writestr(n, data)
    shutil.move(str(tmp), str(path))


def normalize_template(src: Path, dst: Path, *, profile: WordFormatProfile) -> Path:
    """对基底做样式归正后写到 dst（src 与 dst 可为同一路径），返回 dst。"""
    doc = Document(str(src))

    # 0. 标题样式归正：去自动编号、左对齐（§1）；正文宋体标题黑体、间距行距规范（§2）
    _fix_heading_styles(doc)
    _fix_fonts(doc, profile)
    _fix_spacing(doc)
    _fix_heading_colors_and_sizes(doc, profile)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))
    _fix_toc_and_settings(dst)
    return dst
