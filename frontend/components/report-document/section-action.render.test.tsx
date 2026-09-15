// ABOUTME: 章节动作入口的渲染回归——只在议题章节（H2）且动作已提供时出现，且为标题的兄弟节点。
// ABOUTME: 权益不含整节重写时页面不传该动作，按钮随之不渲染；此处以「是否传入」模拟这两种情形。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// 议题章节（H2 + reportSectionId）会额外渲染准则条款批注，而该组件读 useApp().config；
// 本测试只挂 ReportProvider，故 mock 应用上下文，保持夹具与真实议题章节同形。
vi.mock("@/lib/app-context", () => ({
  useApp: () => ({ config: { user_visible_disclosure_clause_annotations: [] } }),
}));

import { DocumentRenderer } from "@/components/report-document/document-renderer";
import { deriveDocument } from "@/lib/derive";
import { ReportProvider, type ReportDocumentActions } from "@/lib/report-context";
import type { Report } from "@/lib/schema";

const report: Report = {
  knowledgePackageId: "sse_zh_hans",
  title: "t",
  fields: {},
  sections: [
    {
      key: "waste_management",
      title: "废弃物管理",
      // 标题层级是契约字段（derive 取 section.headingLevel ?? 1），议题章节为 2；
      // 章节动作只挂在议题章节上，故夹具必须如实带上它。
      headingLevel: 2,
      reportSectionId: "waste_management",
      blocks: [
        {
          id: "waste.body",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          content: [{ kind: "text", text: "既有正文" }],
          state: "ready",
        },
      ],
    },
  ],
};

function renderDocument(overrides: Partial<ReportDocumentActions> = {}) {
  const actions: ReportDocumentActions = {
    selectBlock: vi.fn(),
    beginEdit: vi.fn(),
    commitEdit: vi.fn(),
    commitTableEdit: vi.fn(),
    cancelEdit: vi.fn(),
    ...overrides,
  };
  const view = render(
    <ReportProvider
      report={report}
      updateTable={vi.fn()}
      updateStakeholderEngagement={vi.fn()}
      preview
      actions={actions}
    >
      <DocumentRenderer nodes={deriveDocument(report)} />
    </ReportProvider>,
  );
  return { ...view, actions };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("章节动作入口", () => {
  it("未提供动作时不渲染按钮——权益不含整节重写即此情形", () => {
    renderDocument();
    expect(screen.queryByRole("button", { name: "重写本节" })).toBeNull();
  });

  it("提供动作时按章节 key 触发重写", () => {
    const regenerateSection = vi.fn();
    renderDocument({ regenerateSection });

    fireEvent.click(screen.getByRole("button", { name: "重写本节" }));

    expect(regenerateSection).toHaveBeenCalledWith("waste_management");
  });

  it("按钮是标题的兄弟节点，不混入标题的可及名称", () => {
    const { container } = renderDocument({ regenerateSection: vi.fn() });
    const heading = container.querySelector("h2");
    expect(heading).not.toBeNull();
    // 控件若放进 <h2>，标题的可及名称会带上按钮文案。
    expect(heading!.textContent).not.toContain("重写本节");
    expect(container.querySelector("[data-section-action]")).not.toBeNull();
  });
});
