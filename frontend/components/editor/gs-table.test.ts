// ABOUTME: 表格可编辑性回归，保证派生投影不会在预览或工作台暴露第二个录入入口。
// ABOUTME: KPI 附录行只能经定量元数据写入，不能直接修改 table.children。
import { expect, it } from "vitest";

import { isTableEditable } from "../../lib/table-editability";

it("派生表无论行源配置如何均不可编辑", () => {
  expect(
    isTableEditable({
      id: "appendix.esg_key_performance_metrics",
      type: "table",
      blockType: "fixed",
      source: "derived",
      table: { rowSource: "user", colDefs: [], children: [] },
    }),
  ).toBe(false);
});
