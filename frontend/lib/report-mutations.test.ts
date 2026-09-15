// ABOUTME: Report 写回函数测试，锁定正文、表格与生命周期状态只修改结构化 Report 且不改原实例。
import { describe, expect, it } from "vitest";

import { applyBlockText, findBlock, updateBlockState, updateBlockTable } from "./report-mutations";
import type { Report } from "./schema";

const report: Report = {
  title: "测试报告",
  fields: {},
  intakeItems: [],
  sections: [
    {
      key: "env",
      title: "环境",
      headingLevel: 1,
      blocks: [],
      children: [
        {
          key: "climate",
          title: "气候",
          headingLevel: 2,
          reportSectionId: "climate_change",
          blocks: [
            {
              id: "climate.body",
              type: "paragraph",
              blockType: "generative",
              source: "ai",
              state: "pending",
              content: [{ kind: "text", text: "旧正文" }],
            },
            {
              id: "climate.table",
              type: "table",
              blockType: "generative",
              source: "ai",
              table: {
                colDefs: [{ key: "name", header: "名称" }],
                children: [
                  { headerRow: true, children: [{ type: "th", value: "名称" }] },
                  { children: [{ type: "td", colKey: "name", value: "旧行" }] },
                ],
              },
            },
          ],
        },
      ],
    },
  ],
};

describe("report mutations", () => {
  it("按 block id 写回段落正文，不改原 Report", () => {
    const next = applyBlockText(report, "climate.body", "新正文");

    const block = next.sections[0].children?.[0].blocks[0];
    expect(block?.content).toEqual([{ kind: "text", text: "新正文" }]);
    expect(report.sections[0].children?.[0].blocks[0].content).toEqual([{ kind: "text", text: "旧正文" }]);
  });

  it("按 block id 更新表格并保留其余块", () => {
    const next = updateBlockTable(report, "climate.table", (table) => ({ ...table, caption: "表 1" }));
    expect(next.sections[0].children?.[0].blocks[1].table?.caption).toBe("表 1");
    expect(next.sections[0].children?.[0].blocks[0]).toBe(report.sections[0].children?.[0].blocks[0]);
  });

  it("按 block id 更新生命周期状态并能在嵌套章节里找到块", () => {
    const next = updateBlockState(report, "climate.body", "ready");
    expect(next.sections[0].children?.[0].blocks[0].state).toBe("ready");
    expect(findBlock(next, "climate.body")?.state).toBe("ready");
    expect(findBlock(next, "missing")).toBeUndefined();
  });
});
