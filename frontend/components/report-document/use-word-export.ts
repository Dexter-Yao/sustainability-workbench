// ABOUTME: 报告正文页的 Word 导出编排：先跑服务端确定性诊断并开「导出前检查」，人工确认后才导出并下载。
// ABOUTME: 诊断与导出闸同源（服务端同一组合根）；422 阻断项回填到抽屉，错误以页内 role=alert 文案呈现。
// ABOUTME(en): Word export flow for the document page: server diagnostics gate the checks drawer, export only after confirmation.
// ABOUTME(en): Diagnostics and the export gate share one composition root; blocking issues flow back into the drawer.
"use client";

import { useCallback, useState } from "react";

import { API_BASE, diagnose, exportReport, type Issue } from "@/lib/api";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import type { Report } from "@/lib/schema";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function useWordExport({ report, reportId }: { report: Report; reportId: string | null }) {
  const t = useT();
  const [checkIssues, setCheckIssues] = useState<Issue[] | null>(null);
  const [exporting, setExporting] = useState(false);
  const [alert, setAlert] = useState<string | null>(null);

  const openChecks = useCallback(async () => {
    if (!reportId) return;
    try {
      const diagnostics = await diagnose(reportId, report);
      setCheckIssues(diagnostics.issues);
    } catch (error) {
      // 上游异常消息不进用户文案：它随实现变化且可能携带路径与标识符（CLAUDE.md 用户可见文本边界）。
      console.error("Pre-export diagnosis failed", { apiBase: API_BASE, error });
      setAlert(interpolate(t.wordExport.checksFailed, { reason: t.wordExport.retryLater }));
    }
  }, [report, reportId, t]);

  const confirmExport = useCallback(async () => {
    if (!reportId) return;
    setExporting(true);
    try {
      downloadBlob(await exportReport(report, reportId), "report.docx");
      setCheckIssues(null);
    } catch (error) {
      const blocked = (error as { issues?: Issue[] }).issues;
      if (blocked) {
        setCheckIssues(blocked);
      } else {
        console.error("Word export failed", { apiBase: API_BASE, error });
        setAlert(interpolate(t.wordExport.exportFailed, { reason: t.wordExport.retryLater }));
      }
    } finally {
      setExporting(false);
    }
  }, [report, reportId, t]);

  return {
    checkIssues,
    exporting,
    alert,
    openChecks,
    confirmExport,
    closeChecks: () => setCheckIssues(null),
    dismissAlert: () => setAlert(null),
  };
}
