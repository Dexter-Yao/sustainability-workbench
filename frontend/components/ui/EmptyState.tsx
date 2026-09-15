// ABOUTME: 空状态原语（design.md §4）：线性单色图标（可选）+ 一句话说明 + 主操作按钮（可选）；
// ABOUTME: 不使用插画、装饰卡片或营销文案，文案用动词引导下一步。
"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { Button } from "./Button";

export function EmptyState({
  icon,
  title,
  description,
  action,
  style,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: { label: string; onClick?: () => void; href?: string; primary?: boolean };
  style?: CSSProperties;
}) {
  const actionButton = action ? (
    action.href ? (
      <Link
        href={action.href}
        style={{
          display: "inline-block",
          border: "1px solid var(--accent)",
          background: action.primary === false ? "var(--background)" : "var(--accent)",
          color: action.primary === false ? "var(--accent)" : "var(--accent-foreground)",
          borderRadius: "var(--radius-control)",
          padding: "9px 22px",
          fontSize: "var(--text-body-size)",
          fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
          textDecoration: "none",
        }}
      >
        {action.label}
      </Link>
    ) : (
      <Button variant={action.primary === false ? "secondary" : "primary"} onClick={action.onClick}>
        {action.label}
      </Button>
    )
  ) : null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "48px 0",
        ...style,
      }}
    >
      {icon ? <div style={{ marginBottom: 16, color: "var(--muted-foreground)" }}>{icon}</div> : null}
      <h3
        style={{
          margin: "0 0 8px",
          fontSize: "var(--text-subsection-size)",
          fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
          color: "var(--foreground)",
        }}
      >
        {title}
      </h3>
      {description ? (
        <p
          style={{
            margin: "0 0 16px",
            fontSize: "var(--text-label-size)",
            lineHeight: 1.7,
            color: "var(--muted-foreground)",
            maxWidth: 384,
          }}
        >
          {description}
        </p>
      ) : null}
      {actionButton}
    </div>
  );
}
