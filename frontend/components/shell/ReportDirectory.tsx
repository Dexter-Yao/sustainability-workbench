// ABOUTME: 报告正文页左侧稳定报告目录：以 Section.title 作页内章节导航并展示生成就绪度。
// ABOUTME: 动态 displayTitle 只属正文；本目录不承担标题质量或人工采纳状态。
// ABOUTME: 步骤导航与账户信息归全局顶栏（design.md §3.0）；本目录承载章节树、生成交付入口与报告列表入口。
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Issue } from "@/lib/api";
import { useT } from "@/lib/i18n/locale-context";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { isVisible } from "@/lib/conditions";
import type { Block, Section } from "@/lib/schema";
import { BrandMark } from "@/components/brand/brand-mark";
import {
  reportNavigationEntry,
} from "@/lib/report-navigation-labels";
import { reportSectionsGate } from "./report-directory-state";
import { useReportPreparation } from "./use-report-preparation";

/** 纯装配章节，不在导航中暴露给用户（about_report 自动从全局字段拼装；附录自动装配无专属输入面）。 */
export const HIDDEN_NAV_SECTIONS = new Set(["about_report", "report_appendix"]);

function walkBlocks(section: Section): Block[] {
  return [
    ...(section.blocks ?? []),
    ...(section.children ?? []).flatMap(walkBlocks),
  ];
}

function readiness(section: Section): { ready: number; total: number } {
  const blocks = walkBlocks(section).filter((block) =>
    block.blockType === "generative" || block.blockType === "constrained",
  );
  return {
    ready: blocks.filter((block) => block.state === "ready" || block.state === "locked").length,
    total: blocks.length,
  };
}

function sectionHasIssue(section: Section, issues: Issue[]): boolean {
  const keys = new Set<string>();
  const blockIds = new Set<string>();
  const walk = (candidate: Section) => {
    keys.add(candidate.key);
    for (const block of candidate.blocks ?? []) blockIds.add(block.id);
    for (const child of candidate.children ?? []) walk(child);
  };
  walk(section);
  return issues.some((issue) =>
    issue.level === "block" && (
      (issue.sectionKey ? keys.has(issue.sectionKey) : false) ||
      (issue.blockId ? blockIds.has(issue.blockId) : false) ||
      (issue.reportSectionId ? issue.reportSectionId === section.reportSectionId : false)
    ),
  );
}

export function ReportDirectory({
  issues = [],
  collapsed = false,
  onToggleCollapse,
  activeSectionKey = null,
  onSelectSection,
}: {
  issues?: Issue[];
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  /** Section currently in view on the document page; highlights the matching entry. */
  activeSectionKey?: string | null;
  /** Scrolls the document to a section; owned by the page, the directory never routes. */
  onSelectSection: (sectionKey: string) => void;
}) {
  const t = useT();
  const { report, activeReportCapabilities, activeReportId, savedAt } = useApp();
  const preparation = useReportPreparation(activeReportId, savedAt);
  const pathname = usePathname();
  const scope = activeReportScope(activeReportCapabilities);
  const companyShort = String(report.fields.company_short_name?.value ?? "").trim();
  const companyRegistered = String(report.fields.company_registered_name?.value ?? "").trim();
  const company = companyShort || companyRegistered;
  // 章节可见性与 intake 首步同源：服务端准备投影 report_identity 域 ready 才展示章节树；
  // 投影尚未到达或不可用（本地开发模式）时以已填字段临时判定。
  const sectionsGate = reportSectionsGate(
    preparation,
    {
      company,
      reportingYear: String(report.fields.reporting_year?.value ?? ""),
    },
    t,
  );

  const sectionsVisible = sectionsGate.visible && report.sections.some((section) =>
    !HIDDEN_NAV_SECTIONS.has(section.key) && isVisible(section, report));

  if (scope.status === "loading") {
    return (
      <nav aria-label={t.reportDirectory.nav} style={{ padding: "10px 8px" }}>
        <BrandMark className="mb-4 px-1" />
        <p style={{ margin: "8px 6px", color: "var(--muted-foreground)", fontSize: "var(--text-label-size)" }} role="status">
          {t.reportDirectory.loadingScope}
        </p>
      </nav>
    );
  }

  const renderSection = (section: Section, level: number): React.ReactNode => {
    if (HIDDEN_NAV_SECTIONS.has(section.key)) return null;
    if (!isVisible(section, report)) return null;
    const progress = readiness(section);
    return (
      <div key={section.key}>
        <button
          type="button"
          data-section-key={section.key}
          onClick={() => onSelectSection(section.key)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            padding: "5px 6px",
            paddingLeft: 6 + level * 14,
            border: 0,
            borderRadius: "var(--radius-control)",
            background: activeSectionKey === section.key ? "var(--accent-subtle)" : "transparent",
            color: activeSectionKey === section.key ? "var(--accent)" : "var(--foreground)",
            fontSize: "var(--text-label-size)",
            fontWeight: activeSectionKey === section.key || level === 0 ? 600 : 400,
            textAlign: "left",
            cursor: "pointer",
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginRight: "auto" }}>
            {section.title}
          </span>
          {sectionHasIssue(section, issues) ? (
            <span role="img" aria-label={t.reportDirectory.exportBlocked} data-tip-right={t.reportDirectory.exportBlocked} style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--destructive)" }} />
          ) : null}
          {progress.total > 0 ? (
            <span style={{ color: "var(--muted-foreground)", fontSize: "var(--text-overline-size)" }}>{progress.ready}/{progress.total}</span>
          ) : null}
        </button>
        {(section.children ?? []).map((child) => renderSection(child, level + 1))}
      </div>
    );
  };

  if (collapsed) {
    return (
      <nav aria-label={t.reportDirectory.nav} style={{ padding: "10px 6px" }}>
        <BrandMark compact className="mb-2 flex h-8 w-9" />
        <button type="button" onClick={onToggleCollapse} aria-label={t.reportDirectory.expand} style={{ width: 36, height: 32, border: 0, background: "transparent", cursor: "pointer", color: "var(--muted-foreground)" }}>
          ☰
        </button>
        <Link href="/reports/generation" aria-label={t.shell.reportGenerationPage} data-tip-right={t.shell.reportGenerationPage} style={{ width: 36, height: 32, display: "grid", placeItems: "center", textDecoration: "none", color: pathname.startsWith("/reports/generation") ? "var(--accent)" : "var(--muted-foreground)" }}>⇩</Link>
        <Link href={reportNavigationEntry("all-reports").href} aria-label={t.shell.allReports} data-tip-right={t.shell.allReports} style={{ width: 36, height: 32, display: "grid", placeItems: "center", textDecoration: "none", color: pathname === "/reports" ? "var(--accent)" : "var(--muted-foreground)" }}>⊞</Link>
      </nav>
    );
  }

  return (
    <nav aria-label={t.reportDirectory.nav} style={{ padding: "10px 8px 12px" }}>
      <BrandMark className="mb-4 px-1" />
      <div style={{ display: "flex", alignItems: "center", fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", margin: "4px 6px 6px", letterSpacing: "0.04em" }}>
        <span style={{ marginRight: "auto" }}>{t.reportDirectory.nav}</span>
        <button type="button" onClick={onToggleCollapse} aria-label={t.reportDirectory.collapse} style={{ border: 0, background: "transparent", cursor: "pointer", color: "inherit" }}>«</button>
      </div>
      <Link href="/reports/generation" aria-current={pathname.startsWith("/reports/generation") ? "page" : undefined} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 6px", marginBottom: 2, borderRadius: "var(--radius-control)", background: pathname.startsWith("/reports/generation") ? "var(--accent-subtle)" : "transparent", color: pathname.startsWith("/reports/generation") ? "var(--accent)" : "var(--foreground)", fontSize: "var(--text-label-size)", fontWeight: 600, textDecoration: "none" }}>
        <span aria-hidden>⇩</span><span>{t.shell.reportGenerationPage}</span>
      </Link>
      {/* 「我的报告」在导航面，工作台目录同样承担报告列表入口；标签同源 lib/report-navigation-labels。 */}
      <Link href={reportNavigationEntry("all-reports").href} aria-current={pathname === "/reports" ? "page" : undefined} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 6px", marginBottom: 8, borderRadius: "var(--radius-control)", background: pathname === "/reports" ? "var(--accent-subtle)" : "transparent", color: pathname === "/reports" ? "var(--accent)" : "var(--foreground)", fontSize: "var(--text-label-size)", fontWeight: 600, textDecoration: "none" }}>
        <span aria-hidden>⊞</span><span>{t.shell.allReports}</span>
      </Link>
      {sectionsGate.visible ? (
        <>
          {sectionsVisible ? (
            <div style={{ fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", margin: "10px 6px 6px" }}>{t.reportDirectory.sections}</div>
          ) : null}
          {report.sections.map((section) => renderSection(section, 0))}
        </>
      ) : (
        <>
          <div style={{ fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", margin: "10px 6px 6px" }}>{t.reportDirectory.sections}</div>
          <Link
            href={sectionsGate.guidance.href}
            style={{
              display: "block",
              padding: "7px 6px",
              borderRadius: "var(--radius-control)",
              fontSize: "var(--text-label-size)",
              lineHeight: 1.6,
              color: "var(--muted-foreground)",
              textDecoration: "none",
            }}
          >
            {sectionsGate.guidance.message}
            <span style={{ color: "var(--accent)", marginLeft: 6 }}>{sectionsGate.guidance.actionLabel}</span>
          </Link>
        </>
      )}
    </nav>
  );
}
