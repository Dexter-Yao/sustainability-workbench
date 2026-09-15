// ABOUTME: 状态点形状编码唯一实现（design.md §4 三重编码）：颜色之外用形状区分——实心圆/脉冲/
// ABOUTME: 空心环/三角，供步骤条、清单行、文件结果卡复用；文字通道由调用方并列提供。
"use client";

import type { CSSProperties } from "react";

export type StatusDotKind = "done" | "active" | "attention" | "pending" | "blocked";

export function StatusDot({ kind, size = 8, style }: { kind: StatusDotKind; size?: number; style?: CSSProperties }) {
  const base: CSSProperties = { flexShrink: 0, display: "inline-block", ...style };
  switch (kind) {
    case "done":
      return (
        <span
          aria-hidden
          style={{ ...base, width: size, height: size, borderRadius: "50%", background: "var(--success)" }}
        />
      );
    case "active":
      return (
        <span
          aria-hidden
          className="gs-status-pulse"
          style={{
            ...base,
            width: size,
            height: size,
            borderRadius: "50%",
            background: "var(--success)",
            boxShadow: "0 0 0 3px var(--accent-subtle)",
          }}
        />
      );
    case "attention":
      return (
        <span
          aria-hidden
          style={{
            ...base,
            width: size,
            height: size,
            borderRadius: "50%",
            border: "2px solid var(--warning)",
            boxSizing: "border-box",
            background: "transparent",
          }}
        />
      );
    case "blocked":
      return (
        <span
          aria-hidden
          style={{
            ...base,
            width: size + 1,
            height: size + 1,
            background: "var(--destructive)",
            clipPath: "polygon(50% 0, 100% 100%, 0 100%)",
          }}
        />
      );
    case "pending":
    default:
      return (
        <span
          aria-hidden
          style={{ ...base, width: size, height: size, borderRadius: "50%", background: "var(--border-strong)" }}
        />
      );
  }
}
