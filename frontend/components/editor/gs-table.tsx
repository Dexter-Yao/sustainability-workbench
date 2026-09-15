// ABOUTME: 统一表格组件（Report 直接作真相、Plate 只是投影）：一套干净三线表样式渲染只读/可编辑表，合并交给 HTML colSpan/rowSpan。
// ABOUTME: 可编辑性逐表逐列派生；生成或用户编辑后的有效内容直接处于 ready，不设置采纳步骤。
"use client";

import { useLayoutEffect, useRef, type CSSProperties } from "react";

import { useT } from "@/lib/i18n/locale-context";
import { useReport } from "@/lib/report-context";
import { isTableEditable } from "@/lib/table-editability";
import type { Block, GsColDef, GsTable, GsTableCell, GsTableRow } from "@/lib/schema";
import { StakeholderEngagementTable } from "./stakeholder-engagement-table";

const INK = "var(--foreground)"; // 可编辑内容墨色
const MUTED = "var(--muted-foreground)"; // 不可编辑内容灰化

function cellText(v: string | string[] | null | undefined): string {
  if (Array.isArray(v)) return v.join("、");
  return v ?? "";
}

function emptyDataRow(colDefs: GsColDef[]): GsTableRow {
  return { type: "tr", children: colDefs.map((c) => ({ type: "td", colKey: c.key, value: null })) };
}

// 列级可编辑：可编辑表内，text 列若来自评估则给定只读（如 IRO 议题列），其余可编辑。
function isColEditable(col: GsColDef, blk: Block, tablesEditable: boolean): boolean {
  if (!tablesEditable || !isTableEditable(blk)) return false;
  return !(col.cellType === "text" && blk.source === "assessment");
}

// 安静控件：多选——保持内联排版，但使用原生按钮提供键盘与选中状态语义。
function MultiSelectCell({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 10px" }}>
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button
            type="button"
            key={o}
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            aria-pressed={on}
            style={{ border: "none", background: "transparent", cursor: "pointer", userSelect: "none", fontSize: 14, color: on ? "var(--accent)" : "var(--border-strong)", fontWeight: on ? 600 : 400, padding: 0 }}
          >
            {o}
          </button>
        );
      })}
    </div>
  );
}

// 安静控件：单选——内联下拉，极简边框。
function SingleSelectCell({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useT();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ border: "none", borderBottom: "1px solid var(--border)", background: "transparent", fontSize: 14, fontFamily: "var(--font-serif)", color: INK, padding: "1px 0" }}
    >
      <option value="">{t.gsTable.notSelected}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

// 安静控件：文本/生成文本——内联自增高文本域，无边框透明底，观感同纯文本但可改。
function TextCell({ value, label, onChange }: { value: string; label: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const resize = () => {
    const textarea = ref.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  };
  useLayoutEffect(resize, [value]);
  return (
    <textarea
      ref={ref}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={1}
      className="gs-input"
      style={{ width: "100%", boxSizing: "border-box", border: "none", background: "transparent", resize: "none", fontSize: 14, lineHeight: 1.6, fontFamily: "var(--font-serif)", color: INK, padding: 0, overflow: "hidden", overflowWrap: "anywhere" }}
      onInput={resize}
    />
  );
}

function columnPercentages(table: GsTable, colDefs: GsColDef[], showActions: boolean): string[] {
  const weights = table.layoutProfile === "risk_response_matrix" ? table.columnWidthWeights : null;
  if (!weights) return [];
  const values = colDefs.map((col) => Math.max(Number(weights[col.key] ?? 1), 1));
  if (showActions) values.push(4);
  const total = values.reduce((sum, value) => sum + value, 0);
  return values.map((value) => `${(value / total) * 100}%`);
}

function DataCell({
  col,
  cell,
  rowIdx,
  blk,
  blockId,
}: {
  col: GsColDef;
  cell: GsTableCell;
  rowIdx: number;
  blk: Block;
  blockId: string;
}) {
  const { commitTableEdit, tablesEditable } = useReport();
  const value = cell.value;
  const options = cell.options ?? col.options ?? [];
  // 经编辑日志提交：一次单元格改动 = 一条可撤销的整表 before/after。
  const setValue = (v: string | string[]) =>
    commitTableEdit(blockId, (t) => ({
      ...t,
      children: (t.children ?? []).map((r, idx) =>
        idx === rowIdx
          ? { ...r, children: r.children.map((c) => (c.colKey === col.key ? { ...c, value: v } : c)) }
          : r,
      ),
    }));

  // 只读单元格：灰化纯文本，直观表达不可编辑。
  if (!isColEditable(col, blk, tablesEditable)) {
    return <span style={{ color: MUTED }}>{cellText(value)}</span>;
  }
  if (col.cellType === "multi_select" && options.length) {
    return <MultiSelectCell options={options} value={Array.isArray(value) ? value : []} onChange={setValue} />;
  }
  if (col.cellType === "single_select" && options.length) {
    return <SingleSelectCell options={options} value={cellText(value)} onChange={setValue} />;
  }
  return <TextCell value={cellText(value)} label={col.header} onChange={setValue} />;
}

export function GsTableBlock({ blk, table, blockId }: { blk: Block; table: GsTable; blockId: string }) {
  const t = useT();
  const { commitTableEdit, tablesEditable } = useReport();
  if (table.rowSource === "stakeholder_engagement") return <StakeholderEngagementTable />;
  const colDefs = table.colDefs ?? [];
  const children = table.children ?? [];
  const colByKey: Record<string, GsColDef> = Object.fromEntries(colDefs.map((c) => [c.key, c]));
  const narrowFirst = !!table.firstColumnNarrow && colDefs.length >= 2;
  const editable = tablesEditable && isTableEditable(blk);
  const indexed = children.map((r, idx) => ({ r, idx }));
  const headerRows = indexed.filter((x) => x.r.headerRow);
  const dataRows = indexed.filter((x) => !x.r.headerRow);
  // 数据行含合并（如 IRO 双行）时，行级操作列/增删行与合并网格冲突，仅做单元格编辑。
  const hasDataMerge = dataRows.some(({ r }) => r.children.some((c) => (c.colSpan ?? 1) > 1 || (c.rowSpan ?? 1) > 1));
  const showActions = editable && !hasDataMerge;
  const widths = columnPercentages(table, colDefs, showActions);

  const addRow = () =>
    commitTableEdit(blockId, (t) => ({ ...t, children: [...(t.children ?? []), emptyDataRow(t.colDefs ?? [])] }));
  const removeRow = (rowIdx: number) =>
    commitTableEdit(blockId, (t) => ({ ...t, children: (t.children ?? []).filter((_, idx) => idx !== rowIdx) }));

  const th: CSSProperties = {
    background: "var(--surface)",
    color: "var(--muted-foreground)",
    fontWeight: 600,
    textAlign: "center",
    padding: "8px 10px",
    whiteSpace: "normal",
    verticalAlign: "middle",
    lineHeight: 1.45,
    borderTop: "1.5px solid var(--border-strong)",
    borderBottom: "1.5px solid var(--border-strong)",
  };
  const td: CSSProperties = {
    padding: "8px 10px",
    borderBottom: "1px solid var(--border-strong)",
    verticalAlign: "middle",
    lineHeight: 1.55,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
  };
  const ctrl: CSSProperties = { border: "none", background: "transparent", cursor: "pointer", color: MUTED, fontSize: 13, marginRight: 6 };

  return (
    <div contentEditable={false}>
      <table
        style={{ borderCollapse: "collapse", width: "100%", tableLayout: "fixed", fontFamily: "var(--font-serif)", fontSize: 13, borderTop: "1.5px solid var(--border-strong)", borderBottom: "1.5px solid var(--border-strong)" }}
      >
        {widths.length ? (
          <colgroup>
            {widths.map((width, index) => (
              <col key={index} style={{ width }} />
            ))}
          </colgroup>
        ) : null}
        <tbody>
          {headerRows.map(({ r, idx }) => (
            <tr key={`h${idx}`}>
              {r.children.map((cell, ci) => {
                const span = (cell.colSpan ?? 1) > 1 ? cell.colSpan : undefined;
                const narrow = narrowFirst && ci === 0 && (cell.colSpan ?? 1) === 1;
                return (
                  <th key={ci} colSpan={span} style={{ ...th, ...(narrow ? { width: "1%" } : {}) }}>
                    {cellText(cell.value)}
                  </th>
                );
              })}
              {showActions ? <th style={{ ...th, width: "1%" }} aria-label={t.gsTable.actionsColumn} /> : null}
            </tr>
          ))}
          {dataRows.length === 0 ? (
            <tr>
              <td colSpan={colDefs.length + (showActions ? 1 : 0)} style={{ ...td, color: MUTED }}>
                {editable ? t.gsTable.emptyEditable : t.gsTable.emptyReadonly}
              </td>
            </tr>
          ) : (
            dataRows.map(({ r, idx }) => (
              <tr key={idx}>
                {r.children.map((cell, ci) => {
                  const col = cell.colKey ? colByKey[cell.colKey] : undefined;
                  const span = (cell.colSpan ?? 1) > 1 ? cell.colSpan : undefined;
                  const rspan = (cell.rowSpan ?? 1) > 1 ? cell.rowSpan : undefined;
                  const narrow = narrowFirst && ci === 0 && (cell.colSpan ?? 1) === 1;
                  const controlled = col?.cellType === "single_select" || col?.cellType === "multi_select";
                  return (
                    <td
                      key={ci}
                      colSpan={span}
                      rowSpan={rspan}
                      style={{ ...td, ...(narrow ? { width: "1%", whiteSpace: "nowrap" } : {}), ...(controlled ? { textAlign: "center" } : {}) }}
                    >
                      {col ? (
                        <DataCell col={col} cell={cell} rowIdx={idx} blk={blk} blockId={blockId} />
                      ) : (
                        <span style={{ color: MUTED }}>{cellText(cell.value)}</span>
                      )}
                    </td>
                  );
                })}
                {showActions ? (
                  <td style={{ ...td, textAlign: "center", whiteSpace: "nowrap" }}>
                    {r.state === "failed" ? <span title={t.gsTable.generationFailed} style={{ color: "var(--destructive)", marginRight: 6, fontSize: 12 }}>⚠</span> : null}
                    <button onClick={() => removeRow(idx)} title={t.gsTable.removeRow} aria-label={t.gsTable.removeRow} style={{ ...ctrl, lineHeight: 1 }}>
                      ✕
                    </button>
                  </td>
                ) : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {showActions ? (
        <div style={{ marginTop: 6, display: "flex", gap: 14, fontFamily: "var(--font-sans)" }}>
          <button
            onClick={addRow}
            style={{ border: "none", background: "transparent", color: MUTED, fontSize: 13, cursor: "pointer", padding: 0 }}
          >
            {t.gsTable.addRow}
          </button>
        </div>
      ) : null}
    </div>
  );
}
