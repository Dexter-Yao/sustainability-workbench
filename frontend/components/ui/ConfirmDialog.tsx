// ABOUTME: 破坏性操作确认对话框唯一实现（design.md §4.0.1 规则③）：取代 window.confirm；
// ABOUTME: 原生 <dialog> 承载焦点陷阱与 Esc，遮罩点击关闭，关闭后浏览器自动恢复触发控件焦点。
"use client";

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { Button } from "./Button";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "取消",
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={(event) => {
        // 点击遮罩（dialog 自身而非内容）关闭。
        if (event.target === dialogRef.current) onCancel();
      }}
      style={{
        // Tailwind preflight 会清零所有元素 margin，而原生 <dialog> 的视口居中依赖 UA 的
        // margin: auto——必须显式恢复，否则弹窗贴左上角。
        margin: "auto",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-container)",
        boxShadow: "var(--shadow-modal)",
        padding: 0,
        maxWidth: 420,
        width: "calc(100vw - 48px)",
        background: "var(--background)",
        color: "var(--foreground)",
      }}
    >
      <div style={{ padding: "20px 22px" }}>
        <h2
          style={{
            margin: "0 0 8px",
            fontSize: "var(--text-section-size)",
            fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
            color: "var(--foreground)",
          }}
        >
          {title}
        </h2>
        {description ? (
          <p
            style={{
              margin: 0,
              fontSize: "var(--text-label-size)",
              lineHeight: 1.75,
              color: "var(--foreground-secondary)",
            }}
          >
            {description}
          </p>
        ) : null}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button variant={destructive ? "destructive" : "primary"} size="sm" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
