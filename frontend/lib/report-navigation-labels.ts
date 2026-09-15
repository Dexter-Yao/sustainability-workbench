// ABOUTME: 报告级导航条目与页面标题唯一事实源：编制页左栏报告组、工作台目录、
// ABOUTME: 生成交付页面包屑与页标题同源于此；标签、说明与去向不得在消费侧双写。

export interface ReportNavigationEntry {
  id: "current-report-delivery" | "all-reports";
  href: string;
}

/**
 * 展示顺序即数组顺序：先账户全部报告，后当前报告的交付物——从大范围到当前一份，
 * 与用户的心智顺序一致。
 *
 * 不设 description：标签本身已自解释，左栏每条再挂一行说明只是噪音。
 */
export const REPORT_NAVIGATION_ENTRIES: readonly ReportNavigationEntry[] = [
  { id: "all-reports", href: "/reports" },
  { id: "current-report-delivery", href: "/reports/generation" },
];

/**
 * 生成与交付页的**遥测屏标签**（design.md §7 注册表中文名）。
 *
 * 与 data-screen-id 同级的稳定标识，屏幕上不显示；页内 h1 与面包屑等用户可见文案
 * 走字典（t.shell.reportGenerationPage），随界面语言变化。两者刻意分开：
 * 让屏标签跟着字典走，遥测标识会随用户切语言漂移。
 */
export const REPORT_GENERATION_SCREEN_LABEL = "报告生成与交付";

/** 报告正文页的遥测屏标签；用户可见文案见 t.shell.reportDocumentPage。 */
export const REPORT_DOCUMENT_SCREEN_LABEL = "报告正文";
export const REPORT_DOCUMENT_PATH = "/reports/document";

export function reportNavigationEntry(
  id: ReportNavigationEntry["id"],
): ReportNavigationEntry {
  const entry = REPORT_NAVIGATION_ENTRIES.find((candidate) => candidate.id === id);
  if (!entry) throw new Error(`unknown report navigation entry: ${id}`);
  return entry;
}
