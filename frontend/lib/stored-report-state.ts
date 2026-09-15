// ABOUTME: 浏览器与服务端报告状态快照的 parse-first 边界，只保存用户事实和实例内容。
// ABOUTME: StoredReportStateV4 类型与 Ajv schema 均由后端独立领域合同生成；旧本地快照由应用边界明确废弃。
import { parseStoredReportStateValue } from "./contract-parser";
import type {
  StoredReportStateV4,
  StoredTableRow,
} from "./stored-report-state.generated";
import type { Block, Report } from "./schema";

export type { StoredReportStateV4 } from "./stored-report-state.generated";

export const STORED_REPORT_STATE_VERSION = 4;

export class StoredReportStateVersionError extends Error {
  constructor(readonly actualVersion: unknown) {
    super(`不支持的报告状态版本：${String(actualVersion)}`);
    this.name = "StoredReportStateVersionError";
  }
}

export class StoredReportStateJSONError extends Error {}

function emptyStoredReportState(): StoredReportStateV4 {
  return {
    version: STORED_REPORT_STATE_VERSION,
    fields: {},
    intakeItems: {},
    assessmentInput: null,
    disclosureProfile: null,
    appendixPackage: null,
    meta: null,
    stakeholderEngagement: null,
    sectionTitles: {},
    generatedBlocks: {},
    tableBlocks: {},
    imageBlocks: {},
    companyBusinessSummary: null,
  };
}

function walkBlocks(sections: Report["sections"], visit: (block: Block) => void) {
  for (const section of sections ?? []) {
    for (const block of section.blocks ?? []) visit(block);
    walkBlocks(section.children ?? [], visit);
  }
}

function walkSections(
  sections: Report["sections"],
  visit: (section: Report["sections"][number]) => void,
) {
  for (const section of sections ?? []) {
    visit(section);
    walkSections(section.children ?? [], visit);
  }
}

function isGeneratedParagraph(block: Block): boolean {
  return block.type === "paragraph" && (
    block.blockType === "generative" || block.blockType === "constrained"
  );
}

function isPersistedTableBlock(block: Block): boolean {
  return block.type === "table"
    && !!block.table
    && block.source !== "derived"
    && block.table.rowSource !== "stakeholder_engagement";
}

function fieldValues(report: Report): StoredReportStateV4["fields"] {
  const values: StoredReportStateV4["fields"] = {};
  for (const [key, field] of Object.entries(report.fields ?? {})) {
    values[key] = field.value ?? null;
  }
  return values;
}

function intakeAnswers(report: Report): StoredReportStateV4["intakeItems"] {
  const answers: StoredReportStateV4["intakeItems"] = {};
  for (const item of report.intakeItems ?? []) {
    if (item.answer !== undefined || item.supplement !== undefined) {
      answers[item.key] = {
        answer: item.answer ?? null,
        supplement: item.supplement ?? null,
      };
    }
  }
  return answers;
}

function storedTableRows(rows: NonNullable<Block["table"]>["children"]): StoredTableRow[] {
  return (rows ?? []).map((row) => ({
    type: row.type ?? "tr",
    headerRow: row.headerRow ?? false,
    state: row.state ?? null,
    origin: row.origin
      ? {
          from: row.origin.from ?? "ai",
          theme: row.origin.theme ?? null,
          category: row.origin.category ?? null,
          driver_hint: row.origin.driver_hint ?? null,
        }
      : null,
    children: (row.children ?? []).map((cell) => ({
      type: cell.type ?? "td",
      colKey: cell.colKey ?? null,
      value: cell.value ?? null,
      options: cell.options ?? null,
      colSpan: cell.colSpan ?? 1,
      rowSpan: cell.rowSpan ?? 1,
      cellState: cell.cellState ?? null,
    })),
  }));
}

/**
 * 新建报告的首个状态：只承载新报告真实拥有的事实——输入字段默认值与模板初始配置。
 *
 * 不走 reportToStoredReportState：那个函数按模板装配重建全量投影，会把尚未生成的
 * 空块骨架（content/state 均为 null 的 generatedBlocks、只有表头行的 tableBlocks）
 * 一并写入。这些骨架不是用户事实；写入边界按报告侧口径全等比较，
 * 会把范围外章节的骨架判为范围外而 403，使新建流程在第二步失败、
 * 报告建成却无法进入。
 */
export function newReportStoredState(report: Report): StoredReportStateV4 {
  const state = emptyStoredReportState();
  state.fields = fieldValues(report);
  state.disclosureProfile = report.disclosureProfile ?? null;
  state.appendixPackage = report.appendixPackage ?? null;
  return state;
}

/** 状态侧 meta → 报告内容 meta：剔除只属于编排的字段。
 *
 * `primaryInputMode`（填报方式）是报告级**编排**事实，落在状态 meta 上供生成闸与导出闸
 * 共同裁定；但 Report 合同 `extra="forbid"`，把它原样带进 Report.meta 会让 /api/plan
 * 整体 422、编制页只剩一行错误。投影必须显式列出报告内容字段，
 * 不做整体透传——下次再往状态 meta 加编排字段时，这里的遗漏才不会变成线上故障。
 */
function reportMetaFromStored(meta: StoredReportStateV4["meta"]): Report["meta"] | null {
  if (!meta) return null;
  return {
    quantitativeMetrics: meta.quantitativeMetrics,
    materialityStrategy: meta.materialityStrategy ?? null,
  } as Report["meta"];
}

export function reportToStoredReportState(report: Report): StoredReportStateV4 {
  const state = emptyStoredReportState();
  state.fields = fieldValues(report);
  state.intakeItems = intakeAnswers(report);
  state.assessmentInput = report.assessmentInput ?? null;
  state.disclosureProfile = report.disclosureProfile ?? null;
  state.appendixPackage = report.appendixPackage ?? null;
  state.meta = report.meta ?? null;
  state.stakeholderEngagement = report.stakeholderEngagement ?? null;
  walkSections(report.sections ?? [], (section) => {
    if (section.displayTitle) state.sectionTitles[section.key] = section.displayTitle;
  });
  walkBlocks(report.sections ?? [], (block) => {
    if (isGeneratedParagraph(block)) {
      state.generatedBlocks[block.id] = {
        content: block.content ?? null,
        state: block.state ?? null,
      };
    } else if (isPersistedTableBlock(block) && block.table) {
      state.tableBlocks[block.id] = {
        children: storedTableRows(block.table.children),
        state: block.state ?? null,
      };
    } else if (
      block.image?.layoutAssetSlot
      && (block.image.layoutAssetIds?.length ?? 0) > 0
    ) {
      // 素材承载位的放置结果必须随状态往返,否则工作台保存会清空已放置图片。
      state.imageBlocks[block.id] = {
        layoutAssetIds: block.image.layoutAssetIds ?? [],
        state: "ready",
      };
    }
  });
  // Validation applies schema defaults in place (`useDefaults`), and the snapshot shares
  // `meta` and other sub-objects with the runtime Report by reference. Validate a copy so
  // orchestration defaults such as `meta.primaryInputMode` never land on Report.meta, whose
  // server contract forbids extra fields (plan, diagnose and export would all reject it).
  return parseStoredReportStateValue(structuredClone(state));
}

export function parseStoredReportState(raw: string | null): StoredReportStateV4 {
  if (raw === null) return emptyStoredReportState();
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new StoredReportStateJSONError("报告状态快照不是有效 JSON", { cause: error });
  }
  if (
    parsed === null
    || typeof parsed !== "object"
    || Array.isArray(parsed)
    || !("version" in parsed)
    || parsed.version !== STORED_REPORT_STATE_VERSION
  ) {
    const version = parsed !== null
      && typeof parsed === "object"
      && !Array.isArray(parsed)
      && "version" in parsed
      ? parsed.version
      : "缺失";
    throw new StoredReportStateVersionError(version);
  }
  return parseStoredReportStateValue(parsed);
}

export function parseLocalStoredReportState(raw: string | null): {
  state: StoredReportStateV4 | null;
  discardedObsoleteVersion: boolean;
} {
  try {
    return { state: parseStoredReportState(raw), discardedObsoleteVersion: false };
  } catch (error) {
    if (error instanceof StoredReportStateVersionError) {
      return { state: null, discardedObsoleteVersion: true };
    }
    throw error;
  }
}

function applyFieldValues(
  template: Report,
  state: StoredReportStateV4,
): Report["fields"] {
  const fields: Report["fields"] = {};
  for (const [key, field] of Object.entries(template.fields ?? {})) {
    fields[key] = {
      ...field,
      value: Object.prototype.hasOwnProperty.call(state.fields, key)
        ? state.fields[key]
        : field.value,
    };
  }
  return fields;
}

function applyIntakeAnswers(
  template: Report,
  state: StoredReportStateV4,
): Report["intakeItems"] {
  return (template.intakeItems ?? []).map((item) => {
    const stored = state.intakeItems[item.key];
    return stored
      ? {
          ...item,
          answer: stored.answer ?? null,
          supplement: stored.supplement ?? null,
        }
      : item;
  });
}

function applyStoredBlocks(
  sections: Report["sections"],
  state: StoredReportStateV4,
): Report["sections"] {
  return (sections ?? []).map((section) => ({
    ...section,
    displayTitle: state.sectionTitles[section.key] ?? section.displayTitle,
    blocks: (section.blocks ?? []).map((block) => {
      if (isGeneratedParagraph(block)) {
        const stored = state.generatedBlocks[block.id];
        return stored
          ? {
              ...block,
              content: stored.content ?? block.content,
              state: stored.state ?? block.state,
            }
          : block;
      }
      if (isPersistedTableBlock(block) && block.table) {
        const stored = state.tableBlocks[block.id];
        return stored
          ? {
              ...block,
              state: stored.state ?? block.state,
              table: {
                ...block.table,
                children: stored.children ?? block.table.children,
              },
            }
          : block;
      }
      if (block.image?.layoutAssetSlot) {
        const stored = state.imageBlocks[block.id];
        return stored
          ? {
              ...block,
              state: stored.state,
              image: { ...block.image, layoutAssetIds: stored.layoutAssetIds },
            }
          : block;
      }
      return block;
    }),
    children: section.children
      ? applyStoredBlocks(section.children, state)
      : section.children,
  }));
}

export function applyStoredStateToTemplate(
  template: Report,
  state: StoredReportStateV4,
): Report {
  const storedAppendix = state.appendixPackage;
  const templateAppendix = template.appendixPackage;
  return {
    ...template,
    fields: applyFieldValues(template, state),
    intakeItems: applyIntakeAnswers(template, state),
    assessmentInput: state.assessmentInput ?? template.assessmentInput ?? null,
    assessment: null,
    disclosureProfile: state.disclosureProfile ?? template.disclosureProfile ?? null,
    appendixPackage: storedAppendix
      ? {
          ...templateAppendix,
          ...storedAppendix,
          ...(storedAppendix.externalAssuranceReport
            ? {
                externalAssuranceReport: {
                  ...templateAppendix?.externalAssuranceReport,
                  ...storedAppendix.externalAssuranceReport,
                },
              }
            : {}),
          ...(storedAppendix.readerFeedbackContactInformation
            ? {
                readerFeedbackContactInformation: {
                  ...templateAppendix?.readerFeedbackContactInformation,
                  ...storedAppendix.readerFeedbackContactInformation,
                },
              }
            : {}),
        }
      : templateAppendix,
    meta: reportMetaFromStored(state.meta) ?? template.meta ?? null,
    stakeholderEngagement: state.stakeholderEngagement
      ?? template.stakeholderEngagement
      ?? null,
    sections: applyStoredBlocks(template.sections ?? [], state),
  };
}

/**
 * 以最近一次权威服务端 state 为基线,保全前端投影覆盖不到的内容。
 *
 * 浏览器运行时 Report 只含当前已装配的章节与答案键集;议题章节的生成正文、表格行、素材图片放置
 * 与 intake 答案(generatedBlocks/tableBlocks/imageBlocks/intakeItems 中不属于当前投影键集的键)
 * 在 reportToStoredReportState 的重建中会随装配变化而缺席。若直接整体 PUT,会把这些服务端事实
 * 无声抹掉——前端是窄投影的 owner,不是全量 state 的 owner。
 */
export function mergeStoredStatePreservingUnprojected(
  projected: StoredReportStateV4,
  baseline: StoredReportStateV4,
  projectedBlockIds: ReadonlySet<string>,
  projectedSectionKeys: ReadonlySet<string>,
  projectedIntakeItemKeys: ReadonlySet<string>,
): StoredReportStateV4 {
  const mergeByKeys = <T>(
    own: Record<string, T>,
    base: Record<string, T>,
    projectedKeys: ReadonlySet<string>,
  ): Record<string, T> => {
    const next: Record<string, T> = { ...own };
    for (const [key, value] of Object.entries(base)) {
      if (!projectedKeys.has(key) && !(key in next)) next[key] = value;
    }
    return next;
  };
  return {
    ...projected,
    // 以下两个字段是**服务端拥有**的（后端 SERVER_OWNED_STATE_FIELDS）：权威保全在
    // put_state 的锁内、与 CAS 同事务，锁内旧值定义上不可能陈旧。这里的回填只是
    // 第二道防线，用于减少无谓的字段抖动——它依赖「baseline 是新鲜的」这个前端
    // 无法自证的前提，因此不得被当作正确性来源（基线陈旧时这里的
    // `?? null` 恰恰是覆盖的执行者，而非防护）。
    companyBusinessSummary: baseline.companyBusinessSummary ?? null,
    meta: projected.meta
      ? { ...projected.meta, primaryInputMode: baseline.meta?.primaryInputMode ?? null }
      : baseline.meta ?? null,
    intakeItems: mergeByKeys(projected.intakeItems, baseline.intakeItems, projectedIntakeItemKeys),
    sectionTitles: mergeByKeys(projected.sectionTitles, baseline.sectionTitles, projectedSectionKeys),
    generatedBlocks: mergeByKeys(projected.generatedBlocks, baseline.generatedBlocks, projectedBlockIds),
    tableBlocks: mergeByKeys(projected.tableBlocks, baseline.tableBlocks, projectedBlockIds),
    imageBlocks: mergeByKeys(projected.imageBlocks, baseline.imageBlocks, projectedBlockIds),
  };
}

/** 生成用于 PUT 的完整 state:前端拥有的部分来自当前投影,投影之外的部分来自权威基线。 */
export function buildStoredReportStatePayload(
  report: Report,
  baseline: StoredReportStateV4 | null,
): StoredReportStateV4 {
  const projected = reportToStoredReportState(report);
  if (!baseline) return projected;
  const blockIds = new Set<string>();
  const sectionKeys = new Set<string>();
  const intakeItemKeys = new Set<string>();
  walkSections(report.sections ?? [], (section) => sectionKeys.add(section.key));
  walkBlocks(report.sections ?? [], (block) => blockIds.add(block.id));
  for (const item of report.intakeItems ?? []) intakeItemKeys.add(item.key);
  return mergeStoredStatePreservingUnprojected(projected, baseline, blockIds, sectionKeys, intakeItemKeys);
}

export function serializeStoredReportState(
  report: Report,
  baseline: StoredReportStateV4 | null = null,
): string {
  return JSON.stringify(buildStoredReportStatePayload(report, baseline));
}
