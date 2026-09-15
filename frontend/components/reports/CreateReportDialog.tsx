// ABOUTME: 新建报告时选择报告类型（知识包 = 准则 × 语言）的对话框；清单与默认项均由服务端投影，前端不硬编码。
// ABOUTME: 与 ConfirmDialog 同用原生 <dialog>（焦点陷阱、Esc、遮罩关闭），但承载单选表单而非纯确认语义。
"use client";

import { useEffect, useRef, type CSSProperties } from "react";

import { Button } from "@/components/ui/Button";
import type { ReportProfileOption } from "@/lib/report-store";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";

export function CreateReportDialog({
  open,
  options,
  selectedProfileId,
  creating,
  onSelect,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  options: ReportProfileOption[];
  selectedProfileId: string | null;
  creating: boolean;
  onSelect: (profileId: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const t = useT();
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
        if (event.target === dialogRef.current) onCancel();
      }}
      style={{
        // 与 ConfirmDialog 同因：Tailwind preflight 清零 margin 后须显式恢复 UA 的视口居中。
        margin: "auto",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-container)",
        boxShadow: "var(--shadow-modal)",
        padding: 0,
        maxWidth: 460,
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
          }}
        >
          {t.createReport.heading}
        </h2>
        <p
          style={{
            margin: "0 0 14px",
            fontSize: "var(--text-supporting-size)",
            color: "var(--muted-foreground)",
            lineHeight: 1.6,
          }}
        >
          {t.createReport.body}
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {options.map((option) => (
            <label
              key={option.report_profile_id}
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                padding: "10px 12px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-control)",
                cursor: creating ? "default" : "pointer",
                fontSize: "var(--text-body-size)",
                lineHeight: 1.5,
              }}
            >
              <input
                type="radio"
                name="reportProfile"
                value={option.report_profile_id}
                checked={selectedProfileId === option.report_profile_id}
                disabled={creating}
                onChange={() => onSelect(option.report_profile_id)}
                style={{ marginTop: 3 }}
              />
              {/* 准则名按包（产品资产，各包用自己的语言），内容语言名按界面语言：
                  整串写在服务端会让英文界面渲染出「上海证券交易所… · 简体中文」的混排。 */}
              <span>
                {interpolate(t.createReport.optionLabel, {
                  standard: option.display_name,
                  language: t.createReport.contentLanguage[option.language],
                })}
              </span>
            </label>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <Button
            variant="secondary"
            onClick={onCancel}
            disabled={creating}
            disabledReason={creating ? t.createReport.creating : undefined}
          >
            {t.createReport.cancel}
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            disabled={creating || !selectedProfileId}
            disabledReason={creating ? t.createReport.creating : !selectedProfileId ? t.createReport.selectFirst : undefined}
          >
            {creating ? t.createReport.confirming : t.createReport.confirm}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
