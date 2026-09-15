// ABOUTME: 矩阵增量预览回归：矩阵自进入页面即在场——空画布、已评议题即时落点，
// ABOUTME: 最后一分保存成功后回填权威 resolved，出现完成摘要与一次性强调（gs-matrix-reveal）。
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

const SCALE = { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 };
const TOPICS = [
  { assessmentTopicId: "t1", name: "议题一", dimension: "环境" },
  { assessmentTopicId: "t2", name: "议题二", dimension: "社会" },
];

function inputFixture(overrides: Record<string, unknown> = {}) {
  return {
    state_seq: 1,
    score_scale: SCALE,
    topics: TOPICS,
    current: null,
    resolved: null,
    ...overrides,
  };
}

const fetchAssessmentInput = vi.fn();
const putAssessmentInput = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAssessmentInput: (...args: unknown[]) => fetchAssessmentInput(...args),
  putAssessmentInput: (...args: unknown[]) => putAssessmentInput(...args),
  downloadAssessmentTemplate: vi.fn(),
  importAssessmentWorkbook: vi.fn(),
  StructuredInputConflictError: class StructuredInputConflictError extends Error {},
}));

import IntakeScoringPage from "./page";

afterEach(() => {
  cleanup();
  fetchAssessmentInput.mockReset();
  putAssessmentInput.mockReset();
});

describe("矩阵增量预览", () => {
  it("进入页面矩阵即在场：零评分显示空画布与实时状态", async () => {
    fetchAssessmentInput.mockResolvedValue(inputFixture());
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });
    expect(screen.getByText("已评分 0 / 2 · 随填写实时更新")).toBeTruthy();
    expect(document.querySelector('[data-quadrant="dual"]')).toBeTruthy();
  });

  it("已评议题即时落点，未评议题不出现", async () => {
    fetchAssessmentInput.mockResolvedValue(
      inputFixture({
        current: {
          threshold: { financial: 4, impact: 4 },
          scores: [{ assessmentTopicId: "t1", financialScore: 4.5, impactScore: 2 }],
        },
      }),
    );
    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });
    expect(document.querySelector('[data-topic-id="t1"]')).toBeTruthy();
    expect(document.querySelector('[data-topic-id="t2"]')).toBeNull();
    expect(screen.getByText("已评分 1 / 2 · 随填写实时更新")).toBeTruthy();
    // 图例计数跟随预览散点。
    expect(screen.getByText("已评分 1 / 2 · 随填写实时更新")).toBeTruthy();
  });

  it("最后一分保存成功后出现完成摘要与一次性强调", async () => {
    fetchAssessmentInput.mockResolvedValueOnce(
      inputFixture({
        current: {
          threshold: { financial: 4, impact: 4 },
          scores: [{ assessmentTopicId: "t1", financialScore: 4.5, impactScore: 4.5 }],
        },
      }),
    );
    // 完整保存后的回填：服务端权威解析到达。
    fetchAssessmentInput.mockResolvedValueOnce(
      inputFixture({
        state_seq: 2,
        current: {
          threshold: { financial: 4, impact: 4 },
          scores: [
            { assessmentTopicId: "t1", financialScore: 4.5, impactScore: 4.5 },
            { assessmentTopicId: "t2", financialScore: 2, impactScore: 2 },
          ],
        },
        resolved: {
          reportingYear: 2026,
          threshold: { financial: 4, impact: 4 },
          counts: { dual: 1, impact_only: 0, financial_only: 0, non_material: 1, total: 2 },
          topics: [
            { assessmentTopicId: "t1", name: "议题一", dimension: "环境", determination: "scored", materiality: "dual", financialScore: 4.5, impactScore: 4.5 },
            { assessmentTopicId: "t2", name: "议题二", dimension: "社会", determination: "scored", materiality: "non", financialScore: 2, impactScore: 2 },
          ],
        },
      }),
    );
    putAssessmentInput.mockResolvedValue({
      state_seq: 2,
      state: { assessmentInput: { threshold: { financial: 4, impact: 4 }, scores: [] } },
    });

    render(<IntakeScoringPage />);
    await screen.findByRole("img", { name: "双重重要性议题矩阵" });

    // 填上最后一分（t2 两维），触发防抖自动保存 → 回填权威 resolved。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 财务重要性"), { target: { value: "2" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 影响重要性"), { target: { value: "2" } });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1_800));
    });
    expect(putAssessmentInput).toHaveBeenCalled();

    await screen.findByText(/评估完成：/, {}, { timeout: 5_000 });
    expect(screen.getByText(/该矩阵将进入报告「议题重要性评估」章/)).toBeTruthy();
    const panel = document.querySelector(".gs-scoring-matrix-panel");
    expect(panel?.className).toContain("gs-matrix-reveal");
  });
});
