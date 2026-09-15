// ABOUTME: 定量信息页整批提交载荷构造纯逻辑：留空项记为默认无数值原因，供自动保存与"保存全部"共用。
// ABOUTME: 独立于 page.tsx 之外，避免 Next.js 对 page 文件仅允许特定命名导出的类型约束。
import { derivedSumValue, isDerivedSumMetric } from "@/lib/quantitative-metrics";
import type { QuantitativeMetricDef } from "@/lib/report-api.generated";
import type { QuantitativeMetricDraft, QuantitativeNoValueReason } from "@/lib/schema";

export const DEFAULT_NO_VALUE_REASON: QuantitativeNoValueReason = "not_collected";

export function isAnswered(draft: QuantitativeMetricDraft | undefined): boolean {
  return String(draft?.value ?? "").trim() !== "";
}

/**
 * 整批提交载荷：catalog 内每一项都会出现，留空项记为默认无数值原因（不会被后端完整性校验拒绝）。
 * 自动保存与"保存全部"共用同一构造，保证两者提交语义一致。
 *
 * 目录声明为求和派生的指标（如温室气体排放总量＝范围一＋范围二）在此就地求得：
 * 提交出去的即是正确事实，下游读到的值与录入页所见一致，无需任何一端再算一遍。
 * 来源未填齐时派生不成立，按无值原因提交，不产出只累加了部分来源的数字。
 */
export function buildMetricsPayload(
  catalog: QuantitativeMetricDef[],
  drafts: Record<string, QuantitativeMetricDraft>,
  finalizeDecimalDraft: (value: string) => string,
): Record<string, QuantitativeMetricDraft> {
  return Object.fromEntries(catalog.map((metric) => {
    const draft = drafts[metric.key] ?? {};
    const value = isDerivedSumMetric(metric)
      ? (derivedSumValue(metric, drafts) ?? "")
      : finalizeDecimalDraft(String(draft.value ?? ""));
    return [metric.key, {
      value: value || null,
      noValueReason: value ? null : (draft.noValueReason ?? DEFAULT_NO_VALUE_REASON),
      department: String(draft.department ?? "").trim() || null,
      note: String(draft.note ?? "").trim() || null,
    }];
  }));
}
