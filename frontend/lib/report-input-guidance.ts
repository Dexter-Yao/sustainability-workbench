// ABOUTME: 报告模板的输入体验投影：按 SSOT 说明路径读取用户释义，并在新建报告时解析默认规则。
// ABOUTME: 该模块不持久化模板配置、不改写已有用户值，也不包含 Agent 或生成语义。
import type { Report } from "./schema";

type InputGuidance = NonNullable<Report["inputGuidance"]>[string];

export function inputGuidanceAt(report: Report, path: string): InputGuidance | null {
  return report.inputGuidance?.[path] ?? null;
}

function defaultReportingYear(now: Date): string {
  return String(now.getFullYear() - 1);
}

function reportYear(fields: Report["fields"]): string | null {
  const value = String(fields.reporting_year?.value ?? "").trim();
  return /^\d{4}$/.test(value) ? value : null;
}

function defaultValue(rule: InputGuidance["defaultRule"], fields: Report["fields"], now: Date): string | null {
  if (rule === "previous_calendar_year") return defaultReportingYear(now);
  const year = reportYear(fields);
  if (!year) return null;
  if (rule === "reporting_year_start") return `${year}-01-01`;
  if (rule === "reporting_year_end") return `${year}-12-31`;
  return null;
}

function fieldKeyFromPath(path: string): string | null {
  const match = /^fields\.([A-Za-z0-9_]+)\.value$/.exec(path);
  return match?.[1] ?? null;
}

function applyFieldDefault(
  fields: Report["fields"],
  fieldKey: string,
  guidance: InputGuidance,
  now: Date,
): Report["fields"] {
  const field = fields[fieldKey];
  if (!field || (field.value !== null && field.value !== undefined) || !guidance.defaultRule) return fields;
  const value = defaultValue(guidance.defaultRule, fields, now);
  return value === null ? fields : { ...fields, [fieldKey]: { ...field, value } };
}

/**
 * 用户填入报告年份后，为仍然为空的报告期起止补上该年度默认值。
 *
 * 只填空、不覆盖：用户手工填过（含主动清空为 ""）的日期一律保持不变，
 * 非整年报告期不会被改回 1/1–12/31。默认值仍由合同的 defaultRule 派生，
 * 本函数不自带年份算法。
 */
export function withReportPeriodDefaults(
  report: Report,
  changedFieldKey: string,
): Report {
  if (changedFieldKey !== "reporting_year") return report;
  let fields = report.fields;
  for (const [path, guidance] of Object.entries(report.inputGuidance ?? {})) {
    const fieldKey = fieldKeyFromPath(path);
    if (
      fieldKey !== "report_period_start"
      && fieldKey !== "report_period_end"
    ) {
      continue;
    }
    fields = applyFieldDefault(fields, fieldKey, guidance, new Date());
  }
  return fields === report.fields ? report : { ...report, fields };
}

/** 仅用于新建报告或无本地快照时；已有用户值（包括主动清空后的空字符串）保持不变。 */
export function applyReportInputDefaults(template: Report, now: Date = new Date()): Report {
  let fields = { ...template.fields };
  const guidanceEntries = Object.entries(template.inputGuidance ?? {});
  const reportingYear = guidanceEntries.find(([path]) => path === "fields.reporting_year.value");

  if (reportingYear) {
    fields = applyFieldDefault(fields, "reporting_year", reportingYear[1], now);
  }
  for (const [path, guidance] of guidanceEntries) {
    const fieldKey = fieldKeyFromPath(path);
    if (fieldKey && fieldKey !== "reporting_year") fields = applyFieldDefault(fields, fieldKey, guidance, now);
  }
  return { ...template, fields };
}
