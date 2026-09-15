// ABOUTME: 双重重要性矩阵交互预览（前端 SVG）——四象限底色常驻（design.md §3.2.1，与后端 matrix_chart.py 同源），
// ABOUTME: 图例选择即时淡入淡出、阈值线即时移动、hover 显示得分；
// ABOUTME: 可见散点全部就地标注官方议题名，贪心挑选八方位候选避免标签互相重叠或压住散点。
// ABOUTME: 纯展示组件，得分仅用于画图不进 prompt（LLM 上下文边界）；工作台块预览与 Word 导出仍用后端渲染源。
// ABOUTME: 无散点时仍绘制空坐标系（象限底色 + 阈值十字），并提供增量预览分类（见 classifyPreviewMateriality）。
import type { AssessmentResult, Materiality, MaterialityThreshold, ScoredAssessmentResult } from "@/lib/schema";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";

const QUAD_COLOR: Record<Materiality, string> = {
  dual: "var(--accent)",
  impact: "var(--ai)",
  financial: "var(--warning)",
  non: "var(--muted-foreground)",
};

/**
 * 四象限底色透明度（design.md §3.2.1）：右上双高最深 → 左下最浅，以深浅表达重要性递减。
 * 与后端 matrix_chart.py 的 matplotlib alpha、评分页图例色块三处同源同值，改一处必须改三处。
 */
export const QUAD_FILL_OPACITY: Record<Materiality, number> = {
  dual: 0.5,
  financial: 0.3,
  impact: 0.28,
  non: 0.1,
};

const LABEL_FONT = 9.5;
const LABEL_H = 12;

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

function boxesOverlap(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** 中文标签宽度估算：按方块字宽 ≈ 字号计（西文字符按 0.6 计），另加 2px 余量。 */
function labelWidth(name: string): number {
  let width = 2;
  for (const char of name) {
    width += char.charCodeAt(0) > 0x2e80 ? LABEL_FONT : LABEL_FONT * 0.6;
  }
  return width;
}

/**
 * 贪心标签布局：每个可见散点在八个方位候选（右/左/上/下/四角）中挑首个
 * 既在画布内、又不与已放置标签和任何可见散点相交的位置；全部冲突时退回右侧兜底。
 * 输入按 y 再 x 排序保证确定性；被隐藏分类的散点不占位也不标注。
 */
function placeLabels(
  points: { id: string; cx: number; cy: number; name: string }[],
  width: number,
  height: number,
): Record<string, Box> {
  const obstacles: Box[] = points.map((point) => ({ x: point.cx - 6, y: point.cy - 6, w: 12, h: 12 }));
  const placed: Box[] = [];
  const out: Record<string, Box> = {};
  const ordered = [...points].sort((a, b) => a.cy - b.cy || a.cx - b.cx);
  for (const point of ordered) {
    const w = labelWidth(point.name);
    const half = LABEL_H / 2;
    const candidates: Box[] = [
      { x: point.cx + 8, y: point.cy - half, w, h: LABEL_H },
      { x: point.cx - 8 - w, y: point.cy - half, w, h: LABEL_H },
      { x: point.cx - w / 2, y: point.cy - 9 - LABEL_H, w, h: LABEL_H },
      { x: point.cx - w / 2, y: point.cy + 9, w, h: LABEL_H },
      { x: point.cx + 7, y: point.cy - 9 - LABEL_H, w, h: LABEL_H },
      { x: point.cx + 7, y: point.cy + 9, w, h: LABEL_H },
      { x: point.cx - 7 - w, y: point.cy - 9 - LABEL_H, w, h: LABEL_H },
      { x: point.cx - 7 - w, y: point.cy + 9, w, h: LABEL_H },
    ];
    const fits = candidates.find(
      (box) =>
        box.x >= 2
        && box.x + box.w <= width - 2
        && box.y >= 4
        && box.y + box.h <= height - 26
        && !placed.some((other) => boxesOverlap(box, other))
        && !obstacles.some((other) => boxesOverlap(box, other)),
    );
    const box = fits ?? candidates[0];
    out[point.id] = box;
    placed.push(box);
  }
  return out;
}

/**
 * 增量预览分类：与后端 `assessment_classify.classify_materiality` 同源同规则，
 * 改一处必须同步改另一处（测试守护）。只用于填写过程中的即时预览——权威分类永远是
 * 服务端 resolved；评分完整后页面展示即切换为权威结果，两值由规则同一性保证一致。
 */
export function classifyPreviewMateriality(
  financial: number,
  impact: number,
  threshold: MaterialityThreshold,
): Materiality {
  const financialMaterial = financial >= threshold.financial;
  const impactMaterial = impact >= threshold.impact;
  if (financialMaterial && impactMaterial) return "dual";
  if (financialMaterial) return "financial";
  if (impactMaterial) return "impact";
  return "non";
}

export function MaterialityMatrix({
  topics,
  threshold,
  visibleMaterialities,
  topicNames,
  scoreMax,
  axisLabels,
}: {
  topics: AssessmentResult["topics"];
  threshold: MaterialityThreshold;
  /** 图例选择的可见分类；未提供视为全部可见。被隐藏分类淡出而非移除，切换即时平滑。 */
  visibleMaterialities?: ReadonlySet<Materiality>;
  /** assessmentTopicId → 官方议题名；标注与 hover 提示使用。 */
  topicNames?: Record<string, string>;
  /** 评分尺度上限（score_scale.maximum）：无散点时据以撑开空坐标系。 */
  scoreMax?: number;
  /** 两轴名称：包资产（assessmentVocabulary.materialityAxes），随报告所属包的语言。 */
  axisLabels: { financial: string; impact: string };
}) {
  const t = useT();
  const scored = topics.filter(
    (topic): topic is ScoredAssessmentResult => topic.determination !== "fixed" && "financialScore" in topic,
  );
  const isVisible = (materiality: Materiality) =>
    visibleMaterialities ? visibleMaterialities.has(materiality) : true;

  const W = 480;
  const H = 440;
  const pad = 46;
  const fins = scored.map((topic) => topic.financialScore);
  const imps = scored.map((topic) => topic.impactScore);
  // 对称半径（与后端 matrix_chart.py 同一算法）：两轴各以阈值为中心取对称半径，使阈值十字落在
  // 几何中心、四象限等面积。若改用 min/max 贴合数据跨度，象限面积会随数据分布悬殊，
  // 铺上底色后视觉上暗示「面积大的判定区更重要」，与实际语义相反。
  // 无散点时按评分尺度撑开坐标系，让空画布也呈现完整的四象限语义。
  const scaleCeiling = scoreMax ?? Math.max(threshold.financial, threshold.impact) + 1;
  const radius = (scored.length
    ? Math.max(
      ...fins.map((score) => Math.abs(score - threshold.financial)),
      ...imps.map((score) => Math.abs(score - threshold.impact)),
      0.5,
    )
    : Math.max(
      threshold.financial,
      scaleCeiling - threshold.financial,
      threshold.impact,
      scaleCeiling - threshold.impact,
      0.5,
    )) * 1.18;
  const px = (v: number) =>
    pad + ((v - (threshold.financial - radius)) / (radius * 2)) * (W - pad * 2);
  const py = (v: number) =>
    H - pad - ((v - (threshold.impact - radius)) / (radius * 2)) * (H - pad * 2);
  const tx = px(threshold.financial);
  const ty = py(threshold.impact);

  const nameOf = (topic: ScoredAssessmentResult) =>
    topicNames?.[topic.assessmentTopicId] ?? topic.assessmentTopicId;
  // 标签只对当前可见散点布局：过滤后空间释放，剩余标签自动展开到更舒适的位置。
  const labelBoxes = placeLabels(
    scored
      .filter((topic) => isVisible(topic.materiality))
      .map((topic) => ({
        id: topic.assessmentTopicId,
        cx: px(topic.financialScore),
        cy: py(topic.impactScore),
        name: nameOf(topic),
      })),
    W,
    H,
  );

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={t.scoring.matrixAria}
      style={{ maxWidth: 480, display: "block" }}
    >
      {/* 四象限底色：常驻不受图例过滤影响——象限是坐标系静态分区，过滤只作用于散点（design.md §3.2.1）。 */}
      {(
        [
          ["dual", tx, pad, W - pad - tx, ty - pad],
          ["financial", tx, ty, W - pad - tx, H - pad - ty],
          ["impact", pad, pad, tx - pad, ty - pad],
          ["non", pad, ty, tx - pad, H - pad - ty],
        ] as const
      ).map(([materiality, x, y, w, h]) => (
        <rect
          key={materiality}
          data-quadrant={materiality}
          x={x}
          y={y}
          width={Math.max(0, w)}
          height={Math.max(0, h)}
          fill="var(--chart-quadrant)"
          fillOpacity={QUAD_FILL_OPACITY[materiality]}
        />
      ))}
      {/* 坐标轴 */}
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="var(--border)" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="var(--border)" />
      {/* 阈值分界线（本地阈值草稿即时反映）：走白色——铺上四象限底色后浅灰在深蓝上读不出。 */}
      <line x1={tx} y1={pad} x2={tx} y2={H - pad} stroke="var(--background)" strokeOpacity={0.75} strokeDasharray="4 3" />
      <line x1={pad} y1={ty} x2={W - pad} y2={ty} stroke="var(--background)" strokeOpacity={0.75} strokeDasharray="4 3" />
      {/* 议题散点：隐藏分类淡出保位（即时切换不跳布局）；可见散点就地标注官方议题名 */}
      {scored.map((topic) => {
        const shown = isVisible(topic.materiality);
        const name = nameOf(topic);
        const cx = px(topic.financialScore);
        const cy = py(topic.impactScore);
        const box = shown ? labelBoxes[topic.assessmentTopicId] : undefined;
        return (
          <g
            key={topic.assessmentTopicId}
            data-topic-id={topic.assessmentTopicId}
            data-shown={shown}
            className="gs-matrix-point"
            style={{ opacity: shown ? 1 : 0.12, transition: "opacity .18s ease" }}
          >
            <circle
              cx={cx}
              cy={cy}
              r={5}
              fill={QUAD_COLOR[topic.materiality]}
              fillOpacity={0.85}
              stroke="var(--background)"
              strokeWidth={1}
            >
              <title>{interpolate(t.scoring.pointTooltip, { name, financialAxis: axisLabels.financial, financial: topic.financialScore, impactAxis: axisLabels.impact, impact: topic.impactScore })}</title>
            </circle>
            {box ? (
              <text
                x={box.x}
                y={box.y + LABEL_H - 3}
                fontSize={LABEL_FONT}
                fill="var(--foreground-secondary)"
              >
                {name}
              </text>
            ) : null}
          </g>
        );
      })}
      {/* 空态提示：坐标系常驻，评分开始后散点逐个落位。 */}
      {scored.length === 0 ? (
        <text x={W / 2} y={H / 2 - 6} fontSize="12" fill="var(--muted-foreground)" textAnchor="middle">
          {t.scoring.matrixEmptyHint}
        </text>
      ) : null}
      {/* 轴标题 */}
      <text x={W / 2} y={H - 12} fontSize="11" fill="var(--muted-foreground)" textAnchor="middle">
        {axisLabels.financial} →
      </text>
      <text
        x={14}
        y={H / 2}
        fontSize="11"
        fill="var(--muted-foreground)"
        textAnchor="middle"
        transform={`rotate(-90 14 ${H / 2})`}
      >
        {axisLabels.impact} →
      </text>
    </svg>
  );
}
