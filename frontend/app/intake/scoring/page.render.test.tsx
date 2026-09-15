// ABOUTME: 重要性评分页的真实渲染回归：模拟用户键入评分,复现线上"一填就崩/跳"的更新循环。
// ABOUTME: mock 外部服务边界(api/app-context/路由),页面组件本体真实渲染;若存在无限更新将在此失败。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/intake/scoring",
}));

const applyServerReportUpdate = vi.fn();
const applyAuthoritativeReportState = vi.fn().mockResolvedValue(undefined);

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
    applyAuthoritativeReportState,
    applyServerReportUpdate,
  }),
}));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => ({
    status: "ready",
    collectsMaterialityAssessment: true,
    allowedMetricKeys: [],
  }),
}));

vi.mock("@/components/editor/matrix-image", () => ({
  MatrixImage: () => null,
}));

const assessmentFixture = {
  state_seq: 1,
  score_scale: { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 },
  topics: [
    { assessmentTopicId: "t1", name: "议题一", dimension: "环境" },
    { assessmentTopicId: "t2", name: "议题二", dimension: "社会" },
  ],
  current: null,
  resolved: null,
};

const putAssessmentInput = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAssessmentInput: vi.fn(() => Promise.resolve(assessmentFixture)),
  putAssessmentInput: (...args: unknown[]) => putAssessmentInput(...args),
  downloadAssessmentTemplate: vi.fn(),
  importAssessmentWorkbook: vi.fn(),
  StructuredInputConflictError: class StructuredInputConflictError extends Error {},
}));

import IntakeScoringPage from "./page";

afterEach(cleanup);

describe("评分页渲染回归", () => {
  it("键入评分不产生无限更新循环,输入值保留", async () => {
    render(<IntakeScoringPage />);
    // 等待 fixture 加载完成(fetchAssessmentInput resolve → hydrate)。
    const financial = await screen.findByLabelText("议题一 财务重要性");
    await act(async () => {
      fireEvent.change(financial, { target: { value: "3" } });
    });
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3");
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 影响重要性"), { target: { value: "4" } });
    });
    expect((screen.getByLabelText("议题一 影响重要性") as HTMLInputElement).value).toBe("4");
    // 连续多次键入(模拟真实节奏)仍稳定。
    for (const value of ["4.5", "4", "2.5"]) {
      await act(async () => {
        fireEvent.change(screen.getByLabelText("议题二 财务重要性"), { target: { value } });
      });
    }
    expect((screen.getByLabelText("议题二 财务重要性") as HTMLInputElement).value).toBe("2.5");
  });

  // 覆盖门槛若只在点击生成时告知一次,用户可能填到一半离开、以为这步已完成。
  // 提示只在「已开始且未填满」时在场:未开始没有可失去的进度,
  // 填满则门槛已达成,两端出现都是噪音。
  it("评分填到一半时就地告知覆盖门槛,未开始与已填满时不出现", async () => {
    render(<IntakeScoringPage />);
    await screen.findByLabelText("议题一 财务重要性");
    const notice = /评分需覆盖全部议题才会写入报告/;

    // 一个分都没填:不提示。
    expect(screen.queryByText(notice)).toBeNull();

    // 填完第一个议题的两维 → 部分完成,提示出现。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 财务重要性"), { target: { value: "3" } });
    });
    // 只填一维不算这个议题已完成,仍是零完成。
    expect(screen.queryByText(notice)).toBeNull();
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 影响重要性"), { target: { value: "4" } });
    });
    expect(screen.getByText(notice)).toBeTruthy();

    // 填满全部议题 → 门槛达成,提示撤走。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 财务重要性"), { target: { value: "2" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 影响重要性"), { target: { value: "1" } });
    });
    expect(screen.queryByText(notice)).toBeNull();
  });
});
