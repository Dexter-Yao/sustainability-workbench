// ABOUTME: 就地提示唯一实现（design.md §4 InlineAlert）：左 3px 语义色竖规 + 6% 底 + 形状图标 + 文字，
// ABOUTME: 取代散落的裸色文字；错误提示不得降级为中性色。
"use client";

import type { CSSProperties, ReactNode } from "react";
import { StatusDot, type StatusDotKind } from "./StatusDot";

export type InlineAlertVariant = "error" | "warning" | "success";

const VARIANT_SPEC: Record<
  InlineAlertVariant,
  { rule: string; background: string; dot: StatusDotKind; role: "alert" | "status" }
> = {
  error: { rule: "var(--destructive)", background: "var(--destructive-surface)", dot: "blocked", role: "alert" },
  warning: { rule: "var(--warning)", background: "var(--warning-surface)", dot: "attention", role: "status" },
  success: { rule: "var(--success)", background: "var(--success-surface)", dot: "done", role: "status" },
};

export function InlineAlert({
  variant,
  children,
  style,
}: {
  variant: InlineAlertVariant;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const spec = VARIANT_SPEC[variant];
  return (
    <div
      role={spec.role}
      className="gs-alert-enter"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "11px 14px",
        borderLeft: `3px solid ${spec.rule}`,
        background: spec.background,
        ...style,
      }}
    >
      <StatusDot kind={spec.dot} style={{ marginTop: 5 }} />
      <div
        style={{
          fontSize: "var(--text-label-size)",
          lineHeight: 1.75,
          color: "var(--foreground-secondary)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
