// ABOUTME: 报告正文页的块级编辑动作：一次提交 = 一条 BlockTextEdit{blockId, before, after}，日志按动作撤销/重做。
// ABOUTME: 纯函数，不持有状态；Report 仍是真相源，编辑动作只是把用户意图写回 Report 的可回放形式。
// ABOUTME(en): Block-level edit actions for the report document page: one commit is one BlockTextEdit, replayable and undoable.
// ABOUTME(en): Pure functions with no state; the Report stays the truth, an edit is the replayable form of the user's intent.

import { applyBlockContent, findBlock, updateBlockState, updateBlockTable } from "./report-mutations";
import type { GsTable, Inline, Report } from "./schema";

export interface BlockTextEdit {
  kind?: "text";
  blockId: string;
  before: Inline[];
  after: Inline[];
}

/**
 * 表格的一次提交：整表前后像。
 *
 * 与段落同构地记录 before/after，而不是逐键写回——后者是三条互不记录的写路径
 * （单元格、增行、删行），改动既无撤销也无差异。整表快照换来的是「一次操作一次撤销」。
 */
export interface BlockTableEdit {
  kind: "table";
  blockId: string;
  before: GsTable;
  after: GsTable;
}

export type BlockEdit = BlockTextEdit | BlockTableEdit;

export function isTableEdit(edit: BlockEdit): edit is BlockTableEdit {
  return edit.kind === "table";
}

export interface EditLog {
  past: BlockEdit[];
  future: BlockEdit[];
}

export const EMPTY_EDIT_LOG: EditLog = { past: [], future: [] };

/** Plain text of a block's inline content; refs never occur in editable blocks (template audit). */
export function inlineText(content: Inline[] | null | undefined): string {
  return (content ?? []).map((inline) => (inline.kind === "text" ? inline.text ?? "" : "")).join("");
}

/** Build the edit a commit would perform; null when the block is missing or the text is unchanged. */
export function blockTextEdit(report: Report, blockId: string, text: string): BlockTextEdit | null {
  const block = findBlock(report, blockId);
  if (!block) return null;
  const before = block.content ?? [];
  if (inlineText(before) === text) return null;
  return { blockId, before, after: [{ kind: "text", text }] };
}

export function applyBlockTextEdit(report: Report, edit: BlockTextEdit): Report {
  return updateBlockState(applyBlockContent(report, edit.blockId, edit.after), edit.blockId, "ready");
}

export function revertBlockTextEdit(report: Report, edit: BlockTextEdit): Report {
  return applyBlockContent(report, edit.blockId, edit.before);
}

/** Build the table edit a commit would perform; null when the block has no table or nothing changed. */
export function blockTableEdit(
  report: Report,
  blockId: string,
  updater: (table: GsTable) => GsTable,
): BlockTableEdit | null {
  const before = findBlock(report, blockId)?.table;
  if (!before) return null;
  const after = updater(before);
  if (after === before) return null;
  return { kind: "table", blockId, before, after };
}

export function applyBlockTableEdit(report: Report, edit: BlockTableEdit): Report {
  return updateBlockState(
    updateBlockTable(report, edit.blockId, () => edit.after),
    edit.blockId,
    "ready",
  );
}

export function revertBlockTableEdit(report: Report, edit: BlockTableEdit): Report {
  return updateBlockTable(report, edit.blockId, () => edit.before);
}

/** Apply any edit forward; the page dispatches on kind so undo and redo share one path. */
export function applyEdit(report: Report, edit: BlockEdit): Report {
  return isTableEdit(edit) ? applyBlockTableEdit(report, edit) : applyBlockTextEdit(report, edit);
}

/** Revert any edit; text reverts content only, tables restore the whole table. */
export function revertEdit(report: Report, edit: BlockEdit): Report {
  return isTableEdit(edit) ? revertBlockTableEdit(report, edit) : revertBlockTextEdit(report, edit);
}

export function commitEdit(log: EditLog, edit: BlockEdit): EditLog {
  return { past: [...log.past, edit], future: [] };
}

export function undoEdit(log: EditLog): { log: EditLog; edit: BlockEdit } | null {
  const edit = log.past[log.past.length - 1];
  if (!edit) return null;
  return { log: { past: log.past.slice(0, -1), future: [edit, ...log.future] }, edit };
}

export function redoEdit(log: EditLog): { log: EditLog; edit: BlockEdit } | null {
  const edit = log.future[0];
  if (!edit) return null;
  return { log: { past: [...log.past, edit], future: log.future.slice(1) }, edit };
}

/** Blocks touched by any edit still in the past; used when no generated baseline is available. */
export function editedBlockIdsFromLog(log: EditLog): Set<string> {
  return new Set(log.past.map((edit) => edit.blockId));
}
