// ABOUTME: 诊断问题行的跳转决策——把 Issue 的定位字段解析成「就地滚动候选 + 导航兜底」。
// ABOUTME: 纯函数无 DOM 依赖；报告正文页先试滚动候选，全部落空时按 fallbackHref 导航。

import type { Issue } from "@/lib/api";
import { configAnchorId } from "@/lib/config-anchors";

export interface IssueJumpPlan {
  /** 依次尝试的报告正文页内 DOM 选择器；命中即滚动定位。 */
  scrollSelectors: string[];
  /** 所有选择器落空时的导航目标；null 表示该问题无可跳转去处。 */
  fallbackHref: string | null;
}

const INTAKE_INFO_PATH_PREFIXES = ["fields.", "disclosureProfile.", "appendixPackage."];

export function resolveIssueJump(issue: Issue): IssueJumpPlan {
  const scrollSelectors = [
    issue.fieldKey ? `[data-field="${issue.fieldKey}"]` : null,
    issue.blockId ? `[data-block-id="${issue.blockId}"]` : null,
  ].filter((selector): selector is string => selector !== null);

  let fallbackHref: string | null = null;
  const path = issue.path;
  if (path && INTAKE_INFO_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    fallbackHref = `/intake/info#${configAnchorId(path)}`;
  } else if (path?.startsWith("sections.")) {
    const sectionKey = path.split(".")[1];
    fallbackHref = sectionKey ? `/reports/document#section-${sectionKey}` : null;
  }
  if (!fallbackHref && issue.actionHref) fallbackHref = issue.actionHref;
  return { scrollSelectors, fallbackHref };
}
