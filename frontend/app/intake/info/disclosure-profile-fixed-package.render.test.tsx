// ABOUTME: 准则由知识包固定时（港交所两包）披露准则节的页面级回归：陈述编制依据，不渲染沪深北单选器。
// ABOUTME: 行业目录同步切到 HSIC——给香港发行人一份国标 GB/T 4754 单选是错的口径。
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

// 港交所繁體报告：包由 report_profile_id 决定，/api/plan 在入口绑定 knowledgePackageId。
const report = {
  title: "t",
  knowledgePackageId: "hkex_zh_hant",
  // 字段定义随知识包下发（label 已是该包语言）；页面不再自带中文 label 副本。
  fields: {
    industry_major_category: {
      key: "industry_major_category",
      label: "所屬行業",
      type: "enum",
      source: "user_input",
      value: null,
    },
    industry_division: {
      key: "industry_division",
      label: "主營業務",
      type: "enum",
      source: "user_input",
      value: null,
    },
  },
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
    activeReportId: "report-hk",
    activeReportCapabilities: { material_agent_enabled: true },
    report,
    savedAt: null,
    setDisclosureProfile: vi.fn(),
    setFieldValue: vi.fn(),
    setIntakeAnswer: vi.fn(),
  }),
}));

import IntakeInfoPage from "./page";

describe("准则由知识包固定时的披露准则节", () => {
  it("不渲染沪深北单选器，改为陈述包固定的编制依据", () => {
    render(<IntakeInfoPage />);

    expect(screen.queryAllByRole("radio", { name: /证券交易所/ })).toHaveLength(0);
    expect(
      screen.getByText("香港聯合交易所有限公司《證券上市規則》附錄C2《環境、社會及管治報告守則》"),
    ).toBeTruthy();
  });

  it("行业门类用 HSIC 而非国标 GB/T 4754", () => {
    render(<IntakeInfoPage />);

    const select = screen.getByLabelText(/所屬行業/) as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.textContent ?? "");

    expect(options.some((text) => text.includes("地產建築業"))).toBe(true);
    // 国标门类（如「A 农、林、牧、渔业」）不应出现在港交所报告里。
    expect(options.some((text) => text.includes("农、林、牧、渔业"))).toBe(false);
  });
});
