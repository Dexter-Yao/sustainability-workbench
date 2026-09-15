// ABOUTME: 状态标签唯一实现（design.md §4）：20px 高、语义色 10% 底 + 饱和字；
// ABOUTME: 状态文字取服务端投影的中文语义，前端不自造措辞。
"use client";

import type { CSSProperties, ReactNode } from "react";

export type BadgeVariant = "success" | "generating" | "attention" | "blocked" | "neutral";

const VARIANT_COLORS: Record<BadgeVariant, { background: string; color: string }> = {
  success: { background: "var(--accent-subtle)", color: "var(--accent)" },
  generating: { background: "var(--ai-subtle)", color: "var(--ai)" },
  attention: { background: "var(--warning-subtle)", color: "var(--warning)" },
  blocked: { background: "var(--destructive-subtle)", color: "var(--destructive)" },
  neutral: { background: "var(--surface-sunken)", color: "var(--muted-foreground)" },
};

export function Badge({
  variant,
  children,
  style,
}: {
  variant: BadgeVariant;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <span
      style={{
        height: 20,
        display: "inline-flex",
        alignItems: "center",
        padding: "0 8px",
        borderRadius: "var(--radius-pill)",
        fontSize: "var(--text-overline-size)",
        fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
        whiteSpace: "nowrap",
        ...VARIANT_COLORS[variant],
        ...style,
      }}
    >
      {children}
    </span>
  );
}
