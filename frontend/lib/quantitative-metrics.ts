// ABOUTME: ESG 定量信息收集的 Report 写回逻辑：页面采集元数据，正式附录表只保留对外 KPI 行。
// ABOUTME: 不新增 AppendixPackage 顶层契约；复用现有 GsTable 表格导出与诊断机制。

import type {
  GsTableRow,
  QuantitativeMetricDraft,
  QuantitativeMetricsVocabulary,
  Report,
} from "./schema";
import { finalizeDecimalDraft, isFieldValueAllowed } from "./input-validation";
import { updateBlockTable } from "./report-mutations";
import type { QuantitativeMetricDef } from "./report-api.generated";

export const APPENDIX_METRICS_BLOCK_ID = "appendix.esg_key_performance_metrics";

export function standaloneMetricLabel(metric: QuantitativeMetricDef): string {
  return metric.standaloneLabel?.trim() || metric.metricLabel;
}

/** 该指标是否由目录声明的其他指标求和得出；派生关系来自目录，前端不硬编码任何 key。 */
export function isDerivedSumMetric(metric: QuantitativeMetricDef): boolean {
  return (metric.sumOfMetricKeys?.length ?? 0) > 0;
}

/** 按小数位对齐做整数求和，避免 0.1+0.2 这类二进制浮点误差进入报告数字。
 *
 * 全程 BigInt 定点运算、小数点靠字符串拼回：先前用 `String(total / factor)` 收尾，
 * 结果 < 1e-6 时 JS 产出科学计数法（0.0000001+0.0000002 → "3e-7"），而服务端
 * QuantitativeMetricDraft.value 只接受纯十进制，整批自动保存被 422 拒收；小数位过多时
 * `10 ** places` 还会溢出成 Infinity 而产出 "NaN"。派生值不经 finalizeDecimalDraft 复核，
 * 这里是它进入载荷前的唯一收敛点。 */
function addDecimalStrings(values: string[]): string {
  const places = Math.max(...values.map((value) => (value.split(".")[1] ?? "").length));
  const zero = BigInt(0);
  const total = values.reduce((sum, value) => {
    const negative = value.startsWith("-");
    const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
    const scaled = BigInt(`${whole}${fraction.padEnd(places, "0")}`);
    return sum + (negative ? -scaled : scaled);
  }, zero);
  if (places === 0) return String(total);
  const negative = total < zero;
  const digits = (negative ? -total : total).toString().padStart(places + 1, "0");
  const fraction = digits.slice(-places).replace(/0+$/, "");
  return `${negative ? "-" : ""}${digits.slice(0, -places)}${fraction ? `.${fraction}` : ""}`;
}

/** 求和来源全部填写时得出派生值；任一缺失或非数值则返回 null——不产出残缺的和。
 *
 * 返回 null 时调用方应保留该指标为空，由用户按无值原因说明，而不是显示一个
 * 只累加了部分来源的数字。 */
export function derivedSumValue(
  metric: QuantitativeMetricDef,
  drafts: Record<string, QuantitativeMetricDraft>,
): string | null {
  const sources = metric.sumOfMetricKeys ?? [];
  if (sources.length === 0) return null;
  const values: string[] = [];
  for (const key of sources) {
    const raw = finalizeDecimalDraft(String(drafts[key]?.value ?? ""));
    if (raw === "") return null;
    values.push(raw);
  }
  return addDecimalStrings(values);
}

/**
 * 温室气体核算标准的「其他」哨兵。
 *
 * 该词是合同数据而非代码常量（schema 的 QuantitativeMetricsVocabulary 注释）：它必须与
 * 包内选项清单同语言，写死「其他」会让英文包（otherStandardLabel 为 "Other"）永远比不中，
 * 「其他」分支的补充输入框因此恒不启用。
 */
export function greenhouseGasOtherStandardLabel(report: Report): string {
  return report.quantitativeMetricsVocabulary?.otherStandardLabel ?? "";
}

export interface QuantitativeMetricMeta {
  metrics: Record<string, QuantitativeMetricDraft>;
  greenhouseGasAccountingStandard?: string;
  greenhouseGasAccountingStandardOther?: string;
}

type ReportMeta = NonNullable<Report["meta"]> & {
  quantitativeMetrics?: QuantitativeMetricMeta;
};

function quantitativeMeta(report: Report): QuantitativeMetricMeta {
  const meta = report.meta as ReportMeta | null | undefined;
  return { metrics: {}, ...(meta?.quantitativeMetrics ?? {}) };
}

function metricDraft(report: Report, key: string): QuantitativeMetricDraft {
  return quantitativeMeta(report).metrics[key] ?? {};
}

export function getMetricDraft(report: Report, key: string): QuantitativeMetricDraft {
  return metricDraft(report, key);
}

export function hasQuantitativeMetricValue(report: Report, key: string): boolean {
  return String(metricDraft(report, key).value ?? "").trim() !== "";
}

export function getGreenhouseGasAccountingStandard(report: Report): string {
  return quantitativeMeta(report).greenhouseGasAccountingStandard ?? "";
}

export function getGreenhouseGasAccountingStandardOther(report: Report): string {
  return quantitativeMeta(report).greenhouseGasAccountingStandardOther ?? "";
}

function metricPath(metric: QuantitativeMetricDef): string {
  return [metric.category, ...metric.groupPath].filter(Boolean).join(" / ");
}

/**
 * 备注列文本。措辞模板与分隔符都是包资产（`quantitativeMetricsVocabulary`）：
 * 英文包的模板是 "Accounting standard: {standard}"、分隔符是 "; "，写死中文会让英文
 * 交付物的备注列出现中文标签与全角分号。
 */
function metricRemark(
  metric: QuantitativeMetricDef,
  draft: QuantitativeMetricDraft,
  meta: QuantitativeMetricMeta,
  vocabulary: QuantitativeMetricsVocabulary | null,
): string {
  const parts: string[] = [];
  const standard = meta.greenhouseGasAccountingStandard === (vocabulary?.otherStandardLabel ?? "")
    ? meta.greenhouseGasAccountingStandardOther
    : meta.greenhouseGasAccountingStandard;
  if (metric.requiresGreenhouseGasAccountingStandard && standard) {
    const template = vocabulary?.accountingStandardRemarkTemplate ?? "核算标准：{standard}";
    parts.push(template.replace("{standard}", standard));
  }
  if (draft.note?.trim()) parts.push(draft.note.trim());
  return parts.join(vocabulary?.remarkSeparator ?? "；");
}

function rowForMetric(
  metric: QuantitativeMetricDef,
  draft: QuantitativeMetricDraft,
  meta: QuantitativeMetricMeta,
  vocabulary: QuantitativeMetricsVocabulary | null,
): GsTableRow {
  return {
    type: "tr",
    headerRow: false,
    state: "ready",
    children: [
      { type: "td", colKey: "category", value: metricPath(metric) },
      { type: "td", colKey: "metric", value: metric.metricLabel },
      { type: "td", colKey: "unit", value: metric.unit },
      { type: "td", colKey: "value", value: draft.value ?? "" },
      { type: "td", colKey: "remark", value: metricRemark(metric, draft, meta, vocabulary) },
    ],
  };
}

function withRows(report: Report, visibleMetrics: QuantitativeMetricDef[], meta: QuantitativeMetricMeta): Report {
  const vocabulary = report.quantitativeMetricsVocabulary ?? null;
  return updateBlockTable(report, APPENDIX_METRICS_BLOCK_ID, (table) => {
    const headerRows = (table.children ?? []).filter((row) => row.headerRow);
    const rows = visibleMetrics
      .filter((metric) => String(meta.metrics[metric.key]?.value ?? "").trim() !== "")
      .map((metric) => rowForMetric(metric, meta.metrics[metric.key] ?? {}, meta, vocabulary));
    return { ...table, children: [...headerRows, ...rows] };
  });
}

function withQuantitativeMeta(report: Report, nextQuant: QuantitativeMetricMeta): Report {
  return {
    ...report,
    meta: {
      ...((report.meta ?? {}) as Record<string, unknown>),
      quantitativeMetrics: nextQuant,
    },
  };
}

export function projectQuantitativeMetricRows(report: Report, visibleMetrics: QuantitativeMetricDef[]): Report {
  return withRows(report, visibleMetrics, quantitativeMeta(report));
}

export function updateQuantitativeMetricDraft(
  report: Report,
  metric: QuantitativeMetricDef,
  patch: QuantitativeMetricDraft,
  visibleMetrics: QuantitativeMetricDef[],
): Report {
  if (
    patch.value !== undefined
    && patch.value !== null
    && !isFieldValueAllowed("number", patch.value)
  ) return report;
  const current = quantitativeMeta(report);
  const draft = { ...(current.metrics[metric.key] ?? {}), ...patch };
  const metrics = { ...current.metrics };
  if (Object.values(draft).some((value) => String(value ?? "").trim() !== "")) {
    metrics[metric.key] = draft;
  } else {
    delete metrics[metric.key];
  }
  const next = withQuantitativeMeta(report, { ...current, metrics });
  return withRows(next, visibleMetrics, { ...current, metrics });
}

export function updateGreenhouseGasAccountingStandard(
  report: Report,
  value: string,
  visibleMetrics: QuantitativeMetricDef[],
): Report {
  const current = quantitativeMeta(report);
  const nextQuant = { ...current, greenhouseGasAccountingStandard: value };
  const next = withQuantitativeMeta(report, nextQuant);
  return withRows(next, visibleMetrics, nextQuant);
}

export function updateGreenhouseGasAccountingStandardOther(
  report: Report,
  value: string,
  visibleMetrics: QuantitativeMetricDef[],
): Report {
  const current = quantitativeMeta(report);
  const nextQuant = { ...current, greenhouseGasAccountingStandardOther: value };
  const next = withQuantitativeMeta(report, nextQuant);
  return withRows(next, visibleMetrics, nextQuant);
}
