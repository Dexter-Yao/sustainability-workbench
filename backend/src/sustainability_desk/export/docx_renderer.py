# ABOUTME: schema→docx 渲染器——遍历自包含契约 + 实例数据，渲染成 Word（复用模板外壳：封面/页眉/页码/样式）。
# ABOUTME: 标题按 Heading 样式、正文 ref 填值、备注低调(小字/斜体/红)、表格三线表、图片占位、条件按 appears_when 显隐；导出前 fail-loud 校验必备议题章节。
# ABOUTME(en): schema-to-docx renderer — walks the self-contained contract and instance data into Word, reusing the
# ABOUTME(en): base template shell. Conditionals follow appears_when; required topic sections are checked before export.
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Mapping
from zoneinfo import ZoneInfo

import yaml
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.text.run import Run

from sustainability_desk.contract.assessment_projection import apply_assessment_projection
from sustainability_desk.contract.knowledge_packages import knowledge_package_of, load_knowledge_package
from sustainability_desk.contract.language import list_separator
from sustainability_desk.contract.disclosure_standards_index import (
    apply_disclosure_standards_index_projection,
)
from sustainability_desk.contract.section_titles import resolved_display_title
from sustainability_desk.contract.models import Block, Field, Report
from sustainability_desk.contract.renderability import (
    block_is_renderable,
    renderable_table_rows,
    section_is_renderable,
)
from sustainability_desk.contract.report_values import display_report_ref
from sustainability_desk.contract.section_number import number_sections
from sustainability_desk.contract.visibility import assessment_value, visible
from sustainability_desk.export.media import prune_unused_media
from sustainability_desk.export.toc import (
    finalize_toc_page_numbers,
    page_layout_renderer,
    toc_includes_heading_level,
)
from sustainability_desk.export.figure_projection import FigureKind, FigureNumbering, FigureSpec
from sustainability_desk.export.footnotes import add_footnote
from sustainability_desk.export.format_profile import WordFormatProfile, load_format_profile, rgb

if TYPE_CHECKING:
    # report_review_packages 已依赖本模块的 DocumentRenderPlan；只做类型标注避免循环导入。
    from sustainability_desk.report_review_packages import (
        MaterialProcessingNotice,
        StandardsComplianceNotice,
    )

def _theme_color(profile: WordFormatProfile, name: str) -> RGBColor:
    """按 profile theme 段字段名取色；颜色参数的唯一入口。"""

    return rgb(getattr(profile.theme, name))


def format_profile_for(report: Report) -> WordFormatProfile:
    """The Report carries its knowledge package; the package owns the Word format profile."""

    return load_format_profile(knowledge_package_of(report))


_MATRIX_IMAGE_BLOCK_ID = "sm.matrix_image"
# 交付物只有完整报告一种版式：目录、封面、正文编号节与目录页码定稿共用同一套结构逻辑。
DocumentDeliveryVariant = Literal["standard", "review"]


class UnresolvedReportReferenceError(RuntimeError):
    """渲染时遇到无值且无回退文案的正文引用；上游 diagnose 闸应已阻断，此处只 fail-loud。"""

    def __init__(self, ref: str | None) -> None:
        super().__init__(f"导出渲染遇到无值且无回退文案的引用：{ref}")
        self.ref = ref


@dataclass(frozen=True)
class ResolvedEvidenceImage:
    """已冻结的图片字节与资产元数据；renderer 不读取私有对象存储。

    宽度由上游解析器按确定性规则给出(宽高比/图类),renderer 不自行判断尺寸。
    """

    data: bytes
    caption: str | None
    alt_text: str
    width_cm: float
    kind: FigureKind = "evidence_image"


@dataclass(frozen=True)
class RenderedContentUnit:
    """最终 Word 中一个可见内容单元的稳定渲染身份。"""

    anchor_id: str
    block_id: str
    kind: Literal["paragraph", "list", "table", "image"]
    text: str


@dataclass(frozen=True)
class DocumentRenderPlan:
    """从 revision 派生的渲染导航投影；不拥有报告事实。"""

    report: Report
    section_labels: dict[str, str]
    units: tuple[RenderedContentUnit, ...]

    @property
    def unit_anchor_ids(self) -> frozenset[str]:
        return frozenset(item.anchor_id for item in self.units)


# ---- 内容解析 ----
def _inline_text(content, report) -> str:
    out = []
    for inl in content or []:
        if inl.kind == "text":
            out.append(inl.text or "")
        else:
            v = (
                assessment_value(inl.ref, report)
                if inl.ref and inl.ref.startswith("assessment.")
                else None
            )
            if v is None:
                v = display_report_ref(inl.ref, report)
            if isinstance(v, list):
                v = list_separator(knowledge_package_of(report).language).join(str(item) for item in v if str(item).strip())
            if v not in (None, ""):
                out.append(str(v))
            elif inl.fallback:
                out.append(inl.fallback)
            else:
                # 交付级严格性由 render_final_docx 入口的引用预扫描承担（fail-loud）；
                # 此处保持宽渲染，供局部文档（测试/内部预览）复用，不泄露内部 ref key。
                continue
    return "".join(out)


def _assert_final_references_resolved(report: Report) -> None:
    """交付级渲染前置扫描：可见正文中无值且无回退文案的引用即 fail-loud。

    /api/export 与生成 worker 都必须先过 diagnose 闸；此扫描是渲染边界的最后防线，
    确保闸漏检时终止渲染，而不是交付带静默空洞的 Word。
    """

    def walk(sections) -> None:
        for sec in sections:
            if not visible(sec, report):
                continue
            for block in sec.blocks:
                if not visible(block, report):
                    continue
                for inl in block.content or []:
                    if inl.kind != "ref" or not inl.ref or inl.fallback:
                        continue
                    value = (
                        assessment_value(inl.ref, report)
                        if inl.ref.startswith("assessment.")
                        else None
                    )
                    if value is None:
                        value = display_report_ref(inl.ref, report)
                    if value in (None, "") or (
                        isinstance(value, str) and not value.strip()
                    ):
                        raise UnresolvedReportReferenceError(inl.ref)
            if sec.children:
                walk(sec.children)

    walk(report.sections)


# ---- 三线表 ----
def _set_three_line(profile: WordFormatProfile, table) -> None:
    three = profile.tables.three_line
    outer_sz = str(int(three.outer_size_pt * 8))
    inner_sz = str(int(three.inner_h_size_pt * 8))
    outer_color = getattr(profile.theme, three.outer_color)
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), outer_sz)
        e.set(qn("w:color"), outer_color)
        borders.append(e)
    for edge in ("left", "right", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), three.vertical_edges)
        borders.append(e)
    ih = OxmlElement("w:insideH")
    ih.set(qn("w:val"), "single")
    ih.set(qn("w:sz"), inner_sz)
    ih.set(qn("w:color"), three.inner_h_color)
    borders.append(ih)
    tblPr.append(borders)


def _set_col_widths(
    profile: WordFormatProfile,
    doc,
    table,
    ncols: int,
    first_narrow: bool,
    weights: list[int] | None = None,
) -> None:
    """显式列宽：优先按列权重分配；无权重时首列可窄化，否则等分。"""
    sec = doc.sections[-1]
    content = int(sec.page_width - sec.left_margin - sec.right_margin)  # EMU
    if weights and len(weights) == ncols and sum(weights) > 0:
        total = sum(weights)
        widths = [int(content * weight / total) for weight in weights]
        widths[-1] += content - sum(widths)
    elif first_narrow and ncols >= 2:
        w0 = int(content * profile.tables.first_column_narrow_ratio)
        rest = (content - w0) // (ncols - 1)
        widths = [w0] + [rest] * (ncols - 1)
    else:
        widths = [content // ncols] * ncols
    table.autofit = False
    tblPr = table._tbl.tblPr
    tblLayout = tblPr.find(qn("w:tblLayout"))
    if tblLayout is None:
        tblLayout = OxmlElement("w:tblLayout")
        tblPr.append(tblLayout)
    tblLayout.set(qn("w:type"), "fixed")
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w / 635)))  # EMU → dxa(twip)
    for j, w in enumerate(widths):
        for cell in table.columns[j].cells:
            cell.width = Emu(w)
    # 表整体宽度显式设为列宽之和（dxa），确保 fixed 布局列宽真正生效
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:type"), "dxa")
    tblW.set(qn("w:w"), str(int(sum(widths) / 635)))


def _column_width_weights(tm) -> list[int] | None:
    """读取表格自身声明的列宽比例，不以某一种表格版式作为前提。"""
    if not tm.columnWidthWeights:
        return None
    return [max(int(tm.columnWidthWeights.get(col.key, 1)), 1) for col in tm.colDefs]


def _repeat_header(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    tblHeader = trPr.find(qn("w:tblHeader"))
    if tblHeader is None:
        tblHeader = OxmlElement("w:tblHeader")
        trPr.append(tblHeader)
    tblHeader.set(qn("w:val"), "true")


def _keep_row_together(row) -> None:
    """避免一条业务记录在分页处被拆成无题目的续行。"""
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def _set_cell_margins(profile: WordFormatProfile, cell) -> None:
    margins = profile.tables.cell_margins_dxa
    top, start, bottom, end = margins.top, margins.start, margins.bottom, margins.end
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (
        ("top", top),
        ("start", start),
        ("bottom", bottom),
        ("end", end),
    ):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _is_review_only_column(cell, table_model, column_index: int) -> bool:
    """该单元格是否属于只进审阅稿的列。

    数据格自带 colKey；表头单元不带，按列序号对到 colDefs。列身份由
    quantitative_metrics.REVIEW_ONLY_COLUMN_KEYS 拥有，渲染层不写字面列名。
    正式稿走到这里时这些列已被投影裁掉，故无需再按 variant 分支。
    """

    from sustainability_desk.quantitative_metrics import REVIEW_ONLY_COLUMN_KEYS

    key = cell.colKey
    if key is None and 0 <= column_index < len(table_model.colDefs):
        key = table_model.colDefs[column_index].key
    return key in REVIEW_ONLY_COLUMN_KEYS


def _set_cell_text(
    profile: WordFormatProfile,
    cell,
    text: str,
    *,
    header: bool = False,
    align_center: bool = False,
    review_only: bool = False,
) -> None:
    """写入单元格文本；review_only 的列用备注红字标出其不进正式稿。

    审阅稿比正式稿多的内容分三类：前置说明页与页脚各自带自我声明、Word 批注是原生
    元数据形态，读者都不会误当正文；只有附录 KPI 表的「口径备注」列与其余四列长得
    完全一样，读者无从知道它不在正式稿里。故用既有的
    note_red 语义色标出——该色位在 profile 里定义为「备注红字（内部校准语义）」，
    语义正对。不用底纹：格式标准禁表头深色填充。
    """
    cell.text = ""
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    _set_cell_margins(profile, cell)
    # 单元格值中的换行是受控多行语义(如索引表一条款对应多个章节),按行拆成单元格内多段。
    lines = text.split("\n") or [""]
    for index, line in enumerate(lines):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        paragraph.alignment = (
            WD_ALIGN_PARAGRAPH.CENTER
            if (header or align_center)
            else WD_ALIGN_PARAGRAPH.LEFT
        )
        paragraph.paragraph_format.space_before = Pt(
            profile.tables.cell_space_before_pt
        )
        paragraph.paragraph_format.space_after = Pt(profile.tables.cell_space_after_pt)
        paragraph.paragraph_format.line_spacing = profile.tables.cell_line_spacing
        run = paragraph.add_run(line)
        run.bold = bool(header and profile.tables.header_bold)
        run.font.size = Pt(
            profile.tables.header_font_size_pt if header else profile.tables.cell_font_size_pt
        )
        run.font.name = "SimSun"
        run._element.rPr.rFonts.set(
            qn("w:eastAsia"), profile.tables.cell_east_asia_font
        )
        if review_only:
            run.font.color.rgb = _theme_color(profile, "note_red")
        elif header:
            run.font.color.rgb = _theme_color(profile, profile.tables.header_color)


# ---- 块渲染 ----
def _ensure_list_numbering(doc, profile: WordFormatProfile) -> dict:
    """在 numbering 部件中确保存在无序(bullet)与有序(decimal)编号定义，返回 {类型: numId}。"""
    numbering = doc.part.numbering_part.element
    abs_ids = [
        int(e.get(qn("w:abstractNumId")))
        for e in numbering.findall(qn("w:abstractNum"))
    ]
    num_ids = [int(e.get(qn("w:numId"))) for e in numbering.findall(qn("w:num"))]
    ba, oa = max(abs_ids, default=0) + 1, max(abs_ids, default=0) + 2
    bn, on = max(num_ids, default=0) + 1, max(num_ids, default=0) + 2

    def _abstract(abs_id, fmt, text):
        a = OxmlElement("w:abstractNum")
        a.set(qn("w:abstractNumId"), str(abs_id))
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        for tag, val in (
            ("w:start", "1"),
            ("w:numFmt", fmt),
            ("w:lvlText", text),
            ("w:lvlJc", "left"),
        ):
            e = OxmlElement(tag)
            e.set(qn("w:val"), val)
            lvl.append(e)
        ppr = OxmlElement("w:pPr")
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), str(profile.lists.indent_left_dxa))
        ind.set(qn("w:hanging"), str(profile.lists.hanging_dxa))
        ppr.append(ind)
        lvl.append(ppr)
        a.append(lvl)
        return a

    def _num(num_id, abs_id):
        n = OxmlElement("w:num")
        n.set(qn("w:numId"), str(num_id))
        ab = OxmlElement("w:abstractNumId")
        ab.set(qn("w:val"), str(abs_id))
        n.append(ab)
        return n

    first_num = numbering.find(qn("w:num"))
    for a in (
        _abstract(ba, "bullet", profile.lists.bullet_char),
        _abstract(oa, "decimal", profile.lists.ordered_level_text),
    ):
        if first_num is not None:
            first_num.addprevious(a)
        else:
            numbering.append(a)
    cleanup = numbering.find(qn("w:numIdMacAtCleanup"))
    for n in (_num(bn, ba), _num(on, oa)):
        if cleanup is not None:
            cleanup.addprevious(n)
        else:
            numbering.append(n)
    return {"unordered": bn, "ordered": on}


def _apply_list(p, num_id: int) -> None:
    pPr = p._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    numPr.append(ilvl)
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), str(num_id))
    numPr.append(nid)
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is not None:
        pStyle.addnext(numPr)
    else:
        pPr.insert(0, numPr)


def _indent_first_line(p, profile: WordFormatProfile) -> None:
    """正文首行缩进 2 字符（中文报告规范）。"""
    pPr = p._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLineChars"), str(profile.body.first_line_indent_chars * 100))
    ind.set(qn("w:firstLine"), str(profile.body.first_line_indent_twips))


def _ensure_caption_styles(doc, profile: WordFormatProfile) -> None:
    """题注命名样式（Caption Figure/Caption Table）：参数归格式 profile，居中、图下表上。"""

    cap = profile.captions
    space = profile.tables.caption_space_pt
    for name, position in (
        ("Caption Figure", cap.figure_position),
        ("Caption Table", cap.table_position),
    ):
        try:
            style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        except ValueError:
            style = doc.styles[name]
        style.font.size = Pt(cap.font_size_pt)
        style.font.color.rgb = _theme_color(profile, cap.color)
        pf = style.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.space_before = Pt(space if position == "below" else 0)
        pf.space_after = Pt(space if position == "above" else 0)


def _emit_caption(doc, style_name: str, text: str):
    """按命名题注样式输出题注段，返回首个 run 供批注锚定。"""

    p = doc.add_paragraph(text, style=style_name)
    return p.runs[0]


def _plate_text(nodes) -> str:
    """从 Plate 文本骨架抽取纯文本（value 兜空时的回退；真相仍是 cell.value）。"""
    out: list[str] = []
    for n in nodes or []:
        if isinstance(n, dict):
            for leaf in n.get("children", []):
                if isinstance(leaf, dict):
                    out.append(leaf.get("text", ""))
    return "".join(out)


def _cell_display(cell, separator: str) -> str:
    """单元格导出文本：多选按包语言的列表分隔符连接，标量直出，空值回退 Plate 文本骨架。"""
    v = cell.value
    if isinstance(v, list):
        return separator.join(str(x) for x in v)
    if v not in (None, ""):
        return str(v)
    return _plate_text(cell.children)


def _render_rows(tm, report, block_id: str | None = None):
    """兼容既有 renderer 测试；实际判定由 contract.renderability 统一拥有。"""

    return renderable_table_rows(tm, report, block_id)


def _render_table(
    doc,
    blk: Block,
    report,
    *,
    profile: WordFormatProfile,
    numbering: FigureNumbering,
    in_appendix: bool,
    figure_specs: list[FigureSpec],
    comment_text: str | None = None,
) -> None:
    """按 colDefs + children 渲染：表头作真实行（th 底色加粗），合并用 _Cell.merge（colSpan/rowSpan），三线表样式。"""
    tm = blk.table
    figure_spec = numbering.assign(
        "table",
        block_id=blk.id,
        kind="table",
        caption=tm.caption,
        in_appendix=in_appendix,
    )
    figure_specs.append(figure_spec)
    caption_run = _emit_caption(doc, "Caption Table", figure_spec.caption_text)
    ncols = len(tm.colDefs)
    col_by_key = {col.key: col for col in tm.colDefs}
    rows = _render_rows(tm, report, blk.id)
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_three_line(profile, table)
    _set_col_widths(
        profile, doc, table, ncols, tm.firstColumnNarrow, _column_width_weights(tm)
    )
    occupied: set[tuple[int, int]] = (
        set()
    )  # 被上方 rowSpan/colSpan 覆盖的网格位（合并占位，跳过）
    for ri, row in enumerate(rows):
        if row.headerRow:
            _repeat_header(table.rows[ri])
        else:
            _keep_row_together(table.rows[ri])
        ci = 0
        for cell in row.children:
            while (ri, ci) in occupied:
                ci += 1
            cspan, rspan = max(cell.colSpan, 1), max(cell.rowSpan, 1)
            anchor = table.cell(ri, ci)
            if cspan > 1 or rspan > 1:
                anchor = anchor.merge(table.cell(ri + rspan - 1, ci + cspan - 1))
                for r in range(ri, ri + rspan):
                    for c in range(ci, ci + cspan):
                        if (r, c) != (ri, ci):
                            occupied.add((r, c))
            display = _cell_display(cell, list_separator(profile.language))
            # 表头单元不带 colKey，按列序号对到 colDefs 才能判定是否 review-only。
            review_only = _is_review_only_column(cell, tm, ci)
            if cell.type == "th":
                _set_cell_text(
                    profile, anchor, display, header=True, review_only=review_only
                )
            else:
                col_def = col_by_key.get(cell.colKey or "")
                align_center = bool(
                    col_def
                    and col_def.cellType in ("single_select", "multi_select")
                    or (tm.firstColumnNarrow and ci == 0 and cspan == 1)
                )
                _set_cell_text(
                    profile,
                    anchor,
                    display,
                    align_center=align_center,
                    review_only=review_only,
                )
            ci += cspan
    _add_customer_comment(doc, caption_run, comment_text, profile=profile)
    if tm.disclaimer:
        p = doc.add_paragraph()
        r = p.add_run(profile.labels.table_note_prefix + tm.disclaimer)
        r.font.size = Pt(profile.captions.table_note_font_size_pt)
        r.italic = profile.captions.table_note_italic
        r.font.color.rgb = _theme_color(profile, profile.captions.color)


def _render_image(
    doc,
    blk: Block,
    report,
    resolved_images: dict[str, tuple[ResolvedEvidenceImage, ...]] | None = None,
    *,
    profile: WordFormatProfile,
    numbering: FigureNumbering,
    in_appendix: bool,
    figure_specs: list[FigureSpec],
    comment_text: str | None = None,
) -> None:
    resolved_group = (resolved_images or {}).get(blk.id)
    if resolved_group:
        for index, resolved in enumerate(resolved_group):
            figure_spec = numbering.assign(
                "figure",
                block_id=blk.id,
                kind=resolved.kind,
                caption=resolved.caption,
                in_appendix=in_appendix,
            )
            figure_specs.append(figure_spec)
            paragraph = doc.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture_run = paragraph.add_run()
            shape = picture_run.add_picture(
                BytesIO(resolved.data), width=Cm(resolved.width_cm)
            )
            shape._inline.docPr.set("descr", resolved.alt_text)
            caption_run = _emit_caption(doc, "Caption Figure", figure_spec.caption_text)
            # 客户批注只锚定承载块的首个内容单元,后续图片沿用既有可见内容。
            if index == 0:
                _add_customer_comment(
                    doc, caption_run or picture_run, comment_text, profile=profile
                )
        return
    derived_render_failed = False
    if blk.image and blk.image.derivedVisualization:
        spec = blk.image.derivedVisualization
        png = None
        if spec.kind == "quantitative_metric_summary":
            from sustainability_desk.export.metric_summary_chart import (
                render_quantitative_metric_summary,
            )

            try:
                png = render_quantitative_metric_summary(
                    report,
                    spec.metricKeys,
                    featured_metric_keys=spec.featuredMetricKeys,
                    display_mode=spec.displayMode,
                    group_by=spec.groupBy,
                )
            except Exception:  # noqa: BLE001 — 渲染失败回退占位文字，不阻断导出
                derived_render_failed = True
                png = None
        if png is not None:
            # 议题指标摘要图（metric_summary）不参与全文
            # 图片编号——不调用 numbering.assign（不占「图N」）、不进入 figure_specs
            # 清单；后续真图编号顺延不受它影响。题注（如有）以无编号纯题注输出。
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture_run = p.add_run()
            picture_run.add_picture(
                BytesIO(png),
                width=Cm(profile.figures.widths_cm.derived_metric_summary),
            )
            caption = blk.image.caption
            caption_run = (
                _emit_caption(doc, "Caption Figure", caption.strip())
                if caption and caption.strip()
                else None
            )
            _add_customer_comment(
                doc, caption_run or picture_run, comment_text, profile=profile
            )
            return
        if spec.emptyBehavior == "hide" and not derived_render_failed:
            return

    # 双重重要性矩阵图据评估得分实时渲染嵌入；其余 image 块保持占位文字。
    if (
        blk.image
        and blk.id == _MATRIX_IMAGE_BLOCK_ID
        and report.assessment
        and report.assessment.topics
    ):
        from sustainability_desk.export.matrix_chart import render_materiality_matrix

        try:
            png = render_materiality_matrix(
                report.assessment, package=knowledge_package_of(report)
            )
        except Exception:  # noqa: BLE001 — 渲染失败回退占位文字，不阻断导出
            png = None
        if png is not None:
            figure_spec = numbering.assign(
                "figure",
                block_id=blk.id,
                kind="materiality_matrix",
                caption=blk.image.caption,
                in_appendix=in_appendix,
            )
            figure_specs.append(figure_spec)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture_run = p.add_run()
            picture_run.add_picture(
                BytesIO(png), width=Cm(profile.figures.widths_cm.materiality_matrix)
            )
            caption_run = _emit_caption(doc, "Caption Figure", figure_spec.caption_text)
            _add_customer_comment(
                doc, caption_run or picture_run, comment_text, profile=profile
            )
            return
    box = doc.add_paragraph()
    fallback_text = (
        blk.image.placeholder
        or blk.image.caption
        or (profile.labels.derived_figure_failed if derived_render_failed else "")
    )
    r = box.add_run(profile.labels.image_placeholder_template.format(text=fallback_text))
    r.font.color.rgb = _theme_color(profile, "placeholder_gray")
    # 占位即未渲染成图：不占编号、不输出题注（编号只计实际渲染的图表）。
    _add_customer_comment(doc, r, comment_text, profile=profile)


def _block_renderable(blk: Block, report: Report) -> bool:
    """兼容既有 renderer 调用；公开判定由 contract.renderability 统一拥有。"""

    return block_is_renderable(blk, report)


def _section_renderable(sec, report: Report) -> bool:
    """兼容既有 renderer 调用；公开判定由 contract.renderability 统一拥有。"""

    return section_is_renderable(sec, report)


def _prepared_report_for_render(report: Report) -> Report:
    """在唯一位置应用 Word 可见性投影，供两份交付 Word 共同消费。"""

    from sustainability_desk.contract.stakeholder_engagement import (
        apply_stakeholder_engagement_projection,
    )
    from sustainability_desk.quantitative_metrics import (
        apply_quantitative_metrics_table_projection,
    )

    prepared = apply_stakeholder_engagement_projection(report)
    prepared = apply_assessment_projection(prepared)
    prepared = apply_quantitative_metrics_table_projection(prepared)
    prepared = apply_disclosure_standards_index_projection(prepared)
    return prepared


def _rendered_units_for_sections(
    sections, report: Report
) -> tuple[RenderedContentUnit, ...]:
    labels = format_profile_for(report).labels
    units: list[RenderedContentUnit] = []

    def visit(section) -> None:
        if not _section_renderable(section, report):
            return
        for block in section.blocks:
            if not _block_renderable(block, report):
                continue
            if block.listType:
                text = _inline_text(block.content, report)
                if text.strip():
                    units.append(
                        RenderedContentUnit(
                            anchor_id=f"block:{block.id}:list:0",
                            block_id=block.id,
                            kind="list",
                            text=text,
                        )
                    )
            elif block.type == "table" and block.table:
                text = block.table.caption or labels.default_table_unit_text
                units.append(
                    RenderedContentUnit(
                        anchor_id=f"block:{block.id}:table:0",
                        block_id=block.id,
                        kind="table",
                        text=text,
                    )
                )
            elif block.type == "image" and block.image:
                text = block.image.caption or block.image.placeholder or labels.default_image_unit_text
                units.append(
                    RenderedContentUnit(
                        anchor_id=f"block:{block.id}:image:0",
                        block_id=block.id,
                        kind="image",
                        text=text,
                    )
                )
            else:
                text = _inline_text(block.content, report)
                segments = [
                    segment.strip()
                    for segment in re.split(r"\n+", text)
                    if segment.strip()
                ]
                for index, segment in enumerate(segments):
                    units.append(
                        RenderedContentUnit(
                            anchor_id=f"block:{block.id}:paragraph:{index}",
                            block_id=block.id,
                            kind="paragraph",
                            text=segment,
                        )
                    )
        for child in section.children or []:
            visit(child)

    for section in sections:
        visit(section)
    return tuple(units)


def build_document_render_plan(report: Report) -> DocumentRenderPlan:
    """冻结正文投影与稳定 anchor，供普通和批注 Word 同源渲染。"""

    prepared = _prepared_report_for_render(report)
    labels = (
        number_sections(
            prepared.sections,
            lambda node: _section_renderable(node, prepared),
            scheme=format_profile_for(report).numbering.section_scheme,
            unnumbered_chapter_keys=format_profile_for(report).numbering.unnumbered_chapter_keys,
        )
    )
    return DocumentRenderPlan(
        report=prepared,
        section_labels=labels,
        units=_rendered_units_for_sections(prepared.sections, prepared),
    )


def _add_customer_comment(
    doc: Document, run, text: str | None, *, profile: WordFormatProfile
) -> None:
    """只在批注 Word 中写入真实 OOXML comment，正文不承担说明文本。"""

    if not text:
        return
    has_drawing = bool(run._r.findall(qn("w:drawing")))
    if not run.text.strip() and not has_drawing:
        raise ValueError("客户批注必须附着到非空可见 Word run")
    doc.add_comment(run, text=text, author=profile.footer.provider_name, initials="AI")


def _render_block(
    doc,
    blk: Block,
    report,
    list_ids: dict,
    resolved_images: dict[str, tuple[ResolvedEvidenceImage, ...]] | None = None,
    comment_text_by_anchor: Mapping[str, str] | None = None,
    *,
    profile: WordFormatProfile,
    numbering: FigureNumbering,
    in_appendix: bool,
    figure_specs: list[FigureSpec],
) -> None:
    if not _block_renderable(blk, report):
        return
    if blk.listType:
        p = doc.add_paragraph(_inline_text(blk.content, report), style="List Paragraph")
        _apply_list(p, list_ids[blk.listType])
        comment = (comment_text_by_anchor or {}).get(f"block:{blk.id}:list:0")
        if comment:
            _add_customer_comment(doc, p.runs[0], comment, profile=profile)
        return
    if blk.type == "table" and blk.table:
        _render_table(
            doc,
            blk,
            report,
            profile=profile,
            numbering=numbering,
            in_appendix=in_appendix,
            figure_specs=figure_specs,
            comment_text=(comment_text_by_anchor or {}).get(f"block:{blk.id}:table:0"),
        )
        return
    if blk.type == "image" and blk.image:
        _render_image(
            doc,
            blk,
            report,
            resolved_images,
            profile=profile,
            numbering=numbering,
            in_appendix=in_appendix,
            figure_specs=figure_specs,
            comment_text=(comment_text_by_anchor or {}).get(f"block:{blk.id}:image:0"),
        )
        return
    if blk.placeholderNotice:
        # 升级占位块：范围外议题章节的唯一正文，弱化样式呈现，不参与图编号。
        p = doc.add_paragraph(blk.placeholderNotice, style="Normal")
        for r in p.runs:
            r.font.color.rgb = _theme_color(profile, profile.captions.color)
            r.font.italic = True
        return
    # paragraph：多段生成正文按空行拆成多个真实 Word 段落（段距由 Normal 样式承载，不插空行段）
    text = _inline_text(blk.content, report)
    segments = [s.strip() for s in re.split(r"\n+", text) if s.strip()] or [text]
    footnote_text = _inline_text(blk.footnote, report).strip() if blk.footnote else ""
    for index, seg in enumerate(segments):
        p = doc.add_paragraph(seg, style="Normal")
        # 脚注挂在本块最后一段末尾：引用标记必须落在正文之后、批注锚点之前。
        if footnote_text and index == len(segments) - 1:
            add_footnote(
                doc,
                p,
                footnote_text,
                text_style_name=profile.footnotes.text_style_name,
                reference_style_name=profile.footnotes.reference_style_name,
            )
        if blk.styleRole == "source_note":
            for r in p.runs:
                r.font.size = Pt(profile.captions.source_note_font_size_pt)
                r.font.color.rgb = _theme_color(profile, profile.captions.color)
        else:
            _indent_first_line(p, profile)  # 正文首行缩进 2 字符
        comment = (comment_text_by_anchor or {}).get(
            f"block:{blk.id}:paragraph:{index}"
        )
        if comment:
            _add_customer_comment(doc, p.runs[0], comment, profile=profile)


# ---- 外壳 + 封面 ----
def _is_toc_sdt(sdt) -> bool:
    """模板中的目录内容控件是唯一允许保留的正文外壳内容。"""

    return any(
        "TOC" in (node.text or "") for node in sdt.findall(".//" + qn("w:instrText"))
    )


def _prepare_shell(doc, *, retain_cover_and_toc: bool) -> None:
    """清空模板正文；完整报告仅保留目录，封面始终由当前交付投影重建。"""

    body = doc.element.body
    keep = {qn("w:sectPr")}
    for ch in list(body):
        if ch.tag in keep:
            continue
        if retain_cover_and_toc and ch.tag == qn("w:sdt") and _is_toc_sdt(ch):
            continue
        else:
            body.remove(ch)


def _set_east_asia_font(run: Run, font_name: str) -> None:
    run.font.name = font_name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def _move_before_toc(toc_sdt, paragraph) -> None:
    """把新建封面段落放在目录内容控件之前，保持封面、目录、正文的真实顺序。"""

    if toc_sdt is None:
        raise ValueError("完整报告模板缺少目录内容控件")
    toc_sdt.addprevious(paragraph._p)


def _move_before_toc_after(toc_sdt, element, *, after) -> None:
    """把说明页的段落或表格元素放在封面之后、目录之前；``after`` 为同页已落位的前一个元素。

    说明页是读报告前的前置提示，故排在目录之前。它整体位于封面与目录之间，既不进目录、
    也不参与正文章号编号——正式稿与审阅稿的章号、目录由此保持逐条一致。
    首个元素挂在目录控件正前方，其余依次跟在前一个之后，保证页内顺序稳定。
    """

    if toc_sdt is None:
        raise ValueError("完整报告模板缺少目录内容控件")
    if after is None:
        toc_sdt.addprevious(element)
    else:
        after.addnext(element)


def _append_page_field(paragraph) -> None:
    """插入真实 PAGE 域，不依赖写死的页码文本。"""

    begin_run = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run.append(begin)
    paragraph._p.append(begin_run)
    instruction_run = OxmlElement("w:r")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    instruction_run.append(instruction)
    paragraph._p.append(instruction_run)
    separate_run = OxmlElement("w:r")
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run.append(separate)
    paragraph._p.append(separate_run)
    cached_run = OxmlElement("w:r")
    cached_text = OxmlElement("w:t")
    cached_text.text = "1"
    cached_run.append(cached_text)
    paragraph._p.append(cached_run)
    end_run = OxmlElement("w:r")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run.append(end)
    paragraph._p.append(end_run)


def _restart_page_numbering(section) -> None:
    """将正文所在节的页码从 1 重新开始；封面和目录不属于正文页码。"""

    section_properties = section._sectPr
    page_number_type = section_properties.find(qn("w:pgNumType"))
    if page_number_type is None:
        page_number_type = OxmlElement("w:pgNumType")
        section_properties.append(page_number_type)
    page_number_type.set(qn("w:start"), "1")


def _begin_numbered_body_section(doc: Document) -> None:
    """在完整报告的目录后开始新的正文节，封面与目录页不显示或占用正文页码。"""

    doc.add_section(WD_SECTION.NEW_PAGE)
    _restart_page_numbering(doc.sections[-1])


def _clear_footer(section) -> None:
    """解除继承并清空指定节的页脚，避免封面和目录泄露正文页码。"""

    footer = section.footer
    footer.is_linked_to_previous = False
    for paragraph in list(footer.paragraphs):
        paragraph._element.getparent().remove(paragraph._element)


def _add_attribution_line(
    section, *, profile: WordFormatProfile, text: str, with_page_number: bool
) -> None:
    """写一行页脚：左侧制作说明，可选右侧页码。

    制作说明是交付物的出处声明，读者在封面即应看到，故所有节都承载；
    页码只属于正文节——封面与目录页不占用正文页码（见 _restart_page_numbering）。
    """

    line = section.footer.add_paragraph()
    line.alignment = WD_ALIGN_PARAGRAPH.LEFT
    line.paragraph_format.space_after = Pt(0)
    size = Pt(profile.footer.review_font_size_pt)
    cover_gray = _theme_color(profile, "cover_gray")

    def _styled(run):
        run.font.size = size
        run.font.color.rgb = cover_gray
        _set_east_asia_font(run, profile.footer.east_asia_font)
        return run

    _styled(line.add_run(text))
    if not with_page_number:
        return
    available_width = section.page_width - section.left_margin - section.right_margin
    line.paragraph_format.tab_stops.add_tab_stop(
        available_width,
        WD_TAB_ALIGNMENT.RIGHT,
    )
    line.add_run("\t")
    _styled(line.add_run(profile.labels.page_number_prefix))
    _append_page_field(line)
    _styled(line.add_run(profile.labels.page_number_suffix))


def _configure_footer(
    doc: Document,
    *,
    profile: WordFormatProfile,
    delivery_variant: DocumentDeliveryVariant,
    review_generated_at: datetime | None,
) -> None:
    """两种交付物都全篇承载制作说明；页码只属于正文节。

    制作说明是交付物的出处声明，读者翻开封面第一眼就应看到它，因此封面、
    资料处理说明与目录同样承载；这些页仍不显示页码，避免与正文页码序列混淆。
    两稿的差别只在生成时点：审阅稿额外带冻结时间用于分辨版本，正式稿不带。
    """

    if delivery_variant == "review" and review_generated_at is None:
        raise ValueError("审阅版 Word 必须绑定冻结的生成时间")
    front_sections = tuple(doc.sections[:-1])
    body_sections = (doc.sections[-1],)

    attribution_parts = [profile.footer.review_prefix_standard]
    if profile.footer.review_contact:
        attribution_parts.append(profile.footer.review_contact)
    if profile.footer.repository_url:
        attribution_parts.append(profile.footer.repository_url)
    if delivery_variant == "review":
        # 审阅稿额外承载冻结的生成时点：它是内部定稿依据，用于分辨版本。
        timestamp = review_generated_at.astimezone(
            ZoneInfo(profile.footer.timezone)
        ).strftime(profile.footer.timestamp_format)
        attribution_parts.append(
            profile.labels.generated_at_template.format(timestamp=timestamp)
        )
    attribution = " · ".join(attribution_parts)
    for section in front_sections:
        _clear_footer(section)
        _add_attribution_line(
            section, profile=profile, text=attribution, with_page_number=False
        )

    for section in body_sections:
        _clear_footer(section)
        _add_attribution_line(
            section, profile=profile, text=attribution, with_page_number=True
        )


def _set_ai_disclosure_metadata(
    doc, *, profile: WordFormatProfile, company_name: str, year: str
) -> None:
    """写入《标识办法》第五条要求的文件元数据隐式标识。

    三要素：生成合成标签（AIGC）、服务提供者（格式 profile 的 provider_name）、内容制作编号。
    编号由封面已可见的企业名与年度派生——report_id 等内部标识不进交付物（用户可见文本
    边界），故不作编号来源。

    元数据是补充层，承担告知义务的是封面那行显式标识。此处按办法第五条的三要素写成
    可读串，不追 GB 45438-2025 的字段编码：交付物由用户自行决定去向，不经内容分发
    平台，逐字符对齐国标编码在本场景不带来实际收益。
    """

    doc.core_properties.comments = (
        f"AIGC;{profile.footer.provider_name};{company_name}-{year}"
    )


def _inject_cover(
    doc: Document,
    report,
    *,
    profile: WordFormatProfile,
    delivery_variant: DocumentDeliveryVariant,
) -> Run | None:
    """基于当前 Report 重建简洁正式的封面，并返回企业名称锚点。"""

    def _fv(key):
        f = report.fields.get(key)
        return f.value if f is not None else None

    name = str(_fv("company_registered_name") or "")
    year = str(_fv("reporting_year") or "")
    toc_sdt = next(
        (sdt for sdt in doc.element.body.findall(qn("w:sdt")) if _is_toc_sdt(sdt)),
        None,
    )
    inserted: list = []

    def add_cover_paragraph(*, alignment=WD_ALIGN_PARAGRAPH.CENTER):
        paragraph = doc.add_paragraph()
        paragraph.alignment = alignment
        inserted.append(paragraph)
        return paragraph

    cover = profile.cover_full_report
    cover_gray = _theme_color(profile, "cover_gray")
    if delivery_variant == "review":
        logo = add_cover_paragraph(alignment=WD_ALIGN_PARAGRAPH.LEFT)
        logo.paragraph_format.space_before = Pt(cover.logo_space_before_pt)
        logo.paragraph_format.space_after = Pt(cover.logo_space_after_pt)
        # 封面不放品牌字标图片；此段只保留审阅稿封面的版面留白。
    else:
        spacer = add_cover_paragraph()
        spacer.paragraph_format.space_before = Pt(cover.standard_spacer_before_pt)
        spacer.paragraph_format.space_after = Pt(0)

    company = add_cover_paragraph()
    company.paragraph_format.space_before = Pt(
        cover.company_space_before_review_pt
        if delivery_variant == "review"
        else cover.company_space_before_standard_pt
    )
    company.paragraph_format.space_after = Pt(cover.company_space_after_pt)
    company_run = company.add_run(name)
    company_run.bold = True
    company_run.font.size = Pt(cover.company_font_size_pt)
    company_run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    _set_east_asia_font(company_run, profile.body.east_asia_font)

    title_text = cover.title_text
    report_title = add_cover_paragraph()
    report_title.paragraph_format.space_after = Pt(cover.title_space_after_pt)
    title_run = report_title.add_run(title_text)
    title_run.bold = True
    title_run.font.size = Pt(cover.title_font_size_pt)
    title_run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    _set_east_asia_font(title_run, profile.body.east_asia_font)

    period = add_cover_paragraph()
    period.paragraph_format.space_after = Pt(cover.period_space_after_pt)
    period_run = period.add_run(profile.labels.reporting_period_template.format(year=year))
    period_run.font.size = Pt(cover.period_font_size_pt)
    period_run.font.color.rgb = cover_gray
    _set_east_asia_font(period_run, profile.body.east_asia_font)

    # 《人工智能生成合成内容标识办法》第四条：文本类内容在起始位置添加显著提示。
    # 正式稿与审阅稿一律承载——标识义务看内容是否 AI 生成，与稿件类型无关。
    ai_disclosure = add_cover_paragraph()
    ai_disclosure.paragraph_format.space_before = Pt(cover.ai_disclosure_space_before_pt)
    ai_disclosure_run = ai_disclosure.add_run(cover.ai_disclosure_text)
    ai_disclosure_run.font.size = Pt(cover.ai_disclosure_font_size_pt)
    ai_disclosure_run.font.color.rgb = cover_gray
    _set_east_asia_font(ai_disclosure_run, profile.body.east_asia_font)

    page_break = add_cover_paragraph()
    page_break.add_run().add_break(WD_BREAK.PAGE)
    for paragraph in inserted:
        _move_before_toc(toc_sdt, paragraph)
    doc.core_properties.title = profile.labels.document_title_template.format(
        year=year, title=title_text
    )
    _set_ai_disclosure_metadata(doc, profile=profile, company_name=name, year=year)
    return company_run


def _inject_material_processing_notice(doc, notice, *, profile: WordFormatProfile):
    """在封面之后、目录之前插入资料处理说明页（仅审阅稿）。

    说明页是读报告前的前置提示，故排在目录之前。标题走普通段落而非 Heading 样式：
    多级编号与目录域都只收录 Heading，因此本页既不占「第N章」章号也不进目录，
    正式稿与审阅稿的章号、目录逐条一致。
    返回本页最后一个已落位元素，供后续前置页接续排布。
    """

    style = profile.material_processing_notice
    cover_gray = _theme_color(profile, "cover_gray")
    toc_sdt = next(
        (sdt for sdt in doc.element.body.findall(qn("w:sdt")) if _is_toc_sdt(sdt)),
        None,
    )
    inserted: list = []

    def add_paragraph(*, size, space_before=0, space_after=0, indent_chars=0):
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(space_before)
        paragraph.paragraph_format.space_after = Pt(space_after)
        # 不显式设定则继承正文 1.5 倍行距，续行与条目间距等宽而被误读成新条目。
        paragraph.paragraph_format.line_spacing = style.line_spacing_multiple
        if indent_chars:
            ind = OxmlElement("w:ind")
            ind.set(qn("w:leftChars"), str(indent_chars * 100))
            paragraph._p.get_or_add_pPr().append(ind)
        inserted.append((paragraph, size))
        return paragraph

    def add_run(paragraph, text, size, *, bold=False, gray=False):
        run = paragraph.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        if gray:
            run.font.color.rgb = cover_gray
        _set_east_asia_font(run, profile.body.east_asia_font)
        return run

    heading = add_paragraph(
        size=style.heading_font_size_pt, space_after=style.heading_space_after_pt
    )
    add_run(heading, notice.heading, style.heading_font_size_pt, bold=True)

    lead = add_paragraph(
        size=style.lead_font_size_pt, space_after=style.lead_space_after_pt
    )
    add_run(lead, notice.lead, style.lead_font_size_pt, gray=True)

    def add_sub_heading(text: str) -> None:
        sub_heading = add_paragraph(
            size=style.file_name_font_size_pt,
            space_before=style.file_name_space_before_pt,
            space_after=style.file_name_space_after_pt,
        )
        # 小节标题与引导句随其后的内容走，不在页末孤悬。
        sub_heading.paragraph_format.keep_with_next = True
        add_run(sub_heading, text, style.file_name_font_size_pt, bold=True)

    def add_sub_lead(text: str) -> None:
        sub_lead = add_paragraph(
            size=style.lead_font_size_pt, space_after=style.item_space_after_pt
        )
        sub_lead.paragraph_format.keep_with_next = True
        add_run(sub_lead, text, style.lead_font_size_pt, gray=True)

    if notice.files:
        add_sub_heading(notice.files_heading)
        add_sub_lead(notice.files_lead)
    for file in notice.files:
        name = add_paragraph(
            size=style.item_font_size_pt,
            space_before=style.next_action_space_after_pt,
            space_after=style.file_name_space_after_pt,
        )
        add_run(name, file.material_name, style.item_font_size_pt, bold=True)
        for index, item in enumerate(file.items, start=1):
            body = add_paragraph(
                size=style.item_font_size_pt, space_after=style.item_space_after_pt
            )
            add_run(body, f"{index}. {item.message}", style.item_font_size_pt)
            action = add_paragraph(
                size=style.next_action_font_size_pt,
                space_after=style.next_action_space_after_pt,
                indent_chars=style.next_action_indent_chars,
            )
            add_run(
                action,
                f"{style.next_action_label}　",
                style.next_action_font_size_pt,
                bold=True,
                gray=True,
            )
            add_run(action, item.next_action, style.next_action_font_size_pt, gray=True)

    page_break = add_paragraph(size=style.item_font_size_pt)
    page_break.add_run().add_break(WD_BREAK.PAGE)

    previous = None
    for element_owner, _ in inserted:
        element = element_owner._element
        _move_before_toc_after(toc_sdt, element, after=previous)
        previous = element
    return previous


def _inject_standards_compliance_notice(
    doc, notice, *, profile: WordFormatProfile, after_element=None
):
    """在封面（及资料处理说明页）之后、目录之前插入准则对照说明页（仅审阅稿）。

    与资料处理说明页共用版式与定位机制：标题走普通段落而非 Heading 样式，
    因此本页既不占章号也不进目录，正式稿与审阅稿的章号、目录逐条一致。
    返回本页最后一个已落位元素，供后续前置页接续排布。
    """

    style = profile.material_processing_notice
    cover_gray = _theme_color(profile, "cover_gray")
    toc_sdt = next(
        (sdt for sdt in doc.element.body.findall(qn("w:sdt")) if _is_toc_sdt(sdt)),
        None,
    )
    inserted: list = []

    def add_paragraph(*, size, space_before=0, space_after=0, indent_chars=0):
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(space_before)
        paragraph.paragraph_format.space_after = Pt(space_after)
        # 不显式设定则继承正文 1.5 倍行距，续行与条目间距等宽而被误读成新条目。
        paragraph.paragraph_format.line_spacing = style.line_spacing_multiple
        if indent_chars:
            ind = OxmlElement("w:ind")
            ind.set(qn("w:leftChars"), str(indent_chars * 100))
            paragraph._p.get_or_add_pPr().append(ind)
        inserted.append((paragraph, size))
        return paragraph

    def add_run(paragraph, text, size, *, bold=False, gray=False):
        run = paragraph.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        if gray:
            run.font.color.rgb = cover_gray
        _set_east_asia_font(run, profile.body.east_asia_font)
        return run

    heading = add_paragraph(
        size=style.heading_font_size_pt, space_after=style.heading_space_after_pt
    )
    add_run(heading, notice.heading, style.heading_font_size_pt, bold=True)

    lead = add_paragraph(size=style.lead_font_size_pt, space_after=style.lead_space_after_pt)
    add_run(lead, notice.lead, style.lead_font_size_pt, gray=True)

    summary = add_paragraph(size=style.item_font_size_pt, space_after=style.item_space_after_pt)
    add_run(summary, notice.summary, style.item_font_size_pt)

    for group in notice.groups:
        group_heading = add_paragraph(
            size=style.file_name_font_size_pt,
            space_before=style.file_name_space_before_pt,
            space_after=style.file_name_space_after_pt,
        )
        group_heading.paragraph_format.keep_with_next = True
        add_run(group_heading, group.heading, style.file_name_font_size_pt, bold=True)

        group_lead = add_paragraph(
            size=style.lead_font_size_pt, space_after=style.item_space_after_pt
        )
        group_lead.paragraph_format.keep_with_next = True
        add_run(group_lead, group.lead, style.lead_font_size_pt, gray=True)

        for index, item in enumerate(group.items, start=1):
            body = add_paragraph(
                size=style.item_font_size_pt, space_after=style.item_space_after_pt
            )
            add_run(
                body,
                f"{index}. 【{item.scope_label}】{item.message}",
                style.item_font_size_pt,
            )
            if item.next_action is None:
                continue
            action = add_paragraph(
                size=style.next_action_font_size_pt,
                space_after=style.next_action_space_after_pt,
                indent_chars=style.next_action_indent_chars,
            )
            add_run(
                action,
                f"{style.next_action_label}　",
                style.next_action_font_size_pt,
                bold=True,
                gray=True,
            )
            add_run(action, item.next_action, style.next_action_font_size_pt, gray=True)

    page_break = add_paragraph(size=style.item_font_size_pt)
    page_break.add_run().add_break(WD_BREAK.PAGE)

    previous = after_element
    for element_owner, _ in inserted:
        element = element_owner._element
        _move_before_toc_after(toc_sdt, element, after=previous)
        previous = element
    return previous


def _refresh_toc_cache(doc) -> None:
    """重建目录项：标题书签与逐项 PAGEREF 域必须成对生成。

    页码缓存会在最终版式阶段确定；此处不得标脏字段，否则 Word 打开交付
    件时会尝试更新所有字段并显示安全提示。
    """
    headings: list[tuple[int, str, str]] = []
    bookmark_ids = [
        int(bookmark_id)
        for marker in doc.element.findall(".//" + qn("w:bookmarkStart"))
        if (bookmark_id := marker.get(qn("w:id"))) is not None and bookmark_id.isdigit()
    ]
    next_bookmark_id = max(bookmark_ids, default=0) + 1
    toc_bookmark_index = 1
    for paragraph in doc.paragraphs:
        style_name = paragraph.style.name if paragraph.style is not None else ""
        match = re.fullmatch(r"Heading ([1-4])", style_name)
        if match and paragraph.text.strip():
            level = int(match.group(1))
            if toc_includes_heading_level(level):
                bookmark_name = f"GS_TOC_{toc_bookmark_index:03d}"
                toc_bookmark_index += 1
                paragraph_element = paragraph._p
                old_toc_bookmark_ids = {
                    marker.get(qn("w:id"), "")
                    for marker in paragraph_element.findall(qn("w:bookmarkStart"))
                    if marker.get(qn("w:name"), "").startswith("GS_TOC_")
                }
                for marker in paragraph_element.findall(qn("w:bookmarkStart")):
                    if marker.get(qn("w:name"), "").startswith("GS_TOC_"):
                        paragraph_element.remove(marker)
                for marker in paragraph_element.findall(qn("w:bookmarkEnd")):
                    if marker.get(qn("w:id"), "") in old_toc_bookmark_ids:
                        paragraph_element.remove(marker)
                bookmark_start = OxmlElement("w:bookmarkStart")
                bookmark_start.set(qn("w:id"), str(next_bookmark_id))
                bookmark_start.set(qn("w:name"), bookmark_name)
                paragraph_element.insert(
                    1 if paragraph_element.find(qn("w:pPr")) is not None else 0,
                    bookmark_start,
                )
                bookmark_end = OxmlElement("w:bookmarkEnd")
                bookmark_end.set(qn("w:id"), str(next_bookmark_id))
                paragraph_element.append(bookmark_end)
                headings.append((level, paragraph.text.strip(), bookmark_name))
                next_bookmark_id += 1

    toc_sdt = next(
        (
            sdt
            for sdt in doc.element.body.findall(qn("w:sdt"))
            if any(
                "TOC" in (node.text or "")
                for node in sdt.findall(".//" + qn("w:instrText"))
            )
        ),
        None,
    )
    if toc_sdt is None:
        return
    content = toc_sdt.find(qn("w:sdtContent"))
    if content is None:
        return

    paragraphs = content.findall(qn("w:p"))
    start_index: int | None = None
    end_index: int | None = None
    field_depth = 0
    for index, paragraph in enumerate(paragraphs):
        instructions = "".join(
            node.text or "" for node in paragraph.findall(".//" + qn("w:instrText"))
        )
        if start_index is None and "TOC" in instructions:
            start_index = index
        if start_index is None:
            continue
        depth_before = field_depth
        for field_char in paragraph.findall(".//" + qn("w:fldChar")):
            char_type = field_char.get(qn("w:fldCharType"))
            if char_type == "begin":
                field_depth += 1
            elif char_type == "end":
                field_depth -= 1
        if depth_before > 0 and field_depth == 0:
            end_index = index
            break
    if start_index is None or end_index is None:
        return

    for paragraph in paragraphs[start_index : end_index + 1]:
        content.remove(paragraph)

    insertion_index = start_index
    for level, title, bookmark_name in headings:
        paragraph = OxmlElement("w:p")
        paragraph_properties = OxmlElement("w:pPr")
        paragraph_style = OxmlElement("w:pStyle")
        paragraph_style.set(qn("w:val"), f"TOC{level}")
        paragraph_properties.append(paragraph_style)
        paragraph.append(paragraph_properties)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("w:anchor"), bookmark_name)
        hyperlink.set(qn("w:history"), "1")
        text_run = OxmlElement("w:r")
        text_node = OxmlElement("w:t")
        text_node.text = title
        text_run.append(text_node)
        hyperlink.append(text_run)
        paragraph.append(hyperlink)
        tab_run = OxmlElement("w:r")
        tab_run.append(OxmlElement("w:tab"))
        paragraph.append(tab_run)
        begin_run = OxmlElement("w:r")
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        # 标记为脏：下面写入的展示缓存只是占位的「1」，阅读器打开时据书签重算真实页码。
        # 装了 LibreOffice 时 finalize_toc_page_numbers 会写入实算页码并清掉本标记
        # （交付给外部时页码即已冻结）；没装则保留，由 Word / LibreOffice 自行解析——
        # PAGEREF 指向同文档内的书签，不是外部引用，不触发 Word 的外部内容安全提示。
        begin.set(qn("w:dirty"), "true")
        begin_run.append(begin)
        paragraph.append(begin_run)
        instruction_run = OxmlElement("w:r")
        instruction = OxmlElement("w:instrText")
        instruction.set(qn("xml:space"), "preserve")
        instruction.text = f" PAGEREF {bookmark_name} \\h "
        instruction_run.append(instruction)
        paragraph.append(instruction_run)
        separate_run = OxmlElement("w:r")
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        separate_run.append(separate)
        paragraph.append(separate_run)
        page_run = OxmlElement("w:r")
        page_text = OxmlElement("w:t")
        page_text.text = "1"
        page_run.append(page_text)
        paragraph.append(page_run)
        end_run = OxmlElement("w:r")
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        end_run.append(end)
        paragraph.append(end_run)
        content.insert(insertion_index, paragraph)
        insertion_index += 1


def _render_section(
    doc,
    sec,
    report,
    list_ids,
    labels,
    resolved_images=None,
    comment_text_by_anchor: Mapping[str, str] | None = None,
    *,
    profile: WordFormatProfile,
    numbering: FigureNumbering,
    figure_specs: list[FigureSpec],
    in_appendix: bool = False,
    page_break_before: bool = False,
) -> None:
    """递归渲染章节：不可见 → 整棵子树跳过（级联）；可见 → 编号+标题(按 headingLevel) + 叶子块 + 子节。"""
    if not _section_renderable(sec, report):
        return
    appendix = in_appendix or sec.key == "report_appendix"
    # 所有用户可见 Heading 统一走动态标题 → titleContent → 稳定标题 resolver。
    label = labels.get(sec.key, "")
    title = resolved_display_title(sec, report)
    if title:
        heading = doc.add_paragraph(label + title, style=f"Heading {sec.headingLevel}")
        if page_break_before or sec.key == "report_appendix":
            heading.paragraph_format.page_break_before = True
    for blk in sec.blocks:
        _render_block(
            doc,
            blk,
            report,
            list_ids,
            resolved_images,
            comment_text_by_anchor,
            profile=profile,
            numbering=numbering,
            in_appendix=appendix,
            figure_specs=figure_specs,
        )
    for child in sec.children or []:
        _render_section(
            doc,
            child,
            report,
            list_ids,
            labels,
            resolved_images,
            comment_text_by_anchor,
            profile=profile,
            numbering=numbering,
            figure_specs=figure_specs,
            in_appendix=appendix,
            page_break_before=sec.key == "report_appendix",
        )
def render_docx(
    report: Report,
    shell_path: Path,
    out_path: Path,
    *,
    resolved_images: dict[str, tuple[ResolvedEvidenceImage, ...]] | None = None,
    render_plan: DocumentRenderPlan | None = None,
    comment_text_by_anchor: Mapping[str, str] | None = None,
    delivery_variant: DocumentDeliveryVariant = "standard",
    review_generated_at: datetime | None = None,
    cover_comment_text: str | None = None,
    material_processing_notice: "MaterialProcessingNotice | None" = None,
    standards_compliance_notice: "StandardsComplianceNotice | None" = None,
    figure_specs_out: list[FigureSpec] | None = None,
) -> Path:
    plan = render_plan or build_document_render_plan(report)
    unknown_anchors = set(comment_text_by_anchor or {}) - plan.unit_anchor_ids
    if unknown_anchors:
        raise ValueError(f"客户批注引用了不可见内容单元：{sorted(unknown_anchors)}")
    if delivery_variant == "standard" and (
        comment_text_by_anchor
        or review_generated_at is not None
        or cover_comment_text
        or material_processing_notice is not None
        or standards_compliance_notice is not None
    ):
        raise ValueError(
            "正式版 Word 不得包含审阅批注、审阅页脚、封面说明、资料处理说明页或准则对照说明页"
        )
    if delivery_variant == "review" and review_generated_at is None:
        raise ValueError("审阅版 Word 必须绑定冻结的生成时间")
    report = plan.report
    if delivery_variant == "standard":
        # 口径备注是复核性说明,只进审阅稿;正式交付稿在共享 render plan 之上
        # 再做一次裁列投影(从定量事实幂等重建,不影响审阅稿与批注锚点)。
        from sustainability_desk.quantitative_metrics import (
            apply_quantitative_metrics_table_projection,
        )

        report = apply_quantitative_metrics_table_projection(
            report, include_remark_column=False
        )
    profile = format_profile_for(report)
    doc = Document(str(shell_path))
    _prepare_shell(doc, retain_cover_and_toc=True)
    _ensure_caption_styles(doc, profile)
    _begin_numbered_body_section(doc)
    list_ids = _ensure_list_numbering(doc, profile)
    numbering = FigureNumbering(profile)
    figure_specs: list[FigureSpec] = []
    cover_company_run: Run | None = None
    _configure_footer(
        doc,
        profile=profile,
        delivery_variant=delivery_variant,
        review_generated_at=review_generated_at,
    )
    # 完整报告在正文之前保留目录；正文节由 _begin_numbered_body_section 换页开始。
    labels = plan.section_labels
    for index, sec in enumerate(report.sections):
        _render_section(
            doc,
            sec,
            report,
            list_ids,
            labels,
            resolved_images,
            comment_text_by_anchor,
            profile=profile,
            numbering=numbering,
            figure_specs=figure_specs,
            page_break_before=False,
        )
    cover_company_run = _inject_cover(
        doc,
        report,
        profile=profile,
        delivery_variant=delivery_variant,
    )
    # 说明页在封面落位之后插入：两者都挂在目录控件之前，后插入者更贴近目录，
    # 故最终顺序为 封面 → 资料处理说明 → 准则对照说明 → 目录 → 正文第一章。
    last_notice_element = None
    if material_processing_notice is not None:
        last_notice_element = _inject_material_processing_notice(
            doc, material_processing_notice, profile=profile
        )
    if standards_compliance_notice is not None:
        _inject_standards_compliance_notice(
            doc,
            standards_compliance_notice,
            profile=profile,
            after_element=last_notice_element,
        )
    _refresh_toc_cache(doc)
    if cover_comment_text:
        if cover_company_run is None:
            raise ValueError("审阅版封面缺少可批注的报告主体名称")
        _add_customer_comment(doc, cover_company_run, cover_comment_text, profile=profile)
    if figure_specs_out is not None:
        figure_specs_out.extend(figure_specs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    prune_unused_media(out_path)
    return out_path


def render_final_docx(
    report: Report,
    shell_path: Path,
    out_path: Path,
    *,
    resolved_images: dict[str, tuple[ResolvedEvidenceImage, ...]] | None = None,
    render_plan: DocumentRenderPlan | None = None,
    comment_text_by_anchor: Mapping[str, str] | None = None,
    delivery_variant: DocumentDeliveryVariant = "standard",
    review_generated_at: datetime | None = None,
    cover_comment_text: str | None = None,
    material_processing_notice: "MaterialProcessingNotice | None" = None,
    standards_compliance_notice: "StandardsComplianceNotice | None" = None,
    figure_specs_out: list[FigureSpec] | None = None,
) -> Path:
    """渲染正式交付 DOCX，并在完整报告正文定稿后更新目录页码；渲染前先做引用预扫描。"""

    plan = render_plan or build_document_render_plan(report)
    _assert_final_references_resolved(plan.report)
    output = render_docx(
        report,
        shell_path,
        out_path,
        resolved_images=resolved_images,
        render_plan=plan,
        comment_text_by_anchor=comment_text_by_anchor,
        delivery_variant=delivery_variant,
        review_generated_at=review_generated_at,
        cover_comment_text=cover_comment_text,
        material_processing_notice=material_processing_notice,
        standards_compliance_notice=standards_compliance_notice,
        figure_specs_out=figure_specs_out,
    )
    # 装了 LibreOffice 就把页码预先算好并冻结（交付给外部时打开即完整）；没装则保留
    # PAGEREF 的 dirty 标记，由阅读器打开时据书签自行解析。两条路径都给出目录与页码，
    # 差别只在算的时机——故版式引擎是增强项而非硬依赖，不为这点确定性要求整套办公套件。
    if page_layout_renderer() is not None:
        finalize_toc_page_numbers(output, profile=format_profile_for(report))
    return output


def load_values(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_values_flat(path: Path) -> dict:
    """把 typed 样本输入投影为 fill_report 测试所需的扁平值，所有派生量仍走生产 resolver。"""
    from sustainability_desk.contract.assessment_classify import (
        industry_display,
        resolve_materiality_assessment,
    )
    from sustainability_desk.contract.company_inputs import parse_company_inputs
    from sustainability_desk.contract.knowledge_packages import knowledge_package_for_path

    package = knowledge_package_for_path(Path(path))
    raw = load_values(path)
    inputs = parse_company_inputs(raw["inputs"], package=package)
    fields = dict(inputs.fields)
    major = str(fields.get("industry_major_category", "") or "")
    division = str(fields.get("industry_division", "") or "")
    if major or division:
        fields["industry"] = industry_display(major, division)
    if inputs.business_summary:
        fields["company_business_summary"] = inputs.business_summary
    context_report = Report(
        knowledgePackageId=package.id,
        title="sample",
        fields={
            key: Field(
                key=key, label=key, type="string", source="user_input", value=value
            )
            for key, value in inputs.fields.items()
        },
        disclosureProfile=inputs.disclosureProfile,
        sections=[],
    )
    assessment = resolve_materiality_assessment(inputs.assessmentInput, context_report)
    content = raw.get("content") or {}
    return {
        "fields": fields,
        "intake": {
            k: {"answer": s.answer, "supplement": s.supplement}
            for k, s in inputs.intake.items()
        },
        "disclosureProfile": inputs.disclosureProfile.model_dump(),
        "appendixPackage": inputs.appendixPackage.model_dump(),
        "assessment": assessment.model_dump(),
        "generated": content.get("generated", {}),
        "tables": content.get("tables", {}),
    }


ROOT = Path(__file__).resolve().parents[4]
BACKEND = Path(__file__).resolve().parents[3]


def render_instance(instance_path: Path, out_path: Path) -> Path:
    """渲染一份自包含填充 Report（前端产出的实例 JSON/YAML）为 Word。"""
    from sustainability_desk.contract.loader import load_contract
    from sustainability_desk.export.normalize_template import normalize_template

    report = load_contract(instance_path)
    package = knowledge_package_of(report)
    base = normalize_template(
        package.base_template_path,
        BACKEND / "out" / "base.docx",
        profile=load_format_profile(package),
    )
    return render_final_docx(report, base, out_path)


def main() -> None:
    import sys

    from sustainability_desk.export.normalize_template import normalize_template

    # With an argument: render a filled instance JSON; without: render one package's sample values.
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--package="):
        out = render_instance(
            Path(sys.argv[1]), BACKEND / "out" / "report_instance.docx"
        )
        print(f"实例 Word: {out}")
        return

    package_id = next(
        (arg.removeprefix("--package=") for arg in sys.argv[1:] if arg.startswith("--package=")),
        "sse_zh_hans",
    )
    package = load_knowledge_package(package_id)
    base = normalize_template(
        package.base_template_path,
        BACKEND / "out" / "base.docx",
        profile=load_format_profile(package),
    )
    from sustainability_desk.contract.build_report import build_report
    from sustainability_desk.contract.company_inputs import parse_company_inputs
    from sustainability_desk.contract.fill import ReportContent, apply_report_content

    raw = load_values(package.sample_values_path)
    report = build_report(parse_company_inputs(raw["inputs"], package=package))
    report = apply_report_content(
        report, ReportContent.model_validate(raw.get("content") or {})
    )
    out = render_final_docx(
        report, base, BACKEND / "out" / f"report_instance_{package.id}.docx"
    )
    print(f"样本实例 Word: {out}")


if __name__ == "__main__":
    main()
