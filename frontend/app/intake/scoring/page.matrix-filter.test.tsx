// ABOUTME: 评分页分类图例交互回归：图例为视图级过滤（计数随当前预览散点，完成后与权威值一致），矩阵是前端 SVG 即时预览——
// ABOUTME: 被隐藏分类的散点淡出保位（data-shown=false）而非移除，清单同步过滤，完整结果恢复全显。
// ABOUTME: 并锁住四象限底色（design.md §3.2.1）：四档透明度齐备且常驻，过滤只作用于散点不删减象限。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/intake/scoring",
}));

vi.mock("@/lib/app-context", () => ({
  useAppOptional: () => null,
  useApp: () => ({
    // 分类名是包资产：真实 useApp() 保证 report 非空（AppProvider 在 report 为空时
    // 直接渲染错误页），此处补齐 assessmentVocabulary 才是真实形态。
    report: {
      assessmentVocabulary: {
        materiality: { dual: "双重重要性", impact: "影响重要性", financial: "财务重要性", non: "非重要性" },
        materialityAxes: { financial: "财务重要性", impact: "影响重要性" },
        iroKind: { impact: "影响", risk: "风险", opportunity: "机遇", risk_opportunity: "风险与机遇" },
        impactClass: { actual_positive: "实际正面影响", potential_positive: "潜在正面影响", potential_negative: "潜在负面影响" },
      },
    },
    activeReportId: "report-1",
    activeReportCapabilities: { report_profile_id: "sse_zh_hans@1" },
    applyAuthoritativeReportState: vi.fn().mockResolvedValue(undefined),
    applyServerReportUpdate: vi.fn(),
  }),
}));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => ({
    status: "ready",
    collectsMaterialityAssessment: true,
    allowedMetricKeys: [],
  }),
}));

const assessmentFixture = {
  state_seq: 1,
  score_scale: { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 },
  topics: [
    { assessmentTopicId: "t1", name: "议题一", dimension: "环境" },
    { assessmentTopicId: "t2", name: "议题二", dimension: "社会" },
    { assessmentTopicId: "t3", name: "议题三", dimension: "治理" },
    { assessmentTopicId: "t4", name: "议题四", dimension: "环境" },
  ],
  current: {
    threshold: { financial: 4, impact: 4 },
    scores: [
      { assessmentTopicId: "t1", financialScore: 4.5, impactScore: 4.5 },
      { assessmentTopicId: "t2", financialScore: 3, impactScore: 4.5 },
      { assessmentTopicId: "t3", financialScore: 4.5, impactScore: 3 },
      { assessmentTopicId: "t4", financialScore: 2, impactScore: 2 },
    ],
  },
  resolved: {
    reportingYear: 2026,
    threshold: { financial: 4, impact: 4 },
    counts: { dual: 1, impact_only: 1, financial_only: 1, non_material: 1, total: 4 },
    topics: [
      { assessmentTopicId: "t1", name: "议题一", dimension: "环境", determination: "scored", materiality: "dual", financialScore: 4.5, impactScore: 4.5 },
      { assessmentTopicId: "t2", name: "议题二", dimension: "社会", determination: "scored", materiality: "impact", financialScore: 3, impactScore: 4.5 },
      { assessmentTopicId: "t3", name: "议题三", dimension: "治理", determination: "scored", materiality: "financial", financialScore: 4.5, impactScore: 3 },
      { assessmentTopicId: "t4", name: "议题四", dimension: "环境", determination: "scored", materiality: "non", financialScore: 2, impactScore: 2 },
    ],
  },
};

vi.mock("@/lib/api", () => ({
  fetchAssessmentInput: vi.fn(() => Promise.resolve(assessmentFixture)),
  putAssessmentInput: vi.fn(),
  downloadAssessmentTemplate: vi.fn(),
  importAssessmentWorkbook: vi.fn(),
  StructuredInputConflictError: class StructuredInputConflictError extends Error {},
}));

import IntakeScoringPage from "./page";
import { QUAD_FILL_OPACITY } from "./matrix";

afterEach(cleanup);

function pointShown(topicId: string): string | null {
  const node = document.querySelector(`[data-topic-id="${topicId}"]`);
  return node?.getAttribute("data-shown") ?? null;
}

describe("评分页分类图例交互", () => {
  it("默认全显：矩阵散点全部可见、清单完整", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });
    expect(pointShown("t1")).toBe("true");
    expect(pointShown("t4")).toBe("true");
    // 清单行与在线表单行各一处。
    expect(screen.getAllByText("议题一").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: /双重重要/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("点击图例即时淡出对应散点并过滤清单，完整结果恢复全显", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /双重重要/ }));
    });
    // 散点淡出保位（仍在 DOM），不发网络请求、不换图。
    expect(pointShown("t1")).toBe("false");
    expect(pointShown("t2")).toBe("true");
    // 清单行（span）隐藏，表单行保留。
    expect(screen.queryByText("议题一", { selector: "span" })).toBeNull();
    expect(screen.getByText("议题二", { selector: "span" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /双重重要/ }).getAttribute("aria-pressed")).toBe("false");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /完整结果/ }));
    });
    expect(pointShown("t1")).toBe("true");
    expect(screen.getByText("议题一", { selector: "span" })).toBeTruthy();
  });

  it("可见散点较少时就地标注官方议题名", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });
    // 4 个散点 ≤ 标注上限：SVG 内出现议题名文本标注。
    const matrix = screen.getByRole("img", { name: "双重重要性议题矩阵" });
    expect(matrix.textContent).toContain("议题一");
  });
});

/**
 * 四象限底色若在前端 SVG 中丢失（只剩右上一块淡绿）而图例仍展示底色色阶，
 * 图例就在解释画布上不存在的编码。以下用例锁住 design.md §3.2.1 的两条不变量。
 */
describe("矩阵四象限底色", () => {
  function quadrant(materiality: string): SVGRectElement | null {
    return document.querySelector(`[data-quadrant="${materiality}"]`);
  }

  it("四个象限底色齐备，取 --chart-quadrant 的四档透明度", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });

    for (const [materiality, opacity] of Object.entries(QUAD_FILL_OPACITY)) {
      const rect = quadrant(materiality);
      expect(rect, `缺少 ${materiality} 象限底色`).toBeTruthy();
      expect(rect?.getAttribute("fill")).toBe("var(--chart-quadrant)");
      expect(Number(rect?.getAttribute("fill-opacity"))).toBe(opacity);
      // 象限必须有实际面积，否则等同于没画。
      expect(Number(rect?.getAttribute("width"))).toBeGreaterThan(0);
      expect(Number(rect?.getAttribute("height"))).toBeGreaterThan(0);
    }
    // 右上双重重要最深、左下非重要最浅，深浅表达重要性递减。
    expect(QUAD_FILL_OPACITY.dual).toBeGreaterThan(QUAD_FILL_OPACITY.financial);
    expect(QUAD_FILL_OPACITY.financial).toBeGreaterThan(QUAD_FILL_OPACITY.impact);
    expect(QUAD_FILL_OPACITY.impact).toBeGreaterThan(QUAD_FILL_OPACITY.non);
  });

  it("四象限等面积：阈值十字落在几何中心", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });

    const size = (materiality: string) => {
      const rect = quadrant(materiality);
      return { w: Number(rect?.getAttribute("width")), h: Number(rect?.getAttribute("height")) };
    };
    // 左右两列等宽、上下两行等高（浮点留 0.01 容差）——否则面积最大的「非重要」象限
    // 会在视觉上压过「双重重要」，与语义相反。
    expect(size("dual").w).toBeCloseTo(size("impact").w, 2);
    expect(size("financial").w).toBeCloseTo(size("non").w, 2);
    expect(size("dual").h).toBeCloseTo(size("financial").h, 2);
    expect(size("impact").h).toBeCloseTo(size("non").h, 2);
  });

  it("象限底色常驻：图例过滤只淡出散点，不删减象限", async () => {
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /双重重要/ }));
    });
    expect(pointShown("t1")).toBe("false");
    // 散点淡出，但四个象限一个不少、透明度不变。
    for (const [materiality, opacity] of Object.entries(QUAD_FILL_OPACITY)) {
      expect(quadrant(materiality), `过滤后丢失 ${materiality} 象限`).toBeTruthy();
      expect(Number(quadrant(materiality)?.getAttribute("fill-opacity"))).toBe(opacity);
    }
  });
});
