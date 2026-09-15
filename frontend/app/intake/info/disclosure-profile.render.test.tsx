// ABOUTME: 披露准则的页面级回归：内地包三所指引可选、其他参考文件禁用；准则由知识包固定的包不渲染选择器。
// ABOUTME: 已保存的历史值必须照常回显——禁用只关闭写入，不隐藏事实（design.md §4.0.2）。
// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/intake/info",
}));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => ({
    status: "ready",
    materialAgentEnabled: true,
    canGenerate: true,
  }),
}));

// preparation 是本页唯一的网络读取；用永挂 Promise 隔断，保持用例无 I/O、无噪声输出。
vi.mock("@/lib/material-workspace-api", () => ({
  fetchReportPreparation: () => new Promise(() => {}),
}));

vi.mock("@/lib/api", () => ({
  downloadReportBasicsTemplate: vi.fn(),
  importReportBasicsWorkbook: vi.fn(),
}));

// 历史报告：收窄前已勾选港交所守则并填了其他参考文件。
const setDisclosureProfile = vi.fn();
const report = {
  title: "t",
  fields: {},
  intakeItems: [],
  disclosureProfile: {
    mainlandStandard: "sse",
    includesHongKongExchangeGuide: true,
    additionalDisclosureReferences: ["《企业可持续披露准则——基本准则（试行）》"],
  },
  sections: [],
};

vi.mock("@/lib/app-context", () => ({
  useApp: () => ({
    activeReportId: "report-1",
    activeReportCapabilities: { material_agent_enabled: true },
    report,
    savedAt: null,
    setDisclosureProfile,
    setFieldValue: vi.fn(),
    setIntakeAnswer: vi.fn(),
  }),
}));

import IntakeInfoPage from "./page";

describe("披露准则收窄", () => {
  it("沪、深、北三所指引保持可选", () => {
    render(<IntakeInfoPage />);
    const radios = screen.getAllByRole("radio", { name: /证券交易所/ });
    expect(radios).toHaveLength(3);
    for (const radio of radios) expect((radio as HTMLInputElement).disabled).toBe(false);
  });

  it("港交所守则禁用，并陈述「暂未开放」而非承诺时间点", () => {
    render(<IntakeInfoPage />);
    const checkbox = screen.getByRole("checkbox", { name: /港交所/ }) as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
    const reasons = screen.getAllByText("暂未开放。当前仅支持在所属准则包内编制。");
    expect(reasons.length).toBeGreaterThanOrEqual(2);
    for (const reason of reasons) {
      expect(reason.textContent).not.toMatch(/敬请期待|即将|上线/);
    }
  });

  it("历史已保存值照常回显，禁用不清空既有编制依据", () => {
    render(<IntakeInfoPage />);
    const checkbox = screen.getByRole("checkbox", { name: /港交所/ }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    const textarea = screen.getByRole("textbox", { name: /其他准则/ }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("《企业可持续披露准则——基本准则（试行）》");
    expect(textarea.disabled).toBe(true);
  });
});
