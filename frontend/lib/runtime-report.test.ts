// ABOUTME: Runtime Report 恢复测试——动态报告结构先由 Planner 装配，再将 V4 用户状态回填到稳定 key。
// ABOUTME: 验证状态快照不拥有章节结构，也不会因首次静态模板缺少动态块而丢失用户内容。
import { describe, expect, it, vi } from "vitest";

import type { Report } from "./schema";
import type { StoredReportStateV4 } from "./stored-report-state";

const apiMocks = vi.hoisted(() => ({ plan: vi.fn() }));
vi.mock("./api", () => ({ plan: apiMocks.plan }));

import { restoreRuntimeReport } from "./runtime-report";

const staticTemplate: Report = {
  title: "模板",
  fields: {},
  intakeItems: [],
  sections: [{ key: "about_report", title: "关于本报告", blocks: [] }],
};

const state: StoredReportStateV4 = {
  version: 4,
  fields: {},
  intakeItems: { "climate.q1": { answer: "已填写" } },
  assessmentInput: {
    reportingYear: 2025,
    threshold: { financial: 3, impact: 3 },
    scores: [{
      assessmentTopicId: "climate_change",
      financialScore: 5,
      impactScore: 5,
    }],
  },
  disclosureProfile: null,
  appendixPackage: undefined,
  meta: null,
  sectionTitles: {},
  generatedBlocks: {
    "climate.main": { content: [{ kind: "text", text: "当前生成正文" }], state: "ready" },
  },
  tableBlocks: {},
  imageBlocks: {},
};

describe("restoreRuntimeReport", () => {
  it("在 Planner 动态装配后回填议题问卷和生成正文", async () => {
    const assembled: Report = {
      ...staticTemplate,
      intakeItems: [{ key: "climate.q1", contentScopeId: "climate_change", prompt: "问题", kind: "text" }],
      sections: [{
        key: "climate_change",
        title: "应对气候变化",
        reportSectionId: "climate_change",
        blocks: [{
          id: "climate.main",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          content: [{ kind: "text", text: "模板草稿" }],
        }],
      }],
    };
    apiMocks.plan.mockResolvedValueOnce({ report: assembled, diagnostics: [], added: ["climate_change"], dropped: [] });

    const restored = await restoreRuntimeReport(staticTemplate, state, "cv-current");

    expect(apiMocks.plan).toHaveBeenCalledWith(expect.objectContaining({ assessmentInput: state.assessmentInput }), "cv-current");
    expect(restored.intakeItems[0]?.answer).toBe("已填写");
    expect(restored.sections[0]?.blocks[0]).toMatchObject({
      state: "ready",
      content: [{ kind: "text", text: "当前生成正文" }],
    });
  });

  it("保留 Planner 对利益相关方适用范围的协调结果", async () => {
    const storedProfile = {
      scopeAssessmentTopicIds: ["climate_change"],
      entries: [],
    } as unknown as NonNullable<Report["stakeholderEngagement"]>;
    const reconciledProfile = {
      scopeAssessmentTopicIds: ["climate_change", "technology_ethics"],
      entries: [],
    } as unknown as NonNullable<Report["stakeholderEngagement"]>;
    const stakeholderState = { ...state, stakeholderEngagement: storedProfile };
    apiMocks.plan.mockResolvedValueOnce({
      report: { ...staticTemplate, stakeholderEngagement: reconciledProfile },
      diagnostics: [],
      added: [],
      dropped: [],
    });

    const restored = await restoreRuntimeReport(staticTemplate, stakeholderState, "cv-current");

    expect(restored.stakeholderEngagement).toBe(reconciledProfile);
  });
});
