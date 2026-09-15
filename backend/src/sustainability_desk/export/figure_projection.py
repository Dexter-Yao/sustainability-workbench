# ABOUTME: 图表渲染投影层——FigureSpec/TableSpec 与全文连续编号引擎；渲染期派生，不进数据。
# ABOUTME: 编号策略归 word_zh 格式 profile（全文连续 + 附录 A.N）；题注内容仍归各 owner 合同。
# ABOUTME(en): Figure rendering projection — FigureSpec/TableSpec and the document-wide continuous numbering engine;
# ABOUTME(en): derived at render time, never stored. Numbering policy belongs to word_zh; caption content to its owners.
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sustainability_desk.export.format_profile import WordFormatProfile

# 议题指标摘要图（metric_summary）不参与图片编号，也不产生
# FigureSpec（渲染层直接输出无编号题注）；保留枚举成员仅作图表种类分类语义。
FigureKind = Literal[
    "evidence_image",
    "metric_summary",
    "materiality_matrix",
    "org_chart",
    "process_flow",
]
NumberedKind = Literal["figure", "table"]

@dataclass(frozen=True)
class FigureSpec:
    """一个实际渲染的图表的版式身份：编号、题注文本与来源块。"""

    block_id: str
    kind: FigureKind | Literal["table"]
    numbered_kind: NumberedKind
    number_label: str
    caption_text: str
    in_appendix: bool


class FigureNumbering:
    """图表编号引擎：正文全文连续（图1/表1），附录子树编 图A.1/表A.1。

    仅对实际渲染且参与编号的图表计数：受控省略、隐藏与渲染失败的图表不占号；
    议题指标摘要图（metric_summary）虽实际渲染但不占号、
    不进 figure_specs 清单。
    每次 render_docx 调用新建实例，图编号独立起编。
    """

    def __init__(self, profile: WordFormatProfile) -> None:
        self._separator = profile.numbering.number_caption_separator
        self._label_separator = profile.numbering.label_number_separator
        self._kind_labels = {
            "figure": profile.labels.figure_label,
            "table": profile.labels.table_label,
        }
        self._appendix_prefix = profile.labels.appendix_number_prefix
        self._counters: dict[NumberedKind, int] = {"figure": 0, "table": 0}
        self._appendix_counters: dict[NumberedKind, int] = {"figure": 0, "table": 0}

    def assign(
        self,
        numbered_kind: NumberedKind,
        *,
        block_id: str,
        kind: FigureKind | Literal["table"],
        caption: str | None,
        in_appendix: bool,
    ) -> FigureSpec:
        counters = self._appendix_counters if in_appendix else self._counters
        counters[numbered_kind] += 1
        ordinal = counters[numbered_kind]
        prefix = self._kind_labels[numbered_kind]
        number_label = (
            f"{prefix}{self._label_separator}{self._appendix_prefix}{ordinal}"
            if in_appendix
            else f"{prefix}{self._label_separator}{ordinal}"
        )
        caption_text = (
            f"{number_label}{self._separator}{caption.strip()}"
            if caption and caption.strip()
            else number_label
        )
        return FigureSpec(
            block_id=block_id,
            kind=kind,
            numbered_kind=numbered_kind,
            number_label=number_label,
            caption_text=caption_text,
            in_appendix=in_appendix,
        )
