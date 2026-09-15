// ABOUTME: 按钮四级唯一实现（design.md §4.0.1）：primary 每屏至多一个（dev 断言）、置灰必须给
// ABOUTME: disabledReason 同行原因、destructive 只描边绝不实心；破坏性确认走 ConfirmDialog。
"use client";

import { useEffect, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "text" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT_STYLE: Record<ButtonVariant, CSSProperties> = {
  primary: {
    border: "1px solid var(--accent)",
    background: "var(--accent)",
    color: "var(--accent-foreground)",
  },
  secondary: {
    border: "1px solid var(--border-strong)",
    background: "var(--background)",
    color: "var(--foreground-secondary)",
  },
  text: {
    border: 0,
    background: "transparent",
    color: "var(--accent)",
  },
  destructive: {
    border: "1px solid var(--destructive)",
    background: "var(--background)",
    color: "var(--destructive)",
  },
};

const SIZE_PADDING: Record<ButtonSize, string> = {
  sm: "7px 14px",
  md: "9px 22px",
  lg: "10px 24px",
};

export function Button({
  variant,
  size = "md",
  disabled,
  disabledReason,
  children,
  style,
  type = "button",
  ...rest
}: {
  variant: ButtonVariant;
  size?: ButtonSize;
  /** disabled 为真时必填：同行渲染为 --warning 12px 文字，说明为什么不可用。 */
  disabledReason?: string;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    if (variant !== "primary") return;
    const count = document.querySelectorAll('[data-gs-button-variant="primary"]').length;
    if (count > 1) {
      console.error(
        `design.md §4.0.1 违规：当前路由渲染树中出现 ${count} 个 variant="primary" 按钮（应至多一个）。`,
      );
    }
  });

  if (process.env.NODE_ENV !== "production" && disabled && !disabledReason) {
    console.error("design.md §4.0.1 违规：disabled 按钮必须提供 disabledReason。", children);
  }

  const button = (
    <button
      type={type}
      disabled={disabled}
      data-gs-button-variant={variant}
      style={{
        ...VARIANT_STYLE[variant],
        borderRadius: "var(--radius-control)",
        padding: variant === "text" ? "9px 4px" : SIZE_PADDING[size],
        fontSize: "var(--text-body-size)",
        fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
        fontFamily: "inherit",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transition: "background .12s, border-color .12s, color .12s",
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );

  if (disabled && disabledReason) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
        {button}
        <span
          style={{
            fontSize: "var(--text-supporting-size)",
            color: "var(--warning)",
            lineHeight: 1.5,
          }}
        >
          {disabledReason}
        </span>
      </span>
    );
  }
  return button;
}
