# ABOUTME: 双重重要性矩阵图渲染——据评估得分生成 PNG（matplotlib + adjustText 自动避让标签并加引线）。
# ABOUTME: 得分仅用于画图，绝不进入任何模型 prompt（LLM 上下文边界）；十字取阈值并置于几何中心，四象限等面积。
# ABOUTME: visible_materialities 仅供交互预览按分类过滤散点；Word 导出调用不传参，始终完整渲染。
# ABOUTME(en): Double materiality matrix rendering — a PNG from assessment scores (matplotlib plus adjustText labels).
# ABOUTME(en): Scores are used only for drawing and never enter any model prompt; quadrants are equal-area on the axes.
from __future__ import annotations

import logging
from io import BytesIO
from typing import AbstractSet

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 — 必须在 use("Agg") 之后导入
from adjustText import adjust_text  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from sustainability_desk.contract.models import (  # noqa: E402
    AssessmentResult,
    Materiality,
    MaterialityThreshold,
)
from sustainability_desk.contract.assessment_classify import DEFAULT_THRESHOLD  # noqa: E402
from sustainability_desk.contract.knowledge_packages import KnowledgePackage  # noqa: E402
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.contract.topic_registry import load_topic_contract  # noqa: E402
from sustainability_desk.export.chart_fonts import configure_chart_font  # noqa: E402

logger = logging.getLogger(__name__)

MATRIX_IMAGE_BLOCK_ID = "sm.matrix_image"

_QUADRANT_BLUE = "#3D7CC9"
_DOT_PURPLE = "#7048AE"
_AXIS_GREEN = "#5FB246"
_LABEL_GRAY = "#1F2937"
_LEADER_GRAY = "#9CA3AF"
_VISIBLE_CATEGORIES: frozenset[str] = frozenset(("dual", "impact", "financial", "non"))

_CHOSEN_FONT = configure_chart_font()


def parse_visible_materialities(visible: str) -> set[Materiality]:
    """解析交互预览的过滤参数（逗号分隔分类名）；忽略空片段，未知分类报错。"""
    parsed: set[Materiality] = set()
    for token in visible.split(","):
        token = token.strip()
        if not token:
            continue
        if token not in _VISIBLE_CATEGORIES:
            raise ValueError(f"未知的矩阵过滤分类：{token}")
        parsed.add(token)  # type: ignore[arg-type] — 已由 _VISIBLE_CATEGORIES 校验
    return parsed


def render_materiality_matrix(
    assessment: AssessmentResult,
    *,
    package: KnowledgePackage,
    threshold: MaterialityThreshold | None = None,
    visible_materialities: AbstractSet[Materiality] | None = None,
) -> bytes:
    """据评估结果渲染双重重要性矩阵 PNG（横轴财务、纵轴影响）。

    十字线取分类阈值并置于几何中心，使四象限等面积、各议题落入其所属象限；议题按得分散点，
    名称经 adjustText 自动避让并按需加引线，全部约束在绘图区内。得分仅用于画图，绝不进入 prompt。

    ``visible_materialities`` 为视图级过滤：仅散点与标签按分类筛选，坐标尺度仍以全量评分议题为准，
    过滤视图与完整图同轴同象限；分类直接取评估结果自带 materiality（权威解析结果），不在此重算。
    过滤后无评分议题时渲染空矩阵（仅象限底色与坐标轴），不视为错误。
    """
    scored = [topic for topic in assessment.topics if topic.determination == "scored"]
    if not scored:
        raise ValueError("评估无议题，无法渲染双重重要性矩阵图")
    if visible_materialities is None:
        topics = scored
    else:
        topics = [topic for topic in scored if topic.materiality in visible_materialities]

    th = threshold or assessment.threshold or DEFAULT_THRESHOLD
    tf, ti = float(th.financial), float(th.impact)
    fins = [float(t.financialScore) for t in scored]
    imps = [float(t.impactScore) for t in scored]
    pts = [(float(t.financialScore), float(t.impactScore)) for t in topics]

    # 对称半径：十字（阈值）落几何中心、四象限等面积；贴合数据跨度（留边距）使点充分散布，
    # 极小跨度时兜底避免坐标塌缩；据此各点落入其所属象限。
    max_dist = max([abs(f - tf) for f in fins] + [abs(i - ti) for i in imps])
    radius = max(max_dist * 1.18, 0.5)
    lo_f, hi_f, lo_i, hi_i = tf - radius, tf + radius, ti - radius, ti + radius

    fig, ax = plt.subplots(figsize=(7.6, 7.6))
    # 四象限底色：右上（双高）最深 → 左下最浅，以深浅表达重要性递减。
    for x0, y0, width, height, alpha in (
        (tf, ti, hi_f - tf, hi_i - ti, 0.50),
        (lo_f, ti, tf - lo_f, hi_i - ti, 0.28),
        (tf, lo_i, hi_f - tf, ti - lo_i, 0.30),
        (lo_f, lo_i, tf - lo_f, ti - lo_i, 0.10),
    ):
        ax.add_patch(Rectangle((x0, y0), width, height, facecolor=_QUADRANT_BLUE, alpha=alpha, linewidth=0))

    ax.scatter(
        [f for f, _ in pts],
        [i for _, i in pts],
        s=45,
        color=_DOT_PURPLE,
        zorder=3,
        edgecolors="white",
        linewidths=0.8,
    )
    registry = load_topic_contract(package)
    texts = [
        ax.text(
            f,
            i,
            registry.assessmentTopicsById[topic.assessmentTopicId].name,
            fontsize=10,
            color=_LABEL_GRAY,
            zorder=5,
        )
        for topic, (f, i) in zip(topics, pts)
    ]

    ax.set_xlim(lo_f, hi_f)
    ax.set_ylim(lo_i, hi_i)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # 绿色箭头坐标轴（自左下角向右、向上）。
    ax.annotate("", xy=(hi_f, lo_i), xytext=(lo_f, lo_i),
                arrowprops=dict(arrowstyle="-|>", color=_AXIS_GREEN, lw=2.2, mutation_scale=22))
    ax.annotate("", xy=(lo_f, hi_i), xytext=(lo_f, lo_i),
                arrowprops=dict(arrowstyle="-|>", color=_AXIS_GREEN, lw=2.2, mutation_scale=22))
    axes = assessment_vocabulary(package).materialityAxes
    ax.set_xlabel(axes.financial, fontsize=12, labelpad=12)
    ax.set_ylabel(axes.impact, fontsize=12, labelpad=12)

    # 自动避让标签 + 引线；约束在坐标区内，避免标签压轴或出象限。
    if texts:
        adjust_text(
            texts,
            x=[f for f, _ in pts],
            y=[i for _, i in pts],
            ax=ax,
            arrowprops=dict(arrowstyle="-", color=_LEADER_GRAY, lw=0.6),
            expand=(1.3, 1.5),
            ensure_inside_axes=True,
        )

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return buf.getvalue()
