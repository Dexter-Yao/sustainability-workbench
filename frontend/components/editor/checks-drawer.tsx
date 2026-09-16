// ABOUTME: 导出前校验抽屉：列出阻断项（必填缺失）与建议项（要点缺失/疑似数字），可跳转到位置，人工确认后导出。
// ABOUTME: 阻断项存在时禁止导出（与服务端 fail-loud 一致）；建议项仅提示、不拦截。
// ABOUTME: 动态标题过期是唯一能在本抽屉内自助清除的阻断项（design.md §5.4 的前两项处理）。
"use client";

import type { Issue } from "@/lib/api";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { issueMessage } from "@/lib/issue-message";

import { SideDrawer } from "./side-drawer";

/** 动态标题过期的 issue code；它的处理入口就在本抽屉，不需要跳走。 */
const STALE_TITLE_CODE = "stale_display_title";

/** issue.path 形如 `sections.<key>.displayTitle`，第二段即章节 key。 */
function sectionKeyOf(issue: Issue): string | null {
  if (issue.sectionKey) return issue.sectionKey;
  const parts = (issue.path ?? "").split(".");
  return parts[0] === "sections" && parts[1] ? parts[1] : null;
}

export function ChecksDrawer({
  issues,
  exporting,
  onConfirm,
  onClose,
  onJump,
  onKeepTitle,
  onEditTitle,
}: {
  issues: Issue[];
  exporting: boolean;
  onConfirm: () => void;
  onClose: () => void;
  onJump: (issue: Issue) => void;
  /** 按当前正文重新确认该章节标题；省略即不提供该动作。 */
  onKeepTitle?: (sectionKey: string) => void;
  /** 由用户给出标题文本；省略即不提供该动作。 */
  onEditTitle?: (sectionKey: string) => void;
}) {
  const t = useT();
  const blocks = issues.filter((i) => i.level === "block");
  const warns = issues.filter((i) => i.level === "warn");

  const actionButton = (label: string, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: "1px solid var(--border)",
        background: "var(--background)",
        color: "var(--foreground-secondary)",
        borderRadius: "var(--radius-control)",
        fontSize: 12,
        padding: "3px 8px",
        cursor: "pointer",
        flexShrink: 0,
      }}
    >
      {label}
    </button>
  );

  const row = (issue: Issue, i: number, color: string) => {
    const sectionKey = issue.code === STALE_TITLE_CODE ? sectionKeyOf(issue) : null;
    const remedies = sectionKey
      ? [
          onKeepTitle ? actionButton(t.checksDrawer.keepTitle, () => onKeepTitle(sectionKey)) : null,
          onEditTitle ? actionButton(t.checksDrawer.editTitle, () => onEditTitle(sectionKey)) : null,
        ].filter(Boolean)
      : [];

    return (
      <div
        key={`${issue.code}-${i}`}
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          padding: "8px 0",
          borderBottom: "1px solid var(--border)",
          fontSize: 13,
          color: "var(--foreground-secondary)",
          lineHeight: 1.6,
        }}
      >
        <span style={{ color, marginTop: 2, flexShrink: 0 }}>●</span>
        <button
          onClick={() => onJump(issue)}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            marginRight: "auto",
            textAlign: "left",
            border: "none",
            background: "transparent",
            cursor: "pointer",
            padding: 0,
            fontSize: 13,
            color: "inherit",
            lineHeight: 1.6,
          }}
        >
          <span>{issueMessage(issue, t)}</span>
          <span aria-hidden style={{ color: "var(--accent)", flexShrink: 0 }}>
            →
          </span>
        </button>
        {remedies}
      </div>
    );
  };

  return (
    <SideDrawer labelId="export-checks-title" onClose={onClose} width={380}>
        <div style={{ display: "flex", alignItems: "center", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
          <strong id="export-checks-title" style={{ fontSize: "var(--text-subsection-size)", marginRight: "auto" }}>{t.checksDrawer.heading}</strong>
          <button data-drawer-initial-focus onClick={onClose} aria-label={t.checksDrawer.close} style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: "var(--text-glyph-size)", color: "var(--muted-foreground)" }}>
            ✕
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
          {issues.length === 0 ? (
            <p style={{ fontSize: 13, color: "var(--success)", lineHeight: 1.7, borderLeft: "2px solid var(--border)", paddingLeft: 8, margin: "0 0 12px" }}>{t.checksDrawer.clean}</p>
          ) : null}

          {blocks.length ? (
            <section style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 12, fontWeight: 600, color: "var(--destructive)", margin: "0 0 4px" }}>
                {interpolate(t.checksDrawer.blockingHeading, { count: blocks.length })}
              </h3>
              {blocks.map((it, i) => row(it, i, "var(--destructive)"))}
            </section>
          ) : null}

          {warns.length ? (
            <section>
              <h3 style={{ fontSize: 12, fontWeight: 600, color: "var(--warning)", margin: "0 0 4px" }}>
                {interpolate(t.checksDrawer.warnHeading, { count: warns.length })}
              </h3>
              {warns.map((it, i) => row(it, i, "var(--warning)"))}
            </section>
          ) : null}
        </div>

        <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
          {blocks.length ? (
            <div style={{ fontSize: 12, color: "var(--destructive)", marginBottom: 8, borderLeft: "2px solid var(--border)", paddingLeft: 8 }}>
              {interpolate(t.checksDrawer.blockingFooter, { count: blocks.length })}
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              onClick={onClose}
              style={{ border: "1px solid var(--border)", background: "var(--background)", color: "var(--foreground-secondary)", borderRadius: "var(--radius-control)", fontSize: 13, padding: "6px 14px", cursor: "pointer" }}
            >
              {t.checksDrawer.cancel}
            </button>
            <button
              onClick={onConfirm}
              disabled={exporting || blocks.length > 0}
              style={{
                border: `1px solid var(--accent)`,
                background: "var(--accent)",
                color: "var(--accent-foreground)",
                borderRadius: "var(--radius-control)",
                fontSize: 13,
                padding: "6px 14px",
                cursor: "pointer",
                opacity: exporting || blocks.length > 0 ? 0.5 : 1,
              }}
            >
              {exporting ? t.checksDrawer.exporting : t.checksDrawer.confirm}
            </button>
          </div>
        </div>
    </SideDrawer>
  );
}
