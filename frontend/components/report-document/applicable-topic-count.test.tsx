// ABOUTME: 「本报告披露议题数量」正文引用的取值来源回归：现算自服务端评分结果，不取前端基数。
// ABOUTME: 议题范围是知识包属性（上交所 24 个、港交所 16 个），任何前端写死的基数都会对另一个包印错。
// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn().mockResolvedValue("access-token") }));
vi.mock("@/lib/app-context", () => ({
  useApp: () => ({ activeReportId: "report-1", config: { blocks: [], user_visible_disclosure_clause_annotations: [] } }),
}));

import { ReportProvider } from "@/lib/report-context";
import type { AssessmentResult, Report } from "@/lib/schema";

import { RefInline } from "./document-nodes";

afterEach(cleanup);

const REF = "assessment.applicableTopicCount";

function scoredTopics(count: number): AssessmentResult["topics"] {
  return Array.from({ length: count }, (_, index) => ({
    assessmentTopicId: `topic_${index}`,
    determination: "scored" as const,
    materiality: "non" as const,
    financialScore: 1,
    impactScore: 1,
  }));
}

function reportWith(knowledgePackageId: string, topicCount: number | null): Report {
  return {
    title: "t",
    fields: {},
    intakeItems: [],
    sections: [],
    knowledgePackageId,
    assessment: topicCount === null ? null : { reportingYear: 2026, topics: scoredTopics(topicCount) },
  };
}

function renderRef(report: Report) {
  render(
    <ReportProvider
      report={report}
      updateTable={() => {}}
      updateStakeholderEngagement={() => {}}
      preview
    >
      <RefInline refKey={REF} />
    </ReportProvider>,
  );
}

describe("本报告披露议题数量", () => {
  it("港交所包按其 16 个评分议题现算，不落到上交所的基数", () => {
    renderRef(reportWith("hkex_en", 16));
    expect(screen.getByText("16")).toBeTruthy();
    expect(screen.queryByText("23")).toBeNull();
  });

  it("上交所包按其 24 个评分议题现算", () => {
    renderRef(reportWith("sse_zh_hans", 24));
    expect(screen.getByText("24")).toBeTruthy();
  });

  it("尚未评分时渲染占位而非编造数字", () => {
    renderRef(reportWith("hkex_en", null));
    expect(screen.getByText("【本报告披露议题数量】")).toBeTruthy();
  });
});
