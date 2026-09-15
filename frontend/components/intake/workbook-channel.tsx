// ABOUTME: 分步页 Excel 双通道的共享实现（design.md §3.1）：「下载{表名}模板」+「导入{表名}」+ 整行拖拽。
// ABOUTME: 导入先经 ConfirmDialog 确认覆盖语义（全通道统一措辞），再 persistNow 落定在线草稿并取乐观锁序号，成功后以服务端权威 state 重建本地报告。
"use client";

import { useState, type CSSProperties } from "react";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FileDropZone } from "@/components/ui/FileDropZone";
import { useApp } from "@/lib/app-context";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import type { StructuredInputMutationResponse } from "@/lib/report-api.generated";

const ACCEPT = ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** 页面用于展示操作结果的回调；错误信息已按单元格投影格式化。 */
export interface WorkbookChannelNote {
  kind: "success" | "error";
  text: string;
}

export function WorkbookChannel({
  tableLabel,
  onDownload,
  onImport,
  onNote,
  successText,
}: {
  /** 表名（如「议题信息表」），拼入「下载{表名}模板」「导入{表名}」。 */
  tableLabel: string;
  onDownload: (reportId: string) => Promise<void>;
  onImport: (
    reportId: string,
    file: File,
    expectedStateSeq: number,
  ) => Promise<StructuredInputMutationResponse>;
  onNote: (note: WorkbookChannelNote | null) => void;
  successText: string;
}) {
  const t = useT();
  const { activeReportId, persistNow, applyAuthoritativeReportState } = useApp();
  const [templateBusy, setTemplateBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  // 导入是整批覆盖动作：文件选定后先经确认对话框，与报告列表统一册导入同一语义与措辞。
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);

  const download = async () => {
    if (!activeReportId) return;
    setTemplateBusy(true);
    onNote(null);
    try {
      await onDownload(activeReportId);
    } catch (error) {
      // 异常细节进控制台：用户可见文案只承载稳定措辞，不透传后端原文（那会让
      // 异常消息隐式成为用户契约，且英文界面下必然露出后端中文）。
      console.error("Workbook template download failed", error);
      onNote({
        kind: "error",
        text: interpolate(t.workbookChannel.templateDownloadFailed, { table: tableLabel }),
      });
    } finally {
      setTemplateBusy(false);
    }
  };

  const importFile = async (file: File) => {
    if (!activeReportId) return;
    setImportBusy(true);
    onNote(null);
    try {
      // 先落定在线草稿：导入是整批替换，页面上尚未保存的修改必须先成为权威状态的一部分。
      const expectedStateSeq = await persistNow();
      const mutation = await onImport(activeReportId, file, expectedStateSeq);
      await applyAuthoritativeReportState(mutation.state, mutation.state_seq);
      onNote({ kind: "success", text: successText });
    } catch (error) {
      console.error("Workbook import failed", error);
      onNote({
        kind: "error",
        text: interpolate(t.workbookChannel.importFailed, { table: tableLabel }),
      });
    } finally {
      setImportBusy(false);
    }
  };

  const disabled = !activeReportId || importBusy;

  return (
    <div style={{ padding: "12px 0 16px", borderBottom: "1px solid var(--border)" }}>
      <Button
        variant="secondary"
        size="sm"
        disabled={templateBusy || !activeReportId}
        disabledReason={templateBusy ? t.workbookChannel.generatingTemplate : t.workbookChannel.reportLoading}
        onClick={() => void download()}
      >
        {templateBusy ? t.workbookChannel.preparingTemplate : interpolate(t.workbookChannel.downloadTemplate, { table: tableLabel })}
      </Button>
      {/* 拖放目标必须自己可见：若整条工具条是隐形投放区，文案却说「拖入此区域」，
          指向一个看不见的东西。虚线框把该区域画出来，选择文件的入口也收进框内。 */}
      <FileDropZone
        dashed
        disabled={disabled}
        style={{ marginTop: 10 }}
        onFiles={(files) => {
          const file = files.find((candidate) => candidate.name.toLowerCase().endsWith(".xlsx"));
          if (!file) {
            onNote({ kind: "error", text: interpolate(t.workbookChannel.wrongFormat, { table: tableLabel }) });
            return;
          }
          setPendingImportFile(file);
        }}
      >
        <label
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            padding: "14px 16px",
            fontSize: "var(--text-supporting-size)",
            color: "var(--muted-foreground)",
            cursor: disabled ? "not-allowed" : "pointer",
            opacity: disabled ? 0.4 : 1,
          }}
        >
          {importBusy ? (
            interpolate(t.workbookChannel.importing, { table: tableLabel })
          ) : (
            <>
              {t.workbookChannel.dropHint}
              <span
                style={{
                  color: "var(--foreground)",
                  fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
                  textDecoration: "underline",
                  textUnderlineOffset: 2,
                }}
              >
                {t.workbookChannel.chooseFile}
              </span>
            </>
          )}
          <input
            type="file"
            accept={ACCEPT}
            disabled={disabled}
            style={{ display: "none" }}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) setPendingImportFile(file);
              event.target.value = "";
            }}
          />
        </label>
      </FileDropZone>
      <ConfirmDialog
        open={pendingImportFile !== null}
        title={interpolate(t.workbookChannel.confirmTitle, { table: tableLabel })}
        description={t.workbookChannel.confirmBody}
        confirmLabel={t.workbookChannel.confirmAction}
        destructive
        onConfirm={() => {
          const file = pendingImportFile;
          setPendingImportFile(null);
          if (file) void importFile(file);
        }}
        onCancel={() => setPendingImportFile(null)}
      />
    </div>
  );
}
