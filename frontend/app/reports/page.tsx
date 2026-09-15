"use client";
// ABOUTME: 报告列表页（design.md §7 key=report-list）——登录后默认落地页；空状态承载编制流程说明侧栏，
// ABOUTME: 有数据态行式列表回答「填到第几步、能不能生成、下一步该干什么」；行操作直接展示（查看报告/
// ABOUTME: 继续/删除报告，删除经 ConfirmDialog 确认）；「新建报告」点击即创建服务端报告并进入分步流第一步。
import Link from "next/link";
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/shell/AppShell";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CreateReportDialog } from "@/components/reports/CreateReportDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { downloadUnifiedWorkbookBlankTemplate, importUnifiedWorkbook } from "@/lib/api";
import { accountErrorMessage } from "@/lib/account-error-message";
import { ApiError, isSessionExpired } from "@/lib/api-error";
import { useAuth } from "@/lib/auth-context";
import { useAccount } from "@/lib/account-context";
import { getIntakeSteps } from "@/lib/intake-steps";
import { fetchReportPreparation, type ReportPreparation } from "@/lib/material-workspace-api";
import {
  fetchLatestReportGeneration,
  isReportGenerationActive,
} from "@/lib/report-generation-api";
import type { ReportGenerationProjection } from "@/lib/report-api.generated";
import { reportCreateAvailability } from "@/lib/report-create-availability";
import { resumeHrefFrom } from "@/lib/resume-target";
import { stepShortLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { formatDate } from "@/lib/i18n/format";
import { useLocale, useT } from "@/lib/i18n/locale-context";
import {
  archiveReport,
  createReport,
  currentReportId,
  fetchReportProfileOptions,
  getReportState,
  listReports,
  setCurrentReportId,
  type ReportProfileOption,
  type ReportSummary,
} from "@/lib/report-store";
import { REPORT_DOCUMENT_PATH } from "@/lib/report-navigation-labels";
import { reportDisplayTitle } from "./report-display-title";

const WORKBOOK_ACCEPT = ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** 行内 Excel 通道的文字链样式：从属操作，不与右侧行操作按钮争夺视觉权重。 */
const workbookLinkStyle: CSSProperties = {
  border: 0,
  padding: 0,
  background: "transparent",
  color: "var(--accent)",
  fontSize: "var(--text-supporting-size)",
  fontFamily: "var(--font-sans)",
  cursor: "pointer",
};

interface ReportRowFacts {
  preparation: ReportPreparation | null;
  generation: ReportGenerationProjection | null;
}

/** 行级状态派生：完成度、状态 Badge 与「下一步」一句话，全部来自服务端投影。
 *
 * 措辞按服务端投影的**稳定 id**（area.id、generation.status）取字典，不转述后端下发的
 * 中文串——后端文案是简体的，英文界面下直接渲染会混排。仅在 id 未登记时才回落到
 * 后端 title，那是新增区块尚未登记的显式信号。 */
function rowPresentation(facts: ReportRowFacts | undefined, t: Dictionary): {
  badge: { variant: BadgeVariant; label: string } | null;
  progress: { ready: number; total: number } | null;
  nextStep: string | null;
} {
  if (!facts) return { badge: null, progress: null, nextStep: null };
  const { preparation, generation } = facts;
  const progress = preparation
    ? {
        ready: preparation.areas.filter((area) => area.status === "ready").length,
        total: preparation.areas.length,
      }
    : null;
  let badge: { variant: BadgeVariant; label: string } | null = null;
  if (generation && isReportGenerationActive(generation.status)) {
    badge = { variant: "generating", label: t.reportList.badgeGenerating };
  } else if (generation?.status === "succeeded") {
    badge = { variant: "success", label: t.reportList.badgeGenerated };
  } else {
    badge = { variant: "neutral", label: t.reportList.badgeDraft };
  }
  let nextStep: string | null = null;
  if (generation && isReportGenerationActive(generation.status)) {
    nextStep = t.reportList.nextAwaitGeneration;
  } else if (preparation) {
    const pendingArea = preparation.areas.find((area) => area.status === "needs_input");
    if (pendingArea) {
      const areas = t.reportList.areas as Record<string, string | undefined>;
      nextStep = interpolate(t.reportList.nextContinue, {
        area: areas[pendingArea.id] ?? pendingArea.title ?? t.reportList.nextContinueFallback,
      });
    } else if (preparation.generation_eligible) {
      nextStep = generation?.status === "succeeded"
        ? t.reportList.nextCanUpdateOrDownload
        : t.reportList.nextCanGenerate;
    } else if (preparation.generation_blockers.length > 0) {
      // blocker.label 由后端按包下发（字段名取自知识包合同，天然是包语言），可直接呈现。
      nextStep = interpolate(t.reportList.nextContinue, {
        area: preparation.generation_blockers[0].label,
      });
    }
  }
  return { badge, progress, nextStep };
}

function ProcessAside() {
  const t = useT();
  // 无报告语境下按轻量版完整路径展示步骤名；只列步骤名，不写时长与副说明（design.md §3.0/§7.2）。
  const steps = getIntakeSteps({
    collectsMaterialityAssessment: true,
    materialAgentEnabled: true,
  });
  return (
    <aside
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-container)",
        padding: 20,
        background: "var(--background)",
      }}
    >
      <div
        style={{
          fontSize: "var(--text-overline-size)",
          fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
          letterSpacing: ".06em",
          color: "var(--muted-foreground)",
          marginBottom: 14,
        }}
      >
        {t.reportList.processHeading}
      </div>
      <div style={{ display: "grid", gap: 16 }}>
        {steps.map((step, index) => (
          <div key={step.href} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 10, alignItems: "center" }}>
            <span
              style={{
                width: 22,
                height: 22,
                borderRadius: "50%",
                background: index === 0 ? "var(--accent-subtle)" : "var(--surface-sunken)",
                color: index === 0 ? "var(--accent)" : "var(--muted-foreground)",
                display: "grid",
                placeItems: "center",
                fontSize: "var(--text-overline-size)",
                fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
              }}
            >
              {index + 1}
            </span>
            <span
              style={{
                fontSize: "var(--text-label-size)",
                fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
                color: "var(--foreground)",
              }}
            >
              {stepShortLabel(t, step.key)}
            </span>
          </div>
        ))}
        <div
          style={{
            paddingTop: 14,
            borderTop: "1px solid var(--border)",
            display: "grid",
            gridTemplateColumns: "24px 1fr",
            gap: 10,
            alignItems: "center",
          }}
        >
          <span aria-hidden style={{ width: 22, height: 22, display: "grid", placeItems: "center", fontSize: "var(--text-label-size)", color: "var(--accent)" }}>
            ⇩
          </span>
          <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
            {t.reportList.processGenerate}
          </span>
        </div>
      </div>
    </aside>
  );
}

function EmptyReportsIcon() {
  return (
    <svg
      width="44"
      height="44"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6" />
      <path d="M9 17h4" />
    </svg>
  );
}

export default function ReportListPage() {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const { session, loading, configured, signOut } = useAuth();
  const { snapshot: account, loading: accountLoading } = useAccount();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [rowFacts, setRowFacts] = useState<Record<string, ReportRowFacts>>({});
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ReportSummary | null>(null);
  // 统一填报工作簿（基础资料+评分+定量+议题问题）：模板下载是账户级空白母版、页面只有
  // 一个入口；导入按报告行进行且必须先确认覆盖语义（design.md §3.1）。busy 与结果按行隔离。
  const [blankTemplateBusy, setBlankTemplateBusy] = useState(false);
  const [workbookBusyReportId, setWorkbookBusyReportId] = useState<string | null>(null);
  const [pendingWorkbookImport, setPendingWorkbookImport] = useState<{
    report: ReportSummary;
    file: File;
  } | null>(null);
  const [workbookNote, setWorkbookNote] = useState<{
    reportId: string;
    kind: "success" | "error";
    text: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await listReports();
      setReports(list);
      const active = list.filter((report) => report.status === "active");
      // 每份报告并行取准备投影与最近生成运行；单份失败只影响该行的派生展示，不阻断列表。
      const facts = await Promise.all(
        active.map(async (report) => {
          const [preparation, generation] = await Promise.all([
            fetchReportPreparation(report.id).catch(() => null),
            fetchLatestReportGeneration(report.id).catch(() => null),
          ]);
          return [report.id, { preparation, generation }] as const;
        }),
      );
      setRowFacts(Object.fromEntries(facts));
    } catch (cause) {
      // 会话过期时刷新永远无效：给重新登录语义并回登录页。
      if (isSessionExpired(cause)) {
        setError(t.reportList.errorSessionExpired);
        void signOut().then(() => router.replace("/login"));
        return;
      }
      setError(t.reportList.errorListLoad);
    }
  }, [router, signOut, t.reportList.errorListLoad, t.reportList.errorSessionExpired]);

  useEffect(() => {
    if (!configured) return;
    if (!loading && !session) {
      router.replace("/login");
      return;
    }
    if (session) void Promise.resolve().then(refresh);
  }, [configured, loading, session, router, refresh]);

  // 「新建报告」点击即创建服务端报告，不存在本地草稿模式：
  // 创建成功后设当前报告指针并进入分步流第一步；失败原样呈现原因，不静默。
  const [creating, setCreating] = useState(false);
  // 建报先选报告类型（知识包 = 准则 × 语言）：清单与默认项由服务端投影，前端不硬编码。
  const [profileDialogOpen, setProfileDialogOpen] = useState(false);
  const [profileOptions, setProfileOptions] = useState<ReportProfileOption[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);

  async function handleOpenCreateDialog() {
    if (!account || creating) return;
    setError(null);
    try {
      const options = await fetchReportProfileOptions();
      setProfileOptions(options.profiles);
      setSelectedProfileId(options.default_report_profile_id);
      setProfileDialogOpen(true);
    } catch (cause) {
      setError(accountErrorMessage(cause, t.reportList.errorProfileOptions));
    }
  }

  async function handleCreate() {
    if (!account || creating || !selectedProfileId) return;
    setError(null);
    setCreating(true);
    try {
      const created = await createReport(undefined, undefined, selectedProfileId);
      setProfileDialogOpen(false);
      setCurrentReportId(account.account.id, created.id);
      router.push("/intake/info");
    } catch (cause) {
      setCreating(false);
      setProfileDialogOpen(false);
      if (isSessionExpired(cause)) {
        setError(t.reportList.errorSessionExpired);
        void signOut().then(() => router.replace("/login"));
        return;
      }
      // 创建是「建报告」与「写入首个状态」两步：第一步成功而第二步失败时，服务端已
      // 存在一份报告并占住名额，列表却仍是失败前的旧快照。不刷新就会让用户对着一个
      // 看不见的报告反复点新建、反复 403，且没有任何东西可删。
      await refresh();
      setError(
        cause instanceof ApiError && cause.code === "active_report_limit_reached"
          ? t.reportList.errorActiveLimit
          : accountErrorMessage(cause, t.reportList.errorCreate),
      );
    }
  }

  function handleOpen(report: ReportSummary) {
    if (!account) {
      setError(t.reportList.errorAccountPending);
      return;
    }
    setCurrentReportId(account.account.id, report.id);
    // 「继续」就该回到该继续的那一步：行内已经据 preparation 算出「下一步是什么」并显示给
    // 用户，点下去却固定跳第一步，等于让用户自己再走一遍。准备状态尚未取回时退回第一步。
    router.push(resumeHrefFrom(rowFacts[report.id]?.preparation ?? null));
  }

  // 已生成的报告直接进入报告正文页阅读与修订；交付物下载入口在其左栏目录的「报告生成与交付」。
  function handleViewGeneration(report: ReportSummary) {
    if (!account) {
      setError(t.reportList.errorAccountPending);
      return;
    }
    setCurrentReportId(account.account.id, report.id);
    router.push(REPORT_DOCUMENT_PATH);
  }

  async function handleBlankTemplateDownload() {
    if (blankTemplateBusy) return;
    setBlankTemplateBusy(true);
    setError(null);
    try {
      await downloadUnifiedWorkbookBlankTemplate();
    } catch (cause) {
      setError(accountErrorMessage(cause, t.reportList.errorTemplateDownload));
    } finally {
      setBlankTemplateBusy(false);
    }
  }

  async function handleWorkbookImport(report: ReportSummary, file: File) {
    setWorkbookBusyReportId(report.id);
    setWorkbookNote(null);
    try {
      // 导入是对该报告状态的整批替换：以服务端当前 state_seq 作乐观锁基线，
      // 阈值留空由服务端回退到该报告已保存的评估阈值。
      const server = await getReportState(report.id);
      await importUnifiedWorkbook(report.id, file, server.state_seq, null);
      setWorkbookNote({
        reportId: report.id,
        kind: "success",
        text: t.reportList.importSucceeded,
      });
      await refresh();
    } catch (cause) {
      setWorkbookNote({
        reportId: report.id,
        kind: "error",
        text: accountErrorMessage(cause, t.reportList.errorWorkbookImport),
      });
    } finally {
      setWorkbookBusyReportId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setError(null);
    try {
      await archiveReport(deleteTarget.id);
      // 指针指向刚被删除的报告时必须一并清除：否则从 / 进入会被指向一份已删报告，
      // 加载失败后再弹回列表，中间白走一趟。
      if (account && currentReportId(account.account.id) === deleteTarget.id) {
        setCurrentReportId(account.account.id, null);
      }
      setDeleteTarget(null);
      await refresh();
    } catch {
      setDeleteTarget(null);
      setError(t.reportList.errorDelete);
    }
  }

  const activeReports = reports?.filter((report) => report.status === "active") ?? [];
  const activeLimit = account?.capabilities.active_report_limit ?? null;
  // 「能否新建」在空列表态与有数据态是同一个判定，由同一处派生（见该模块注释）。
  const createAvailability = reportCreateAvailability(
    {
      creating,
      accountLoading,
      activeReportCount: activeReports.length,
      activeReportLimit: activeLimit,
      canCreateReport: account?.capabilities.can_create_report,
    },
    t,
  );

  if (!configured) {
    return (
      <main data-screen-id="report-list" data-screen-label="报告列表" style={{ padding: 24 }}>
        <p style={{ fontSize: "var(--text-body-size)", color: "var(--muted-foreground)" }}>
          {t.reportList.authUnconfigured}
        </p>
      </main>
    );
  }

  const emptyState = reports !== null && activeReports.length === 0;

  return (
    <AppShell screenId="report-list" screenLabel="报告列表" reportContext={false} contentMaxWidth={emptyState ? 988 : 960}>
      {error ? (
        <p role="alert" style={{ margin: "0 0 16px", fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>
          {error}
        </p>
      ) : null}

      {reports === null ? (
        <LoadingState type="list" />
      ) : emptyState ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 300px",
            gap: 36,
            alignItems: "start",
            padding: "20px 0",
          }}
        >
          <div>
            <h1 style={{ margin: "0 0 6px", fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
              {t.reportList.emptyHeading}
            </h1>
            <p style={{ margin: "0 0 24px", fontSize: "var(--text-body-size)", lineHeight: 1.8, color: "var(--foreground-secondary)" }}>
              {interpolate(t.reportList.emptyBody, { product: t.product.name })}
            </p>
            <div
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-container)",
                padding: 28,
                textAlign: "center",
              }}
            >
              <EmptyState
                icon={<EmptyReportsIcon />}
                title={t.reportList.emptyStateTitle}
                style={{ padding: 0, gap: 0 }}
              />
              <div style={{ marginTop: 20, display: "flex", justifyContent: "center", alignItems: "center", gap: 12 }}>
                <Button
                  variant={profileDialogOpen ? "secondary" : "primary"}
                  size="lg"
                  disabled={createAvailability.disabled}
                  disabledReason={createAvailability.reason}
                  onClick={() => void handleOpenCreateDialog()}
                >
                  {creating ? t.reportList.creating : t.reportList.newReport}
                </Button>
                <Button
                  variant="secondary"
                  size="lg"
                  disabled={blankTemplateBusy || accountLoading}
                  disabledReason={blankTemplateBusy ? t.reportList.generatingTemplate : t.reportList.accountLoading}
                  onClick={() => void handleBlankTemplateDownload()}
                >
                  {t.reportList.downloadWorkbookTemplate}
                </Button>
              </div>
            </div>
          </div>
          <ProcessAside />
        </div>
      ) : (
        <div style={{ padding: "8px 0" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            {/* 页面标题与左栏报告组/面包屑同源（lib/report-navigation-labels），不单写。 */}
            <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
              {t.shell.allReports}
            </h1>
            <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {activeLimit !== null
                ? interpolate(t.reportList.pageSubtitleWithLimit, { count: activeReports.length, limit: activeLimit })
                : interpolate(t.reportList.pageSubtitleCount, { count: activeReports.length })}
            </span>
            <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 10 }}>
              <Button
                variant="secondary"
                disabled={blankTemplateBusy || accountLoading}
                disabledReason={blankTemplateBusy ? t.reportList.generatingTemplate : t.reportList.accountLoading}
                onClick={() => void handleBlankTemplateDownload()}
              >
                {t.reportList.downloadWorkbookTemplate}
              </Button>
              <Button
                variant={profileDialogOpen ? "secondary" : "primary"}
                disabled={createAvailability.disabled}
                disabledReason={createAvailability.reason}
                onClick={() => void handleOpenCreateDialog()}
              >
                {creating ? t.reportList.creating : t.reportList.newReport}
              </Button>
            </span>
          </div>
          {account ? (
            <p style={{ margin: "6px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {account.account.organization_name ?? account.account.email}
            </p>
          ) : null}

          <ul style={{ listStyle: "none", margin: "16px 0 0", padding: 0 }}>
            {activeReports.map((report) => {
              const presentation = rowPresentation(rowFacts[report.id], t);
              return (
                <li
                  key={report.id}
                  style={{
                    // 三列固定网格（标题 / 完成度 / 操作）：操作按钮数量随行状态不同，
                    // 用固定列宽保证完成度与操作区跨行严格对齐。
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) 180px 308px",
                    gap: 20,
                    alignItems: "center",
                    padding: "16px 0",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Link
                        href="/intake/info"
                        onClick={(event) => {
                          event.preventDefault();
                          handleOpen(report);
                        }}
                        style={{
                          fontSize: "var(--text-body-size)",
                          fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
                          color: "var(--foreground)",
                          textDecoration: "none",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {reportDisplayTitle(report, t, locale)}
                      </Link>
                      {presentation.badge ? (
                        <Badge variant={presentation.badge.variant}>{presentation.badge.label}</Badge>
                      ) : null}
                    </div>
                    <p style={{ margin: "4px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                      {interpolate(t.reportList.lastUpdated, { date: formatDate(report.updated_at, locale) })}
                      {presentation.nextStep ? ` · ${presentation.nextStep}` : ""}
                    </p>
                    {/* 统一填报工作簿导入（报告级整册通道）：每行一个导入入口，
                        模板下载归页头唯一入口；导入前经 ConfirmDialog 确认覆盖语义。 */}
                    <p style={{ margin: "6px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                      <label
                        style={{
                          ...workbookLinkStyle,
                          cursor: workbookBusyReportId === report.id ? "default" : "pointer",
                          opacity: workbookBusyReportId === report.id ? 0.5 : 1,
                        }}
                      >
                        {workbookBusyReportId === report.id ? t.reportList.importing : t.reportList.importWorkbook}
                        <input
                          type="file"
                          accept={WORKBOOK_ACCEPT}
                          disabled={workbookBusyReportId === report.id}
                          style={{ display: "none" }}
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) setPendingWorkbookImport({ report, file });
                            event.target.value = "";
                          }}
                        />
                      </label>
                    </p>
                    {workbookNote?.reportId === report.id ? (
                      <p
                        role={workbookNote.kind === "error" ? "alert" : "status"}
                        style={{
                          margin: "6px 0 0",
                          fontSize: "var(--text-supporting-size)",
                          color: workbookNote.kind === "error" ? "var(--destructive)" : "var(--accent)",
                          whiteSpace: "normal",
                        }}
                      >
                        {workbookNote.text}
                      </p>
                    ) : null}
                  </div>
                  {presentation.progress && presentation.progress.total > 0 ? (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", marginBottom: 4 }}>
                        <span>{t.reportList.completion}</span>
                        <span>
                          {interpolate(t.reportList.completionSteps, { ready: presentation.progress.ready, total: presentation.progress.total })}
                        </span>
                      </div>
                      <div style={{ height: 4, background: "var(--surface-sunken)", borderRadius: "var(--radius-pill)", overflow: "hidden" }}>
                        <div
                          style={{
                            height: "100%",
                            width: `${(presentation.progress.ready / presentation.progress.total) * 100}%`,
                            background: "var(--accent)",
                          }}
                        />
                      </div>
                    </div>
                  ) : (
                    <div aria-hidden />
                  )}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10, whiteSpace: "nowrap" }}>
                    {rowFacts[report.id]?.generation?.status === "succeeded" ? (
                      <Button variant="secondary" size="sm" onClick={() => handleViewGeneration(report)}>
                        {t.reportList.viewReport}
                      </Button>
                    ) : null}
                    <Button variant="secondary" size="sm" onClick={() => handleOpen(report)}>
                      {rowFacts[report.id]?.generation?.status === "succeeded"
                        ? t.reportList.viewInputs
                        : presentation.progress && presentation.progress.ready > 0
                          ? t.reportList.resume
                          : t.reportList.open}
                    </Button>
                    <Button
                      variant="text"
                      size="sm"
                      style={{ color: "var(--destructive)" }}
                      onClick={() => setDeleteTarget(report)}
                    >
                      {t.reportList.deleteReport}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <CreateReportDialog
        open={profileDialogOpen}
        options={profileOptions}
        selectedProfileId={selectedProfileId}
        creating={creating}
        onSelect={setSelectedProfileId}
        onConfirm={() => void handleCreate()}
        onCancel={() => setProfileDialogOpen(false)}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget ? interpolate(t.reportList.deleteConfirmTitle, { title: reportDisplayTitle(deleteTarget, t, locale) }) : ""}
        description={t.reportList.deleteConfirmBody}
        confirmLabel={t.reportList.deleteConfirmAction}
        destructive
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
      {/* 导入覆盖确认：与分步页各 Excel 通道同一语义与措辞（design.md §3.1）。 */}
      <ConfirmDialog
        open={pendingWorkbookImport !== null}
        title={
          pendingWorkbookImport
            ? interpolate(t.reportList.importConfirmTitle, { title: reportDisplayTitle(pendingWorkbookImport.report, t, locale) })
            : ""
        }
        description={t.reportList.importConfirmBody}
        confirmLabel={t.reportList.importConfirmAction}
        destructive
        onConfirm={() => {
          const pending = pendingWorkbookImport;
          setPendingWorkbookImport(null);
          if (pending) void handleWorkbookImport(pending.report, pending.file);
        }}
        onCancel={() => setPendingWorkbookImport(null)}
      />
    </AppShell>
  );
}
