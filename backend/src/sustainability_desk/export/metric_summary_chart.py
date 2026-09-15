# ABOUTME: ESG 定量指标摘要图渲染——按 image.derivedVisualization 从 Report.meta.quantitativeMetrics 确定性生成 PNG。
# ABOUTME: 仅使用用户填写的报告年度指标值；图内不写标题、说明、内部 key 或 agent-facing 标签。
# ABOUTME(en): ESG quantitative metric summary chart — deterministically renders a PNG from Report.meta metrics per
# ABOUTME(en): image.derivedVisualization. Uses only user-entered report-year values; no internal keys or agent labels.
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from sustainability_desk.contract.knowledge_packages import knowledge_package_of  # noqa: E402
from sustainability_desk.contract.models import Report  # noqa: E402
from sustainability_desk.export.chart_fonts import configure_chart_font  # noqa: E402
from sustainability_desk.export.format_profile import load_format_profile  # noqa: E402
from sustainability_desk.quantitative_metrics import quantitative_metric_display_label, quantitative_metric_value, quantitative_metrics_by_key  # noqa: E402

_PNG_DPI = 150
_BG = "#FFFFFF"
_CARD_BG = "#FFFFFF"
_CARD_EDGE = "#D7DEE8"
_TEXT = "#20242A"
_MUTED = "#667085"
_ACCENT = "#1F4E79"
_HEADER_BG = "#F4F6F8"

configure_chart_font()


@dataclass(frozen=True)
class MetricSummaryEntry:
    key: str
    label: str
    value: str
    unit: str
    group: str


@dataclass(frozen=True)
class MetricSummaryLayout:
    """绘图前的确定性版式投影；只包含最终可见的报告事实。"""

    yearLabel: str
    mode: str
    entries: tuple[MetricSummaryEntry, ...]
    featuredEntries: tuple[MetricSummaryEntry, ...] = ()
    tableHeaders: tuple[str, str, str] = ("", "", "")


def _display_width(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def _wrap_display(text: str, width: int, *, max_lines: int = 2) -> str:
    lines: list[str] = []
    current = ""
    current_width = 0
    for char in text:
        char_width = 2 if ord(char) > 127 else 1
        if current and current_width + char_width > width:
            carried = ""
            if char.isascii() and not char.isspace() and current[-1].isascii() and " " in current:
                head, _, carried = current.rpartition(" ")
                current = head
            lines.append(current)
            current = carried + char
            current_width = _display_width(current)
            if len(lines) == max_lines:
                break
        else:
            current += char
            current_width += char_width
    if len(lines) < max_lines and current:
        lines.append(current)
    if _display_width("".join(lines)) < _display_width(text) and lines:
        lines[-1] = lines[-1].rstrip("…") + "…"
    return "\n".join(lines)


def _report_year_label(report: Report) -> str:
    field = report.fields.get("reporting_year")
    value = field.value if field is not None else None
    if value in (None, "") and report.assessment:
        value = report.assessment.reportingYear
    labels = load_format_profile(knowledge_package_of(report)).labels
    if value in (None, ""):
        return labels.metric_year_fallback
    return labels.metric_year_template.format(year=value)


def _metric_value(report: Report, key: str) -> str | None:
    return quantitative_metric_value(report, key)


def filled_metric_entries(
    report: Report,
    metric_keys: list[str],
    *,
    group_by: str = "none",
) -> list[MetricSummaryEntry]:
    metrics = quantitative_metrics_by_key(knowledge_package_of(report))
    entries: list[MetricSummaryEntry] = []
    for key in metric_keys:
        metric = metrics.get(key)
        if metric is None:
            continue
        value = _metric_value(report, key)
        if value is None:
            continue
        if group_by == "category":
            group = metric.category
        elif group_by == "none":
            group = ""
        else:
            group = metric.groupPath[-1] if metric.groupPath else metric.category
        entries.append(
            MetricSummaryEntry(
                key=key,
                label=quantitative_metric_display_label(metric),
                value=value,
                unit=metric.unit,
                group=group,
            )
        )
    return entries


def _select_featured(entries: list[MetricSummaryEntry], featured_keys: list[str]) -> list[MetricSummaryEntry]:
    by_key = {entry.key: entry for entry in entries}
    featured = [by_key[key] for key in featured_keys if key in by_key]
    if featured:
        return featured[:3]
    return entries[:3]


def _mode(display_mode: str, count: int) -> str:
    if display_mode != "auto":
        return display_mode
    if count <= 3:
        return "highlight_cards"
    if count <= 8:
        return "compact_cards"
    return "summary_table"


def build_metric_summary_layout(
    report: Report,
    metric_keys: list[str],
    *,
    featured_metric_keys: list[str] | None = None,
    display_mode: str = "auto",
    group_by: str = "none",
) -> MetricSummaryLayout | None:
    """先解析报告年度、有效指标和显示模式，再把稳定投影交给绘图层。"""

    entries = filled_metric_entries(report, metric_keys, group_by=group_by)
    if not entries:
        return None
    mode = _mode(display_mode, len(entries))
    featured = _select_featured(entries, featured_metric_keys or []) if mode == "summary_table" else []
    headers = load_format_profile(knowledge_package_of(report)).labels.metric_table_headers
    return MetricSummaryLayout(
        yearLabel=_report_year_label(report),
        mode=mode,
        entries=tuple(entries),
        featuredEntries=tuple(featured),
        tableHeaders=(headers.metric, headers.value, headers.unit),
    )


def _new_canvas(width: int, height: int):
    fig = plt.figure(figsize=(width / _PNG_DPI, height / _PNG_DPI), dpi=_PNG_DPI, facecolor=_BG)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")
    return fig, ax


def _text_width(ax, text: str, *, fontsize: float, fontweight: str = "normal") -> float:
    probe = ax.text(0, 0, text, fontsize=fontsize, fontweight=fontweight, alpha=0)
    ax.figure.canvas.draw()
    width = probe.get_window_extent(renderer=ax.figure.canvas.get_renderer()).width
    probe.remove()
    return float(width)


def _fit_font_size(
    ax,
    text: str,
    *,
    max_width: float,
    start: int,
    minimum: int,
    fontweight: str = "normal",
) -> int:
    for size in range(start, minimum - 1, -1):
        if _text_width(ax, text, fontsize=size, fontweight=fontweight) <= max_width:
            return size
    return minimum


def _draw_year(ax, year_label: str, *, x: float = 34, y: float = 24) -> None:
    ax.text(x, y, year_label, color=_MUTED, fontsize=11, va="top")


def _draw_card(ax, x: float, y: float, w: float, h: float, entry: MetricSummaryEntry) -> None:
    ax.add_patch(Rectangle((x, y), w, h, linewidth=1.0, edgecolor=_CARD_EDGE, facecolor=_CARD_BG))
    left = x + 22
    right = x + w - 22
    content_w = right - left
    if entry.group:
        ax.text(left, y + 28, entry.group, color=_MUTED, fontsize=10, va="top")
    label_y = y + 50 if entry.group else y + 28
    ax.text(left, label_y, _wrap_display(entry.label, 24), color=_TEXT, fontsize=13,
            va="top", linespacing=1.25)
    value_font = _fit_font_size(
        ax,
        entry.value,
        max_width=content_w - min(82, max(38, _display_width(entry.unit) * 6)),
        start=29,
        minimum=19,
        fontweight="bold",
    )
    value_w = _text_width(ax, entry.value, fontsize=value_font, fontweight="bold")
    unit_font = 11 if value_font < 24 else 12
    unit_x = min(left + value_w + 10, right - _text_width(ax, entry.unit, fontsize=unit_font))
    baseline = y + h - 24
    ax.text(left, baseline, entry.value, color=_TEXT, fontsize=value_font, fontweight="bold", va="baseline")
    ax.text(unit_x, baseline - 2, entry.unit, color=_MUTED, fontsize=unit_font, va="baseline")


def _draw_highlight_cards(layout: MetricSummaryLayout) -> bytes:
    width = 1400
    height = 246
    fig, ax = _new_canvas(width, height)
    margin = 34
    gap = 24
    entries = list(layout.entries)
    _draw_year(ax, layout.yearLabel)
    card_w = (width - margin * 2 - gap * (len(entries) - 1)) / len(entries)
    for index, entry in enumerate(entries):
        _draw_card(ax, margin + index * (card_w + gap), 52, card_w, 166, entry)
    return _save(fig)


def _draw_compact_cards(layout: MetricSummaryLayout) -> bytes:
    entries = list(layout.entries)
    columns = 3 if len(entries) > 2 else len(entries)
    rows = (len(entries) + columns - 1) // columns
    width = 1400
    margin = 34
    top = 58
    gap_x = 22
    gap_y = 22
    card_h = 156
    height = top + rows * card_h + (rows - 1) * gap_y + margin
    fig, ax = _new_canvas(width, height)
    _draw_year(ax, layout.yearLabel)
    card_w = (width - margin * 2 - gap_x * (columns - 1)) / columns
    for index, entry in enumerate(entries):
        row, col = divmod(index, columns)
        _draw_card(ax, margin + col * (card_w + gap_x), top + row * (card_h + gap_y), card_w, card_h, entry)
    return _save(fig)


def _draw_summary_table(layout: MetricSummaryLayout) -> bytes:
    entries = list(layout.entries)
    featured = list(layout.featuredEntries)
    width = 1400
    margin = 34
    card_gap = 22
    card_h = 152
    card_top = 58
    row_h = 48
    table_top = card_top + card_h + 28
    height = table_top + row_h * (len(entries) + 1) + margin
    fig, ax = _new_canvas(width, height)
    _draw_year(ax, layout.yearLabel)

    card_w = (width - margin * 2 - card_gap * 2) / 3
    for index, entry in enumerate(featured[:3]):
        _draw_card(ax, margin + index * (card_w + card_gap), card_top, card_w, card_h, entry)

    table_x = margin
    table_w = width - margin * 2
    ax.add_patch(Rectangle((table_x, table_top), table_w, row_h * (len(entries) + 1),
                           linewidth=1.0, edgecolor=_CARD_EDGE, facecolor=_BG))
    ax.add_patch(Rectangle((table_x, table_top), table_w, row_h, linewidth=0, facecolor=_HEADER_BG))
    headers = layout.tableHeaders
    xs = (table_x + 24, table_x + table_w * 0.68, table_x + table_w * 0.86)
    for text, x in zip(headers, xs):
        ax.text(x, table_top + 29, text, color=_ACCENT, fontsize=12, fontweight="bold", va="center")
    for index, entry in enumerate(entries):
        y = table_top + row_h * (index + 1)
        ax.add_line(plt.Line2D([table_x, table_x + table_w], [y, y], color=_CARD_EDGE, linewidth=0.8))
        label = f"{entry.group}｜{entry.label}" if entry.group else entry.label
        ax.text(xs[0], y + row_h / 2, _wrap_display(label, 58, max_lines=1), color=_TEXT, fontsize=11, va="center")
        ax.text(xs[1], y + row_h / 2, entry.value, color=_TEXT, fontsize=12, fontweight="bold", va="center")
        ax.text(xs[2], y + row_h / 2, entry.unit, color=_MUTED, fontsize=11, va="center")
    return _save(fig)


def _save(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=_PNG_DPI, facecolor=_BG)
    plt.close(fig)
    return buf.getvalue()


def render_quantitative_metric_summary(
    report: Report,
    metric_keys: list[str],
    *,
    featured_metric_keys: list[str] | None = None,
    display_mode: str = "auto",
    group_by: str = "none",
) -> bytes | None:
    layout = build_metric_summary_layout(
        report,
        metric_keys,
        featured_metric_keys=featured_metric_keys,
        display_mode=display_mode,
        group_by=group_by,
    )
    if layout is None:
        return None
    if layout.mode == "highlight_cards":
        return _draw_highlight_cards(layout)
    if layout.mode == "compact_cards":
        return _draw_compact_cards(layout)
    return _draw_summary_table(layout)
