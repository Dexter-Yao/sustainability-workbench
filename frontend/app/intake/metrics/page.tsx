// ABOUTME: 定量信息页消费 report-bound 结构化输入合同，在线填写与 xlsx 导入均整批原子替换。
// ABOUTME: 每项可填写数值或留空；留空项提交时记为默认无数值原因，页面单页全量渲染（sheet 作一级分区，不分页）。
// ABOUTME: 整批载荷（留空项已补默认原因，完整性天然满足）经 use-structured-autosave 防抖自动保存，
// ABOUTME: 成功后本地投影 meta.quantitativeMetrics 并重跑 KPI 行，不触发权威重载；409 暂停自动保存，横幅点击后才 hydrate。
// ABOUTME: 页头（h1/进度）、说明归位（口径常驻·术语与来源折进 ⓘ）、前进方向与三线表按 design.md §2.2.1、§4 整改。
"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import { CoachMarks } from "@/components/onboarding/CoachMarks";
import { NextStepLink } from "@/components/intake/intake-step-navigation";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FileDropZone } from "@/components/ui/FileDropZone";
import { Hint } from "@/components/ui/Hint";
import { InlineAlert } from "@/components/ui/InlineAlert";
import {
  downloadQuantitativeMetricsTemplate,
  fetchQuantitativeMetricsInput,
  importQuantitativeMetricsWorkbook,
  putQuantitativeMetricsInput,
  StructuredInputConflictError,
} from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepKey } from "@/lib/intake-steps";
import { stepLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { finalizeDecimalDraft, isDecimalDraft, normalizeDecimalPaste } from "@/lib/input-validation";
import {
  derivedSumValue,
  greenhouseGasOtherStandardLabel,
  isDerivedSumMetric,
  projectQuantitativeMetricRows,
  standaloneMetricLabel,
} from "@/lib/quantitative-metrics";
import type {
  QuantitativeMetricDef,
  QuantitativeMetricsResponse,
} from "@/lib/report-api.generated";
import type {
  QuantitativeMetricDraft,
} from "@/lib/schema";
import { useStructuredAutosave } from "@/lib/use-structured-autosave";

import { buildMetricsPayload, isAnswered } from "./draft-metrics";

const ACCEPT = ".xlsx";

/** 页内提示状态机：kind 决定颜色语义，text 是唯一渲染文案；不再靠字符串子串猜测成败。 */
interface IntakeNote {
  kind: "success" | "error" | "conflict" | "info";
  text: string;
}

const NOTE_COLOR: Record<IntakeNote["kind"], string> = {
  success: "var(--accent)",
  error: "var(--destructive)",
  conflict: "var(--warning)",
  info: "var(--muted-foreground)",
};

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-control)",
  background: "var(--background)",
  color: "var(--foreground)",
  fontSize: "var(--text-body-size)",
  padding: "6px 8px",
};

export default function IntakeMetricsPage() {
  const t = useT();
  const { report, activeReportId, activeReportCapabilities, applyAuthoritativeReportState, applyServerReportUpdate } = useApp();
  // 「其他」哨兵随知识包语言（英文包是 "Other"）；写死中文会让该分支在英文包上恒不命中。
  const otherStandardLabel = greenhouseGasOtherStandardLabel(report);
  const scope = activeReportScope(activeReportCapabilities);
  const [input, setInput] = useState<QuantitativeMetricsResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, QuantitativeMetricDraft>>({});
  const [standard, setStandard] = useState("");
  const [standardOther, setStandardOther] = useState("");
  const [busy, setBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  // 导入是整批覆盖动作：文件选定后先经确认对话框（全 Excel 通道统一语义与措辞）。
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [note, setNote] = useState<IntakeNote | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const hydrate = useCallback((next: QuantitativeMetricsResponse) => {
    setInput(next);
    setDrafts(next.current.metrics);
    setStandard(next.current.greenhouseGasAccountingStandard ?? "");
    setStandardOther(next.current.greenhouseGasAccountingStandardOther ?? "");
  }, []);
  const reload = useCallback(async () => {
    if (!activeReportId) throw new Error(t.scoring.noActiveReport);
    const next = await fetchQuantitativeMetricsInput(activeReportId);
    hydrate(next);
  }, [activeReportId, hydrate, t]);

  useEffect(() => {
    let cancelled = false;
    if (!activeReportId) return;
    void fetchQuantitativeMetricsInput(activeReportId)
      .then((next) => {
        if (!cancelled) hydrate(next);
      })
      .catch((error) => {
        console.error("Quantitative metrics load failed", error);
        if (!cancelled) setNote({ kind: "error", text: t.metrics.errorLoad });
      });
    return () => { cancelled = true; };
  }, [activeReportId, hydrate, t]);

  const catalog = useMemo(
    () => scope.status === "ready"
      ? (input?.catalog.filter((metric) => scope.allowedMetricKeys.includes(metric.key)) ?? [])
      : [],
    [input, scope.allowedMetricKeys, scope.status],
  );
  const sheets = useMemo(
    () => [...new Set(catalog.map((metric) => metric.sheet))],
    [catalog],
  );
  const completed = catalog.filter((metric) => isAnswered(drafts[metric.key])).length;
  const progress = catalog.length ? Math.round((completed / catalog.length) * 100) : 0;
  const ghgStandardRequired = catalog.some(
    (metric) => metric.requiresGreenhouseGasAccountingStandard
      && String(drafts[metric.key]?.value ?? "").trim() !== "",
  ) ?? false;

  function updateMetric(key: string, next: QuantitativeMetricDraft) {
    setDrafts((current) => ({ ...current, [key]: next }));
  }

  async function handleMutationError(error: unknown) {
    if (error instanceof StructuredInputConflictError) {
      await applyAuthoritativeReportState(error.current.state, error.current.state_seq);
      await reload();
      setNote({ kind: "conflict", text: t.scoring.conflictNote });
      return;
    }
    throw error;
  }

  async function applyMutation(
    mutation: Awaited<ReturnType<typeof putQuantitativeMetricsInput>>,
    successMessage: string,
  ) {
    await applyAuthoritativeReportState(mutation.state, mutation.state_seq);
    await reload();
    setNote({ kind: "success", text: successMessage });
  }

  const autosavePayload = useMemo(
    () => ({
      metrics: buildMetricsPayload(catalog, drafts, finalizeDecimalDraft),
      greenhouseGasAccountingStandard: standard || null,
      greenhouseGasAccountingStandardOther: standardOther || null,
    }),
    [catalog, drafts, standard, standardOther],
  );

  // 自动保存：整批提交（留空项已按默认无数值原因补全，完整性天然满足）；成功后本地投影 meta.quantitativeMetrics
  // 并用当前 catalog 重跑 KPI 行投影，不触发权威重载；state_seq 直接取 mutation 响应。
  const autosave = useStructuredAutosave({
    payload: autosavePayload,
    enabled: Boolean(input && activeReportId) && catalog.length > 0,
    isConflict: (error) => error instanceof StructuredInputConflictError,
    save: async (payload) => {
      if (!input || !activeReportId) throw new Error(t.scoring.noActiveReport);
      const mutation = await putQuantitativeMetricsInput(activeReportId, {
        expected_state_seq: input.state_seq,
        ...payload,
      });
      applyServerReportUpdate(
        (current) => projectQuantitativeMetricRows(
          {
            ...current,
            meta: {
              ...(current.meta ?? {}),
              quantitativeMetrics: mutation.state.meta?.quantitativeMetrics,
            },
          },
          catalog,
        ),
        mutation.state_seq,
        mutation.state,
      );
      setInput((current) => (current ? { ...current, state_seq: mutation.state_seq } : current));
    },
  });

  // 自动保存失败态直接派生渲染，不经 effect 回写 note（避免同步 setState 级联渲染）；
  // note 仍优先显示（用户刚触发的操作结果），自动保存失败在其后兜底展示。
  const displayedNote = note ?? (autosave.state === "error"
    ? { kind: "error" as const, text: autosave.error ?? t.metrics.errorAutosaveDraft }
    : null);

  const [conflictReloading, setConflictReloading] = useState(false);

  // 409 冲突态：暂停自动保存、草稿保留在本页；只有用户点击后才丢弃本页未保存修改并加载最新内容。
  async function handleConflictReload() {
    setConflictReloading(true);
    try {
      await reload();
      autosave.resume();
      setNote(null);
    } catch (error) {
      console.error("Reload failed", error);
      setNote({ kind: "error", text: t.metrics.errorReloadLatest });
    } finally {
      setConflictReloading(false);
    }
  }

  async function importWorkbook(file: File) {
    if (!input || !activeReportId) return;
    setBusy(true);
    setNote(null);
    try {
      const mutation = await importQuantitativeMetricsWorkbook(
        activeReportId,
        file,
        input.state_seq,
      );
      await applyMutation(mutation, t.metrics.importSucceeded);
    } catch (error) {
      try {
        await handleMutationError(error);
      } catch (unhandled) {
        console.error("Metrics import failed", unhandled);
        setNote({ kind: "error", text: interpolate(t.workbookChannel.importFailed, { table: t.metrics.templateTableLabel }) });
      }
    } finally {
      setBusy(false);
    }
  }

  // 单页全量渲染（不再按 sheet 分部分翻页）：sheet 作为一级分区标题，其下按 category 分组。
  const sheetSections = useMemo(() => {
    return sheets.map((sheet) => {
      const groups: { category: string; metrics: QuantitativeMetricDef[] }[] = [];
      let currentCategory = "";
      for (const metric of catalog) {
        if (metric.sheet !== sheet) continue;
        if (metric.category !== currentCategory) {
          currentCategory = metric.category;
          groups.push({ category: currentCategory, metrics: [metric] });
        } else {
          groups[groups.length - 1].metrics.push(metric);
        }
      }
      return { sheet, groups };
    });
  }, [sheets, catalog]);

  // 页标题派生自步骤声明（intakeStepLabel），由 scope 投影，不本地特判。
  // 注意：该调用必须位于所有钩子之后——钩子声明区间内的未知函数调用会使 React Compiler
  // 无法保持本组件既有手动 memoization（preserve-manual-memoization）。
  const pageTitle = stepLabel(t, intakeStepKey("/intake/metrics"));

  return (
    <main style={{ padding: "0 0 24px" }}>
      <CoachMarks
        stepKey="intake-metrics"
        items={[{ anchorId: "coach-metrics-excel", text: t.metrics.coachExcel }]}
      />
      {/* 页头：h1 + 因果说明 + 全局进度（design.md §2.2.1 必需信息常驻） */}
      <div style={{ padding: "10px 0 16px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
          <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
            {pageTitle}
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
            <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {interpolate(t.metrics.completedOf, { done: completed, total: catalog.length })}
            </span>
            {/* 定量信息为选填页：页首与页脚同置「下一步」，明示可不填完直接进入下一步（design.md §3.1）。 */}
            <NextStepLink pathname="/intake/metrics" scope={scope} />
          </div>
        </div>
        <div
          style={{ marginTop: 10, height: 4, background: "var(--surface-sunken)", borderRadius: "var(--radius-pill)", overflow: "hidden" }}
          role="progressbar"
          aria-valuenow={completed}
          aria-valuemin={0}
          aria-valuemax={catalog.length}
        >
          <div style={{ height: "100%", width: `${progress}%`, background: "var(--accent)", borderRadius: "var(--radius-pill)", transition: "width 0.3s ease" }} />
        </div>
        <p style={{ margin: "10px 0 0", fontSize: "var(--text-label-size)", color: "var(--foreground-secondary)", lineHeight: 1.7 }}>
          {t.metrics.intro}
        </p>
      </div>

      {/* Excel 通道：下载模板 / 导入，与重要性评分页同一形态与命名模式（「下载{表名}模板」「导入{表名}」）。
          拖放区自身可见（FileDropZone dashed）——隐形投放区配上「拖入此区域」的文案，
          等于指向一个看不见的东西。 */}
      <div style={{ padding: "12px 0 16px", borderBottom: "1px solid var(--border)" }}>
        <Button
          variant="secondary"
          size="sm"
          id="coach-metrics-excel"
          disabled={templateBusy || !input || !activeReportId}
          disabledReason={templateBusy ? t.workbookChannel.generatingTemplate : t.metrics.dataLoading}
          onClick={async () => {
            if (!activeReportId) return;
            setTemplateBusy(true);
            setNote(null);
            try {
              await downloadQuantitativeMetricsTemplate(activeReportId);
            } catch (error) {
              console.error("Metrics template download failed", error);
              setNote({ kind: "error", text: interpolate(t.workbookChannel.templateDownloadFailed, { table: t.metrics.templateTableLabel }) });
            } finally {
              setTemplateBusy(false);
            }
          }}
        >
          {templateBusy ? t.workbookChannel.preparingTemplate : t.metrics.downloadTemplate}
        </Button>
        <FileDropZone
          dashed
          disabled={busy || !input}
          style={{ marginTop: 10 }}
          onFiles={(files) => {
            const file = files.find((candidate) => candidate.name.toLowerCase().endsWith(".xlsx"));
            if (!file) {
              setNote({ kind: "error", text: interpolate(t.workbookChannel.wrongFormat, { table: t.metrics.templateTableLabel }) });
              return;
            }
            setPendingImportFile(file);
          }}
        >
          <label
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              padding: "14px 16px",
              fontSize: "var(--text-supporting-size)",
              color: "var(--muted-foreground)",
              cursor: busy || !input ? "not-allowed" : "pointer",
              opacity: busy || !input ? 0.4 : 1,
            }}
          >
            {t.workbookChannel.dropHint}
            <span style={{ color: "var(--foreground)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], textDecoration: "underline", textUnderlineOffset: 2 }}>
              {t.workbookChannel.chooseFile}
            </span>
            <input type="file" accept={ACCEPT} disabled={busy || !input} style={{ display: "none" }} onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) setPendingImportFile(file);
              event.target.value = "";
            }} />
          </label>
        </FileDropZone>
      </div>
      <ConfirmDialog
        open={pendingImportFile !== null}
        title={interpolate(t.workbookChannel.confirmTitle, { table: t.metrics.templateTableLabel })}
        description={t.workbookChannel.confirmBody}
        confirmLabel={t.workbookChannel.confirmAction}
        destructive
        onConfirm={() => {
          const file = pendingImportFile;
          setPendingImportFile(null);
          if (file) void importWorkbook(file);
        }}
        onCancel={() => setPendingImportFile(null)}
      />

      {/* 提示区 */}
      {!activeReportId ? (
        <div role="alert" style={{ marginTop: 8, color: "var(--destructive)", fontSize: "var(--text-label-size)" }}>
          {t.scoring.noActiveReport}
        </div>
      ) : displayedNote ? (
        <div role={displayedNote.kind === "error" ? "alert" : "status"} style={{ padding: "10px 0", color: NOTE_COLOR[displayedNote.kind], fontSize: "var(--text-label-size)" }}>{displayedNote.text}</div>
      ) : null}

      {autosave.state === "conflict" ? (
        <InlineAlert variant="warning" style={{ marginTop: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ marginRight: "auto" }}>{t.scoring.conflictBanner}</span>
            <button
              type="button"
              disabled={conflictReloading}
              onClick={() => void handleConflictReload()}
              style={{ border: "none", background: "transparent", color: "var(--warning)", cursor: "pointer", fontSize: "var(--text-label-size)", textDecoration: "underline" }}
            >
              {conflictReloading ? t.scoring.conflictReloading : t.shell.loadLatestDiscardLocal}
            </button>
          </div>
        </InlineAlert>
      ) : null}

      {/* GHG 核算标准 */}
      {ghgStandardRequired ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 1fr) minmax(200px, 1fr)", gap: 10, padding: "14px 0", borderBottom: "1px solid var(--border)" }}>
          <label>
            <div style={{ fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)", marginBottom: 4 }}>{t.metrics.ghgStandard}</div>
            <select value={standard} onChange={(event) => setStandard(event.target.value)} className="gs-input" style={inputStyle}>
              <option value="">{t.reportConfig.notSelected}</option>
              {input?.greenhouse_gas_accounting_standard_options.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
          <label>
            <div style={{ fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)", marginBottom: 4 }}>{t.metrics.ghgStandardOther}</div>
            <input value={standardOther} disabled={standard !== otherStandardLabel} onChange={(event) => setStandardOther(event.target.value)} placeholder={t.metrics.ghgStandardOtherPlaceholder} style={{ ...inputStyle, opacity: standard === otherStandardLabel ? 1 : 0.5 }} />
          </label>
        </div>
      ) : null}

      {/* 指标表格：sheet 一级分区 + category 分组三线表——表头 --surface 底 + --border-strong 顶/底线 */}
      <div style={{ marginTop: 0 }}>
        {sheetSections.map((section) => (
          <div key={section.sheet}>
            <div style={{ padding: "20px 0 6px", fontSize: "var(--text-section-size)", fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
              {section.sheet}
            </div>
            {section.groups.map((group) => (
          <div key={group.category}>
            <div style={{
              padding: "10px 0 6px",
              fontSize: "var(--text-label-size)",
              fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
              color: "var(--foreground)",
              borderBottom: "1px solid var(--border)",
            }}>
              {group.category}
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
              <colgroup>
                <col style={{ width: "40%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "34%" }} />
                <col style={{ width: "16%" }} />
              </colgroup>
              <thead>
                <tr style={{ background: "var(--surface)", borderTop: "1.5px solid var(--border-strong)", borderBottom: "1.5px solid var(--border-strong)" }}>
                  <th style={{ padding: "8px 4px", fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--muted-foreground)", textAlign: "left" }}>{t.metrics.colMetric}</th>
                  <th style={{ padding: "8px 4px", fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--muted-foreground)", textAlign: "center" }}>{t.metrics.colUnit}</th>
                  <th style={{ padding: "8px 4px", fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--muted-foreground)", textAlign: "left" }}>{t.metrics.colValue}</th>
                  <th style={{ padding: "8px 4px", fontSize: "var(--text-supporting-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--muted-foreground)", textAlign: "center" }}>{t.metrics.colDetail}</th>
                </tr>
              </thead>
              <tbody>
                {group.metrics.map((metric) => {
                  const draft = drafts[metric.key] ?? {};
                  const label = standaloneMetricLabel(metric);
                  const derivedValue = isDerivedSumMetric(metric)
                    ? derivedSumValue(metric, drafts)
                    : undefined;
                  const answered = derivedValue === undefined ? isAnswered(draft) : derivedValue !== null;
                  const isExpanded = expandedKey === metric.key;
                  // 首层与上方分组标题恒等（目录内全部条目皆如此），显示会重复一遍。
                  // 只跳过首层：下层仍是区分信息——培训组的「男性员工」离开「培训覆盖率 › 按性别
                  // 划分」就无法辨认。数据侧 groupPath 保持完整，去重只发生在渲染。
                  const path = metric.groupPath.slice(1).filter(Boolean).join(" › ");
                  return (
                    <MetricRow
                      key={metric.key}
                      metric={metric}
                      label={label}
                      path={path}
                      draft={draft}
                      answered={answered}
                      derivedValue={derivedValue}
                      isExpanded={isExpanded}
                      inputStyle={inputStyle}
                      onUpdate={(next) => updateMetric(metric.key, next)}
                      onToggle={() => setExpandedKey(isExpanded ? null : metric.key)}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
            ))}
          </div>
        ))}
      </div>
      {/* 页内不设保存/翻部分按钮：草稿自动保存（离开页面保底 flush），页间导航唯一归 footer「下一步」。 */}
    </main>
  );
}

function MetricRow({
  metric,
  label,
  path,
  draft,
  answered,
  derivedValue,
  isExpanded,
  inputStyle,
  onUpdate,
  onToggle,
}: {
  metric: QuantitativeMetricDef;
  label: string;
  path: string;
  draft: QuantitativeMetricDraft;
  answered: boolean;
  /** 非派生指标为 undefined；派生指标为求得的值，来源未填齐时为 null。 */
  derivedValue: string | null | undefined;
  isExpanded: boolean;
  inputStyle: CSSProperties;
  onUpdate: (next: QuantitativeMetricDraft) => void;
  onToggle: () => void;
}) {
  const t = useT();
  // 归位（design.md §2.2.1）：metricDefinition（填什么/怎么算）常驻指标名下方；
  // termExplanation（术语与核算口径背景）折进 ⓘ。内部编写痕迹不在此投影。
  return (
    <>
      <tr style={{ borderBottom: "1px solid var(--border)" }}>
        <td style={{ padding: "8px 4px", verticalAlign: "middle" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)", lineHeight: 1.4 }}>{label}</span>
            {metric.termExplanation ? <Hint content={metric.termExplanation} /> : null}
          </div>
          {path ? <div style={{ fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", marginTop: 2 }}>{path}</div> : null}
          {metric.metricDefinition ? (
            <div style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", marginTop: 2, lineHeight: 1.5 }}>
              {metric.metricDefinition}
            </div>
          ) : null}
        </td>
        <td style={{ padding: "8px 4px", verticalAlign: "middle", textAlign: "center", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
          {metric.unit}
        </td>
        <td style={{ padding: "6px 4px", verticalAlign: "middle" }}>
          {derivedValue === undefined ? (
            <input
              type="text"
              inputMode="decimal"
              value={draft.value ?? ""}
              aria-label={interpolate(t.metrics.ariaValue, { label })}
              className="gs-input"
              style={{ ...inputStyle, borderColor: answered ? "var(--border)" : "var(--field-empty-border)", background: "var(--background)" }}
              onChange={(event) => {
                const value = normalizeDecimalPaste(event.target.value);
                if (!isDecimalDraft(value)) return;
                onUpdate({ ...draft, value, noValueReason: value.trim() ? null : draft.noValueReason });
              }}
            />
          ) : (
            // 派生指标不接受手工输入：它由来源指标求和得出，可编辑会造成第二个真相源。
            <input
              type="text"
              readOnly
              value={derivedValue ?? ""}
              aria-label={interpolate(t.metrics.ariaValue, { label })}
              placeholder={t.metrics.derivedPlaceholder}
              className="gs-input"
              style={{ ...inputStyle, borderColor: "var(--border)", background: "var(--surface-sunken)", color: "var(--muted-foreground)" }}
            />
          )}
        </td>
        <td style={{ padding: "6px 4px", verticalAlign: "middle", textAlign: "center" }}>
          <button
            type="button"
            onClick={onToggle}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontSize: "var(--text-section-size)",
              color: "var(--muted-foreground)",
              padding: "2px 6px",
            }}
            aria-label={isExpanded ? t.metrics.collapseDetail : t.metrics.expandDetail}
          >
            {isExpanded ? "▾" : "▸"}
          </button>
        </td>
      </tr>
      {isExpanded ? (
        <tr>
          <td colSpan={4} style={{ padding: "8px 4px 14px", background: "var(--surface-sunken)", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, maxWidth: 480 }}>
              <input
                aria-label={interpolate(t.metrics.ariaDepartment, { label })}
                placeholder={t.metrics.department}
                value={draft.department ?? ""}
                className="gs-input"
                style={inputStyle}
                onChange={(event) => onUpdate({ ...draft, department: event.target.value })}
              />
              <input
                aria-label={interpolate(t.metrics.ariaRemark, { label })}
                placeholder={t.metrics.remark}
                value={draft.note ?? ""}
                className="gs-input"
                style={inputStyle}
                onChange={(event) => onUpdate({ ...draft, note: event.target.value })}
              />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
