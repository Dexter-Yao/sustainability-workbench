// ABOUTME: 标准版报告生成与交付页面，轮询服务端真实运行投影并执行客户交付物下载。
// ABOUTME: 页面仅按公共运行状态决定轮询，不维护浏览器侧生成阶段或推断完成条件。
// ABOUTME: 不依赖报告编辑上下文（路由在 REPORTLESS_ROUTES）：旧契约报告的已生成产物仍可查看下载，
// ABOUTME: 报告指针直接读当前账户的 currentReportId，能力投影按需自取。
"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/Button";
import { InlineAlert } from "@/components/ui/InlineAlert";
import { AppShell } from "@/components/shell/AppShell";
import { useAppOptional } from "@/lib/app-context";
import { useT } from "@/lib/i18n/locale-context";
import { useReportPreparation } from "@/components/shell/use-report-preparation";
import { useAccount } from "@/lib/account-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { generationEntryHref } from "@/lib/intake-steps";
import { fetchReportPreparation } from "@/lib/material-workspace-api";
import {
  currentReportId,
  getReportState,
  subscribeCurrentReportId,
  type ServerReportState,
} from "@/lib/report-store";
import {
  downloadReportGenerationArtifact,
  fetchLatestReportGeneration,
  isReportGenerationActive,
  type ReportGeneration,
  type ReportGenerationArtifact,
} from "@/lib/report-generation-api";
import {
  REPORT_GENERATION_SCREEN_LABEL,
  reportNavigationEntry,
} from "@/lib/report-navigation-labels";
import { ReportGenerationView } from "./report-generation-view";

const POLL_INTERVAL_MS = 2_500;

export function ReportGenerationPage() {
  const t = useT();
  const { snapshot: account } = useAccount();
  const accountId = account?.account.id ?? null;
  const subscribeToCurrentReport = useCallback(
    (listener: () => void) => (accountId ? subscribeCurrentReportId(accountId, listener) : () => {}),
    [accountId],
  );
  const readCurrentReport = useCallback(
    () => (accountId ? currentReportId(accountId) : null),
    [accountId],
  );
  const activeReportId = useSyncExternalStore(subscribeToCurrentReport, readCurrentReport, () => null);
  // 能力投影按需自取（只为派生生成入口路径）；带 reportId 键控派生避免切换报告时残留，
  // 取不到时回退 loading scope 的完整路径入口。
  const [capabilitiesFact, setCapabilitiesFact] = useState<{
    reportId: string;
    capabilities: ServerReportState["capabilities"];
  } | null>(null);
  useEffect(() => {
    if (!activeReportId) return;
    let active = true;
    void getReportState(activeReportId)
      .then((server) => {
        if (active) setCapabilitiesFact({ reportId: activeReportId, capabilities: server.capabilities });
      })
      .catch(() => {
        // 能力投影取不到只影响入口链接的路径推断，不阻断产物查看与下载。
      });
    return () => {
      active = false;
    };
  }, [activeReportId]);
  const reportCapabilities = capabilitiesFact?.reportId === activeReportId ? capabilitiesFact.capabilities : null;
  // 返回入口按报告级填报方式解析（questions 路径末步是议题信息页）；投影未到达时先按未选择兜底。
  // 刷新令牌取 savedAt：填报方式经 PATCH 写入后会 bump 它，传 null 等于承认永不重取——
  // 用户切换过填报方式再进本页，返回链接会指向旧路径的末步页。
  // 与 IntakeStepRail / intake-step-navigation 消费同一字段时的令牌口径一致。
  const generationApp = useAppOptional();
  const entryPreparation = useReportPreparation(activeReportId, generationApp?.savedAt ?? null);
  const entryHref = generationEntryHref(
    activeReportScope(reportCapabilities),
    entryPreparation?.primary_input_mode ?? null,
  );
  const reportIdRef = useRef(activeReportId);
  const [generation, setGeneration] = useState<ReportGeneration | null>(null);
  const [loadedReportId, setLoadedReportId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadingArtifactId, setDownloadingArtifactId] = useState<
    string | null
  >(null);

  const refresh = useCallback(
    async (showInitialLoading = false) => {
      if (!activeReportId) return;
      if (showInitialLoading) setLoading(true);
      else setRefreshing(true);
      try {
        const next = await fetchLatestReportGeneration(activeReportId);
        if (reportIdRef.current !== activeReportId) return;
        // 生成成功后的权威状态同步不在本页发生：本路由无报告编辑上下文，
        // 用户回到任一编辑路由时 AppProvider 会整树重载最新服务端状态。
        setGeneration(next);
        setLoadedReportId(activeReportId);
        setError(null);
      } catch (cause) {
        if (reportIdRef.current !== activeReportId) return;
        console.error("Report generation record load failed", cause);
        setError(t.generationPage.errorLoadRuns);
      } finally {
        if (reportIdRef.current === activeReportId) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [activeReportId, t],
  );

  useEffect(() => {
    reportIdRef.current = activeReportId;
  }, [activeReportId]);

  useEffect(() => {
    if (activeReportId) {
      void Promise.resolve().then(() => refresh(true));
    }
  }, [activeReportId, refresh]);

  const currentGeneration = (
    generation?.report_id === activeReportId ? generation : null
  );
  const activeStatus = currentGeneration?.status;

  // 生成完成后读取 preparation 投影：输入再变化时在交付区提示「可更新」，与分步流末步生成区同源。
  // 状态记「哪份报告可更新」，展示值按当前报告与成功态派生，避免切换报告时残留。
  const [updateAvailableReportId, setUpdateAvailableReportId] = useState<string | null>(null);
  useEffect(() => {
    if (!activeReportId || activeStatus !== "succeeded") return;
    let active = true;
    void fetchReportPreparation(activeReportId)
      .then((preparation) => {
        if (!active) return;
        setUpdateAvailableReportId(preparation.report_update_available ? activeReportId : null);
      })
      .catch(() => {
        if (active) setUpdateAvailableReportId(null);
      });
    return () => {
      active = false;
    };
  }, [activeReportId, activeStatus]);
  const updateAvailable = activeStatus === "succeeded" && updateAvailableReportId === activeReportId;
  useEffect(() => {
    if (!activeStatus || !isReportGenerationActive(activeStatus)) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      timer = setTimeout(async () => {
        await refresh(false);
        if (!cancelled) schedule();
      }, POLL_INTERVAL_MS);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeStatus, refresh]);

  const download = useCallback(
    async (artifact: ReportGenerationArtifact) => {
      setDownloadingArtifactId(artifact.artifact_id);
      setError(null);
      try {
        const blob = await downloadReportGenerationArtifact(artifact);
        const href = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = href;
        anchor.download = artifact.filename;
        anchor.click();
        URL.revokeObjectURL(href);
      } catch (cause) {
        console.error("Artifact download failed", cause);
        setError(t.generationPage.errorDownload);
      } finally {
        setDownloadingArtifactId(null);
      }
    },
    [t],
  );

  return (
    <AppShell
      screenId="report-generation"
      screenLabel={REPORT_GENERATION_SCREEN_LABEL}
      contentMaxWidth={1120}
    >
      <main className="py-6">
        {/* 面包屑：本页无左栏步骤导航（REPORTLESS），报告列表的返回入口由此承担；
            标签与左栏报告组同源（lib/report-navigation-labels）。 */}
        <nav
          aria-label={t.generationPage.breadcrumbAria}
          style={{ marginBottom: 18, fontSize: "var(--text-supporting-size)" }}
        >
          <Link
            href={reportNavigationEntry("all-reports").href}
            style={{ color: "var(--accent)", textDecoration: "none" }}
          >
            {t.shell.allReports}
          </Link>
          <span aria-hidden style={{ margin: "0 8px", color: "var(--muted-foreground)" }}>
            /
          </span>
          <span style={{ color: "var(--muted-foreground)" }}>{t.shell.reportGenerationPage}</span>
        </nav>
        {!activeReportId ? (
          <InlineAlert variant="error">{t.generationPage.selectReportFirst}</InlineAlert>
        ) : null}
        {activeReportId
          && (loading || loadedReportId !== activeReportId)
          && !currentGeneration ? (
            <p style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)" }} role="status">
              {t.generationPage.loadingRuns}
            </p>
          ) : null}
        {activeReportId
          && !loading
          && loadedReportId === activeReportId
          && !currentGeneration ? (
            <section>
              <p style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                {t.generationPage.standardReport}
              </p>
              <h1 style={{ margin: "8px 0 0", fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
                {t.generationPage.notStarted}
              </h1>
              <p
                className="mt-3 max-w-2xl"
                style={{ fontSize: "var(--text-body-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}
              >
                {t.generationPage.notStartedBody}
              </p>
              <Link
                href={entryHref}
                className="mt-5 inline-block no-underline"
                style={{
                  border: "1px solid var(--accent)",
                  borderRadius: "var(--radius-control)",
                  padding: "9px 22px",
                  fontSize: "var(--text-body-size)",
                  fontWeight: 500,
                  background: "var(--accent)",
                  color: "var(--accent-foreground)",
                }}
              >
                {t.generationPage.goStart}
              </Link>
            </section>
          ) : null}
        {activeReportId && error && !currentGeneration ? (
          <InlineAlert variant="error">
            <div className="flex flex-wrap items-center gap-3">
              <span>{error}</span>
              <Button variant="text" size="sm" onClick={() => void refresh(true)}>
                {t.generationPage.retry}
              </Button>
            </div>
          </InlineAlert>
        ) : null}
        {currentGeneration ? (
          <ReportGenerationView
            generation={currentGeneration}
            refreshing={refreshing}
            error={error}
            downloadingArtifactId={downloadingArtifactId}
            updateAvailable={updateAvailable}
            entryHref={entryHref}
            onRefresh={() => void refresh(false)}
            onDownload={(artifact) => void download(artifact)}
          />
        ) : null}
      </main>
    </AppShell>
  );
}
