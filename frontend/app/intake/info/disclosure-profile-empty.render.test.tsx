// ABOUTME: 无存量值时，已停用的两个附加参考项不渲染——新报告不该看见永远灰着的控件。
// ABOUTME: 与 disclosure-profile.render.test.tsx 互补：那份钉住「有存量值必须回显」（design.md §4.0.2）。
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

vi.mock("@/lib/material-workspace-api", () => ({
  fetchReportPreparation: () => new Promise(() => {}),
}));

vi.mock("@/lib/api", () => ({
  downloadReportBasicsTemplate: vi.fn(),
  importReportBasicsWorkbook: vi.fn(),
}));

// 新建报告：两个附加参考项都无值。
const report = {
  title: "t",
  fields: {},
  intakeItems: [],
  disclosureProfile: {
    mainlandStandard: "sse",
    includesHongKongExchangeGuide: false,
    additionalDisclosureReferences: [],
  },
  sections: [],
};

vi.mock("@/lib/app-context", () => ({
  useApp: () => ({
    activeReportId: "report-empty",
    activeReportCapabilities: { material_agent_enabled: true },
    report,
    savedAt: null,
    setDisclosureProfile: vi.fn(),
    setFieldValue: vi.fn(),
    setIntakeAnswer: vi.fn(),
  }),
}));

import IntakeInfoPage from "./page";

describe("无存量值时的已停用参考项", () => {
  it("不渲染港交所守则勾选框与其他准则输入框", () => {
    render(<IntakeInfoPage />);

    expect(screen.queryByRole("checkbox", { name: /港交所/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /其他准则/ })).toBeNull();
    // 「暂未开放」的理由文案随控件一并消失，不留孤立提示。
    expect(screen.queryByText("暂未开放。当前仅支持在所属准则包内编制。")).toBeNull();
  });

  it("沪、深、北三所指引不受影响，仍然可选", () => {
    render(<IntakeInfoPage />);

    const radios = screen.getAllByRole("radio", { name: /证券交易所/ });
    expect(radios).toHaveLength(3);
    for (const radio of radios) expect((radio as HTMLInputElement).disabled).toBe(false);
  });
});
