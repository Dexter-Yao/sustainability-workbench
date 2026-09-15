// ABOUTME: 报告目录响应式初始状态与章节可见性判定的 Parse-First 合同测试。
// ABOUTME: 章节可见性以服务端准备投影 report_identity 域为准；投影缺席才退回字段临时判定，且不可见时必须携带引导入口。
import { describe, expect, it } from "vitest";

import { zhHans } from "@/lib/i18n/zh-Hans";
import type { ReportPreparationProjection } from "@/lib/report-api.generated";

import {
  initialReportDirectoryCollapsed,
  reportSectionsGate,
} from "./report-directory-state";

describe("initialReportDirectoryCollapsed", () => {
  it("defaults compact viewports to collapsed when no preference exists", () => {
    expect(initialReportDirectoryCollapsed(null, true)).toBe(true);
    expect(initialReportDirectoryCollapsed(null, false)).toBe(false);
  });

  it("honors only the explicit persisted collapsed value", () => {
    expect(initialReportDirectoryCollapsed("1", false)).toBe(true);
    expect(initialReportDirectoryCollapsed("0", true)).toBe(false);
    expect(initialReportDirectoryCollapsed("unexpected", true)).toBe(false);
  });
});

function makePreparation(
  identityStatus: "ready" | "needs_input",
  summary = "还有 2 项最低信息需要填写。",
): ReportPreparationProjection {
  return {
    contract: "sustainability_desk.report_preparation.v1",
    report_id: "9ca1a5db-38f8-4748-9b5f-c021dcdf97b7",
    report_state_seq: 3,
    generation_eligible: identityStatus === "ready",
    generation_blockers: [],
    areas: [
      {
        id: "report_identity",
        title: "企业及报告基本信息",
        href: "/intake/info",
        required_for_generation: true,
        status: identityStatus,
        summary: identityStatus === "ready" ? "最低生成信息已填写。" : summary,
        action_label: identityStatus === "ready" ? "查看或修改" : "填写基本信息",
      },
    ],
    report_update_available: false,
    workbench_enabled: true,
  };
}

describe("reportSectionsGate", () => {
  const emptyFields = { company: "", reportingYear: "" };

  it("follows the server identity verdict even when reporting_year is empty", () => {
    // 缺陷实证场景：准备度判定最低生成信息已填写，目录不得再因 reporting_year 缺失整树隐藏。
    expect(reportSectionsGate(makePreparation("ready"), emptyFields, zhHans)).toEqual({
      visible: true,
    });
  });

  it("hides sections with server-worded guidance when identity needs input", () => {
    const gate = reportSectionsGate(
      makePreparation("needs_input"),
      {
        company: "示例",
        reportingYear: "2025",
      },
      zhHans,
    );
    expect(gate).toEqual({
      visible: false,
      guidance: {
        message: "还有 2 项最低信息需要填写。",
        href: "/intake/info",
        actionLabel: "填写基本信息",
      },
    });
  });

  it("falls back to filled fields when the projection is absent", () => {
    expect(
      reportSectionsGate(null, { company: "示例", reportingYear: "2025" }, zhHans),
    ).toEqual({ visible: true });
  });

  it("guides instead of silently hiding when fallback fields are incomplete", () => {
    const gate = reportSectionsGate(null, { company: "示例", reportingYear: " " }, zhHans);
    expect(gate.visible).toBe(false);
    if (!gate.visible) {
      expect(gate.guidance.href).toBe("/intake/info");
      expect(gate.guidance.message).toContain("报告章节");
    }
  });
});
