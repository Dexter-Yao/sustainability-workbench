// ABOUTME: 报告输入体验合同测试，验证默认值仅在新建报告时由模板规则推导，且用户已有值不被覆盖。
// ABOUTME: 说明文本按稳定配置路径读取，前端不自建第二份文案或默认规则。
import { describe, expect, it } from "vitest";

import { applyReportInputDefaults, inputGuidanceAt, withReportPeriodDefaults } from "./report-input-guidance";
import type { Report } from "./schema";
import { reportToStoredReportState } from "./stored-report-state";

const template: Report = {
  title: "template",
  fields: {
    reporting_year: { key: "reporting_year", label: "报告年份", type: "year", source: "user_input" },
    report_period_start: { key: "report_period_start", label: "报告期起始", type: "date", source: "user_input" },
    report_period_end: { key: "report_period_end", label: "报告期截止", type: "date", source: "user_input" },
  },
  inputGuidance: {
    "fields.reporting_year.value": {
      helpText: "填写本报告覆盖的完整年度。",
      defaultRule: "previous_calendar_year",
    },
    "fields.report_period_start.value": {
      helpText: "年度报告默认从报告年份的 1 月 1 日开始。",
      defaultRule: "reporting_year_start",
    },
    "fields.report_period_end.value": {
      helpText: "年度报告默认截至报告年份的 12 月 31 日。",
      defaultRule: "reporting_year_end",
    },
  },
  intakeItems: [],
  sections: [],
};

describe("report input guidance", () => {
  it("在 2026 年新建报告时推导上一完整自然年，且不修改模板", () => {
    const initialized = applyReportInputDefaults(template, new Date("2026-07-15T00:00:00+08:00"));

    expect(initialized.fields.reporting_year.value).toBe("2025");
    expect(initialized.fields.report_period_start.value).toBe("2025-01-01");
    expect(initialized.fields.report_period_end.value).toBe("2025-12-31");
    expect(template.fields.reporting_year.value).toBeUndefined();
    expect(reportToStoredReportState(initialized).fields).toMatchObject({
      reporting_year: "2025",
      report_period_start: "2025-01-01",
      report_period_end: "2025-12-31",
    });
  });

  it("不覆盖用户已填写的报告期事实", () => {
    const customized: Report = {
      ...template,
      fields: {
        ...template.fields,
        reporting_year: { ...template.fields.reporting_year, value: "2024" },
        report_period_start: { ...template.fields.report_period_start, value: "2024-04-01" },
      },
    };

    const initialized = applyReportInputDefaults(customized, new Date("2026-07-15T00:00:00+08:00"));

    expect(initialized.fields.reporting_year.value).toBe("2024");
    expect(initialized.fields.report_period_start.value).toBe("2024-04-01");
    expect(initialized.fields.report_period_end.value).toBe("2024-12-31");
  });

  it("按稳定路径读取统一管理的用户说明", () => {
    expect(inputGuidanceAt(template, "fields.reporting_year.value")?.helpText).toBe("填写本报告覆盖的完整年度。");
    expect(inputGuidanceAt(template, "fields.unknown.value")).toBeNull();
  });
});

describe("填写报告年份后补齐报告期", () => {
  function withYear(value: string): Report {
    return {
      ...template,
      fields: {
        ...template.fields,
        reporting_year: { ...template.fields.reporting_year, value },
      },
    };
  }

  it("报告期为空时按年份补上该年度起止", () => {
    const next = withReportPeriodDefaults(withYear("2025"), "reporting_year");

    expect(next.fields.report_period_start.value).toBe("2025-01-01");
    expect(next.fields.report_period_end.value).toBe("2025-12-31");
  });

  it("用户已填的报告期不被覆盖", () => {
    const customized: Report = {
      ...withYear("2025"),
      fields: {
        ...withYear("2025").fields,
        report_period_start: { ...template.fields.report_period_start, value: "2025-04-01" },
        report_period_end: { ...template.fields.report_period_end, value: "2026-03-31" },
      },
    };

    const next = withReportPeriodDefaults(customized, "reporting_year");

    expect(next.fields.report_period_start.value).toBe("2025-04-01");
    expect(next.fields.report_period_end.value).toBe("2026-03-31");
  });

  it("用户主动清空的报告期保持为空，不被默认值填回", () => {
    const cleared: Report = {
      ...withYear("2025"),
      fields: {
        ...withYear("2025").fields,
        report_period_start: { ...template.fields.report_period_start, value: "" },
        report_period_end: { ...template.fields.report_period_end, value: "" },
      },
    };

    const next = withReportPeriodDefaults(cleared, "reporting_year");

    expect(next.fields.report_period_start.value).toBe("");
    expect(next.fields.report_period_end.value).toBe("");
  });

  it("改动其他字段不触发报告期补齐", () => {
    const source = withYear("2025");
    expect(withReportPeriodDefaults(source, "company_short_name")).toBe(source);
  });

  it("年份非法时不产生日期", () => {
    const next = withReportPeriodDefaults(withYear("20"), "reporting_year");

    expect(next.fields.report_period_start.value).toBeUndefined();
    expect(next.fields.report_period_end.value).toBeUndefined();
  });
});
