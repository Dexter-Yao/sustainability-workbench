// ABOUTME: 向报告正文页的渲染组件提供当前 Report、块查询、块级选中/编辑状态与表格写回动作。
// ABOUTME: 字段与问卷写入归 AppProvider（useApp）；本上下文不持久化，编辑动作由页面经编辑日志写回 Report。
// ABOUTME(en): Provides the current Report, block lookup, block selection/editing state and table write-backs to document renderers.
// ABOUTME(en): Field and intake writes stay in AppProvider; edits flow through the page's edit log back into the Report.
"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { Block, GsTable, Report, StakeholderEngagementProfile } from "./schema";

export interface ReportDocumentActions {
  selectBlock: (blockId: string | null) => void;
  beginEdit: (blockId: string) => void;
  commitEdit: (blockId: string, text: string) => void;
  /**
   * 表格的一次提交：整表 updater 走与段落同一条编辑日志。
   *
   * 表格渲染器不再直接调 `updateTable`——那是三条互不记录的写路径（单元格、增行、删行），
   * 改动既无撤销也无差异。经此入口后「一次操作一次撤销」对段落与表格一致。
   */
  commitTableEdit: (blockId: string, updater: (table: GsTable) => GsTable) => void;
  /**
   * 重写整节（服务端整节生成）。
   *
   * 省略即不渲染入口——权益不含该能力、或页面处于只读场景时都不应出现按钮。
   * 额度、进行中批次与资料门禁一律由服务端裁定，客户端不预判。
   */
  regenerateSection?: (sectionKey: string) => void;
  cancelEdit: () => void;
}

interface ReportCtx extends ReportDocumentActions {
  report: Report;
  blockById: (id: string) => Block | undefined;
  updateTable: (blockId: string, updater: (table: GsTable) => GsTable) => void;
  updateStakeholderEngagement: (updater: (profile: StakeholderEngagementProfile) => StakeholderEngagementProfile) => void;
  /** Read-only rendering for stakeholder profiles; prose and table editing are governed separately. */
  preview: boolean;
  /**
   * 普通表格是否可编辑。
   *
   * 与 `preview` 分开：`preview` 管的是「利益相关方档案这类只读投影」，报告正文页需要
   * 表格可编辑却仍保持该档案只读。合用一个开关会让「解锁表格」连带解锁档案编辑器。
   * 具体某张表能否编辑仍由 `isTableEditable`（blockType/source/rowSource）决定。
   */
  tablesEditable: boolean;
  selectedBlockId: string | null;
  editingBlockId: string | null;
  editedBlockIds: ReadonlySet<string>;
}

const Ctx = createContext<ReportCtx | null>(null);

const NO_ACTIONS: ReportDocumentActions = {
  selectBlock: () => {},
  beginEdit: () => {},
  commitEdit: () => {},
  commitTableEdit: () => {},
  cancelEdit: () => {},
};

const NO_EDITS: ReadonlySet<string> = new Set();

export function ReportProvider({
  report,
  updateTable,
  updateStakeholderEngagement,
  preview,
  tablesEditable = false,
  selectedBlockId = null,
  editingBlockId = null,
  editedBlockIds = NO_EDITS,
  actions = NO_ACTIONS,
  children,
}: {
  report: Report;
  updateTable: (blockId: string, updater: (table: GsTable) => GsTable) => void;
  updateStakeholderEngagement: (updater: (profile: StakeholderEngagementProfile) => StakeholderEngagementProfile) => void;
  preview: boolean;
  /** 省略即不可编辑：只有报告正文页显式开启表格编辑。 */
  tablesEditable?: boolean;
  selectedBlockId?: string | null;
  editingBlockId?: string | null;
  editedBlockIds?: ReadonlySet<string>;
  actions?: ReportDocumentActions;
  children: ReactNode;
}) {
  const value = useMemo<ReportCtx>(() => {
    const map = new Map<string, Block>();
    const walk = (sections: Report["sections"]) => {
      for (const section of sections) {
        for (const block of section.blocks) map.set(block.id, block);
        if (section.children) walk(section.children);
      }
    };
    walk(report.sections);
    return {
      report,
      blockById: (id) => map.get(id),
      updateTable,
      updateStakeholderEngagement,
      preview,
      tablesEditable,
      selectedBlockId,
      editingBlockId,
      editedBlockIds,
      ...actions,
    };
  }, [report, updateTable, updateStakeholderEngagement, preview, tablesEditable, selectedBlockId, editingBlockId, editedBlockIds, actions]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useReport(): ReportCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useReport 必须在 ReportProvider 内使用");
  return ctx;
}
