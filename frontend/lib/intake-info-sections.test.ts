// ABOUTME: 基本信息页区块随知识包显隐的回归：前提字段不在本报告时整块退场。
// ABOUTME: 页面 section 与左栏二级条目同源于本模块，两处不得各写一份判据。
import { describe, expect, it } from "vitest";

import { INTAKE_INFO_SECTIONS, visibleIntakeInfoSections } from "./intake-info-sections";
import type { Report } from "./schema";

function reportWithFields(keys: string[]): Report {
  const fields: Report["fields"] = {};
  for (const key of keys) {
    fields[key] = {
      key,
      label: key,
      type: "string",
      source: "user_input",
      value: null,
    } as Report["fields"][string];
  }
  return { title: "t", fields, intakeItems: [], sections: [] };
}

const SCOPE_SECTION = "section-applicable-scope";

describe("基本信息页区块可见性", () => {
  it("声明了科技伦理字段的报告（内地包）保留适用范围区块", () => {
    const visible = visibleIntakeInfoSections(
      reportWithFields(["has_technology_ethics_sensitive_activity"]),
    );
    expect(visible.map((section) => section.id)).toContain(SCOPE_SECTION);
  });

  it("未声明该字段的报告（港交所两包）整块退场", () => {
    // 保留区块会渲染出一个标着「必填」却没有任何输入的空壳，用户永远填不完。
    const visible = visibleIntakeInfoSections(reportWithFields(["company_registered_name"]));
    expect(visible.map((section) => section.id)).not.toContain(SCOPE_SECTION);
  });

  it("无前提字段的区块对任何报告都可见", () => {
    const unconditional = INTAKE_INFO_SECTIONS.filter((section) => !section.requiresField);
    const visible = visibleIntakeInfoSections(reportWithFields([]));
    expect(visible).toEqual(unconditional);
  });
});
