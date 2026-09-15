// ABOUTME: 导出前检查抽屉的渲染回归——标题过期项自带两项自助处理，其余阻断项只给跳转。
// ABOUTME: 同时守住「阻断项存在时禁止确认导出」这条与服务端 fail-loud 同源的闸。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChecksDrawer } from "./checks-drawer";
import type { Issue } from "@/lib/api";

const staleTitle: Issue = {
  level: "block",
  code: "stale_display_title",
  message: "「应对气候变化」的标题已过期",
  path: "sections.climate_change.displayTitle",
};

const missingField: Issue = {
  level: "block",
  code: "required_input_obligation",
  message: "缺少公司注册名",
  path: "fields.company_registered_name",
};

function renderDrawer(issues: Issue[], overrides: Record<string, unknown> = {}) {
  const handlers = {
    onConfirm: vi.fn(),
    onClose: vi.fn(),
    onJump: vi.fn(),
    onKeepTitle: vi.fn(),
    onEditTitle: vi.fn(),
  };
  const view = render(
    <ChecksDrawer issues={issues} exporting={false} {...handlers} {...overrides} />,
  );
  return { ...view, handlers };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("导出前检查抽屉", () => {
  it("标题过期项给出两项自助处理，并带上章节 key", () => {
    const { handlers } = renderDrawer([staleTitle]);

    fireEvent.click(screen.getByRole("button", { name: "保留当前标题" }));
    expect(handlers.onKeepTitle).toHaveBeenCalledWith("climate_change");

    fireEvent.click(screen.getByRole("button", { name: "编辑标题" }));
    expect(handlers.onEditTitle).toHaveBeenCalledWith("climate_change");
  });

  it("其余阻断项不出现标题动作——它们要回填写页补齐，不在抽屉里自助", () => {
    renderDrawer([missingField]);
    expect(screen.queryByRole("button", { name: "保留当前标题" })).toBeNull();
    expect(screen.queryByRole("button", { name: "编辑标题" })).toBeNull();
  });

  it("未提供处理回调时不渲染动作按钮（只读场景）", () => {
    renderDrawer([staleTitle], { onKeepTitle: undefined, onEditTitle: undefined });
    expect(screen.queryByRole("button", { name: "保留当前标题" })).toBeNull();
  });

  it("有阻断项时禁止确认导出，与服务端 fail-loud 同源", () => {
    renderDrawer([missingField]);
    const confirm = screen.getByRole("button", { name: "确认并导出" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
  });

  it("无问题时可确认导出", () => {
    const { handlers } = renderDrawer([]);
    const confirm = screen.getByRole("button", { name: "确认并导出" });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirm);
    expect(handlers.onConfirm).toHaveBeenCalled();
  });
});
