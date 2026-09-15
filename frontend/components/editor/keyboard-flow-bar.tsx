// ABOUTME: 报告正文键盘流的底部固定条 + 单一说明面板（design.md §5.5「说明只放一处」、dc.html §04）。
// ABOUTME: 只读 editor-shortcuts 目录渲染按平台键位；不持有键盘行为，行为在工作台 DocPane 内处理。
"use client";

import { type CSSProperties } from "react";

import { renderKeys, SHORTCUTS, type KeyToken, type Platform, type ShortcutId } from "@/lib/editor-shortcuts";
import { useT } from "@/lib/i18n/locale-context";
import type { Dictionary } from "@/lib/i18n/dictionary";

const kbd: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  lineHeight: "16px",
  color: "var(--foreground)",
  background: "var(--surface-sunken)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-control)",
  padding: "1px 6px",
  whiteSpace: "nowrap",
};

function Keys({ keys, platform }: { keys: KeyToken[]; platform: Platform }) {
  return <span style={kbd}>{renderKeys(keys, platform)}</span>;
}

function keysOf(id: ShortcutId): KeyToken[] {
  return SHORTCUTS.find((s) => s.id === id)!.keys;
}

// 文案随界面语言变化，故按 t 派生而非模块级常量——常量在模块求值期就定死，读不到字典。
function barHints(t: Dictionary): { id: ShortcutId; text: string }[] {
  return [
    { id: "select", text: t.keyboardFlow.hintSelect },
    { id: "edit", text: t.keyboardFlow.hintEdit },
    { id: "done", text: t.keyboardFlow.hintDone },
    { id: "save", text: t.keyboardFlow.hintSave },
  ];
}

export function KeyboardFlowBar({
  platform,
  onPlatformChange,
  helpOpen,
  onToggleHelp,
}: {
  platform: Platform;
  onPlatformChange: (platform: Platform) => void;
  helpOpen: boolean;
  onToggleHelp: () => void;
}) {
  const t = useT();
  return (
    <>
      {helpOpen ? <HelpPanel platform={platform} onPlatformChange={onPlatformChange} onClose={onToggleHelp} /> : null}
      <div
        style={{
          position: "fixed",
          left: "50%",
          bottom: 16,
          transform: "translateX(-50%)",
          zIndex: 40,
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          justifyContent: "center",
          maxWidth: "calc(100vw - 32px)",
          gap: 16,
          background: "var(--background)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-pill)",
          boxShadow: "var(--shadow-overlay)",
          padding: "8px 18px",
          fontSize: 13,
          color: "var(--muted-foreground)",
          fontFamily: "var(--font-sans)",
        }}
      >
        {barHints(t).map((hint) => (
          <span key={hint.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
            <Keys keys={keysOf(hint.id)} platform={platform} />
            {hint.text}
          </span>
        ))}
        <button
          onClick={onToggleHelp}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            border: "none",
            background: "transparent",
            color: helpOpen ? "var(--accent)" : "var(--muted-foreground)",
            fontSize: 13,
            cursor: "pointer",
            padding: 0,
          }}
        >
          <Keys keys={keysOf("help")} platform={platform} />
          {t.keyboardFlow.allShortcuts}
        </button>
      </div>
    </>
  );
}

function legend(t: Dictionary): { swatch: CSSProperties; title: string; desc: string }[] {
  return [
    { swatch: { color: "var(--foreground)" }, title: t.keyboardFlow.legendInkTitle, desc: t.keyboardFlow.legendInkDesc },
    { swatch: { color: "var(--muted-foreground)" }, title: t.keyboardFlow.legendLockedTitle, desc: t.keyboardFlow.legendLockedDesc },
    {
      swatch: { color: "var(--field-foreground)", background: "var(--field-background)", borderRadius: 3, padding: "0 4px" },
      title: t.keyboardFlow.legendFieldTitle,
      desc: t.keyboardFlow.legendFieldDesc,
    },
  ];
}

function HelpPanel({
  platform,
  onPlatformChange,
  onClose,
}: {
  platform: Platform;
  onPlatformChange: (platform: Platform) => void;
  onClose: () => void;
}) {
  const t = useT();
  const groups: { key: "select_edit" | "common"; title: string }[] = [
    { key: "select_edit", title: t.keyboardFlow.groupSelectEdit },
    { key: "common", title: t.keyboardFlow.groupCommon },
  ];
  return (
    <div
      role="dialog"
      aria-label={t.keyboardFlow.panelLabel}
      style={{
        position: "fixed",
        left: "50%",
        bottom: 76,
        transform: "translateX(-50%)",
        zIndex: 41,
        width: 460,
        maxWidth: "calc(100vw - 32px)",
        background: "var(--background)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-container)",
        boxShadow: "var(--shadow-modal)",
        padding: 20,
        fontFamily: "var(--font-sans)",
        color: "var(--foreground)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", marginBottom: 12 }}>
        <h2 style={{ fontSize: "var(--text-subsection-size)", fontWeight: 600, margin: 0, marginRight: "auto" }}>{t.keyboardFlow.panelHeading}</h2>
        <button onClick={onClose} style={{ border: "none", background: "transparent", color: "var(--muted-foreground)", fontSize: 13, cursor: "pointer", padding: 0 }}>
          {t.keyboardFlow.close}
        </button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", letterSpacing: "0.04em" }}>{t.keyboardFlow.legendHeading}</div>
        {legend(t).map((item) => (
          <div key={item.title} style={{ fontSize: 13, lineHeight: 1.6 }}>
            <span style={item.swatch}>{item.title}</span>
            <span style={{ color: "var(--muted-foreground)" }}>　{item.desc}</span>
          </div>
        ))}
      </div>

      {groups.map((group) => (
        <div key={group.key} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, color: "var(--muted-foreground)", letterSpacing: "0.04em", marginBottom: 6 }}>{group.title}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {SHORTCUTS.filter((s) => s.group === group.key).map((s) => (
              <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 13 }}>
                <span style={{ ...kbd, minWidth: 96, textAlign: "center" }}>{renderKeys(s.keys, platform)}</span>
                <span style={{ color: "var(--muted-foreground)" }}>{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: 10, borderTop: "1px solid var(--border)", paddingTop: 12, fontSize: 13 }}>
        <span style={{ color: "var(--muted-foreground)" }}>{t.keyboardFlow.platformHint}</span>
        {(["mac", "windows"] as Platform[]).map((p) => (
          <button
            key={p}
            onClick={() => onPlatformChange(p)}
            style={{
              border: `1px solid ${platform === p ? "var(--accent)" : "var(--border)"}`,
              background: platform === p ? "var(--accent-subtle)" : "var(--background)",
              color: platform === p ? "var(--accent-hover)" : "var(--muted-foreground)",
              borderRadius: "var(--radius-control)",
              fontSize: 12,
              padding: "3px 12px",
              cursor: "pointer",
            }}
          >
            {p === "mac" ? "⌘ Mac" : "⊞ Windows"}
          </button>
        ))}
      </div>
    </div>
  );
}
