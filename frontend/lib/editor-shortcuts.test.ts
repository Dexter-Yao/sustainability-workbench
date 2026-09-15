// ABOUTME: editor-shortcuts 单元测试——平台修饰键渲染、快捷键目录、按键匹配的纯逻辑校验。
// ABOUTME: 覆盖 Mac/Windows 双键位等价、组合键匹配与非快捷键的拒绝。
import { describe, expect, it } from "vitest";

import { matchShortcut, renderKeys, SHORTCUTS, type ShortcutEvent } from "./editor-shortcuts";

describe("renderKeys · 平台修饰键渲染", () => {
  it("Mac 渲染 ⌘⇧↵ 符号", () => {
    expect(renderKeys(["mod", "shift", "enter"], "mac")).toBe("⌘ ⇧ ↵");
  });
  it("Windows 渲染 Ctrl Shift Enter 文字", () => {
    expect(renderKeys(["mod", "shift", "enter"], "windows")).toBe("Ctrl Shift Enter");
  });
  it("方向键两端一致渲染 ↑ ↓", () => {
    expect(renderKeys(["up", "down"], "mac")).toBe("↑ ↓");
    expect(renderKeys(["up", "down"], "windows")).toBe("↑ ↓");
  });
  it("esc 按平台习惯大小写", () => {
    expect(renderKeys(["esc"], "mac")).toBe("esc");
    expect(renderKeys(["esc"], "windows")).toBe("Esc");
  });
});

describe("SHORTCUTS · 目录唯一定义源", () => {
  it("只保留选择、编辑与通用动作", () => {
    const ids = SHORTCUTS.map((s) => s.id);
    expect(ids).toEqual(["select", "edit", "done", "undo", "save", "help"]);
  });
});

describe("matchShortcut · 按键匹配（mod 随平台映射）", () => {
  const press = (e: Partial<ShortcutEvent>): ShortcutEvent => ({
    key: "",
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    ...e,
  });

  it("已删除的采纳组合键不再匹配", () => {
    expect(matchShortcut(press({ key: "Enter", metaKey: true, shiftKey: true }), "mac")).toBeNull();
    expect(matchShortcut(press({ key: "Enter", ctrlKey: true, shiftKey: true }), "mac")).toBeNull();
    expect(matchShortcut(press({ key: "Enter", ctrlKey: true, shiftKey: true }), "windows")).toBeNull();
  });
  it("裸 Enter → edit；裸 Escape → done", () => {
    expect(matchShortcut(press({ key: "Enter" }), "mac")).toBe("edit");
    expect(matchShortcut(press({ key: "Escape" }), "mac")).toBe("done");
  });
  it("⌘Enter（无 shift）不匹配 edit", () => {
    expect(matchShortcut(press({ key: "Enter", metaKey: true }), "mac")).toBeNull();
  });
  it("↑↓ → select", () => {
    expect(matchShortcut(press({ key: "ArrowUp" }), "mac")).toBe("select");
    expect(matchShortcut(press({ key: "ArrowDown" }), "windows")).toBe("select");
  });
  it("⌘S → save；⌘Z → undo", () => {
    expect(matchShortcut(press({ key: "s", metaKey: true }), "mac")).toBe("save");
    expect(matchShortcut(press({ key: "z", metaKey: true }), "mac")).toBe("undo");
  });
  it("? → help（无修饰）", () => {
    expect(matchShortcut(press({ key: "?" }), "mac")).toBe("help");
  });
  it("普通输入键不匹配任何快捷键", () => {
    expect(matchShortcut(press({ key: "a" }), "mac")).toBeNull();
  });
});
