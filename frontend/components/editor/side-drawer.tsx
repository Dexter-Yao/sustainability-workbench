// ABOUTME: 编辑工作台的模态侧抽屉基础组件——管理遮罩、初始焦点、焦点约束、Esc 关闭和焦点恢复。
// ABOUTME: 仅承载交互可访问性与容器样式；业务标题、内容与操作仍由各抽屉拥有。
"use client";

import { useEffect, useRef, type ReactNode } from "react";

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function SideDrawer({
  labelId,
  onClose,
  width,
  children,
}: {
  labelId: string;
  onClose: () => void;
  width: number;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTarget = panelRef.current?.querySelector<HTMLElement>("[data-drawer-initial-focus]") ?? panelRef.current;
    focusTarget?.focus();
    return () => returnFocusRef.current?.focus();
  }, []);

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(25, 33, 29, 0.25)" }}
      onClick={onClose}
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
            return;
          }
          if (event.key !== "Tab") return;
          const focusables = [...(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
          if (!focusables.length) {
            event.preventDefault();
            panelRef.current?.focus();
            return;
          }
          const first = focusables[0];
          const last = focusables.at(-1)!;
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          height: "100vh",
          width,
          maxWidth: "92vw",
          background: "var(--background)",
          boxShadow: "-2px 0 16px rgba(25, 33, 29, 0.12)",
          display: "flex",
          flexDirection: "column",
          fontFamily: "var(--font-sans)",
        }}
      >
        {children}
      </aside>
    </div>
  );
}
