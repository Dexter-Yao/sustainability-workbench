// ABOUTME: editable-sequence 单元测试——命令态下可编辑段落的上/下导航纯逻辑。
// ABOUTME: 不触 DOM，只对有序 blockId 列表做选择移动的边界校验。
import { describe, expect, it } from "vitest";

import { stepSelection } from "./editable-sequence";

const SEQ = ["a", "b", "c"];

describe("stepSelection · ↑↓ 在可编辑段落间移动", () => {
  it("无当前选中时，向下选第一段、向上选最后一段", () => {
    expect(stepSelection(SEQ, null, "down")).toBe("a");
    expect(stepSelection(SEQ, null, "up")).toBe("c");
  });
  it("向下移动到下一段、向上移动到上一段", () => {
    expect(stepSelection(SEQ, "a", "down")).toBe("b");
    expect(stepSelection(SEQ, "b", "up")).toBe("a");
  });
  it("到达两端不回绕（停在端点）", () => {
    expect(stepSelection(SEQ, "c", "down")).toBe("c");
    expect(stepSelection(SEQ, "a", "up")).toBe("a");
  });
  it("当前 id 不在序列中时按方向落到端点", () => {
    expect(stepSelection(SEQ, "x", "down")).toBe("a");
    expect(stepSelection(SEQ, "x", "up")).toBe("c");
  });
  it("空序列返回 null", () => {
    expect(stepSelection([], null, "down")).toBeNull();
  });
});
