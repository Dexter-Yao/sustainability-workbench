// ABOUTME: 字符级差异纯函数测试：插入、删除、替换合并成片段，相同文本只产等长片段，超长退化为 null。
import { describe, expect, it } from "vitest";

import { TEXT_DIFF_MAX_CHARS, textChanged, textDiff } from "./text-diff";

describe("textDiff", () => {
  it("identical texts yield a single equal segment", () => {
    expect(textDiff("公司持续改进。", "公司持续改进。")).toEqual([{ kind: "equal", text: "公司持续改进。" }]);
  });

  it("merges adjacent inserted characters into one segment", () => {
    expect(textDiff("公司改进。", "公司持续改进。")).toEqual([
      { kind: "equal", text: "公司" },
      { kind: "insert", text: "持续" },
      { kind: "equal", text: "改进。" },
    ]);
  });

  it("reports deletions and replacements", () => {
    const segments = textDiff("报告期内减排 5%。", "报告期内减排 8%。");
    expect(segments).toEqual([
      { kind: "equal", text: "报告期内减排 " },
      { kind: "delete", text: "5" },
      { kind: "insert", text: "8" },
      { kind: "equal", text: "%。" },
    ]);
  });

  it("handles empty sides", () => {
    expect(textDiff("", "新增")).toEqual([{ kind: "insert", text: "新增" }]);
    expect(textDiff("旧", "")).toEqual([{ kind: "delete", text: "旧" }]);
    expect(textDiff("", "")).toEqual([]);
  });

  it("degrades to null beyond the size cap instead of computing a huge table", () => {
    const long = "字".repeat(TEXT_DIFF_MAX_CHARS + 1);
    expect(textDiff(long, "字")).toBeNull();
  });

  it("textChanged is a plain inequality", () => {
    expect(textChanged("a", "a")).toBe(false);
    expect(textChanged("a", "b")).toBe(true);
  });
});
