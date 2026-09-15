// ABOUTME: 资料处理状态文案唯一映射（design.md §7.1 / README §9.2）：全线用「处理」不用「理解」。
// ABOUTME: 资料清单页与生成区共用本表，不各自维护副本。

import type {
  ReportFileAnalysisProjection,
  ReportFileImageAnalysisProjection,
} from "@/lib/material-workspace.generated";
import type { Dictionary } from "@/lib/i18n/dictionary";

/** 状态是 typed 枚举，措辞随界面语言；判定始终依据枚举值，不匹配文案。 */
export function fileAnalysisLabel(
  status: ReportFileAnalysisProjection["status"],
  t: Dictionary,
): string {
  const labels: Record<ReportFileAnalysisProjection["status"], string> = {
    queued: t.fileAnalysis.queued,
    running: t.fileAnalysis.running,
    succeeded: t.fileAnalysis.succeeded,
    needs_attention: t.fileAnalysis.needsAttention,
    failed: t.fileAnalysis.failed,
    superseded: t.fileAnalysis.superseded,
  };
  return labels[status];
}

export function imageAnalysisLabel(
  status: ReportFileImageAnalysisProjection["status"],
  t: Dictionary,
): string {
  const labels: Record<ReportFileImageAnalysisProjection["status"], string> = {
    queued: t.fileAnalysis.queued,
    running: t.fileAnalysis.running,
    succeeded: t.fileAnalysis.imageSucceeded,
    failed: t.fileAnalysis.failed,
    superseded: t.fileAnalysis.superseded,
  };
  return labels[status];
}
