// ABOUTME: 报告列表显示名派生回归——占位标题为「可持续发展报告 · 主体名称」，真实标题优先，
// ABOUTME: 无主体名称的草稿回落到「可持续发展报告草稿 · 创建日」。
import { describe, expect, it } from "vitest";
import { en } from "@/lib/i18n/en";
import { zhHans } from "@/lib/i18n/zh-Hans";

import type { ReportSummary } from "@/lib/report-store";

import { reportDisplayTitle } from "./report-display-title";

function summary(overrides: Partial<ReportSummary>): ReportSummary {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    title: "未命名报告",
    report_type: "lightweight",
    report_profile_id: "lightweight@1",
    data_classification: "customer",
    created_under_profile_id: "lightweight@1",
    contract_version: "contract-test@1",
    status: "active",
    created_at: "2026-08-04T02:00:00+08:00",
    updated_at: "2026-08-04T02:00:00+08:00",
    ...overrides,
  } as ReportSummary;
}

describe("reportDisplayTitle", () => {
  it("占位标题为「可持续发展报告 · 主体名称」", () => {
    expect(
      reportDisplayTitle(summary({ company_registered_name: "示例有限公司" }), zhHans, "zh-Hans"),
    ).toBe("可持续发展报告 · 示例有限公司");
  });

  it("真实标题优先于派生名", () => {
    expect(
      reportDisplayTitle(summary({ title: "2025 年度报告", company_registered_name: "示例有限公司" }), zhHans, "zh-Hans"),
    ).toBe("2025 年度报告");
  });

  it("无主体名称的遗留草稿回落到创建日草稿名", () => {
    // 日期按界面语言格式化，不再自拼「N月N日」；此处只断言草稿语义仍在。
    const title = reportDisplayTitle(summary({ company_registered_name: null }), zhHans, "zh-Hans");
    expect(title.startsWith("可持续发展报告草稿 · ")).toBe(true);
    expect(title).toContain("2026");
  });

  it("英文界面下不泄漏技术标识 lightweight", () => {
    const title = reportDisplayTitle(
      summary({ company_registered_name: "Example Ltd" }),
      en,
      "en",
    );
    expect(title).toBe("Sustainability report · Example Ltd");
    expect(title).not.toContain("lightweight");
  });
});
