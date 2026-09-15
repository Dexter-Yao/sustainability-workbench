// ABOUTME: 「能否新建报告」的单一判定：空列表态与有数据态共用同一结论与同一文案。
// ABOUTME: 名额口径按活跃报告数与账户上限比较；判定分散写两遍必然漂移，本模块不接受第二处实现。
import { interpolate, type Dictionary } from "./i18n/dictionary";

export interface ReportCreateAvailabilityInput {
  /** 正在创建中。 */
  creating: boolean;
  /** 账户能力尚未到达。 */
  accountLoading: boolean;
  /** 当前活跃报告数。 */
  activeReportCount: number;
  /** 该范围的活跃报告上限；null 表示不设上限。 */
  activeReportLimit: number | null;
  /** 账户能力投影中的创建许可；未到达时为 undefined。 */
  canCreateReport: boolean | undefined;
}

export interface ReportCreateAvailability {
  disabled: boolean;
  /** 禁用原因；始终给出可行动的说明，不留空按钮。 */
  reason: string;
}

/**
 * 判定「新建报告」按钮的可用性与禁用原因。
 *
 * 名额已满必须在这里被判出来：若空列表态的按钮漏掉名额判定，而 atLimit 由**可见**
 * 列表算出——服务端已有一份未能打开的报告时列表仍显示为空，按钮永远可点、永远 403，
 * 用户看不到那份报告因而无从删除。
 */
export function reportCreateAvailability(
  input: ReportCreateAvailabilityInput,
  t: Dictionary,
): ReportCreateAvailability {
  const atLimit =
    input.activeReportLimit !== null && input.activeReportCount >= input.activeReportLimit;

  if (input.creating) return { disabled: true, reason: t.createReport.creating };
  if (input.accountLoading) return { disabled: true, reason: t.reportList.accountLoading };
  if (atLimit) {
    return {
      disabled: true,
      reason: interpolate(t.reportList.createBlockedAtLimit, {
        count: input.activeReportCount,
        limit: input.activeReportLimit ?? 0,
      }),
    };
  }
  if (input.canCreateReport !== true) {
    return { disabled: true, reason: t.reportList.createBlockedNoPermission };
  }
  return { disabled: false, reason: "" };
}
