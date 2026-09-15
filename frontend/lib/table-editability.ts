// ABOUTME: Report 表格的可编辑性判定，供工作台和预览共用。
// ABOUTME: 派生和评估投影永远只读，避免写入独立于其事实源的缓存表格行。
import type { Block } from "./schema";

export function isTableEditable(blk: Block): boolean {
  const table = blk.table;
  if (blk.source === "derived") return false;
  if (table?.rowSource === "assessment_topics" || table?.rowSource === "assessment_iro") return false;
  return (
    blk.blockType === "generative" ||
    blk.blockType === "constrained" ||
    blk.source === "user_input" ||
    table?.rowSource === "user" ||
    !!table?.colDefs?.some((column) => column.cellType === "ai_text")
  );
}
