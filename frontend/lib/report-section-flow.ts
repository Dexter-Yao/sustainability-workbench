// ABOUTME: 报告二级章节的前端派生层，按 Report 契约推导内容清单与章节级生成范围。
// ABOUTME: 本模块不扩展 schema、不写 prompt，只读取结构化答案和块生成配置。
import { isVisible } from "./conditions";
import type { Block, Condition, IntakeItem, Report, Section } from "./schema";

export interface ReportSectionSummary {
  reportSectionId: string;
  sectionKey: string;
  title: string;
  intakeTotal: number;
  intakeAnswered: number;
  generationTotal: number;
  generationReady: number;
  firstBlockId: string | null;
}

export interface ReportSectionWorkpaperSection {
  section: Section;
  intakeItems: IntakeItem[];
  blocks: Block[];
}

function nonEmptyText(value: unknown): boolean {
  return typeof value === "string" && value.trim() !== "";
}

function itemByKey(report: Report): Map<string, IntakeItem> {
  return new Map((report.intakeItems ?? []).map((item) => [item.key, item]));
}

function validAnswer(item: IntakeItem): boolean {
  if (item.answer == null) return false;
  if (item.kind === "text") return nonEmptyText(item.answer);
  const options = item.options ?? [];
  if (item.kind === "single_select") {
    return typeof item.answer === "string" && options.includes(item.answer);
  }
  if (!Array.isArray(item.answer) || item.answer.length === 0) return false;
  if (!item.answer.every((entry) => typeof entry === "string" && options.includes(entry))) return false;
  const groups = item.optionGroups ?? [];
  if (groups.length === 0) return true;
  return groups.every((group) => {
    const selected = item.answer as string[];
    const count = group.options.filter((option) => selected.includes(option)).length;
    return count >= (group.minSelections ?? 0);
  });
}

export function intakeItemReady(item: IntakeItem | undefined): boolean {
  if (!item) return false;
  const hasSupplement = nonEmptyText(item.supplement);
  if ((item.optionGroups ?? []).length > 0) return validAnswer(item);
  if (item.answer == null) return hasSupplement;
  if (typeof item.answer === "string" && item.answer.trim() === "") return hasSupplement;
  if (Array.isArray(item.answer) && item.answer.length === 0) return hasSupplement;
  return validAnswer(item) || hasSupplement;
}


export function updateIntakeItem(
  report: Report,
  key: string,
  patch: Pick<IntakeItem, "answer" | "supplement">,
): Report {
  return {
    ...report,
    intakeItems: (report.intakeItems ?? []).map((item) => (item.key === key ? { ...item, ...patch } : item)),
  };
}

function collectReportSections(report: Report): Section[] {
  const reportSections: Section[] = [];
  const walk = (sections: Section[] | null | undefined) => {
    for (const section of sections ?? []) {
      if (!isVisible(section, report)) continue;
      if (section.reportSectionId) reportSections.push(section);
      walk(section.children);
    }
  };
  walk(report.sections);
  return reportSections;
}

function walkBlocks(section: Section, report: Report, visit: (block: Block) => void) {
  if (section.conciseDisclosure && isVisible(section.conciseDisclosure, report)) {
    visit(section.conciseDisclosure);
  }
  for (const block of section.blocks ?? []) {
    if (isVisible(block, report)) visit(block);
  }
  for (const child of section.children ?? []) {
    if (isVisible(child, report)) walkBlocks(child, report, visit);
  }
}

function walkAllBlocks(section: Section, visit: (block: Block) => void) {
  if (section.conciseDisclosure) visit(section.conciseDisclosure);
  for (const block of section.blocks ?? []) visit(block);
  for (const child of section.children ?? []) walkAllBlocks(child, visit);
}

export function reportSectionFor(report: Report, reportSectionId: string): Section | null {
  return collectReportSections(report).find((section) => section.reportSectionId === reportSectionId) ?? null;
}

export function blocksForReportSection(report: Report, reportSectionId: string): Block[] {
  const topic = reportSectionFor(report, reportSectionId);
  const blocks: Block[] = [];
  if (!topic) return blocks;
  walkBlocks(topic, report, (block) => blocks.push(block));
  return blocks;
}

export function generatableBlocksForReportSection(report: Report, reportSectionId: string): Block[] {
  return blocksForReportSection(report, reportSectionId).filter(
    (block) => (block.blockType === "generative" || block.blockType === "constrained") && !!block.generation,
  );
}

function intakeKeysFromCondition(condition: Condition | null | undefined): string[] {
  const keys: string[] = [];
  for (const rule of [...(condition?.all ?? []), ...(condition?.any ?? [])]) {
    if (rule.path.startsWith("intakeItems.")) keys.push(rule.path.slice("intakeItems.".length));
  }
  return keys;
}

function reportSectionIdForBlock(report: Report, blockId: string): string | null {
  const findOwner = (section: Section): string | null => {
    if (section.conciseDisclosure?.id === blockId) return section.reportSectionId ?? null;
    if ((section.blocks ?? []).some((block) => block.id === blockId)) return section.reportSectionId ?? null;
    for (const child of section.children ?? []) {
      const reportSectionId = findOwner(child);
      if (reportSectionId) return reportSectionId;
    }
    return null;
  };
  for (const section of report.sections ?? []) {
    const reportSectionId = findOwner(section);
    if (reportSectionId) return reportSectionId;
  }
  return null;
}

function intakeKeysForBlock(block: Block, report: Report, reportSectionId?: string): string[] {
  const selector = block.generation?.inputs?.evidence;
  const evidenceKeys = selector?.kind === "explicit"
    ? (selector.intakeItems ?? [])
    : selector?.kind === "report_section"
      ? (report.intakeItems ?? [])
          .filter((item) => item.contentScopeId === (reportSectionId ?? reportSectionIdForBlock(report, block.id)))
          .map((item) => item.key)
      : [];
  return [...new Set([
    ...evidenceKeys,
    ...intakeKeysFromCondition(block.appears_when),
  ])];
}

export function reportSectionWorkpaperSections(report: Report, reportSectionId: string): ReportSectionWorkpaperSection[] {
  const topic = reportSectionFor(report, reportSectionId);
  if (!topic) return [];
  const byKey = itemByKey(report);
  const children = (topic.children ?? []).filter((section) => isVisible(section, report));
  const sections = children.length ? children : [topic];

  return sections.map((section) => {
    const blocks: Block[] = [];
    walkBlocks(section, report, (block) => blocks.push(block));
    const keys = new Set<string>();
    walkAllBlocks(section, (block) => {
      for (const key of intakeKeysForBlock(block, report, reportSectionId)) {
        if (byKey.has(key)) keys.add(key);
      }
    });
    const intakeItems = (report.intakeItems ?? []).filter((item) => keys.has(item.key));
    return { section, intakeItems, blocks };
  });
}

export function unassignedReportSectionIntakeItems(report: Report, reportSectionId: string): IntakeItem[] {
  const assigned = new Set(reportSectionWorkpaperSections(report, reportSectionId).flatMap((section) => section.intakeItems.map((item) => item.key)));
  return (report.intakeItems ?? []).filter((item) => item.contentScopeId === reportSectionId && !assigned.has(item.key));
}

function tableReady(block: Block): boolean {
  const rows = block.table?.children?.filter((row) => !row.headerRow) ?? [];
  return rows.length > 0 && rows.every((row) => row.state === "ready" || row.state === "locked");
}

function blockReady(block: Block): boolean {
  return block.state === "ready" || block.state === "locked" || block.state === "omitted" || tableReady(block);
}

export function deriveReportSectionSummaries(report: Report): ReportSectionSummary[] {
  const itemsBySection = new Map<string, IntakeItem[]>();
  for (const item of report.intakeItems ?? []) {
    const list = itemsBySection.get(item.contentScopeId) ?? [];
    list.push(item);
    itemsBySection.set(item.contentScopeId, list);
  }

  return collectReportSections(report).map((section) => {
    const reportSectionId = section.reportSectionId!;
    const items = itemsBySection.get(reportSectionId) ?? [];
    const blocks = generatableBlocksForReportSection(report, reportSectionId);
    return {
      reportSectionId,
      sectionKey: section.key,
      title: section.title || reportSectionId,
      intakeTotal: items.length,
      intakeAnswered: items.filter(intakeItemReady).length,
      generationTotal: blocks.length,
      generationReady: blocks.filter(blockReady).length,
      firstBlockId: blocks[0]?.id ?? null,
    };
  });
}

