// ABOUTME: 报告正文页的节点组件：标题、段落（含列表与字段引用）、表格、图片与准则批注，按文档投影直渲染。
// ABOUTME: 报告正文是独立排版面（serif / 15px / 1.95，design.md §2.2）；颜色即权限（§5.1）、选中/编辑中/已修改视觉（§5.2/§5.5）。
// ABOUTME(en): Node components of the report document page rendered straight from the document projection.
// ABOUTME(en): The report body keeps its own typography face (serif 15px/1.95); colour encodes permission, state is visual only.
"use client";

import { useEffect, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import { GsTableBlock } from "@/components/editor/gs-table";
import { LayoutAssetFigure } from "@/components/editor/layout-asset-figure";
import { MATRIX_IMAGE_BLOCK_ID, MatrixImage } from "@/components/editor/matrix-image";
import { MetricSummaryImage } from "@/components/editor/metric-summary-image";
import { StandardsClauseAnnotation } from "@/components/editor/standards-clause-annotation";
import { useApp } from "@/lib/app-context";
import type { AnnotationNode, HeadingNode, ImageNode, InlineNode, ParagraphNode, TableNode } from "@/lib/derive";
import { useT } from "@/lib/i18n/locale-context";
import { useLayoutAssetMetadata } from "@/lib/layout-asset-metadata-context";
import { useReport } from "@/lib/report-context";
import { reportRefLabel, reportValueToText, resolveReportRef } from "@/lib/report-values";
import type { Report } from "@/lib/schema";
import { findUserVisibleDisclosureClauseAnnotationEntry } from "@/lib/user-visible-disclosure-clause-annotations";

import { BlockTextEditor } from "./block-text-editor";

/** Report body typography face; registered as the sole serif exemption in design-compliance.test.ts. */
export const REPORT_BODY_TYPOGRAPHY: CSSProperties = {
  fontFamily: "var(--font-serif)",
  fontSize: 15,
  lineHeight: 1.95,
  textAlign: "justify",
};

const HEADING_SIZE: Record<HeadingNode["level"], { size: number; margin: string }> = {
  1: { size: 24, margin: "26px 0 12px" },
  2: { size: 20, margin: "20px 0 8px" },
  3: { size: 16, margin: "14px 0 6px" },
  4: { size: 15, margin: "12px 0 6px" },
};

export function sectionAnchorId(sectionKey: string): string {
  return `section-${sectionKey}`;
}

function assessmentValue(refKey: string, report: Report): string | number | null {
  if (!refKey.startsWith("assessment.")) return null;
  // 本报告实际披露的议题数量：现算而非取基数——评分议题范围是知识包属性
  // （上交所 24 个、港交所 16 个），写死任何数字都会对另一个包印出错误的正文。
  // 未评分时返回 null，由 RefInline 渲染占位，好过显示一个错误的数字。
  if (refKey === "assessment.applicableTopicCount") {
    return report.assessment?.topics?.length ?? null;
  }
  if (refKey.startsWith("assessment.counts.")) {
    const key = refKey.slice("assessment.counts.".length);
    const topics = report.assessment?.topics ?? [];
    if (key === "dual") return topics.filter((t) => t.materiality === "dual").length;
    if (key === "impact_only") return topics.filter((t) => t.materiality === "impact").length;
    if (key === "financial_only") return topics.filter((t) => t.materiality === "financial").length;
    if (key === "non_material") return topics.filter((t) => t.materiality === "non").length;
  }
  if (refKey.startsWith("assessment.topics.") && refKey.endsWith(".materiality")) {
    const assessmentTopicId = refKey.slice("assessment.topics.".length, -".materiality".length);
    return report.assessment?.topics?.find((topic) => topic.assessmentTopicId === assessmentTopicId)?.materiality ?? null;
  }
  return null;
}

export function HeadingBlock({ node }: { node: HeadingNode }) {
  const Tag = `h${node.level}` as const;
  const spec = HEADING_SIZE[node.level];
  const { regenerateSection } = useReport();
  const t = useT();
  // 章节动作只挂在议题章节（H2）上：H1 是模块、H3/H4 是段内层级，整节重写以页面为单位。
  // 按钮是标题的**兄弟节点**而非子节点——交互控件放进 <h2> 会让标题的可及名称混入按钮文案。
  const action = node.level === 2 && regenerateSection ? (
    <button
      type="button"
      onClick={() => regenerateSection(node.sectionKey)}
      data-section-action={node.sectionKey}
      style={{
        border: "1px solid var(--border)",
        background: "var(--background)",
        color: "var(--muted-foreground)",
        borderRadius: "var(--radius-control)",
        fontFamily: "var(--font-sans)",
        fontSize: "var(--text-label-size)",
        padding: "3px 10px",
        cursor: "pointer",
        flexShrink: 0,
      }}
    >
      {t.reportDocument.regenerateSection}
    </button>
  ) : null;

  const heading = (
    <Tag
      id={sectionAnchorId(node.sectionKey)}
      data-section-key={node.sectionKey}
      style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: spec.size, color: "var(--foreground)", margin: spec.margin }}
    >
      {node.label}
      {node.title}
    </Tag>
  );

  if (!action) return heading;
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
      {heading}
      <span style={{ marginLeft: "auto" }}>{action}</span>
    </div>
  );
}

/** Field back-fill chip: green in reading and editing alike (design.md §5.3). */
export function RefInline({ refKey }: { refKey: string }) {
  const { report } = useReport();
  const value = assessmentValue(refKey, report) ?? resolveReportRef(refKey, report);
  const text = reportValueToText(value, report);
  const filled = text !== "";
  return (
    <span
      style={{
        color: "var(--field-foreground)",
        background: "var(--field-background)",
        borderRadius: 3,
        padding: "0 4px",
        whiteSpace: "nowrap",
        ...(filled ? {} : { fontSize: "var(--text-label-size)" }),
      }}
    >
      {filled ? text : `【${reportRefLabel(refKey, report)}】`}
    </span>
  );
}

function InlineRun({ inlines }: { inlines: InlineNode[] }) {
  return (
    <>
      {inlines.map((inline, index) =>
        inline.kind === "text" ? <span key={index}>{inline.text}</span> : <RefInline key={index} refKey={inline.refKey} />,
      )}
    </>
  );
}

/** Wraps any block so a click selects it for provenance; the wrapper carries the stable block id. */
function BlockShell({
  blockId,
  className,
  style,
  children,
  onDoubleClick,
}: {
  blockId: string;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
  onDoubleClick?: (event: MouseEvent<HTMLDivElement>) => void;
}) {
  const { selectBlock, selectedBlockId } = useReport();
  return (
    <div
      data-block-id={blockId}
      data-selected={selectedBlockId === blockId || undefined}
      className={className}
      style={style}
      onClick={() => selectBlock(blockId)}
      onDoubleClick={onDoubleClick}
    >
      {children}
    </div>
  );
}

export function ParagraphBlock({ node }: { node: ParagraphNode }) {
  const t = useT();
  const { selectedBlockId, editingBlockId, editedBlockIds, beginEdit, commitEdit } = useReport();
  const marker = node.list === "ordered" ? `${node.index}.` : node.list === "unordered" ? "•" : null;
  const isSelected = selectedBlockId === node.blockId;
  const isEditing = node.editable && editingBlockId === node.blockId;
  const isEdited = node.editable && editedBlockIds.has(node.blockId);
  const plainText = node.inlines.map((inline) => (inline.kind === "text" ? inline.text : "")).join("");

  const style: CSSProperties = {
    ...REPORT_BODY_TYPOGRAPHY,
    position: "relative",
    margin: "0 0 10px",
    // Colour is permission: editable prose is ink, locked prose is grey (design.md §5.1).
    color: node.editable ? "var(--foreground)" : "var(--muted-foreground)",
    ...(node.list ? { paddingLeft: 8 } : { textIndent: "2em" }),
    cursor: "default",
  };
  // Selected: light ground only (design.md §5.5); no bars or borders on prose.
  if (isSelected && !isEditing) {
    style.background = "var(--accent-subtle)";
    style.borderRadius = 6;
    style.padding = "6px 10px";
  }

  return (
    <BlockShell
      blockId={node.blockId}
      className={node.editable ? "gs-editable" : undefined}
      style={style}
      onDoubleClick={node.editable ? () => beginEdit(node.blockId) : undefined}
    >
      {isEditing ? (
        <BlockTextEditor
          initialText={plainText}
          ariaLabel={t.documentNodes.editParagraph}
          typography={REPORT_BODY_TYPOGRAPHY}
          onCommit={(text) => commitEdit(node.blockId, text)}
        />
      ) : (
        <>
          {marker ? <span style={{ userSelect: "none", color: "var(--muted-foreground)", marginRight: 6 }}>{marker}</span> : null}
          <InlineRun inlines={node.inlines} />
        </>
      )}
      {isEdited ? (
        <span
          title={t.documentNodes.edited}
          aria-label={t.documentNodes.edited}
          style={{ position: "absolute", left: -18, top: 10, width: 7, height: 7, borderRadius: "50%", background: "var(--success)" }}
        />
      ) : null}
      {node.editable && !isEditing ? (
        <span className="gs-controls" style={{ position: "absolute", right: -44, top: 4 }}>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              beginEdit(node.blockId);
            }}
            style={{
              border: "none",
              background: "transparent",
              color: "var(--muted-foreground)",
              fontFamily: "var(--font-sans)",
              fontSize: "var(--text-supporting-size)",
              cursor: "pointer",
              padding: "0 4px",
            }}
          >
            {t.documentNodes.editAction}
          </button>
        </span>
      ) : null}
    </BlockShell>
  );
}

export function TableBlock({ node }: { node: TableNode }) {
  const t = useT();
  const { blockById, selectedBlockId } = useReport();
  const block = blockById(node.blockId);
  const table = block?.table;
  const selected = selectedBlockId === node.blockId;
  return (
    <BlockShell
      blockId={node.blockId}
      style={{ margin: "12px 0", ...(selected ? { background: "var(--accent-subtle)", borderRadius: 6, padding: "6px 10px" } : {}) }}
    >
      {table?.caption ? (
        <div style={{ fontSize: "var(--text-label-size)", color: "var(--foreground-secondary)", marginBottom: 4 }}>{t.documentNodes.tableCaptionPrefix}{table.caption}</div>
      ) : null}
      {table && block ? <GsTableBlock blk={block} table={table} blockId={node.blockId} /> : null}
      {table?.disclaimer ? (
        <div style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", marginTop: 4 }}>{t.documentNodes.tableDisclaimerPrefix}{table.disclaimer}</div>
      ) : null}
    </BlockShell>
  );
}

export function ImageBlock({ node }: { node: ImageNode }) {
  const t = useT();
  const { blockById, report, selectedBlockId } = useReport();
  const { activeReportId } = useApp();
  const assetMetadata = useLayoutAssetMetadata();
  const block = blockById(node.blockId);
  const image = block?.image;
  const layoutAssetIds = image?.layoutAssetIds;
  const hasLayoutAssets = !!layoutAssetIds?.length;
  // Captions live with the asset metadata; load them lazily only when a placed asset is on screen.
  useEffect(() => {
    if (hasLayoutAssets) assetMetadata?.ensureLoaded();
  }, [hasLayoutAssets, assetMetadata]);
  const selected = selectedBlockId === node.blockId;
  return (
    <BlockShell
      blockId={node.blockId}
      style={{ margin: "12px 0", ...(selected ? { background: "var(--accent-subtle)", borderRadius: 6, padding: "6px 10px" } : {}) }}
    >
      {node.blockId === MATRIX_IMAGE_BLOCK_ID ? (
        <MatrixImage assessment={report.assessment} fallback={null} />
      ) : image?.derivedVisualization?.kind === "quantitative_metric_summary" ? (
        <MetricSummaryImage report={report} spec={image.derivedVisualization} fallback={null} />
      ) : layoutAssetIds?.length && activeReportId ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {layoutAssetIds.map((assetId) => (
            <LayoutAssetFigure
              key={assetId}
              assetId={assetId}
              reportId={activeReportId}
              caption={assetMetadata?.asset(assetId)?.caption ?? undefined}
            />
          ))}
        </div>
      ) : null}
      {image?.caption && !layoutAssetIds?.length ? (
        <div style={{ fontSize: "var(--text-label-size)", color: "var(--foreground-secondary)", textAlign: "center", marginTop: 4 }}>{t.documentNodes.figureCaptionPrefix}{image.caption}</div>
      ) : null}
    </BlockShell>
  );
}

export function AnnotationBlock({ node }: { node: AnnotationNode }) {
  const { report } = useReport();
  const { config } = useApp();
  const entry = findUserVisibleDisclosureClauseAnnotationEntry(
    config.user_visible_disclosure_clause_annotations,
    report,
    { reportSectionKey: node.sectionKey },
  );
  return <StandardsClauseAnnotation entry={entry} />;
}
