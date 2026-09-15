// ABOUTME: 报告目录消费服务端准备投影的取数 Hook；保存后按 refreshToken 重取以跟随最新判定。
// ABOUTME: 只暴露与当前报告匹配的投影，跨报告切换不泄漏旧结果；取数失败保留同报告的已知投影。
"use client";

import { useEffect, useState } from "react";

import {
  fetchReportPreparation,
  type ReportPreparation,
} from "@/lib/material-workspace-api";

export function useReportPreparation(
  reportId: string | null,
  refreshToken: number | string | null,
): ReportPreparation | null {
  const [loaded, setLoaded] = useState<{
    reportId: string;
    preparation: ReportPreparation;
  } | null>(null);

  useEffect(() => {
    if (!reportId) return;
    let active = true;
    void fetchReportPreparation(reportId).then(
      (preparation) => {
        if (active) setLoaded({ reportId, preparation });
      },
      (error: unknown) => {
        // 本目录取不到投影时降级到字段临时判定，不阻断导航渲染。
        console.error("Report preparation load failed", error);
      },
    );
    return () => {
      active = false;
    };
  }, [reportId, refreshToken]);

  return loaded && loaded.reportId === reportId ? loaded.preparation : null;
}
