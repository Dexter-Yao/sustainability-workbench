// ABOUTME: 运行态 Report 恢复边界——以当前模板和已存用户状态重新装配动态章节，不把结构存进快照。
// ABOUTME: 已登录报告携带其钉住的契约版本；版本不一致由服务端 fail-closed，绝不静默升级或迁移。
import { plan } from "./api";
import { applyStoredStateToTemplate, type StoredReportStateV4 } from "./stored-report-state";
import type { Report } from "./schema";

/**
 * 从模板、用户状态和 Planner 构造 Runtime Report。
 *
 * 初次投影让 Planner 读取用户事实和评分；二次投影将动态议题块的正文、表格和答案按稳定 key 写回。
 */
export async function restoreRuntimeReport(
  template: Report,
  state: StoredReportStateV4,
  expectedContractVersion?: string,
  reportId?: string,
): Promise<Report> {
  const reportWithFacts = applyStoredStateToTemplate(template, state);
  const planned = reportId
    ? await plan(reportWithFacts, expectedContractVersion, reportId)
    : await plan(reportWithFacts, expectedContractVersion);
  const restored = applyStoredStateToTemplate(planned.report, state);
  return {
    ...restored,
    stakeholderEngagement: planned.report.stakeholderEngagement ?? restored.stakeholderEngagement ?? null,
  };
}
