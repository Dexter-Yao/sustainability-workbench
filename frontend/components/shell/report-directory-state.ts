// ABOUTME: 报告目录折叠偏好与章节可见性判定的唯一解析边界。
// ABOUTME: 章节可见性以服务端准备投影 report_identity 域为准；投影缺席时才用已填字段临时判定，且不可见时必须给出引导入口而非静默隐藏。
import type { Dictionary } from "@/lib/i18n/dictionary";
import type { ReportPreparationProjection } from "@/lib/report-api.generated";

export function initialReportDirectoryCollapsed(
  storedPreference: string | null,
  compactViewport: boolean,
): boolean {
  if (storedPreference === null) return compactViewport;
  return storedPreference === "1";
}

export type ReportSectionsGate =
  | { visible: true }
  | {
      visible: false;
      guidance: { message: string; href: string; actionLabel: string };
    };

// 投影缺席时的兜底引导随界面语言变化，故按 t 派生；href 是路由，任何语言下都不变。
function fallbackGuidance(t: Dictionary): { message: string; href: string; actionLabel: string } {
  return {
    message: t.reportDirectoryGate.fallbackMessage,
    href: "/intake/info",
    actionLabel: t.reportDirectoryGate.fallbackAction,
  };
}

/** 章节树可见性与服务端准备中心同源：report_identity 域 ready 才展示章节。 */
export function reportSectionsGate(
  preparation: ReportPreparationProjection | null,
  fallbackFields: { company: string; reportingYear: string },
  t: Dictionary,
): ReportSectionsGate {
  const identity = preparation?.areas.find((area) => area.id === "report_identity");
  if (identity) {
    if (identity.status === "ready") return { visible: true };
    return {
      visible: false,
      guidance: {
        message: identity.summary,
        href: identity.href,
        actionLabel: identity.action_label,
      },
    };
  }
  if (fallbackFields.company.trim() && fallbackFields.reportingYear.trim()) {
    return { visible: true };
  }
  return { visible: false, guidance: fallbackGuidance(t) };
}
