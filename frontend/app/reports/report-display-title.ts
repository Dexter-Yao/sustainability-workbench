// ABOUTME: 报告列表显示名派生——「可持续发展报告 · {报告主体名称}」；主体名称是报告存在的前提，
// ABOUTME: 无主体名称的草稿回落到「可持续发展报告草稿 · 创建日」。真实标题始终最优先。
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { formatDate } from "@/lib/i18n/format";
import type { UiLocale } from "@/lib/i18n/locale";
import type { ReportSummary } from "@/lib/report-store";

/**
 * 后端建报时的默认标题（`api/reports_router.py` 的 CreateReportRequest.title 默认值）。
 *
 * 这是**跨端字面量耦合**：后端改掉该默认文案，本判断即静默失效，报告会显示成
 * 「未命名报告」而不是派生出的显示名。正解是后端 title 默认改 None、前端判 null，
 * 那是公开 API 变更，已登记待办。此处保留镜像并写明，不因界面国际化顺手改契约。
 * 它不随界面语言变化——它比对的是后端存下的值，不是给用户看的文案。
 */
const BACKEND_DEFAULT_TITLE = "未命名报告";

export function reportDisplayTitle(
  report: ReportSummary,
  t: Dictionary,
  locale: UiLocale,
): string {
  if (report.title && report.title !== BACKEND_DEFAULT_TITLE) return report.title;
  const company = (report.company_registered_name ?? "").trim();
  if (company) return interpolate(t.reportList.titleWithCompany, { company });
  return interpolate(t.reportList.titleDraft, {
    date: formatDate(report.created_at, locale),
  });
}
