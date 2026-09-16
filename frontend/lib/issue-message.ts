// ABOUTME: 诊断条目的用户可见文案——按后端稳定 code 取界面语言模板，代入 Issue.params。
// ABOUTME: 后端 message 恒简体，直接渲染会让英文报告的导出前检查混排中文；本模块是唯一出口。
import type { Dictionary } from "@/lib/i18n/dictionary";
import { interpolate } from "@/lib/i18n/dictionary";
import type { Issue } from "@/lib/api";

type IssueTemplates = Dictionary["checksDrawer"]["issues"];

/**
 * 诊断条目的界面语言文案。
 *
 * 与生成阻断侧的 `blockerMessage()`（components/intake/generation-section.tsx）同一纪律：
 * 按稳定标识取词，**不透传后端串**。未登记的 code 回落通用措辞——显示后端原文会让
 * 英文界面突然冒出简体，正是本模块要消除的形态。
 *
 * `params` 里的值本身来自知识包或用户填写（议题名、字段标签、表题），天然是报告语言；
 * 只有连接它们的措辞与阶段名按界面语言取。
 */
export function issueMessage(issue: Issue, t: Dictionary): string {
  const templates = t.checksDrawer.issues;
  const params = issue.params ?? {};

  // key_residue 有带标签与不带标签两种措辞：无标签时不把内部 ref 路径给用户看。
  const key: keyof IssueTemplates | string =
    issue.code === "key_residue" && !params.label ? "key_residue_unlabeled" : issue.code;

  const template = (templates as Record<string, string | undefined>)[key];
  if (!template) return templates.fallback;

  const values: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      values[name] = value.join(t.checksDrawer.issueListSeparator);
    } else if (name === "phase") {
      // 后端传稳定 id（workbench / generation / export），阶段名按界面语言取。
      const phases = t.checksDrawer.issuePhases as Record<string, string | undefined>;
      values[name] = phases[String(value)] ?? String(value);
    } else {
      values[name] = value;
    }
  }
  return interpolate(template, values);
}
