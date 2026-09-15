// ABOUTME: 统一应用外壳（design.md §3.0）：AppTopBar 常驻 + 左栏（报告目录或编制步骤导航）+ 内容区；
// ABOUTME: 报告上下文页内容区右上渲染自动保存态（含 coach-autosave 锚点），顶栏不再承载步骤条与保存态。
// ABOUTME: 承载页面语义 data-screen-id/data-screen-label 与 saveError/conflictNotice/loadWarning 三类非阻断横幅。
"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { useAppOptional } from "@/lib/app-context";
import { useT } from "@/lib/i18n/locale-context";
import { useAuth } from "@/lib/auth-context";
import { AppTopBar } from "./AppTopBar";
import { IntakeStepRail } from "./IntakeStepRail";
import { saveStateLabel } from "./save-state-label";
import { ReportDirectory } from "./ReportDirectory";
import { initialReportDirectoryCollapsed } from "./report-directory-state";
import {
  classifyError,
  reportPageError,
  reportPageReached,
  type TelemetryScreenId,
} from "@/lib/product-telemetry";
import type { Issue } from "@/lib/api";

const NAV_COLLAPSED_KEY = "sustainability-desk:nav-collapsed";

export interface ReportDirectoryNavigation {
  activeSectionKey: string | null;
  onSelectSection: (sectionKey: string) => void;
}

export function AppShell({
  screenId,
  screenLabel,
  children,
  contentMaxWidth = 1400,
  issues,
  directory = false,
  reportContext = true,
}: {
  screenId: string;
  screenLabel: string;
  children: ReactNode;
  contentMaxWidth?: number;
  issues?: Issue[] | null;
  /** 左栏报告目录：仅报告正文页（章节树作页内目录）使用；准备步骤页面依赖步骤导航列。 */
  directory?: false | ReportDirectoryNavigation;
  /** 顶栏是否展示当前报告名、步骤条与保存态（报告列表页为 false）。 */
  reportContext?: boolean;
}) {
  const t = useT();
  // reportless 路由（报告列表等）没有报告 context：横幅区随之缺省，仅渲染顶栏与内容。
  const app = useAppOptional();
  const {
    retrySave,
    saveError,
    loadWarning,
    dismissLoadWarning,
    sessionExpired,
    conflictNotice,
    conflictPending,
    confirmConflictReload,
    dismissConflictNotice,
  } = app ?? {
    retrySave: () => {},
    saveError: null,
    loadWarning: null,
    dismissLoadWarning: () => {},
    sessionExpired: false,
    conflictNotice: null,
    conflictPending: false,
    confirmConflictReload: async () => {},
    dismissConflictNotice: () => {},
  };
  const { signOut } = useAuth();
  const router = useRouter();
  // 编制步骤导航列：报告上下文页（非工作台目录）在左侧固定渲染。
  const directoryNavigation = directory || null;
  const stepRail = reportContext && !directoryNavigation && Boolean(app?.activeReportId);

  // 页面到达与前端错误的唯一上报点：AppShell 覆盖全部报告上下文页面，
  // 各页无需自行埋点；没有它，"打开了但没填"与白屏都不可见。
  const telemetryReportId = app?.activeReportId ?? null;
  useEffect(() => {
    if (!telemetryReportId) return;
    reportPageReached(telemetryReportId, screenId as TelemetryScreenId);
  }, [telemetryReportId, screenId]);

  useEffect(() => {
    if (!telemetryReportId) return;
    const onError = (event: ErrorEvent) => {
      reportPageError(
        telemetryReportId,
        screenId as TelemetryScreenId,
        classifyError(event.error ?? event.message),
      );
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      reportPageError(
        telemetryReportId,
        screenId as TelemetryScreenId,
        "unhandled_rejection",
      );
      void event;
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [telemetryReportId, screenId]);
  const saving = app?.saving ?? false;
  const savedAt = app?.savedAt ?? null;
  // 折叠态：初值展开保证 SSR 与首屏一致，挂载后从 localStorage 解析（parse-first：只认 "1" 为折叠），避免 hydration 不匹配。
  const [collapsed, setCollapsed] = useState(false);
  const directoryEnabled = directoryNavigation !== null;
  useEffect(() => {
    if (!directoryEnabled) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsed(initialReportDirectoryCollapsed(
      window.localStorage.getItem(NAV_COLLAPSED_KEY),
      window.matchMedia("(max-width: 900px)").matches,
    ));
  }, [directoryEnabled]);
  const toggleCollapse = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      window.localStorage.setItem(NAV_COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  }, []);

  return (
    <div
      data-screen-id={screenId}
      data-screen-label={screenLabel}
      style={{ background: "var(--surface)", minHeight: "100vh", fontFamily: "var(--font-sans)" }}
    >
      <AppTopBar showReportContext={reportContext} />
      <div className="gs-app-surface" style={{ padding: "16px 24px", boxSizing: "border-box" }}>
        {/* 统一平面外壳：可选目录 + 内容同处一个工作面，靠细分隔和留白组织层级。 */}
        <div
          className="gs-shell-grid"
          style={{
            display: "grid",
            gridTemplateColumns: directoryNavigation
              ? collapsed
                ? "52px minmax(0, 1fr)"
                : "minmax(240px, 320px) minmax(0, 1fr)"
              : stepRail
                // 步骤栏按内容自适应并封顶：172px 是按中文步骤名定的固定宽，
                // 英文标签更长（"Reporting standard"、"Optional details"）会被
                // nowrap 裁掉尾部。下限保住原有观感，上限防止长标签挤压内容区。
                ? "minmax(172px, max-content) minmax(0, 1fr)"
                : "minmax(0, 1fr)",
            maxWidth: contentMaxWidth,
            margin: "0 auto",
            background: "var(--background)",
            border: "1px solid var(--border)",
            boxSizing: "border-box",
            alignItems: "flex-start",
          }}
        >
          {directoryNavigation ? (
            <aside
              className="gs-shell-nav"
              data-collapsed={collapsed}
              style={{
                position: "sticky",
                top: "calc(var(--topbar-height) + 16px)",
                alignSelf: "start",
                maxHeight: "calc(100vh - var(--topbar-height) - 32px)",
                overflowY: "auto",
                borderRight: "1px solid var(--border)",
                padding: collapsed ? "12px 0" : "20px 16px",
              }}
            >
              <ReportDirectory
                collapsed={collapsed}
                onToggleCollapse={toggleCollapse}
                issues={issues ?? []}
                activeSectionKey={directoryNavigation.activeSectionKey}
                onSelectSection={directoryNavigation.onSelectSection}
              />
            </aside>
          ) : null}
          {stepRail ? (
            <aside
              className="gs-shell-nav"
              style={{
                position: "sticky",
                top: "calc(var(--topbar-height) + 16px)",
                alignSelf: "start",
                maxHeight: "calc(100vh - var(--topbar-height) - 32px)",
                overflowY: "auto",
                borderRight: "1px solid var(--border)",
                padding: "20px 10px",
              }}
            >
              <IntakeStepRail />
            </aside>
          ) : null}
          <main className="gs-shell-main" style={{ minWidth: 0, padding: "24px 28px" }}>
            {reportContext && app?.activeReportId ? (
              <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
                {/* 冲突暂停期间必须如实陈述「未保存」：若该指示器不看 conflictPending，
                    而暂停分支在 setSaving(true) 之前就 return，saving 恒 false、savedAt 停在
                    上一次成功保存——界面会持续显示「已自动保存」，用户以为在存，实际每一次
                    输入都只留在内存里，答案随之丢失。
                    指示器是用户判断「我填的东西在不在」的唯一常驻依据，不得报喜不报忧。 */}
                <span
                  id="coach-autosave"
                  role={conflictPending ? "alert" : undefined}
                  style={{
                    fontSize: "var(--text-supporting-size)",
                    color: conflictPending ? "var(--destructive)" : "var(--muted-foreground)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {saveStateLabel({ conflictPending, saving, savedAt, copy: t.shell })}
                </span>
              </div>
            ) : null}
            {sessionExpired ? (
              <div className="gs-save-error" role="alert">
                <span>{t.shell.sessionExpired}</span>
                <button type="button" onClick={() => void signOut().then(() => router.replace("/login"))}>
                  重新登录
                </button>
              </div>
            ) : null}
            {saveError ? (
              <div className="gs-save-error" role="alert">
                <span>{saveError}</span>
                <button type="button" onClick={retrySave}>{t.shell.retrySave}</button>
              </div>
            ) : null}
            {conflictNotice ? (
              <div className="gs-save-error" role={conflictPending ? "alert" : "status"}>
                <span>{conflictNotice}</span>
                {conflictPending ? (
                  <button type="button" onClick={() => void confirmConflictReload()}>
                    {t.shell.loadLatestDiscardLocal}
                  </button>
                ) : (
                  <button type="button" onClick={dismissConflictNotice}>{t.shell.acknowledge}</button>
                )}
              </div>
            ) : null}
            {loadWarning ? (
              <div className="gs-save-error" role="status">
                <span>{loadWarning}</span>
                <button type="button" onClick={dismissLoadWarning}>{t.shell.acknowledge}</button>
              </div>
            ) : null}
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
