// ABOUTME: 分步页"选填补充"折叠区的唯一共享实现(design.md §3.1);展开后无二级折叠。
// ABOUTME: 基本信息页默认展开:默认折叠会导致选填内容漏填率高。
"use client";

import { type ReactNode, useState } from "react";
import { useT } from "@/lib/i18n/locale-context";

export function OptionalSupplement({
  label,
  hint,
  defaultOpen = false,
  children,
}: {
  label?: string;
  /** 标题行旁的一句话提示,说明不填的后果(如"不填不影响生成");折叠与展开态均显示。 */
  hint?: string;
  /** 初始是否展开;用户仍可点击整行收起。 */
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const t = useT();
  const [open, setOpen] = useState(defaultOpen);
  const [hovered, setHovered] = useState(false);
  return (
    <section style={{ marginTop: 28 }}>
      {/* 整行可点击并带边界与底色:纯文字按钮不被识别为控件,选填内容因此等同不存在
          (design.md §3.1 可发现性)。配色保持中性——折叠区不是主操作,主色按 §2.1
          只留给主操作按钮、活跃导航项、焦点态、进度与回填高亮。 */}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          flexWrap: "wrap",
          width: "100%",
          textAlign: "left",
          border: "1px solid var(--border)",
          borderRadius: 6,
          background: hovered ? "var(--accent-subtle)" : "var(--surface-sunken)",
          padding: "12px 14px",
          cursor: "pointer",
          fontFamily: "var(--font-sans)",
        }}
      >
        <span style={{ fontSize: "var(--text-body-size)", fontWeight: 500, color: "var(--foreground)" }}>
          <span style={{ marginRight: 6 }}>{open ? "▾" : "▸"}</span>
          {label ?? t.reportConfig.optionalSupplementLabel}
        </span>
        {hint ? (
          <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", fontWeight: 400 }}>
            {hint}
          </span>
        ) : null}
      </button>
      {open ? <div style={{ marginTop: 16 }}>{children}</div> : null}
    </section>
  );
}
