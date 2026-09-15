// ABOUTME: 折叠区原语（design.md §3.1 可发现性四条）：有边界、▸/▾ 可供性、中性配色、
// ABOUTME: 一句「后果型备注」只在收起态显示于标签右侧同行。
"use client";

import { useState, type CSSProperties, type ReactNode } from "react";

export function Collapse({
  label,
  consequenceNote,
  defaultOpen = false,
  children,
  style,
}: {
  label: string;
  /** 后果型备注：收起态显示在标签右侧同行（如「不填不影响生成」）。 */
  consequenceNote?: string;
  defaultOpen?: boolean;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [hovered, setHovered] = useState(false);

  return (
    <div style={style}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          padding: "10px 14px",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-control)",
          background: hovered ? "var(--accent-subtle)" : "var(--surface-sunken)",
          cursor: "pointer",
          textAlign: "left",
          fontFamily: "inherit",
          transition: "background .12s",
        }}
      >
        <span
          style={{
            fontSize: "var(--text-body-size)",
            fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
            color: "var(--foreground)",
          }}
        >
          {open ? "▾" : "▸"} {label}
        </span>
        {!open && consequenceNote ? (
          <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
            {consequenceNote}
          </span>
        ) : null}
      </button>
      {open ? <div style={{ marginTop: 16 }}>{children}</div> : null}
    </div>
  );
}
