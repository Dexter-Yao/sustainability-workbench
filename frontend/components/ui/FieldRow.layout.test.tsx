// ABOUTME: 锁定 FieldRow 的版面契约：槽位顺序（说明在控件之上、报错在控件之下）与组内对齐占位。
// ABOUTME: 顺序是用户可见契约（design.md §2.2.1），仅靠肉眼截图无法防回归，故在此固化。
// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

import { FieldGroup, FieldRow } from "./FieldRow";

/** a 是否排在 b 之前（文档顺序）。用 DOM 原生比较，不自己走树。 */
function precedes(a: Node, b: Node): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("FieldRow 槽位顺序", () => {
  it("常驻说明排在控件之前——先读怎么填，再动手填", () => {
    render(
      <FieldRow label="报告发布方式" inlineHint="选择报告对外提供的方式。">
        <select aria-label="报告发布方式">
          <option>未选择</option>
        </select>
      </FieldRow>,
    );

    const hint = screen.getByText("选择报告对外提供的方式。");
    const control = screen.getByRole("combobox");

    expect(precedes(hint, control)).toBe(true);
  });

  it("报错排在控件之后——它针对的是已经填进去的内容", () => {
    render(
      <FieldRow label="报告期截止" error="截止日期须晚于起始日期。">
        <input aria-label="报告期截止" />
      </FieldRow>,
    );

    const error = screen.getByRole("alert");
    const control = screen.getByRole("textbox");

    expect(precedes(control, error)).toBe(true);
  });

  it("说明与报错同时存在时，说明在上、报错在下，互不吞没", () => {
    render(
      <FieldRow label="公司简介" inlineHint="介绍主营业务与规模。" error="至少填写 100 字。">
        <textarea aria-label="公司简介" />
      </FieldRow>,
    );

    // 二者不得共用一个槽位，否则报错会把说明整段顶掉；应当并存。
    const hint = screen.getByText("介绍主营业务与规模。");
    const error = screen.getByRole("alert");
    const control = screen.getByRole("textbox");
    expect(error.textContent).toBe("至少填写 100 字。");
    expect(precedes(hint, control)).toBe(true);
    expect(precedes(control, error)).toBe(true);
  });
});

describe("FieldGroup 对齐占位", () => {
  it("组内他人有说明时，无说明字段渲染等高占位，使控件对齐", () => {
    render(
      <FieldGroup reserveGuidanceSpace>
        <FieldRow label="读者反馈邮箱" inlineHint="读者据此联系公司。">
          <input aria-label="读者反馈邮箱" />
        </FieldRow>
        <FieldRow label="公司地址">
          <input aria-label="公司地址" />
        </FieldRow>
      </FieldGroup>,
    );

    const address = screen.getByLabelText("公司地址");
    const placeholder = address.previousElementSibling;
    expect(placeholder?.tagName).toBe("P");
    // 占位对读屏隐藏：它没有内容，只有高度。
    expect(placeholder?.getAttribute("aria-hidden")).toBe("true");
    expect((placeholder as HTMLElement).style.visibility).toBe("hidden");
  });

  it("整组都没有说明时不留占位，不平白多出空隙", () => {
    render(
      <FieldGroup reserveGuidanceSpace={false}>
        <FieldRow label="公司地址">
          <input aria-label="公司地址" />
        </FieldRow>
      </FieldGroup>,
    );

    const address = screen.getByLabelText("公司地址");
    expect(address.previousElementSibling?.tagName).not.toBe("P");
  });

  it("不在 FieldGroup 中时保持原样，不留占位", () => {
    render(
      <FieldRow label="公司地址">
        <input aria-label="公司地址" />
      </FieldRow>,
    );

    const address = screen.getByLabelText("公司地址");
    expect(address.previousElementSibling?.tagName).not.toBe("P");
  });
});

describe("FieldRow 禁用态（design.md §4.0.2）", () => {
  it("整行降透明至 .4，与 Button 禁用态同值", () => {
    const { container } = render(
      <FieldRow label="同时参考港交所环境、社会及管治报告守则" disabled disabledReason="暂未开放。">
        <input type="checkbox" aria-label="港交所" disabled readOnly />
      </FieldRow>,
    );
    expect((container.firstElementChild as HTMLElement).style.opacity).toBe("0.4");
  });

  it("禁用原因占据说明槽位并排在控件之前，用户先读到原因再看到灰控件", () => {
    render(
      <FieldRow
        label="其他准则、指南或官方文件"
        disabled
        disabledReason="暂未开放。当前仅支持沪、深、北三所可持续发展报告指引。"
      >
        <textarea aria-label="其他准则" disabled readOnly />
      </FieldRow>,
    );
    const reason = screen.getByText("暂未开放。当前仅支持沪、深、北三所可持续发展报告指引。");
    const control = screen.getByRole("textbox");
    expect(precedes(reason, control)).toBe(true);
    expect(reason.style.color).toBe("var(--warning)");
  });

  it("禁用态照常回显已保存值——禁用只关闭写入，不隐藏事实", () => {
    render(
      <FieldRow label="其他准则、指南或官方文件" disabled disabledReason="暂未开放。">
        <textarea aria-label="其他准则" value="《企业可持续披露准则——基本准则（试行）》" disabled readOnly />
      </FieldRow>,
    );
    const control = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(control.value).toBe("《企业可持续披露准则——基本准则（试行）》");
    expect(control.disabled).toBe(true);
  });

  it("禁用但未给原因时 dev 报错——置灰而不说明原因是主要困惑源", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <FieldRow label="港交所守则" disabled>
        <input aria-label="港交所" disabled readOnly />
      </FieldRow>,
    );
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("§4.0.2"));
    spy.mockRestore();
  });
});
