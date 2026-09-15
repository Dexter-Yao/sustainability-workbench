// ABOUTME: 把填充 Report 推导为报告正文页的文档投影：标题/段落/表格/图片/准则批注各成一个类型化节点。
// ABOUTME: 纯函数、结构无关；表格与图片是薄节点（只存 blockId），由渲染组件经 ReportContext 取数；段落内联文本与引用直出。
// ABOUTME(en): Derives the report document projection (typed heading/paragraph/table/image/annotation nodes) from a Report.
// ABOUTME(en): Pure and structure-agnostic; tables and images are thin nodes resolved by renderers via ReportContext.

import { isVisible } from "./conditions";
import { resolvedDisplayTitle } from "./section-titles";
import type { Block, Inline, Report, Section } from "./schema";
import { numberSections, numberingSchemeFor } from "./section-number";

export type InlineNode = { kind: "text"; text: string } | { kind: "ref"; refKey: string };

export interface HeadingNode {
  type: "heading";
  level: 1 | 2 | 3 | 4;
  sectionKey: string;
  /** Section number label such as "一、" or "（一）"; empty for unnumbered front chapters. */
  label: string;
  title: string;
}

export interface ParagraphNode {
  type: "paragraph";
  blockId: string;
  /** generative / constrained prose the user may edit; everything else is locked (design.md §5.1). */
  editable: boolean;
  list: "ordered" | "unordered" | null;
  index: number;
  inlines: InlineNode[];
}

export interface TableNode {
  type: "table";
  blockId: string;
}

export interface ImageNode {
  type: "image";
  blockId: string;
}

export interface AnnotationNode {
  type: "standards_clause_annotation";
  sectionKey: string;
}

export type DocumentNode = HeadingNode | ParagraphNode | TableNode | ImageNode | AnnotationNode;

export function isEditableBlock(block: Block): boolean {
  return block.type === "paragraph" && (block.blockType === "generative" || block.blockType === "constrained");
}

function inlineNodes(content?: Inline[] | null): InlineNode[] {
  return (content ?? []).map((inline) =>
    inline.kind === "text"
      ? { kind: "text", text: inline.text ?? "" }
      : { kind: "ref", refKey: inline.ref ?? "" },
  );
}

// Front chapter zone: top-level chapters that are neither ESG modules nor the appendix, plus descendants.
function frontChapterZoneKeys(sections: Section[]): Set<string> {
  const keys = new Set<string>();
  const mark = (section: Section) => {
    keys.add(section.key);
    for (const child of section.children ?? []) mark(child);
  };
  for (const section of sections) {
    if (!section.reportModuleId && section.key !== "report_appendix") mark(section);
  }
  return keys;
}

/** Derive the whole report as an ordered list of document nodes. */
export function deriveDocument(report: Report): DocumentNode[] {
  const nodes: DocumentNode[] = [];
  const labels = numberSections(
    report.sections,
    (section) => isVisible(section, report),
    numberingSchemeFor(report.knowledgePackageId),
  );
  const frontZone = frontChapterZoneKeys(report.sections);
  let orderedIndex = 0;

  const pushBlock = (block: Block) => {
    if (!isVisible(block, report)) return;
    // Evidence-gated omission mirrors Word/TOC renderability: no empty editable paragraph.
    if (block.state === "omitted") return;
    orderedIndex = block.listType === "ordered" ? orderedIndex + 1 : 0;
    if (block.type === "table") {
      nodes.push({ type: "table", blockId: block.id });
      return;
    }
    if (block.type === "image") {
      // Only images with something to draw enter the document: placed assets, derived charts or
      // the assessment matrix. Empty carrier slots never render a placeholder in a delivered report.
      const image = block.image;
      const drawable = !!image?.layoutAssetIds?.length || !!image?.derivedVisualization || block.source === "assessment";
      if (drawable) nodes.push({ type: "image", blockId: block.id });
      return;
    }
    nodes.push({
      type: "paragraph",
      blockId: block.id,
      editable: !block.listType && isEditableBlock(block),
      list: block.listType ?? null,
      index: orderedIndex,
      inlines: inlineNodes(block.content),
    });
  };

  const subtreeBlockFacts = (section: Section): { hasVisibleBlocks: boolean; hasRenderableBlocks: boolean } => {
    let hasVisibleBlocks = section.blocks.some((block) => isVisible(block, report));
    let hasRenderableBlocks = section.blocks.some((block) => isVisible(block, report) && block.state !== "omitted");
    for (const child of section.children ?? []) {
      if (!isVisible(child, report)) continue;
      const facts = subtreeBlockFacts(child);
      hasVisibleBlocks ||= facts.hasVisibleBlocks;
      hasRenderableBlocks ||= facts.hasRenderableBlocks;
    }
    return { hasVisibleBlocks, hasRenderableBlocks };
  };

  const walkSection = (section: Section) => {
    if (!isVisible(section, report)) return; // cascading: an invisible parent hides its subtree
    // A subtree whose every block is omitted leaves no orphan heading; block-less structural sections still render.
    const facts = subtreeBlockFacts(section);
    if (facts.hasVisibleBlocks && !facts.hasRenderableBlocks) return;
    const title = resolvedDisplayTitle(section, report);
    if (title) {
      orderedIndex = 0; // a heading interrupts ordered-list numbering
      nodes.push({
        type: "heading",
        level: section.headingLevel ?? 1,
        sectionKey: section.key,
        label: frontZone.has(section.key) ? "" : labels.get(section.key) ?? "",
        title,
      });
      const showsStandardsAnnotation =
        ((section.headingLevel ?? 1) === 2 && !!section.reportSectionId) || section.key === "sustainability_mgmt";
      if (showsStandardsAnnotation) {
        nodes.push({ type: "standards_clause_annotation", sectionKey: section.key });
      }
    }
    for (const block of section.blocks) pushBlock(block);
    for (const child of section.children ?? []) walkSection(child);
  };

  for (const section of report.sections) walkSection(section);
  return nodes;
}

/** Ordered ids of blocks a user can select and edit, for the ↑↓ keyboard flow. */
export function editableBlockIds(nodes: readonly DocumentNode[]): string[] {
  return nodes.flatMap((node) => (node.type === "paragraph" && node.editable ? [node.blockId] : []));
}

/** Ordered ids of every block that carries provenance, for click selection. */
export function selectableBlockIds(nodes: readonly DocumentNode[]): string[] {
  return nodes.flatMap((node) =>
    node.type === "paragraph" || node.type === "table" || node.type === "image" ? [node.blockId] : [],
  );
}
