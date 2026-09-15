// ABOUTME: 从当前 ReportStateResponse.capabilities 投影浏览器可见的报告范围。
// ABOUTME: 已打开报告绝不回退到账户 Grant；capability 未到达时页面只能加载或禁用，不能猜测完整范围。
import type { ReportCapabilitiesResponse } from "./report-api.generated";

export type ActiveReportScope =
  | {
      status: "loading";
      collectsMaterialityAssessment: false;
      allowedReportSectionIds: readonly string[];
      allowedMetricKeys: readonly string[];
      canGenerate: false;
      canRegenerateSections: false;
      canExportWord: false;
      materialAgentEnabled: false;
      allowedArtifactKinds: readonly ("word" | "review")[];
    }
  | {
      status: "ready";
      /** 评分页、模板下载导入与矩阵预览是否开放；与评分是否进入交付物无关。 */
      collectsMaterialityAssessment: boolean;
      allowedReportSectionIds: readonly string[];
      allowedMetricKeys: readonly string[];
      canGenerate: boolean;
      canRegenerateSections: boolean;
      canExportWord: boolean;
      materialAgentEnabled: boolean;
      allowedArtifactKinds: readonly ("word" | "review")[];
    };

const LOADING_SCOPE: ActiveReportScope = {
  status: "loading",
  collectsMaterialityAssessment: false,
  allowedReportSectionIds: [],
  allowedMetricKeys: [],
  canGenerate: false,
  canRegenerateSections: false,
  canExportWord: false,
  materialAgentEnabled: false,
  allowedArtifactKinds: [],
};

/** 只消费当前报告的服务端 capability；不得将账户快照作为后备权限来源。 */
export function activeReportScope(
  capabilities: ReportCapabilitiesResponse | null,
): ActiveReportScope {
  if (!capabilities) return LOADING_SCOPE;
  return {
    status: "ready",
    collectsMaterialityAssessment: capabilities.collects_materiality_assessment,
    allowedReportSectionIds: capabilities.allowed_report_section_ids,
    allowedMetricKeys: capabilities.allowed_quantitative_metric_keys,
    canGenerate: capabilities.can_generate,
    canRegenerateSections: capabilities.can_regenerate_sections,
    canExportWord: capabilities.can_export_word,
    materialAgentEnabled: capabilities.material_agent_enabled,
    allowedArtifactKinds: capabilities.allowed_report_artifact_kinds,
  };
}
