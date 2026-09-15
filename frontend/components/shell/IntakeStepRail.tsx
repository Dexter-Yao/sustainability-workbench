// ABOUTME: 左侧固定步骤导航（design.md §3.0）：报告编制步骤的唯一导航面——
// ABOUTME: getIntakeSteps(scope) × preparation.areas[].status 派生状态，不由浏览器推断；顶栏不再承载步骤条。
// ABOUTME: 当前步骤的二级标题（页面区块锚点 + 必填/选填标记）事实源归 lib/intake-info-sections。
// ABOUTME: 步骤组上方的「报告」组承载两个报告级去向：当前报告的生成与交付、账户报告列表（顶栏「我的报告」已移入此处）；标签同源 lib/report-navigation-labels。
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type CSSProperties } from "react";

import { activeReportScope } from "@/lib/active-report-scope";
import { useAppOptional } from "@/lib/app-context";
import { getIntakeSteps, matchIntakeStepIndex } from "@/lib/intake-steps";
import { visibleIntakeInfoSections } from "@/lib/intake-info-sections";
import { reportNavigationLabel, stepShortLabel } from "@/lib/i18n/intake-step-copy";
import { useT } from "@/lib/i18n/locale-context";
import { REPORT_NAVIGATION_ENTRIES } from "@/lib/report-navigation-labels";
import type { ReportPreparation } from "@/lib/material-workspace-api";
import type { PreparationAreaStatus } from "@/lib/report-api.generated";
import { useReportPreparation } from "./use-report-preparation";

/** 准备投影区域 → 步骤路由的对应关系；状态永远来自服务端投影，不由浏览器推断。 */
const AREA_HREF: Record<string, string> = {
  report_identity: "/intake/info",
  materiality: "/intake/scoring",
  quantitative_metrics: "/intake/metrics",
  topic_questions: "/intake/questions",
  materials: "/materials",
};

function areaStatusFor(preparation: ReportPreparation | null, href: string): PreparationAreaStatus | null {
  if (!preparation) return null;
  const area = preparation.areas.find((candidate) => AREA_HREF[candidate.id] === href);
  return area?.status ?? null;
}

/** 报告级导航条目：只有标签，不带步骤编号也不带说明行——标签已自解释。 */
function ReportLevelLink({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      style={{
        display: "block",
        padding: "8px 10px",
        borderRadius: "var(--radius-control)",
        textDecoration: "none",
        background: active ? "var(--accent-subtle)" : "transparent",
      }}
    >
      <span
        style={{
          fontSize: "var(--text-label-size)",
          color: active ? "var(--accent)" : "var(--foreground)",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
    </Link>
  );
}

function StepDot({ state, index }: { state: "done" | "current" | "pending"; index: number }) {
  return (
    <span
      aria-hidden
      style={{
        width: 18,
        height: 18,
        borderRadius: "50%",
        background: state === "pending" ? "var(--surface-sunken)" : "var(--accent)",
        color: state === "pending" ? "var(--muted-foreground)" : "var(--accent-foreground)",
        display: "grid",
        placeItems: "center",
        fontSize: 10,
        fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
        flexShrink: 0,
      }}
    >
      {state === "done" ? "✓" : index}
    </span>
  );
}

/** 报告编制页的左侧步骤导航；无报告上下文（reportless 页面）不渲染。
 * 「新建报告」点击即创建服务端报告，不存在无报告的编制页。 */
export function IntakeStepRail() {
  const t = useT();
  const pathname = usePathname();
  const app = useAppOptional();
  const activeReportId = app?.activeReportId ?? null;
  const savedAt = app?.savedAt ?? null;
  // 路由变化也重拉：填报方式切换（PATCH，不走保存路径）后步骤序列立即随投影更新。
  const preparation = useReportPreparation(activeReportId, `${savedAt ?? 0}:${pathname ?? ""}`);
  const scope = activeReportScope(app?.activeReportCapabilities ?? null);
  const steps = getIntakeSteps(scope, preparation?.primary_input_mode ?? null);
  const currentIndex = matchIntakeStepIndex(pathname, steps);
  // 范围未到达时不渲染：loading 态的能力字段全为 false，会先算出一份缺步骤的序列，随后整条步骤条跳变成权威序列。
  // 步骤序列是从权威能力派生的事实，宁可稍后出现，也不先给一份会自我推翻的。
  if (!activeReportId || scope.status === "loading" || steps.length === 0) return null;
  return (
    <nav aria-label={t.shell.navIntakeSteps} style={{ display: "grid", gap: 2, alignContent: "start" }}>
      {/* 报告级去向：用户在编制页最常找不到「生成的报告在哪看」。
          与步骤组分开陈述，两条目的区别用说明行直说：当前这份报告 vs 账户全部报告；
          标签事实源归 lib/report-navigation-labels。 */}
      <div
        style={{
          fontSize: "var(--text-overline-size)",
          fontWeight: 500,
          letterSpacing: ".06em",
          color: "var(--muted-foreground)",
          padding: "0 10px",
          marginBottom: 8,
        }}
      >
        {t.shell.navReports}
      </div>
      {REPORT_NAVIGATION_ENTRIES.map((entry) => (
        <ReportLevelLink
          key={entry.id}
          href={entry.href}
          label={reportNavigationLabel(t, entry.id)}
          active={pathname === entry.href}
        />
      ))}
      <div
        aria-hidden
        style={{ height: 1, background: "var(--border)", margin: "10px 10px 12px" }}
      />
      <div
        style={{
          fontSize: "var(--text-overline-size)",
          fontWeight: 500,
          letterSpacing: ".06em",
          color: "var(--muted-foreground)",
          padding: "0 10px",
          marginBottom: 8,
        }}
      >
        {t.shell.navIntakeSteps}
      </div>
      {steps.map((step, index) => {
        const areaStatus = areaStatusFor(preparation, step.href);
        // 必填是门禁事实，读服务端准备投影；投影未到达时回退步骤静态声明。
        // questions 路径下议题信息是否成为生成门禁由服务端判定，静态声明表达不了。
        const area = preparation?.areas.find(
          (candidate) => AREA_HREF[candidate.id] === step.href,
        );
        const isRequired = area?.required_for_generation ?? step.required ?? false;
        const isCurrent = index === currentIndex;
        const state: "done" | "current" | "pending" = isCurrent
          ? "current"
          : areaStatus === "ready"
            ? "done"
            : "pending";
        const itemStyle: CSSProperties = {
          display: "flex",
          alignItems: "center",
          gap: 9,
          padding: "8px 10px",
          borderRadius: "var(--radius-control)",
          background: isCurrent ? "var(--accent-subtle)" : "transparent",
          textDecoration: "none",
        };
        const content = (
          <>
            <StepDot state={state} index={index + 1} />
            <span
              style={{
                fontSize: "var(--text-label-size)",
                fontWeight: isCurrent
                  ? ("var(--font-weight-semibold)" as CSSProperties["fontWeight"])
                  : 400,
                color: isCurrent ? "var(--accent)" : "var(--foreground-secondary)",
                whiteSpace: "nowrap",
              }}
            >
              {stepShortLabel(t, step.key)}
            </span>
            {isRequired ? (
              <span
                style={{
                  fontSize: "var(--text-overline-size)",
                  color: "var(--destructive)",
                  alignSelf: "flex-start",
                  lineHeight: 1.4,
                }}
              >
                {t.shell.obligationRequired}
              </span>
            ) : null}
          </>
        );
        // 二级标题：仅当前步骤展开其页面区块（锚点跳转 + 必填/选填标记），
        // 让用户在导航面一眼看到本页哪些必填、哪些选填。
        const subSections =
          isCurrent && step.href === "/intake/info" && app
            ? visibleIntakeInfoSections(app.report).filter(
                (section) =>
                  section.id !== "section-company-profile" ||
                  (app?.report.intakeItems ?? []).some((item) => item.key === "company_profile"),
              )
            : [];
        // 步骤级二级条目（当前仅第 4 步「定性信息」）：所选路径的实际页面是该步的
        // 下级，不是替代它的同级步骤。已选路径后常驻展开，不随当前停留步收起——
        // 用户随时能看到这条路径后续还有哪几页。
        const stepSections = step.sections ?? [];
        // 当前二级条目：按最长前缀选出唯一命中项，避免父路径与子路径同时点亮。
        const activeSectionHref = stepSections.reduce<string | null>((best, section) => {
          if (!pathname) return best;
          if (pathname !== section.href && !pathname.startsWith(`${section.href}/`)) return best;
          return best === null || section.href.length > best.length ? section.href : best;
        }, null);
        return (
          <Fragment key={step.href}>
            <Link
              href={step.href}
              aria-current={isCurrent ? "step" : undefined}
              style={itemStyle}
            >
              {content}
            </Link>
            {stepSections.length > 0 ? (
              <div style={{ display: "grid", gap: 1, padding: "2px 0 6px" }}>
                {stepSections.map((section) => {
                  // 最长前缀命中者唯一高亮：/materials 是 /materials/processing 的前缀，
                  // 按「前缀即命中」会把两条同时点亮，与步骤级同一判据。
                  const active = section.href === activeSectionHref;
                  return (
                    <Link
                      key={section.href}
                      href={section.href}
                      aria-current={active ? "page" : undefined}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 10px 4px 37px",
                        borderRadius: "var(--radius-control)",
                        textDecoration: "none",
                        fontSize: "var(--text-supporting-size)",
                        background: active ? "var(--accent-subtle)" : "transparent",
                        color: active ? "var(--accent)" : "var(--foreground-secondary)",
                      }}
                    >
                      <span style={{ whiteSpace: "nowrap" }}>{stepShortLabel(t, section.key)}</span>
                    </Link>
                  );
                })}
              </div>
            ) : null}
            {subSections.length > 0 ? (
              <div style={{ display: "grid", gap: 1, padding: "2px 0 6px" }}>
                {subSections.map((section) => (
                  <a
                    key={section.id}
                    href={`#${section.id}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "4px 10px 4px 37px",
                      borderRadius: "var(--radius-control)",
                      textDecoration: "none",
                      fontSize: "var(--text-supporting-size)",
                      color: "var(--foreground-secondary)",
                    }}
                  >
                    <span style={{ whiteSpace: "nowrap" }}>{t.intakeInfoSections[section.id as keyof typeof t.intakeInfoSections]}</span>
                    <span
                      style={{
                        fontSize: "var(--text-overline-size)",
                        color: section.obligation === "required" ? "var(--destructive)" : "var(--muted-foreground)",
                        lineHeight: 1.4,
                      }}
                    >
                      {section.obligation === "required" ? t.shell.obligationRequired : t.shell.obligationOptional}
                    </span>
                  </a>
                ))}
              </div>
            ) : null}
          </Fragment>
        );
      })}
    </nav>
  );
}
