// ABOUTME: 条件可见性求值，镜像后端 docx_renderer 的 appears_when 语义；fail-closed——未知 path/op 视为不满足并记 issue。
// ABOUTME: 解析 fields/intakeItems(已作答=exists)/disclosureProfile/appendixPackage/assessment(counts 与 topics.materiality) + blocks.state；报告章节产生由规划层决定，此处不做 ID 门控。

import type { Block, Condition, ConditionRule, Field, Report, Section } from "./schema";
import { resolveReportRef } from "./report-values";

/** fail-closed 判定记录：哪条规则因无法解析或未知 op 被判为不满足（供 UI 提示"等待 X 完成"等）。 */
export interface VisibilityIssue {
  nodeKey?: string;
  path?: string;
  op?: string;
  reason: string;
}

type Resolved = { ok: true; value: unknown } | { ok: false };

function findBlock(report: Report, id: string): Block | null {
  const walk = (secs?: Section[] | null): Block | null => {
    for (const s of secs ?? []) {
      for (const b of s.blocks ?? []) if (b.id === id) return b;
      const child = walk(s.children);
      if (child) return child;
    }
    return null;
  };
  return walk(report.sections);
}

export function intakeExistsKeysFromCondition(condition: Condition | null | undefined): string[] {
  return [...(condition?.all ?? []), ...(condition?.any ?? [])]
    .filter((rule) => rule.op === "exists" && rule.path.startsWith("intakeItems."))
    .map((rule) => rule.path.slice("intakeItems.".length));
}

export const materialExistsKeysFromCondition = intakeExistsKeysFromCondition;

function resolvePath(path: string, report: Report): Resolved {
  if (path.startsWith("fields.") && path.endsWith(".value")) {
    const key = path.slice("fields.".length, -".value".length);
    return { ok: true, value: report.fields[key]?.value ?? null };
  }
  if (path.startsWith("intakeItems.")) {
    const key = path.slice("intakeItems.".length);
    const item = report.intakeItems?.find((i) => i.key === key);
    let ans: unknown = item?.answer ?? null;
    if (typeof ans === "string") ans = ans.trim() === "" ? null : ans;
    else if (Array.isArray(ans)) ans = ans.length === 0 ? null : ans;
    const sup = typeof item?.supplement === "string" && item.supplement.trim() !== "" ? item.supplement : null;
    return { ok: true, value: ans ?? sup }; // 已作答=exists（答案或补充非空；空串/空数组视为未作答）
  }
  if (path.startsWith("quantitativeMetrics.")) {
    const key = path.slice("quantitativeMetrics.".length);
    const value = report.meta?.quantitativeMetrics?.metrics?.[key]?.value;
    return { ok: true, value: typeof value === "string" ? value.trim() || null : value ?? null };
  }
  if (path.startsWith("disclosureProfile.") || path.startsWith("appendixPackage.")) {
    return { ok: true, value: resolveReportRef(path, report) };
  }
  if (path === "meta.materialityStrategy") {
    // 与后端 visibility.resolve_path 同口径：议题重要性策略是报告级事实。
    return { ok: true, value: report.meta?.materialityStrategy ?? null };
  }
  if (path.startsWith("assessment.counts.")) {
    // 与后端 visibility.assessment_counts 同口径现算（含 impact/financial/non 三个别名）。
    // 缺此分支时 assessment.counts.* 落 fail-closed：sm.iro_intro 与 sm.iro_table 服务端可见、
    // 工作台却整块隐藏。
    const alias: Record<string, string> = {
      impact: "impact_only",
      financial: "financial_only",
      non: "non_material",
    };
    const raw = path.slice("assessment.counts.".length);
    const key = alias[raw] ?? raw;
    const topics = report.assessment?.topics ?? [];
    const counts: Record<string, number> = {
      dual: topics.filter((t) => t.materiality === "dual").length,
      impact_only: topics.filter((t) => t.materiality === "impact").length,
      financial_only: topics.filter((t) => t.materiality === "financial").length,
      non_material: topics.filter((t) => t.materiality === "non").length,
      total: topics.length,
    };
    if (!(key in counts)) return { ok: false };
    return { ok: true, value: counts[key] };
  }
  if (path.startsWith("assessment.topics.") && path.endsWith(".materiality")) {
    const id = path.slice("assessment.topics.".length, -".materiality".length);
    const topic = report.assessment?.topics?.find((t) => t.assessmentTopicId === id);
    return { ok: true, value: topic?.materiality ?? null };
  }
  if (path.startsWith("blocks.") && path.endsWith(".state")) {
    const id = path.slice("blocks.".length, -".state".length);
    return { ok: true, value: findBlock(report, id)?.state ?? null };
  }
  return { ok: false };
}

function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === "" || v === false;
}

function evalRule(rule: ConditionRule, report: Report, issues?: VisibilityIssue[]): boolean {
  const resolved = resolvePath(rule.path, report);
  if (!resolved.ok) {
    issues?.push({ path: rule.path, op: rule.op, reason: "无法解析的 path（fail-closed）" });
    return false;
  }
  const v = resolved.value;
  switch (rule.op) {
    case "exists":
      return !isEmpty(v);
    case "not_exists":
      return isEmpty(v);
    case "eq":
      return v === rule.value;
    case "ne":
      return v !== rule.value;
    case "gt":
      return typeof v === "number" && typeof rule.value === "number" && v > rule.value;
    case "in":
      if (!Array.isArray(rule.value)) return false;
      if (Array.isArray(v)) return v.some((entry) => (rule.value as unknown[]).includes(entry));
      return (rule.value as unknown[]).includes(v);
    case "contains_any": {
      if (!Array.isArray(rule.value)) return false;
      const haystack = Array.isArray(v) ? v.map((entry) => String(entry)).join("、") : String(v ?? "");
      return (rule.value as unknown[]).some((needle) => {
        const text = String(needle).trim();
        return text.length > 0 && haystack.includes(text);
      });
    }
    default:
      issues?.push({ path: rule.path, op: rule.op, reason: "未知 op（fail-closed）" });
      return false;
  }
}

export function isVisible(node: Block | Field | Section, report: Report, issues?: VisibilityIssue[]): boolean {
  // section 级议题门控退化：议题章节是否产生由规划层（planner）构建期决定；此处只求 appears_when（块/行级）。
  const cond = node.appears_when as Condition | null | undefined;
  if (!cond) return true;
  if (cond.all) return cond.all.every((r) => evalRule(r, report, issues));
  if (cond.any) return cond.any.some((r) => evalRule(r, report, issues));
  return true;
}
