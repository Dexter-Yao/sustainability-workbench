// ABOUTME: 文档渲染器渲染回归：标题携带章节锚点、受控省略块与空图片承载位不出现、可绘制图片保留容器、选中与编辑态可触达。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn().mockResolvedValue("access-token") }));
vi.mock("@/lib/app-context", () => ({
  useApp: () => ({
    activeReportId: "report-1",
    config: { blocks: [], user_visible_disclosure_clause_annotations: [] },
  }),
}));
vi.mock("@/lib/material-workspace-api", () => ({
  fetchReportFileIntake: vi.fn().mockResolvedValue({ files: [] }),
  updateLayoutAssetCaption: vi.fn(),
}));

import { deriveDocument } from "@/lib/derive";
import { ReportProvider } from "@/lib/report-context";
import type { Report } from "@/lib/schema";

import { DocumentRenderer } from "./document-renderer";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const report: Report = {
  title: "示例报告",
  fields: {},
  intakeItems: [],
  sections: [
    {
      key: "waste",
      title: "废弃物管理",
      headingLevel: 2,
      reportSectionId: "waste_management",
      blocks: [
        {
          id: "waste.body",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          state: "ready",
          content: [{ kind: "text", text: "公司建立了危险废弃物台账。" }],
        },
        {
          id: "waste.fixed",
          type: "paragraph",
          blockType: "fixed",
          source: "template",
          content: [{ kind: "text", text: "本节依据准则要求披露。" }],
        },
        { id: "waste.gated", type: "paragraph", blockType: "generative", source: "ai", state: "omitted" },
        {
          id: "waste.figure",
          type: "image",
          blockType: "fixed",
          source: "template",
          image: { placeholder: "废弃物处置流程图", layoutAssetSlot: true, layoutAssetIds: [] },
        },
        {
          id: "waste.chart",
          type: "image",
          blockType: "fixed",
          source: "derived",
          image: { caption: "废弃物指标概览", derivedVisualization: { kind: "quantitative_metric_summary", metricKeys: [] } },
        },
      ],
    },
  ],
};

function renderDocument(overrides: Partial<Parameters<typeof ReportProvider>[0]> = {}) {
  const actions = { selectBlock: vi.fn(), beginEdit: vi.fn(), commitEdit: vi.fn(), cancelEdit: vi.fn() };
  const view = render(
    <ReportProvider
      report={report}
      updateTable={vi.fn()}
      updateStakeholderEngagement={vi.fn()}
      preview
      actions={actions}
      {...overrides}
    >
      <DocumentRenderer nodes={deriveDocument(report)} />
    </ReportProvider>,
  );
  return { ...view, actions };
}

describe("DocumentRenderer", () => {
  it("headings carry section anchors and omitted blocks never render", () => {
    const { container } = renderDocument();
    const heading = container.querySelector("h2");
    expect(heading?.getAttribute("id")).toBe("section-waste");
    expect(heading?.getAttribute("data-section-key")).toBe("waste");
    expect(container.querySelector('[data-block-id="waste.body"]')).not.toBeNull();
    expect(container.querySelector('[data-block-id="waste.gated"]')).toBeNull();
    // Empty carrier slots never render a placeholder; drawable images keep their block container.
    expect(container.textContent).not.toContain("图片占位");
    expect(container.querySelector('[data-block-id="waste.figure"]')).toBeNull();
    expect(container.querySelector('[data-block-id="waste.chart"]')).not.toBeNull();
  });

  it("clicking a block selects it; double-clicking editable prose begins an edit", () => {
    const { container, actions } = renderDocument();
    const editable = container.querySelector('[data-block-id="waste.body"]')!;
    fireEvent.click(editable);
    expect(actions.selectBlock).toHaveBeenCalledWith("waste.body");
    fireEvent.doubleClick(editable);
    expect(actions.beginEdit).toHaveBeenCalledWith("waste.body");
    fireEvent.doubleClick(container.querySelector('[data-block-id="waste.fixed"]')!);
    expect(actions.beginEdit).toHaveBeenCalledTimes(1);
  });

  it("renders the editor for the block being edited and commits its text", () => {
    const { actions } = renderDocument({ editingBlockId: "waste.body", selectedBlockId: "waste.body" });
    const editor = screen.getByLabelText("编辑本段正文") as HTMLTextAreaElement;
    expect(editor.value).toBe("公司建立了危险废弃物台账。");
    fireEvent.change(editor, { target: { value: "公司建立了危险废弃物台账并按月核对。" } });
    fireEvent.keyDown(editor, { key: "Escape" });
    expect(actions.commitEdit).toHaveBeenCalledWith("waste.body", "公司建立了危险废弃物台账并按月核对。");
  });

  it("marks edited blocks with the modified dot", () => {
    const { container } = renderDocument({ editedBlockIds: new Set(["waste.body"]) });
    expect(container.querySelector('[data-block-id="waste.body"] [aria-label="已修改"]')).not.toBeNull();
  });
});
