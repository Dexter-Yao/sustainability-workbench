# ABOUTME: 双重重要性矩阵图渲染——据评估得分生成 PNG（matplotlib 绘图，标签避让与引线自实现）。
# ABOUTME: 得分仅用于画图，绝不进入任何模型 prompt（LLM 上下文边界）；十字取阈值并置于几何中心，四象限等面积。
# ABOUTME: visible_materialities 仅供交互预览按分类过滤散点；Word 导出调用不传参，始终完整渲染。
# ABOUTME(en): Double materiality matrix rendering — a PNG from assessment scores; label spreading is our own.
# ABOUTME(en): Scores are used only for drawing and never enter any model prompt; quadrants are equal-area on the axes.
from __future__ import annotations

import logging
from io import BytesIO
from typing import AbstractSet

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 — 必须在 use("Agg") 之后导入
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
    名称经 _spread_labels 自动避让并按需加引线，全部约束在绘图区内。得分仅用于画图，绝不进入 prompt。

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
    _spread_labels(fig, ax, texts, pts, bounds=(lo_f, hi_f, lo_i, hi_i))

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return buf.getvalue()


def _spread_labels(fig, ax, texts, pts, *, bounds: tuple[float, float, float, float]) -> None:
    """把重叠的议题标签沿纵向推开，并为移动过的标签补一条引线。

    自己做而不用 adjustText：后者只有 100 KB，却依赖 scipy——为一张图的标签排布
    拖进 70 MB 科学计算库，是整个依赖树里体积与价值最失衡的一处。这里用像素空间的
    迭代位移达到同类效果：取 matplotlib 自己的文本范围（无需额外依赖），逐轮把相撞的
    标签上下推开，越界则夹回坐标区内。

    与 adjustText 的差别诚实说明：它是力导向迭代、收敛更好；此处以纵向位移为主、
    横向重叠时补一点错列，极密集时排布略逊。对二十余个议题的矩阵图实测足够。
    """

    if not texts:
        return

    lo_f, hi_f, lo_i, hi_i = bounds
    # 文本范围要等渲染器就位才准；此处强制一次绘制，取得真实像素外框。
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    def extent(text):
        return text.get_window_extent(renderer=renderer)

    pad = 2.0  # 像素；两标签之间至少留出的空隙
    for _ in range(60):
        boxes = [extent(t) for t in texts]
        order = sorted(range(len(texts)), key=lambda k: boxes[k].y0)
        moved = False
        for a_index, b_index in zip(order, order[1:]):
            a, b = boxes[a_index], boxes[b_index]
            overlap_y = (a.y1 + pad) - b.y0
            if overlap_y <= 0 or a.x1 <= b.x0 or b.x1 <= a.x0:
                continue  # 纵向不相撞，或横向本就错开
            shift = overlap_y / 2.0
            # 横向重叠越多，纵向推开越吃力；此时同时给一点横向位移，让两条标签错列。
            overlap_x = min(a.x1, b.x1) - max(a.x0, b.x0)
            nudge_x = overlap_x / 4.0 if overlap_x > 0 else 0.0
            for index, direction in ((a_index, -1.0), (b_index, 1.0)):
                x_data, y_data = texts[index].get_position()
                x_pixel, y_pixel = ax.transData.transform((x_data, y_data))
                x_new, y_new = ax.transData.inverted().transform(
                    (x_pixel + direction * nudge_x, y_pixel + direction * shift)
                )
                texts[index].set_position(
                    (min(max(x_new, lo_f), hi_f), min(max(y_new, lo_i), hi_i))
                )
            moved = True
        if not moved:
            break

    # 标签被推离原点时补引线；未移动的不画，避免图上出现零长线段。
    for text, (x_point, y_point) in zip(texts, pts):
        x_label, y_label = text.get_position()
        if abs(y_label - y_point) < (hi_i - lo_i) * 0.004:
            continue
        ax.annotate(
            "",
            xy=(x_point, y_point),
            xytext=(x_label, y_label),
            arrowprops=dict(arrowstyle="-", color=_LEADER_GRAY, lw=0.6),
            zorder=4,
        )
