// ABOUTME: 「选填补充」折叠区的可发现性合同测试——design.md §3.1 的四条要求逐条可执行。
// ABOUTME: 渐进披露的前提是用户看得出这里可以展开；纯文字按钮会使选填内容等同不存在。
// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { OptionalSupplement } from "./optional-supplement";

const HINT = "发布与审批、治理制度等；不填不影响生成。";

afterEach(cleanup);

describe("OptionalSupplement", () => {
  it("默认折叠，内容不进入可访问树", () => {
    render(
      <OptionalSupplement hint={HINT}>
        <p>选填字段</p>
      </OptionalSupplement>,
    );
    expect(
      screen.getByRole("button", { name: /选填补充/ }).getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.queryByText("选填字段")).toBeNull();
  });

  it("点击展开与再次收起", () => {
    render(
      <OptionalSupplement hint={HINT}>
        <p>选填字段</p>
      </OptionalSupplement>,
    );
    const trigger = screen.getByRole("button", { name: /选填补充/ });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("选填字段")).toBeTruthy();
    fireEvent.click(trigger);
    expect(screen.queryByText("选填字段")).toBeNull();
  });

  it("一句话说明（不填后果）在折叠与展开态均显示（design.md §3.1）", () => {
    render(
      <OptionalSupplement hint={HINT}>
        <p>选填字段</p>
      </OptionalSupplement>,
    );
    expect(screen.getByText(HINT)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /选填补充/ }));
    expect(screen.getByText(HINT)).toBeTruthy();
  });

  it("defaultOpen 初始展开（基本信息页），仍可手动收起", () => {
    render(
      <OptionalSupplement hint={HINT} defaultOpen>
        <p>选填字段</p>
      </OptionalSupplement>,
    );
    const trigger = screen.getByRole("button", { name: /选填补充/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("选填字段")).toBeTruthy();
    fireEvent.click(trigger);
    expect(screen.queryByText("选填字段")).toBeNull();
  });

  it("折叠态有边界与底色，可被识别为控件而非裸文字", () => {
    render(<OptionalSupplement hint={HINT}><p>选填字段</p></OptionalSupplement>);
    const trigger = screen.getByRole("button", { name: /选填补充/ });
    expect(trigger.style.background).toContain("--surface-sunken");
    expect(trigger.style.borderColor).toContain("--border");
    expect(trigger.style.cursor).toBe("pointer");
  });

  it("三角指示展开态；不用 › 与 ˄（读作装饰而非控件）", () => {
    render(<OptionalSupplement hint={HINT}><p>选填字段</p></OptionalSupplement>);
    const trigger = screen.getByRole("button", { name: /选填补充/ });
    expect(trigger.textContent).toContain("▸");
    expect(trigger.textContent).not.toContain("›");
    fireEvent.click(trigger);
    expect(trigger.textContent).toContain("▾");
    expect(trigger.textContent).not.toContain("˄");
  });

  it("配色保持中性——折叠区不是主操作，不得用主色作文字色（§2.1）", () => {
    const { container } = render(
      <OptionalSupplement hint={HINT}><p>选填字段</p></OptionalSupplement>,
    );
    // 允许 --accent-subtle 作 hover 底色，但任何元素不得以 --accent 作前景色。
    for (const node of Array.from(container.querySelectorAll<HTMLElement>("*"))) {
      expect(node.style.color).not.toBe("var(--accent)");
    }
  });
});
