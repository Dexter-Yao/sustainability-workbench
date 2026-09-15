// ABOUTME: 全局顶栏（design.md §3.0）：所有登录后页面的共同祖先——品牌字标（链接首页）、当前报告名（纯文本）、
// ABOUTME: 与账户邮箱菜单。顶栏不承载报告级动作；步骤导航与报告级去向（我的全部报告/当前报告交付物）在左栏 IntakeStepRail，保存态在内容区右上。
"use client";

import { useRouter } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { BrandMark } from "@/components/brand/brand-mark";
import { reportDisplayTitle } from "@/app/reports/report-display-title";
import { useAccount } from "@/lib/account-context";
import { useLocale, useT } from "@/lib/i18n/locale-context";
import { UI_LOCALES } from "@/lib/i18n/locale";
import { useAppOptional } from "@/lib/app-context";
import { useAuth } from "@/lib/auth-context";
import { listReports, type ReportSummary } from "@/lib/report-store";

function TopBarMenu({
  trigger,
  ariaLabel,
  children,
  align = "right",
}: {
  trigger: ReactNode;
  ariaLabel: string;
  children: ReactNode;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} style={{ position: "relative", display: "flex", alignItems: "center" }}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          border: 0,
          background: "transparent",
          padding: 0,
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        {trigger}
      </button>
      {open ? (
        <div
          role="menu"
          onClick={() => setOpen(false)}
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            ...(align === "right" ? { right: 0 } : { left: 0 }),
            minWidth: 220,
            background: "var(--background)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-container)",
            boxShadow: "var(--shadow-overlay)",
            padding: 6,
            zIndex: 40,
          }}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  textAlign: "left",
  border: 0,
  background: "transparent",
  padding: "8px 10px",
  borderRadius: "var(--radius-control)",
  fontSize: "var(--text-label-size)",
  color: "var(--foreground)",
  cursor: "pointer",
  textDecoration: "none",
  fontFamily: "inherit",
};

export function AppTopBar({ showReportContext = true }: { showReportContext?: boolean }) {
  const router = useRouter();
  // reportless 路由无报告 context：顶栏退化为品牌 + 账户菜单（showReportContext 也应为 false）。
  const app = useAppOptional();
  const activeReportId = app?.activeReportId ?? null;
  const { snapshot: account } = useAccount();
  const t = useT();
  const { locale, selectLocale } = useLocale();
  const { signOut } = useAuth();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);

  useEffect(() => {
    if (!showReportContext || !account) return;
    let active = true;
    void listReports().then(
      (list) => {
        if (active) setReports(list.filter((report) => report.status === "active"));
      },
      () => {
        // 顶栏报告清单取不到时静默降级：报告名退回「当前报告」，切换走 /reports。
      },
    );
    return () => {
      active = false;
    };
  }, [showReportContext, account, activeReportId]);

  const currentReport = reports?.find((report) => report.id === activeReportId) ?? null;

  // 顶栏账户标识用登录身份的邮箱（组织名称是选填项）。
  const accountIdentifier = account?.account.email ?? "";


  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 35,
        height: "var(--topbar-height)",
        background: "var(--background)",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "0 20px",
      }}
    >
      {/* 品牌字标（design.md §2.10）：文字字标，点击回报告列表。 */}
      <BrandMark size={18} />

      {showReportContext && activeReportId ? (
        <>
          <span aria-hidden style={{ width: 1, height: 20, background: "var(--border)" }} />
          {/* 当前报告名：纯文本，不承载切换/新建入口（报告操作在列表页与右侧按钮）。 */}
          <span
            style={{
              fontSize: "var(--text-label-size)",
              fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
              color: "var(--foreground)",
              maxWidth: 260,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {currentReport ? reportDisplayTitle(currentReport, t, locale) : t.topBar.currentReportFallback}
          </span>
        </>
      ) : null}

      <span style={{ margin: "0 auto" }} />

      {/* 顶栏不承载报告级动作：不放「新建报告」——它会与报告列表页的
          同名按钮在同一屏并排出现，属冗余；建报是列表页的职责。
          「我的报告」在左栏报告组：报告列表页本身即该页，无左栏的生成交付页以
          页内面包屑承担返回入口。 */}

      {/* 账户区：展示登录邮箱（无头像图标）；菜单只承载身份事实与退出登录。 */}
      <TopBarMenu
        ariaLabel={t.topBar.accountMenu}
        trigger={
          <span
            style={{
              fontSize: "var(--text-label-size)",
              color: "var(--foreground)",
              maxWidth: 260,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {accountIdentifier} ▾
          </span>
        }
      >
        {account ? (
          <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", marginBottom: 4 }}>
            <p style={{ margin: 0, fontSize: "var(--text-label-size)", color: "var(--foreground)" }}>
              {account.account.organization_name ?? account.account.email}
            </p>
            {account.account.organization_name && account.account.email ? (
              <p style={{ margin: "4px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                {account.account.email}
              </p>
            ) : null}
          </div>
        ) : null}
        {/* 界面语言是用户偏好，与账户身份同属本菜单；报告内容语言由知识包决定，不在此切换。 */}
        <div style={{ padding: "6px 10px 2px", fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)" }}>
          {t.common.languageGroup}
        </div>
        {UI_LOCALES.map((option) => (
          <button
            key={option}
            type="button"
            role="menuitemradio"
            aria-checked={locale === option}
            style={{
              ...menuItemStyle,
              color: locale === option ? "var(--accent)" : "var(--foreground)",
            }}
            onClick={() => selectLocale(option)}
          >
            {option === "en" ? t.common.languageEnglish : t.common.languageSimplifiedChinese}
          </button>
        ))}
        <div style={{ borderTop: "1px solid var(--border)", margin: "4px 0" }} />
        <button
          type="button"
          role="menuitem"
          style={menuItemStyle}
          onClick={() => void signOut().then(() => router.replace("/login"))}
        >
          {t.common.signOut}
        </button>
      </TopBarMenu>
    </header>
  );
}
