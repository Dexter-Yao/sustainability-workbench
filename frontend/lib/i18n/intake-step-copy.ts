// ABOUTME: 步骤名的取词投影：把 IntakeStepKey 换成当前界面语言的长／短标签。
// ABOUTME(en): Projects an IntakeStepKey to its long/short label in the active UI locale.
// ABOUTME: 步骤的稳定事实（href、key、遥测屏标签）归 lib/intake-steps，本模块只做文案投影。
import type { IntakeStepKey } from "../intake-steps";
import type { Dictionary } from "./dictionary";

/** 页面 h1 与左栏一级条目用的长标签。 */
export function stepLabel(t: Dictionary, key: IntakeStepKey): string {
  return t.intakeSteps[key].label;
}

/** 步骤条与「上一步／下一步」用的短标签。 */
export function stepShortLabel(t: Dictionary, key: IntakeStepKey): string {
  return t.intakeSteps[key].short;
}

/** 报告级导航条目的可见标签。 */
export function reportNavigationLabel(
  t: Dictionary,
  id: "all-reports" | "current-report-delivery",
): string {
  return id === "all-reports" ? t.shell.allReports : t.shell.currentReportDelivery;
}
