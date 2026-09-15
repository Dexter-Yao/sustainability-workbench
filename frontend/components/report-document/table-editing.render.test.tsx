// ABOUTME: 表格编辑的渲染回归——tablesEditable 开启后单元格可改且经编辑日志提交；
// ABOUTME: 同时守住「解锁表格不得连带解锁利益相关方档案」这条曾经差点上线的边界。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentRenderer } from "@/components/report-document/document-renderer";
import { deriveDocument } from "@/lib/derive";
import { ReportProvider, useReport, type ReportDocumentActions } from "@/lib/report-context";
import type { Report } from "@/lib/schema";

const report: Report = {
  knowledgePackageId: "sse_zh_hans",
  title: "t",
  fields: {},
  sections: [
    {
      key: "waste",
      title: "废弃物管理",
      blocks: [
        {
          id: "waste.table",
          type: "table",
          blockType: "generative",
          source: "user_input",
          table: {
            rowSource: "user",
            colDefs: [{ key: "item", header: "项目", cellType: "text" }],
            children: [
              { type: "tr", headerRow: true, children: [{ type: "th", colKey: "item", value: "项目" }] },
              { type: "tr", children: [{ type: "td", colKey: "item", value: "危废暂存" }] },
            ],
          },
        },
      ],
    },
  ],
};

function renderTable(overrides: Record<string, unknown> = {}) {
  const actions: ReportDocumentActions = {
    selectBlock: vi.fn(),
    beginEdit: vi.fn(),
    commitEdit: vi.fn(),
    commitTableEdit: vi.fn(),
    cancelEdit: vi.fn(),
  };
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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("表格编辑", () => {
  it("未开启 tablesEditable 时单元格是只读文本，没有第二个录入入口", () => {
    const { container } = renderTable();
    // 可编辑单元格渲染成带 aria-label 的 textarea（TextCell）；只读时只有纯文本。
    expect(container.querySelector("textarea")).toBeNull();
    expect(screen.getByText("危废暂存")).toBeTruthy();
  });

  it("开启后单元格可改，且改动经 commitTableEdit 进编辑日志", () => {
    const { actions } = renderTable({ tablesEditable: true });
    // TextCell 以列 header 作 aria-label，用户可及名称即「项目」。
    const cell = screen.getByLabelText("项目");
    expect(cell.tagName.toLowerCase()).toBe("textarea");

    fireEvent.change(cell, { target: { value: "危废暂存间" } });

    expect(actions.commitTableEdit).toHaveBeenCalled();
    const [blockId, updater] = (actions.commitTableEdit as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(blockId).toBe("waste.table");
    // updater 是纯函数：对传入的表返回新表，由页面据此算出 before/after。
    const next = (updater as (t: Report["sections"][0]["blocks"][0]["table"]) => never)(
      report.sections[0].blocks[0].table,
    ) as unknown as { children: { children: { value: unknown }[] }[] };
    expect(next.children[1].children[0].value).toBe("危废暂存间");
  });

  it("解锁表格不改变 preview：两个开关互不牵连", () => {
    // 利益相关方档案的编辑器由 preview 单独把关（stakeholder-engagement-table
    // 在 !preview 时才渲染 TopicEditor/MethodEditor）。此处断言的是**开关本身**
    // 仍分离——档案渲染需要 report.stakeholderEngagement，本夹具刻意不含它，
    // 故不在此断言其 DOM，避免写成恒真的空选择器。
    let seen: { preview: boolean; tablesEditable: boolean } | null = null;
    function Probe() {
      const { preview, tablesEditable } = useReport();
      seen = { preview, tablesEditable };
      return null;
    }
    render(
      <ReportProvider
        report={report}
        updateTable={vi.fn()}
        updateStakeholderEngagement={vi.fn()}
        preview
        tablesEditable
      >
        <Probe />
      </ReportProvider>,
    );
    expect(seen).toEqual({ preview: true, tablesEditable: true });
  });
});
