// ABOUTME: 用户可见准则批注派生逻辑，来源为附录索引表条款原文。
// ABOUTME: 本模块不读取内部 Prompt 披露要求库，避免用户可见准则与生成约束混用。

import type { UserVisibleDisclosureClauseAnnotationEntry } from "./api";
import type { Report } from "./schema";

export function activeMainlandStandard(report: Report): string {
  return report.disclosureProfile?.mainlandStandard ?? "sse";
}

export function findUserVisibleDisclosureClauseAnnotationEntry(
  entries: UserVisibleDisclosureClauseAnnotationEntry[] | null | undefined,
  report: Report,
  options: { reportSectionKey?: string | null },
): UserVisibleDisclosureClauseAnnotationEntry | null {
  const mainlandStandard = activeMainlandStandard(report);
  return (
    (entries ?? []).find((entry) => {
      if (entry.mainlandStandard !== mainlandStandard) return false;
      if (options.reportSectionKey && entry.reportSectionKey === options.reportSectionKey) return true;
      return false;
    }) ?? null
  );
}
