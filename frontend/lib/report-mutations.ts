// ABOUTME: Report 结构化写回函数：只修改 Report 实例中的块内容、表格与生成生命周期状态，不扩展数据契约。
// ABOUTME(en): Structured write-back helpers for the Report; they touch block content, tables and lifecycle state only.
import type { Block, BlockState, GsTable, Inline, Report } from "./schema";

type Blocks = Report["sections"][number]["blocks"];

export function mapSectionBlocks(
  sections: Report["sections"],
  updater: (blocks: Blocks) => Blocks,
): Report["sections"] {
  return sections.map((section) => ({
    ...section,
    blocks: updater(section.blocks),
    children: section.children ? mapSectionBlocks(section.children, updater) : section.children,
  }));
}

export function findBlock(report: Report, blockId: string): Block | undefined {
  const walk = (sections: Report["sections"]): Block | undefined => {
    for (const section of sections) {
      const hit = section.blocks.find((block) => block.id === blockId);
      if (hit) return hit;
      const nested = section.children ? walk(section.children) : undefined;
      if (nested) return nested;
    }
    return undefined;
  };
  return walk(report.sections);
}

export function applyBlockContent(report: Report, blockId: string, content: Inline[]): Report {
  return {
    ...report,
    sections: mapSectionBlocks(report.sections, (blocks) =>
      blocks.map((block) => (block.id === blockId ? { ...block, content } : block)),
    ),
  };
}

export function applyBlockText(report: Report, blockId: string, text: string): Report {
  return applyBlockContent(report, blockId, [{ kind: "text", text }]);
}

export function updateBlockTable(
  report: Report,
  blockId: string,
  updater: (table: GsTable) => GsTable,
): Report {
  return {
    ...report,
    sections: mapSectionBlocks(report.sections, (blocks) =>
      blocks.map((block) => (block.id === blockId && block.table ? { ...block, table: updater(block.table) } : block)),
    ),
  };
}

export function updateBlockState(report: Report, blockId: string, state: BlockState): Report {
  return {
    ...report,
    sections: mapSectionBlocks(report.sections, (blocks) =>
      blocks.map((block) => (block.id === blockId ? { ...block, state } : block)),
    ),
  };
}
