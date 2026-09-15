// ABOUTME: 报告正文页：生成成功后按 Report 结构阅读整份报告、逐段编辑（块级动作 + 撤销）、逐块查看溯源、导出 Word。
// ABOUTME: 放行门是「最近一次生成成功」；Report 仍由 AppProvider 持久化，本页只把编辑动作写回 Report，不持第二份真相。
// ABOUTME(en): Report document page: read the whole generated report, edit paragraphs as undoable block edits, inspect provenance, export Word.
// ABOUTME(en): Gated on the latest generation having succeeded; AppProvider persists the Report, this page only writes edits into it.
"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";

import { ChecksDrawer } from "@/components/editor/checks-drawer";
import { KeyboardFlowBar } from "@/components/editor/keyboard-flow-bar";
import { SideDrawer } from "@/components/editor/side-drawer";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { useApp } from "@/lib/app-context";
import {
  applyEdit,
  blockTableEdit,
  blockTextEdit,
  commitEdit,
  editedBlockIdsFromLog,
  EMPTY_EDIT_LOG,
  inlineText,
  revertEdit,
  undoEdit,
  type EditLog,
} from "@/lib/block-edits";
import {
  fetchBlockProvenance,
  provenanceByBlock,
  type ReportBlockProvenanceProjection,
} from "@/lib/block-provenance-api";
import { deriveDocument, editableBlockIds } from "@/lib/derive";
import { stepSelection } from "@/lib/editable-sequence";
import { detectPlatform, matchShortcut, type Platform } from "@/lib/editor-shortcuts";
import { resolveIssueJump } from "@/lib/issue-jump";
import { LayoutAssetMetadataProvider } from "@/lib/layout-asset-metadata-context";
import { ReportProvider, type ReportDocumentActions } from "@/lib/report-context";
import { fetchLatestReportGeneration } from "@/lib/report-generation-api";
import { findBlock, updateBlockTable } from "@/lib/report-mutations";
import { activeReportScope } from "@/lib/active-report-scope";
import { getReportState } from "@/lib/report-store";
import {
  regenerateSection as requestSectionRewrite,
  sectionRewriteIntent,
  type SectionRewriteIntent,
} from "@/lib/section-generation-api";
import { resolvedDisplayTitleByKey, updateSectionDisplayTitle } from "@/lib/section-titles";
import { REPORT_DOCUMENT_SCREEN_LABEL } from "@/lib/report-navigation-labels";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import type { Issue } from "@/lib/api";
import type { GsTable, StakeholderEngagementProfile } from "@/lib/schema";

import { BlockProvenancePanel } from "./block-provenance-panel";
import { sectionAnchorId } from "./document-nodes";
import { DocumentRenderer } from "./document-renderer";
import { useWordExport } from "./use-word-export";

type Gate = "checking" | "ready" | "not_generated";
const NARROW_QUERY = "(max-width: 900px)";

const skeletonBar = (width: string): CSSProperties => ({
  height: 14,
  width,
  background: "var(--surface-sunken)",
  borderRadius: "var(--radius-control)",
  marginBottom: 12,
});

export function ReportDocumentPage() {
  const t = useT();
  // Save state is rendered once by AppShell (#coach-autosave); the toolbar does not repeat it.
  const {
    report,
    setReport,
    activeReportId,
    activeReportCapabilities,
    persistNow,
    applyAuthoritativeReportState,
  } = useApp();

  // Render gate: the page shows prose only once the latest generation is known to have succeeded.
  // Facts are keyed by report id so switching reports derives "checking" without a synchronous reset.
  const [generationFact, setGenerationFact] = useState<{ reportId: string; gate: Gate } | null>(null);
  useEffect(() => {
    if (!activeReportId) return;
    let active = true;
    void fetchLatestReportGeneration(activeReportId)
      .then((generation) => {
        if (active) {
          setGenerationFact({
            reportId: activeReportId,
            gate: generation?.status === "succeeded" ? "ready" : "not_generated",
          });
        }
      })
      .catch(() => {
        if (active) setGenerationFact({ reportId: activeReportId, gate: "not_generated" });
      });
    return () => {
      active = false;
    };
  }, [activeReportId]);
  const gate: Gate = generationFact?.reportId === activeReportId ? generationFact.gate : "checking";

  // Provenance of the latest revision; loaded once per report, never inferred in the browser.
  const [provenanceFact, setProvenanceFact] = useState<{
    reportId: string;
    projection: ReportBlockProvenanceProjection | null;
    error: string | null;
  } | null>(null);
  useEffect(() => {
    if (gate !== "ready" || !activeReportId) return;
    let active = true;
    void fetchBlockProvenance(activeReportId)
      .then((projection) => {
        if (active) setProvenanceFact({ reportId: activeReportId, projection, error: null });
      })
      .catch((error: unknown) => {
        console.error("Block provenance load failed", error);
        if (active) {
          setProvenanceFact({
            reportId: activeReportId,
            projection: null,
            error: t.reportDocument.errorProvenance,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [gate, activeReportId, t]);
  const provenance = provenanceFact?.reportId === activeReportId ? provenanceFact.projection : null;
  const provenanceError = provenanceFact?.reportId === activeReportId ? provenanceFact.error : null;
  const provenanceLoading = gate === "ready" && provenanceFact?.reportId !== activeReportId;
  const provenanceEntries = useMemo(() => provenanceByBlock(provenance), [provenance]);

  const nodes = useMemo(() => deriveDocument(report), [report]);
  const editableIds = useMemo(() => editableBlockIds(nodes), [nodes]);

  // Selection / editing state (design.md §5.5 select-edit duality) and the block-level edit log.
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [editingBlockId, setEditingBlockId] = useState<string | null>(null);
  const [editLog, setEditLogState] = useState<EditLog>(EMPTY_EDIT_LOG);
  const editLogRef = useRef(editLog);
  const setEditLog = useCallback((next: EditLog) => {
    editLogRef.current = next;
    setEditLogState(next);
  }, []);
  const reportRef = useRef(report);
  useEffect(() => {
    reportRef.current = report;
  }, [report]);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const editedBlockIds = useMemo<ReadonlySet<string>>(() => {
    if (!provenance) return editedBlockIdsFromLog(editLog);
    const edited = new Set<string>();
    for (const entry of provenance.blocks) {
      if (!entry.generated_content) continue;
      const block = findBlock(report, entry.block_id);
      if (block && inlineText(block.content) !== inlineText(entry.generated_content)) edited.add(entry.block_id);
    }
    return edited;
  }, [provenance, report, editLog]);

  // 整节重写：服务端重新裁定门禁（额度 403、进行中 409、资料门禁 422），客户端不预判。
  // 成功后**重取权威 state 再整体应用**，不用局部 updater——服务端本次改了正文、
  // 章节标题与业务摘要等多个字段，而 applyServerReportUpdate 的局部回放对
  // 非服务端拥有字段（如 sectionTitles）只有这一道防线，逐个回放漏一个就静默丢数据。
  // 必须定义在 actions useMemo **之前**：后者的依赖数组引用它，const 在初始化前处于
  // 暂时性死区，顺序颠倒会在渲染时抛错。
  const rewriteIntentRef = useRef<SectionRewriteIntent | null>(null);
  const [rewritingSection, setRewritingSection] = useState<string | null>(null);
  const [rewriteError, setRewriteError] = useState<string | null>(null);
  const handleRegenerateSection = useCallback(
    (sectionKey: string) => {
      if (!activeReportId || rewritingSection !== null) return;
      void (async () => {
        setRewritingSection(sectionKey);
        setRewriteError(null);
        try {
          const server = await getReportState(activeReportId);
          const intent = sectionRewriteIntent(
            rewriteIntentRef.current,
            activeReportId,
            sectionKey,
            server.state_seq,
            () => crypto.randomUUID(),
          );
          rewriteIntentRef.current = intent;
          const batch = await requestSectionRewrite(
            activeReportId,
            sectionKey,
            reportRef.current,
            intent.baseStateSeq,
            intent.idempotencyKey,
          );
          const applied = await getReportState(activeReportId);
          await applyAuthoritativeReportState(applied.state, batch.state_seq);
          rewriteIntentRef.current = null;
          // 正文已被服务端整节替换，本地撤销日志的 before/after 不再对应当前内容。
          setEditLog(EMPTY_EDIT_LOG);
        } catch (cause) {
          console.error("Section rewrite failed", cause);
          setRewriteError(t.reportDocument.regenerateSectionFailed);
        } finally {
          setRewritingSection(null);
        }
      })();
    },
    [activeReportId, applyAuthoritativeReportState, rewritingSection, setEditLog, t],
  );

  const actions = useMemo<ReportDocumentActions>(
    () => ({
      selectBlock: (blockId) => setSelectedBlockId(blockId),
      beginEdit: (blockId) => {
        if (!editableIds.includes(blockId)) return;
        setSelectedBlockId(blockId);
        setEditingBlockId(blockId);
      },
      commitEdit: (blockId, text) => {
        setEditingBlockId(null);
        setSelectedBlockId(blockId);
        wrapperRef.current?.focus({ preventScroll: true });
        const edit = blockTextEdit(reportRef.current, blockId, text);
        if (!edit) return;
        setReport((current) => applyEdit(current, edit));
        setEditLog(commitEdit(editLogRef.current, edit));
      },
      // 表格与段落共用一条编辑日志：整表 before/after 一次提交、一次撤销。
      commitTableEdit: (blockId, updater) => {
        setSelectedBlockId(blockId);
        const edit = blockTableEdit(reportRef.current, blockId, updater);
        if (!edit) return;
        setReport((current) => applyEdit(current, edit));
        setEditLog(commitEdit(editLogRef.current, edit));
      },
      // 权益不含整节重写时不提供该动作——按钮随之不渲染（HeadingBlock 按是否传入判断）。
      regenerateSection: activeReportScope(activeReportCapabilities).canRegenerateSections
        ? handleRegenerateSection
        : undefined,
      cancelEdit: () => setEditingBlockId(null),
    }),
    [
      activeReportCapabilities,
      editableIds,
      handleRegenerateSection,
      setReport,
      setEditLog,
    ],
  );

  const undo = useCallback(() => {
    const result = undoEdit(editLogRef.current);
    if (!result) return;
    setEditLog(result.log);
    setReport((current) => revertEdit(current, result.edit));
    setSelectedBlockId(result.edit.blockId);
  }, [setEditLog, setReport]);

  const updateTable = useCallback(
    (blockId: string, updater: (table: GsTable) => GsTable) => setReport((current) => updateBlockTable(current, blockId, updater)),
    [setReport],
  );
  const updateStakeholderEngagement = useCallback(
    (updater: (profile: StakeholderEngagementProfile) => StakeholderEngagementProfile) =>
      setReport((current) => (current.stakeholderEngagement ? { ...current, stakeholderEngagement: updater(current.stakeholderEngagement) } : current)),
    [setReport],
  );

  // Keyboard flow: the document column owns ↑↓ / Enter / ⌘Z / ⌘S / ?; the textarea owns Esc.
  const [platform, setPlatform] = useState<Platform>("mac");
  const [helpOpen, setHelpOpen] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setPlatform(detectPlatform()), []);
  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const action = matchShortcut(event, platform);
      if (!action) return;
      const editing = editingBlockId !== null;
      switch (action) {
        case "select":
          if (editing) return;
          event.preventDefault();
          setSelectedBlockId(stepSelection(editableIds, selectedBlockId, event.key === "ArrowUp" ? "up" : "down"));
          break;
        case "edit":
          if (editing || !selectedBlockId || !editableIds.includes(selectedBlockId)) return;
          event.preventDefault();
          setEditingBlockId(selectedBlockId);
          break;
        case "done":
          break; // the editor commits on Esc itself
        case "undo":
          if (editing) return;
          event.preventDefault();
          undo();
          break;
        case "save":
          event.preventDefault();
          void persistNow().catch(() => {});
          break;
        case "help":
          if (editing) return;
          event.preventDefault();
          setHelpOpen((open) => !open);
          break;
      }
    },
    [platform, editingBlockId, editableIds, selectedBlockId, undo, persistNow],
  );

  // Directory ↔ document: the directory scrolls to section anchors; the renderer reports the section in view.
  const [activeSectionKey, setActiveSectionKey] = useState<string | null>(null);
  const onSelectSection = useCallback((sectionKey: string) => {
    setActiveSectionKey(sectionKey);
    const anchor = sectionAnchorId(sectionKey);
    document.getElementById(anchor)?.scrollIntoView({ block: "start", behavior: "smooth" });
    window.history.replaceState(null, "", `#${anchor}`);
  }, []);
  useEffect(() => {
    if (gate !== "ready") return;
    const hash = window.location.hash.slice(1);
    if (hash) document.getElementById(hash)?.scrollIntoView({ block: "start" });
  }, [gate]);

  // Narrow screens turn the docked provenance panel into a drawer (same breakpoint as the shell).
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const apply = () => setNarrow(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  const { checkIssues, exporting, alert, openChecks, confirmExport, closeChecks, dismissAlert } = useWordExport({
    report,
    reportId: activeReportId,
  });
  const onJumpIssue = useCallback((issue: Issue) => {
    const plan = resolveIssueJump(issue);
    for (const selector of plan.scrollSelectors) {
      const target = document.querySelector(selector);
      if (target) {
        target.scrollIntoView({ block: "center", behavior: "smooth" });
        return;
      }
    }
    if (plan.fallbackHref) window.location.assign(plan.fallbackHref);
  }, []);

  const selectedEntry = selectedBlockId ? provenanceEntries.get(selectedBlockId) ?? null : null;
  const selectedBlock = selectedBlockId ? findBlock(report, selectedBlockId) : undefined;
  const selectedText = selectedBlock?.type === "paragraph" ? inlineText(selectedBlock.content) : null;
  const canExport = activeReportCapabilities?.can_export_word === true;
  const undoCount = editLog.past.length;

  // 恢复到生成稿：基线是冻结 revision（随溯源投影下发），刷新后仍在；
  // 内存里的撤销日志刷新即失，故这是「改坏了怎么退回」的持久出口。
  // 恢复本身也走一次编辑提交，因此它同样可被「撤销上一处修改」撤回。
  const restoreGenerated = useCallback(
    (blockId: string) => {
      const generated = provenance?.blocks.find((item) => item.block_id === blockId)?.generated_content;
      if (!generated) return;
      const edit = blockTextEdit(reportRef.current, blockId, inlineText(generated));
      if (!edit) return;
      setReport((current) => applyEdit(current, edit));
      setEditLog(commitEdit(editLogRef.current, edit));
      setSelectedBlockId(blockId);
    },
    [provenance, setReport, setEditLog],
  );

  // 动态标题过期会阻断正式导出（diagnostics 的 stale_display_title）。design.md §5.4 给了
  // 三条处理：重新生成、编辑标题、保留当前标题。前两条在此——「保留」即以当前正文重新盖
  // 指纹，不调用模型；「编辑」由用户给出文本。两者都经既有保存通道落库。
  const keepSectionTitle = useCallback(
    (sectionKey: string) => {
      const current = resolvedDisplayTitleByKey(reportRef.current, sectionKey);
      if (!current) return;
      void updateSectionDisplayTitle(reportRef.current, sectionKey, current).then((next) =>
        setReport(() => next),
      );
    },
    [setReport],
  );

  const editSectionTitle = useCallback(
    (sectionKey: string) => {
      const current = resolvedDisplayTitleByKey(reportRef.current, sectionKey) ?? "";
      const text = window.prompt(t.checksDrawer.editTitlePrompt, current);
      if (text === null || !text.trim()) return;
      void updateSectionDisplayTitle(reportRef.current, sectionKey, text).then((next) =>
        setReport(() => next),
      );
    },
    [setReport, t],
  );

  // 重写失败必须可见：静默失败会让用户以为正文已更新。文案是代码侧生成的稳定提示，
  // 不透传服务端串（403/409/422 各自语义只进日志）。
  const rewriteAlert = rewriteError ? (
    <p
      role="alert"
      style={{
        margin: "0 0 10px",
        fontSize: "var(--text-label-size)",
        color: "var(--destructive)",
      }}
    >
      {rewriteError}
    </p>
  ) : null;

  const panel = (
    <BlockProvenancePanel
      entry={selectedEntry}
      currentText={selectedText}
      projection={provenance}
      loading={provenanceLoading}
      error={provenanceError}
      onClose={narrow ? () => setSelectedBlockId(null) : undefined}
      onRestore={restoreGenerated}
    />
  );

  return (
    <LayoutAssetMetadataProvider reportId={activeReportId ?? null}>
      <ReportProvider
        report={report}
        updateTable={updateTable}
        updateStakeholderEngagement={updateStakeholderEngagement}
        preview
        tablesEditable
        selectedBlockId={selectedBlockId}
        editingBlockId={editingBlockId}
        editedBlockIds={editedBlockIds}
        actions={actions}
      >
        <AppShell
          screenId="report-document"
          screenLabel={REPORT_DOCUMENT_SCREEN_LABEL}
          contentMaxWidth={1680}
          issues={checkIssues}
          directory={gate === "ready" ? { activeSectionKey, onSelectSection } : false}
        >
          {gate === "checking" ? (
            <div aria-busy="true" aria-label={t.reportDocument.loadingAria} style={{ maxWidth: 680, margin: "24px auto" }}>
              <div className="gs-skeleton" style={skeletonBar("40%")} />
              <div className="gs-skeleton" style={skeletonBar("100%")} />
              <div className="gs-skeleton" style={skeletonBar("92%")} />
              <div className="gs-skeleton" style={skeletonBar("96%")} />
            </div>
          ) : null}
          {gate === "not_generated" ? (
            <EmptyState
              title={t.reportDocument.notGeneratedTitle}
              description={t.reportDocument.notGeneratedBody}
              action={{ label: t.reportDocument.goToGeneration, href: "/reports/generation" }}
              style={{ margin: "48px auto" }}
            />
          ) : null}
          {gate === "ready" ? (
            <>
              {rewriteAlert}
              <div className="gs-document-toolbar" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
                <h1 style={{ fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)", margin: 0, marginRight: "auto" }}>
                  {t.shell.reportDocumentPage}
                </h1>
                {rewritingSection !== null ? (
                  <span
                    role="status"
                    style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)", marginRight: 4 }}
                  >
                    {t.reportDocument.regeneratingSection}
                  </span>
                ) : null}
                {undoCount > 0 ? (
                  <Button variant="secondary" size="sm" onClick={undo} style={{ marginRight: 4 }}>
                    {interpolate(t.reportDocument.undo, { count: undoCount })}
                  </Button>
                ) : null}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void openChecks()}
                  disabled={!canExport || exporting}
                  disabledReason={!canExport ? t.reportDocument.exportDisabled : exporting ? t.reportDocument.exporting : undefined}
                >
                  {t.reportDocument.exportWord}
                </Button>
              </div>
              {alert ? (
                <div
                  role="alert"
                  style={{
                    marginBottom: 16,
                    padding: "10px 14px",
                    border: "1px solid var(--destructive)",
                    borderRadius: "var(--radius-control)",
                    color: "var(--destructive)",
                    fontSize: "var(--text-label-size)",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <span style={{ marginRight: "auto" }}>{alert}</span>
                  <button type="button" onClick={dismissAlert} style={{ border: "none", background: "transparent", color: "var(--destructive)", cursor: "pointer", fontSize: "var(--text-label-size)" }}>
                    {t.reportDocument.acknowledge}
                  </button>
                </div>
              ) : null}
              <div
                className="gs-document-layout"
                style={{ display: "grid", gridTemplateColumns: narrow ? "minmax(0, 1fr)" : "minmax(0, 1fr) 360px", gap: 24, alignItems: "start" }}
              >
                {/* Clean document flow, no cards or shadows; ~680px centred column (design.md §2.2/§8). */}
                <div
                  ref={wrapperRef}
                  tabIndex={0}
                  onKeyDown={onKeyDown}
                  className="gs-document-column"
                  style={{ outline: "none", minWidth: 0, width: "100%", maxWidth: 680, margin: "0 auto", padding: "8px 24px 48px", boxSizing: "border-box" }}
                >
                  <DocumentRenderer nodes={nodes} onActiveSectionChange={setActiveSectionKey} />
                </div>
                {!narrow ? (
                  <aside
                    className="gs-document-aside"
                    aria-label={t.reportDocument.sourcesAria}
                    style={{
                      position: "sticky",
                      top: "calc(var(--topbar-height) + 40px)",
                      maxHeight: "calc(100vh - var(--topbar-height) - 56px)",
                      overflowY: "auto",
                      borderLeft: "1px solid var(--border)",
                    }}
                  >
                    {panel}
                  </aside>
                ) : null}
              </div>
            </>
          ) : null}
        </AppShell>

        {gate === "ready" && narrow && selectedBlockId ? (
          <SideDrawer labelId="block-provenance-title" onClose={() => setSelectedBlockId(null)} width={380}>
            {panel}
          </SideDrawer>
        ) : null}

        {gate === "ready" ? (
          <KeyboardFlowBar platform={platform} onPlatformChange={setPlatform} helpOpen={helpOpen} onToggleHelp={() => setHelpOpen((open) => !open)} />
        ) : null}

        {checkIssues !== null ? (
          <ChecksDrawer
            issues={checkIssues}
            exporting={exporting}
            onConfirm={() => void confirmExport()}
            onClose={closeChecks}
            onJump={onJumpIssue}
            onKeepTitle={keepSectionTitle}
            onEditTitle={editSectionTitle}
          />
        ) : null}
      </ReportProvider>
    </LayoutAssetMetadataProvider>
  );
}
