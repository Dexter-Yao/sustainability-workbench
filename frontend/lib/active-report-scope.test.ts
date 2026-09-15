// ABOUTME: 当前报告 scope 前端投影测试，锁定 Report capability 是已打开报告的唯一范围来源。
// ABOUTME: capability 缺失必须 fail-closed，账户 Grant 不能作为范围后备。
import { describe, expect, it } from "vitest";

import { activeReportScope } from "./active-report-scope";
import type { ReportCapabilitiesResponse } from "./report-api.generated";

function capabilities(
  overrides: Partial<ReportCapabilitiesResponse> = {},
): ReportCapabilitiesResponse {
  return {
    allowed_report_section_ids: ["climate_change", "water_resource_management"],
    section_regeneration_limit: 0,
    can_generate: true,
    can_regenerate_sections: true,
    can_export_word: true,
    material_agent_enabled: true,
    collects_materiality_assessment: true,
    allowed_quantitative_metric_keys: ["climate.scope_1"],
    allowed_report_artifact_kinds: ["word", "review"],
    ...overrides,
  };
}

describe("active report scope", () => {
  it("在当前报告 capability 未到达时 fail-closed", () => {
    const loading = activeReportScope(null);
    expect(loading).toMatchObject({
      status: "loading",
      canGenerate: false,
      canExportWord: false,
      materialAgentEnabled: false,
      collectsMaterialityAssessment: false,
      allowedReportSectionIds: [],
    });
  });

  it("只投影服务端声明的章节、指标与交付物种类", () => {
    expect(activeReportScope(capabilities())).toMatchObject({
      status: "ready",
      allowedReportSectionIds: ["climate_change", "water_resource_management"],
      allowedMetricKeys: ["climate.scope_1"],
      allowedArtifactKinds: ["word", "review"],
      collectsMaterialityAssessment: true,
    });
  });
});
