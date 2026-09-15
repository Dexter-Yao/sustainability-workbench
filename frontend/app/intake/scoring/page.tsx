// ABOUTME: 重要性识别页消费 report-bound 结构化输入合同，在线填写与 xlsx 导入均原子替换权威评分。
// ABOUTME: 浏览器只暂存未提交草稿；成功或 409 后必须用服务端 state 与 state_seq 重建报告。
// ABOUTME: 在线草稿走 use-structured-autosave 防抖自动保存（draftScores 过滤两维都已填的行，允许子集提交）；
// ABOUTME: 全覆盖提交走既有权威重载路径，部分草稿本地投影 assessmentInput；409 暂停自动保存，横幅点击后才 hydrate。
// ABOUTME: 分类图例为视图级过滤（默认全显），不改动权威评分与计数；矩阵是前端 SVG 交互预览（./matrix），
// ABOUTME: 图例切换与阈值调整即时反映；工作台块预览与 Word 导出仍用后端渲染源。
"use client";

import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { CoachMarks } from "@/components/onboarding/CoachMarks";
import { NextStepLink } from "@/components/intake/intake-step-navigation";
import { Button } from "@/components/ui/Button";
import { fieldControlBorder } from "@/components/ui/FieldRow";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FileDropZone } from "@/components/ui/FileDropZone";
import { Hint } from "@/components/ui/Hint";
import { InlineAlert } from "@/components/ui/InlineAlert";
import { LoadingState } from "@/components/ui/LoadingState";
import {
  downloadAssessmentTemplate,
  fetchAssessmentInput,
  importAssessmentWorkbook,
  putAssessmentInput,
  StructuredInputConflictError,
} from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepKey } from "@/lib/intake-steps";
import { stepLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { DEFAULT_THRESHOLD } from "@/lib/assessment";
import { assessmentUploadMessage, type AssessmentUploadMessage } from "@/lib/assessment-upload-message";
import { finalizeDecimalDraft, isNumericDraft, normalizeDecimalPaste } from "@/lib/input-validation";
import { materialityScoreGuidance, parseMaterialityScore } from "@/lib/materiality-score";
import type {
  AssessmentCounts,
  AssessmentInputResponse,
  ResolvedAssessmentResponse,
  ResolvedAssessmentTopicResponse,
} from "@/lib/report-api.generated";
import type {
  Materiality,
  MaterialityThreshold,
  Report,
  ScoredAssessmentResult,
} from "@/lib/schema";
import { useStructuredAutosave } from "@/lib/use-structured-autosave";

import { draftScores, type ScoreDraft } from "./draft-scores";
import { classifyPreviewMateriality, MaterialityMatrix, QUAD_FILL_OPACITY } from "./matrix";

const ACCEPT = ".xlsx";
/**
 * 分类名是**包资产**：`Report.assessmentVocabulary.materiality` 由服务端按包下发，
 * 已是该包语言（港交所英文包是 "Highly material" 等）。前端写死一份中文映射，
 * 英文报告的图例与摘要就会显示简体分类名。
 */
function materialityLabels(report: Report): Record<Materiality, string> {
  const labels = report.assessmentVocabulary?.materiality;
  return {
    dual: labels?.dual ?? "",
    impact: labels?.impact ?? "",
    financial: labels?.financial ?? "",
    non: labels?.non ?? "",
  };
}
const MAT_COLOR: Record<Materiality, string> = {
  dual: "var(--accent)",
  impact: "var(--ai)",
  financial: "var(--warning)",
  non: "var(--muted-foreground)",
};
const MAT_ORDER: Materiality[] = ["dual", "impact", "financial", "non"];
// 象限图例色阶由矩阵画布的同一份透明度派生（design.md §3.2.1），不另抄一份数值——
// 图例解释的就是画布上的底色，两处失配即缺陷。
const QUAD_SWATCH: Record<Materiality, string> = Object.fromEntries(
  MAT_ORDER.map((materiality) => [
    materiality,
    `color-mix(in srgb, var(--chart-quadrant) ${QUAD_FILL_OPACITY[materiality] * 100}%, transparent)`,
  ]),
) as Record<Materiality, string>;

const numInputBase: CSSProperties = {
  padding: "7px 8px",
  borderRadius: "var(--radius-control)",
  fontSize: "var(--text-body-size)",
  background: "var(--background)",
  color: "var(--foreground)",
  fontFamily: "inherit",
  textAlign: "center",
};

/** 页内提示状态机：kind 决定颜色语义，text 是唯一渲染文案；不再靠字符串子串猜测成败。 */
interface IntakeNote {
  kind: "success" | "error" | "conflict" | "info";
  text: string;
}

const NOTE_TO_ALERT_VARIANT: Record<IntakeNote["kind"], "error" | "warning" | "success" | null> = {
  success: "success",
  error: "error",
  conflict: "warning",
  info: null,
};

/** 双重重要性维度释义取自合同评分尺度：网页与评分表 Excel 共用一份，不在页面另写。 */
function materialityHint(report: Report | null | undefined, dimension: "financial" | "impact"): string {
  const scale = report?.assessmentScoreScale;
  const parts = dimension === "financial"
    ? [scale?.financialMaterialityDefinition, scale?.financialMaterialityExplanation]
    : [scale?.impactMaterialityDefinition, scale?.impactMaterialityExplanation];
  return parts.filter(Boolean).join("");
}

function ResultRow({ topic, labels }: { topic: ResolvedAssessmentTopicResponse; labels: Record<Materiality, string> }) {
  const color = MAT_COLOR[topic.materiality];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 64px 92px",
        gap: 12,
        padding: "9px 0",
        borderBottom: "1px solid var(--border)",
        fontSize: "var(--text-label-size)",
      }}
    >
      <span>{topic.name}</span>
      <span style={{ color: "var(--muted-foreground)" }}>{topic.dimension}</span>
      <span style={{ color, textAlign: "right" }}>{labels[topic.materiality]}</span>
    </div>
  );
}

/** 完成时刻的分类摘要（权威 resolved counts）：措辞与图例同源于包的 assessmentVocabulary。 */
function completionSummary(counts: AssessmentCounts, labels: Record<Materiality, string>): string {
  return `${labels.dual} ${counts.dual ?? 0} · ${labels.financial} ${counts.financial_only ?? 0} · ${labels.impact} ${counts.impact_only ?? 0} · ${labels.non} ${counts.non_material ?? 0}`;
}

export default function IntakeScoringPage() {
  const t = useT();
  const router = useRouter();
  const {
    report,
    activeReportId,
    activeReportCapabilities,
    applyAuthoritativeReportState,
    applyServerReportUpdate,
  } = useApp();
  // 分类名与两轴名都随报告所属知识包（assessmentVocabulary），不随界面语言。
  const matLabels = materialityLabels(report);
  const axisLabels = {
    financial: report.assessmentVocabulary?.materialityAxes.financial ?? "",
    impact: report.assessmentVocabulary?.materialityAxes.impact ?? "",
  };
  const scope = activeReportScope(activeReportCapabilities);
  const [input, setInput] = useState<AssessmentInputResponse | null>(null);
  const [draft, setDraft] = useState<ScoreDraft>({});
  const [threshold, setThreshold] = useState<MaterialityThreshold>(DEFAULT_THRESHOLD);
  const [thresholdDraft, setThresholdDraft] = useState<{ financial: string; impact: string }>({
    financial: String(DEFAULT_THRESHOLD.financial),
    impact: String(DEFAULT_THRESHOLD.impact),
  });
  const [busy, setBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  // 导入是整批覆盖动作：文件选定后先经确认对话框（全 Excel 通道统一语义与措辞）。
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [note, setNote] = useState<IntakeNote | null>(null);
  const [uploadMessage, setUploadMessage] = useState<AssessmentUploadMessage | null>(null);
  const [visibleMats, setVisibleMats] = useState<ReadonlySet<Materiality>>(() => new Set(MAT_ORDER));

  useEffect(() => {
    if (scope.status === "ready" && !scope.collectsMaterialityAssessment) {
      router.replace("/intake/metrics");
    }
  }, [router, scope.collectsMaterialityAssessment, scope.status]);

  const hydrate = useCallback((next: AssessmentInputResponse) => {
    const scoreById = new Map(
      (next.current?.scores ?? []).map((score) => [score.assessmentTopicId, score]),
    );
    setInput(next);
    const nextThreshold = next.current?.threshold ?? DEFAULT_THRESHOLD;
    setThreshold(nextThreshold);
    setThresholdDraft({
      financial: String(nextThreshold.financial),
      impact: String(nextThreshold.impact),
    });
    setDraft(Object.fromEntries(next.topics.map((topic) => {
      const score = scoreById.get(topic.assessmentTopicId);
      return [topic.assessmentTopicId, {
        financial: score ? String(score.financialScore) : "",
        impact: score ? String(score.impactScore) : "",
      }];
    })));
  }, []);

  const reload = useCallback(async () => {
    if (!activeReportId || scope.status !== "ready" || !scope.collectsMaterialityAssessment) {
      throw new Error(t.scoring.errorNotOffered);
    }
    const next = await fetchAssessmentInput(activeReportId);
    hydrate(next);
    return next;
  }, [activeReportId, hydrate, scope.collectsMaterialityAssessment, scope.status, t]);

  // 评分覆盖全部议题后回填权威 resolved（分类、计数与清单）：只更新投影字段，
  // 不重建 draft/threshold——权威重载会把防抖期内正在键入的内容替换掉。
  const syncResolved = useCallback(async () => {
    if (!activeReportId) return;
    try {
      const next = await fetchAssessmentInput(activeReportId);
      setInput((current) => (current
        ? { ...current, resolved: next.resolved, state_seq: next.state_seq }
        : next));
    } catch {
      // 回填失败不阻断填写：预览仍可用，下次完整保存会再试。
    }
  }, [activeReportId]);

  useEffect(() => {
    let cancelled = false;
    if (!activeReportId || scope.status !== "ready" || !scope.collectsMaterialityAssessment) return;
    void fetchAssessmentInput(activeReportId)
      .then((next) => {
        if (!cancelled) hydrate(next);
      })
      .catch((error) => {
        console.error("Assessment input load failed", error);
        if (!cancelled) {
          console.error("Assessment load failed", error);
          setNote({ kind: "error", text: t.scoring.errorLoad });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeReportId, hydrate, scope.collectsMaterialityAssessment, scope.status, t]);

  async function applyMutation(
    mutation: Awaited<ReturnType<typeof putAssessmentInput>>,
    successMessage: string,
  ) {
    await applyAuthoritativeReportState(mutation.state, mutation.state_seq);
    await reload();
    setNote({ kind: "success", text: successMessage });
  }

  async function handleMutationError(error: unknown) {
    if (error instanceof StructuredInputConflictError) {
      await applyAuthoritativeReportState(
        error.current.state,
        error.current.state_seq,
      );
      await reload();
      setNote({ kind: "conflict", text: t.scoring.conflictNote });
      return;
    }
    throw error;
  }

  const draftScoresPayload = useMemo(() => draftScores(input, draft), [input, draft]);
  // 阈值与评分同属本页一次提交的内容：必须一并进入 payload，否则只改阈值时指纹不变，
  // 自动保存与"保存全部"都会被指纹短路静默跳过。
  const autosavePayload = useMemo(
    () => ({ threshold, scores: draftScoresPayload }),
    [threshold, draftScoresPayload],
  );

  // 自动保存草稿：payload 含阈值与已完成行。enabled 不再要求"至少一行完整"——
  // 否则只改阈值、或清空全部评分（合法的归零意图）都会被挡在通道外而永不落库。
  const autosave = useStructuredAutosave({
    payload: autosavePayload,
    enabled: Boolean(input && activeReportId),
    isConflict: (error) => error instanceof StructuredInputConflictError,
    save: async ({ threshold: submittedThreshold, scores }) => {
      if (!input || !activeReportId) throw new Error(t.scoring.noActiveReport);
      const mutation = await putAssessmentInput(activeReportId, {
        expected_state_seq: input.state_seq,
        threshold: submittedThreshold,
        scores,
      });
      // 无论是否覆盖全部议题，自动保存一律只做本地投影，不触发权威重载：
      // reload() 会用服务端值重建 draft，把用户正在输入的内容替换掉（防抖期内必然发生）。
      // scoring 必须回写 assessmentInput 为刚提交值，否则后续 /state 通道会用旧值覆盖；
      // state_seq 直接取 mutation 响应，保持与 app-context 同一权威序号。
      applyServerReportUpdate(
        (current) => ({ ...current, assessmentInput: mutation.state.assessmentInput }),
        mutation.state_seq,
        mutation.state,
      );
      setInput((current) => (current ? { ...current, state_seq: mutation.state_seq } : current));
      // 本次提交已覆盖全部议题：回填权威 resolved，完成态分类摘要与强调时刻据此派生。
      if (scores.length === input.topics.length) void syncResolved();
    },
  });

  // 自动保存失败态直接派生渲染，不经 effect 回写 note（避免同步 setState 级联渲染）；
  // note 仍优先显示（用户刚触发的操作结果），自动保存失败在其后兜底展示。
  const displayedNote = note ?? (autosave.state === "error"
    ? { kind: "error" as const, text: autosave.error ?? t.scoring.errorAutosaveDraft }
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
      setNote({ kind: "error", text: t.scoring.errorReloadLatest });
    } finally {
      setConflictReloading(false);
    }
  }


  async function onUpload(file: File) {
    if (!input || !activeReportId) return;
    setBusy(true);
    setNote(null);
    setUploadMessage(null);
    try {
      const mutation = await importAssessmentWorkbook(
        activeReportId,
        file,
        input.state_seq,
        threshold,
      );
      await applyMutation(mutation, t.scoring.importSucceeded);
    } catch (error) {
      try {
        await handleMutationError(error);
      } catch (unhandled) {
        setUploadMessage(assessmentUploadMessage(unhandled));
      }
    } finally {
      setBusy(false);
    }
  }

  const completed = input?.topics.filter((topic) => {
    const value = draft[topic.assessmentTopicId];
    return parseMaterialityScore(value?.financial ?? "", input.score_scale) !== null
      && parseMaterialityScore(value?.impact ?? "", input.score_scale) !== null;
  }).length ?? 0;
  const totalTopics = input?.topics.length ?? 0;
  const sortedTopics = [...(input?.resolved?.topics ?? [])]
    .filter((topic) => visibleMats.has(topic.materiality))
    .sort(
      (a, b) => MAT_ORDER.indexOf(a.materiality) - MAT_ORDER.indexOf(b.materiality),
    );
  // 增量预览议题：本地草稿两维齐全即入图，分类走同源镜像规则（权威分类仍是服务端
  // resolved，评分完整后展示切换为权威结果）。固定议题无评分坐标，不参与预览画布。
  const previewTopics = useMemo(() => {
    if (!input) return [] as ScoredAssessmentResult[];
    const topics: ScoredAssessmentResult[] = [];
    for (const topic of input.topics) {
      const value = draft[topic.assessmentTopicId];
      const financial = parseMaterialityScore(value?.financial ?? "", input.score_scale);
      const impact = parseMaterialityScore(value?.impact ?? "", input.score_scale);
      if (financial === null || impact === null) continue;
      topics.push({
        assessmentTopicId: topic.assessmentTopicId,
        determination: "scored",
        materiality: classifyPreviewMateriality(financial, impact, threshold),
        financialScore: financial,
        impactScore: impact,
      });
    }
    return topics;
  }, [input, draft, threshold]);
  const locallyComplete = totalTopics > 0 && completed === totalTopics;

  // 完成时刻：本页访问内权威 resolved 由无到有（最后一分保存成功/导入后）只强调一次；
  // 首次水合即带 resolved（完成态回访）不重复动画。
  const [matrixRevealed, setMatrixRevealed] = useState(false);
  const prevResolvedRef = useRef<{ resolved: ResolvedAssessmentResponse | null } | null>(null);
  useEffect(() => {
    const resolvedNow = input?.resolved ?? null;
    const prev = prevResolvedRef.current;
    prevResolvedRef.current = { resolved: resolvedNow };
    if (prev !== null && prev.resolved === null && resolvedNow) setMatrixRevealed(true);
  }, [input?.resolved]);
  // assessmentTopicId → 官方议题名：矩阵 hover 提示与就地标注使用。
  const topicNames = useMemo(
    () => Object.fromEntries((input?.topics ?? []).map((topic) => [topic.assessmentTopicId, topic.name])),
    [input],
  );
  const isFiltered = visibleMats.size !== MAT_ORDER.length;
  // 图例计数跟随当前预览散点：填写中即所见即所得，完成后与权威 counts 一致（规则同一）。
  const previewCountOf = (materiality: Materiality): number =>
    previewTopics.filter((topic) => topic.materiality === materiality).length;
  const toggleMateriality = useCallback((materiality: Materiality) => {
    setVisibleMats((current) => {
      const next = new Set(current);
      if (next.has(materiality)) {
        next.delete(materiality);
      } else {
        next.add(materiality);
      }
      return next;
    });
  }, []);
  const fixedCount = input?.resolved?.topics.filter(
    (topic) => topic.determination === "fixed",
  ).length ?? 0;

  /**
   * 议题按 dimension 分组，分组顺序取各维度首个议题的 order。
   *
   * 维度标签由服务端按包下发（已是包语言），维度集合也随包变化——港交所两包只有
   * 环境与社会两个维度，没有治理。前端写死一份维度名清单，既会在英文包上完全失配，
   * 也会在维度增减时静默漏排。议题的 order 是服务端给的权威顺序，据它排组即可。
   */
  const dimensionGroups = useMemo(() => {
    const topics = [...(input?.topics ?? [])].sort((a, b) => a.order - b.order);
    const byDimension = new Map<string, typeof topics>();
    for (const topic of topics) {
      const group = byDimension.get(topic.dimension);
      if (group) group.push(topic);
      else byDimension.set(topic.dimension, [topic]);
    }
    return [...byDimension.entries()].map(([dimension, groupTopics]) => ({ dimension, topics: groupTopics }));
  }, [input]);

  if (scope.status === "loading") {
    return (
      <div role="status">
        <LoadingState type="content" text={t.reportConfig.loadingScope} />
      </div>
    );
  }
  if (!scope.collectsMaterialityAssessment) {
    return (
      <p role="status" style={{ color: "var(--muted-foreground)", fontSize: "var(--text-label-size)" }}>
        {t.scoring.notOffered}
      </p>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        {/* 页标题派生自步骤声明（intakeStepLabel），与左栏/页脚导航同源。 */}
        <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
          {stepLabel(t, intakeStepKey("/intake/scoring"))}
        </h1>
        {/* 评分为选填页：页首与页脚同置「下一步」，明示可不填完直接进入下一步（design.md §3.1）。 */}
        <NextStepLink pathname="/intake/scoring" scope={scope} />
      </div>
      <p
        id="coach-scoring-skip"
        style={{ margin: "0 0 20px", fontSize: "var(--text-label-size)", color: "var(--muted-foreground)", lineHeight: 1.7 }}
      >
        {interpolate(t.scoring.intro, { total: totalTopics })}
      </p>

      {!activeReportId ? (
        <InlineAlert variant="error">{t.scoring.noActiveReport}</InlineAlert>
      ) : null}

      {uploadMessage ? (
        <InlineAlert variant="warning" style={{ marginBottom: 16 }}>
          <strong>{uploadMessage.title}</strong>：{uploadMessage.detail}
        </InlineAlert>
      ) : null}

      {autosave.state === "conflict" ? (
        <InlineAlert variant="warning" style={{ marginBottom: 16 }}>
          <span style={{ marginRight: 12 }}>{t.scoring.conflictBanner}</span>
          <button
            type="button"
            disabled={conflictReloading}
            onClick={() => void handleConflictReload()}
            style={{
              border: "none",
              background: "transparent",
              color: "var(--warning)",
              cursor: "pointer",
              fontSize: "var(--text-label-size)",
              textDecoration: "underline",
              padding: 0,
            }}
          >
            {conflictReloading ? t.scoring.conflictReloading : t.shell.loadLatestDiscardLocal}
          </button>
        </InlineAlert>
      ) : displayedNote && NOTE_TO_ALERT_VARIANT[displayedNote.kind] ? (
        <InlineAlert variant={NOTE_TO_ALERT_VARIANT[displayedNote.kind]!} style={{ marginBottom: 16 }}>
          {displayedNote.text}
        </InlineAlert>
      ) : displayedNote ? (
        <p role="status" style={{ color: "var(--muted-foreground)", fontSize: "var(--text-label-size)" }}>
          {displayedNote.text}
        </p>
      ) : null}

      {/* Excel 通道：下载模板 / 导入，与定量信息页同一形态与命名模式（「下载{表名}模板」「导入{表名}」）。
          拖放区自身可见（FileDropZone dashed）——隐形投放区配上「拖入此区域」的文案，
          等于指向一个看不见的东西。 */}
      <div style={{ marginBottom: 20 }}>
        <Button
          variant="secondary"
          size="sm"
          disabled={templateBusy || !input || !activeReportId}
          disabledReason={templateBusy ? t.workbookChannel.generatingTemplate : t.scoring.scoreDataLoading}
          onClick={async () => {
            if (!activeReportId) return;
            setTemplateBusy(true);
            setNote(null);
            try {
              await downloadAssessmentTemplate(activeReportId);
            } catch (error) {
              console.error("Scoring template download failed", error);
              setNote({ kind: "error", text: interpolate(t.workbookChannel.templateDownloadFailed, { table: t.scoring.templateTableLabel }) });
            } finally {
              setTemplateBusy(false);
            }
          }}
        >
          {templateBusy ? t.workbookChannel.preparingTemplate : t.scoring.downloadTemplate}
        </Button>
        <FileDropZone
          dashed
          disabled={busy || !input}
          style={{ marginTop: 10 }}
          onFiles={(files) => {
            const file = files.find((candidate) => candidate.name.toLowerCase().endsWith(".xlsx"));
            if (!file) {
              setNote({ kind: "error", text: interpolate(t.workbookChannel.wrongFormat, { table: t.scoring.templateTableLabel }) });
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
            <input
              type="file"
              accept={ACCEPT}
              disabled={busy || !input}
              style={{ display: "none" }}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) setPendingImportFile(file);
                event.target.value = "";
              }}
            />
          </label>
        </FileDropZone>
      </div>
      <ConfirmDialog
        open={pendingImportFile !== null}
        title={interpolate(t.workbookChannel.confirmTitle, { table: t.scoring.templateTableLabel })}
        description={t.workbookChannel.confirmBody}
        confirmLabel={t.workbookChannel.confirmAction}
        destructive
        onConfirm={() => {
          const file = pendingImportFile;
          setPendingImportFile(null);
          if (file) void onUpload(file);
        }}
        onCancel={() => setPendingImportFile(null)}
      />

      {/* 编制区：单列上下堆叠——矩阵在上、评分表在下，各自独占整幅内容宽
          （见 globals.css gs-scoring-layout）。矩阵是页内一级区块，从进入页面即在场——
          它承载方法论的专业性，不是填完才出现的附录。 */}
      <div className="gs-scoring-layout">
        <div style={{ minWidth: 0 }}>
      {/* 阈值区：与 Excel 通道解耦——阈值是在线判定参数，不属于表格下载/导入动作。 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          flexWrap: "wrap",
          padding: "14px 18px",
          background: "var(--surface)",
          borderRadius: "var(--radius-container)",
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
            {t.scoring.financialThreshold}
          </span>
          <Hint content={materialityHint(report, "financial")} />
          <input
            aria-label={t.scoring.financialThresholdAria}
            style={{ ...numInputBase, width: 56, border: fieldControlBorder(thresholdDraft.financial.trim() !== "") }}
            inputMode="decimal"
            value={thresholdDraft.financial}
            onChange={(event) => {
              const next = normalizeDecimalPaste(event.target.value);
              if (!isNumericDraft(next)) return;
              setThresholdDraft((current) => ({ ...current, financial: next }));
              const finalized = finalizeDecimalDraft(next);
              if (finalized !== "") {
                setThreshold((current) => ({ ...current, financial: Number(finalized) }));
              }
            }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
            {t.scoring.impactThreshold}
          </span>
          <Hint content={materialityHint(report, "impact")} />
          <input
            aria-label={t.scoring.impactThresholdAria}
            style={{ ...numInputBase, width: 56, border: fieldControlBorder(thresholdDraft.impact.trim() !== "") }}
            inputMode="decimal"
            value={thresholdDraft.impact}
            onChange={(event) => {
              const next = normalizeDecimalPaste(event.target.value);
              if (!isNumericDraft(next)) return;
              setThresholdDraft((current) => ({ ...current, impact: next }));
              const finalized = finalizeDecimalDraft(next);
              if (finalized !== "") {
                setThreshold((current) => ({ ...current, impact: Number(finalized) }));
              }
            }}
          />
        </div>
      </div>
      {/* 填写进度 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
          <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}>
            {t.scoring.onlineEntry}
          </span>
          <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
            {interpolate(t.scoring.completedOf, { done: completed, total: totalTopics })}
          </span>
        </div>
        <div style={{ height: 4, background: "var(--surface-sunken)", borderRadius: "var(--radius-pill)", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: `${totalTopics ? Math.round((completed / totalTopics) * 100) : 0}%`,
              background: "var(--accent)",
              borderRadius: "var(--radius-pill)",
              transition: "width 0.3s ease",
            }}
          />
        </div>
        {/* 议题总数由紧邻的进度行表达，此处只保留进度行没有的事实（固定分类与打分口径）。 */}
        {fixedCount || input ? (
          <p style={{ margin: "8px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
            {fixedCount ? interpolate(t.scoring.fixedTopics, { count: fixedCount }) : ""}
            {input ? materialityScoreGuidance(input.score_scale, t) : ""}
          </p>
        ) : null}
        {/* 部分完成的后果若只在点击生成时告知一次，用户可能填到一半离开、以为这步已完成。
            进度行只表达「填了多少」，覆盖门槛要在填写当时就在场。
            未开始与已填满都不显示：前者没有可失去的进度，后者门槛已达成。 */}
        {input && completed > 0 && !locallyComplete ? (
          <p style={{ margin: "6px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
            {t.scoring.coverageWarning}
          </p>
        ) : null}
      </div>
      {/* 议题按 dimension 分组填写：环境/社会/治理三组，首组标题行右侧带列头。 */}
      {dimensionGroups.map((group, groupIndex) => (
        <div key={group.dimension}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: groupIndex === 0 ? "9px 0" : "20px 0 9px",
              borderBottom: "1px solid var(--border-strong)",
            }}
          >
            <span style={{ fontSize: "var(--text-label-size)", fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"], color: "var(--foreground)", marginRight: "auto" }}>
              {group.dimension}{" "}
              <span style={{ fontWeight: 400, color: "var(--muted-foreground)" }}>{interpolate(t.scoring.topicCount, { count: group.topics.length })}</span>
            </span>
            {groupIndex === 0 ? (
              <>
                <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", width: 96, textAlign: "center" }}>
                  {axisLabels.financial}
                </span>
                <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", width: 96, textAlign: "center" }}>
                  {axisLabels.impact}
                </span>
              </>
            ) : null}
          </div>
          {group.topics.map((topic) => {
            const value = draft[topic.assessmentTopicId];
            const financialFilled = (value?.financial ?? "").trim() !== "";
            const impactFilled = (value?.impact ?? "").trim() !== "";
            return (
              <div
                key={topic.assessmentTopicId}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(180px, 1fr) 96px 96px",
                  gap: 10,
                  alignItems: "center",
                  padding: "8px 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "var(--text-label-size)", color: "var(--foreground)" }}>{topic.name}</div>
                <input
                  aria-label={`${topic.name} ${axisLabels.financial}`}
                  style={{ ...numInputBase, width: "100%", boxSizing: "border-box", border: fieldControlBorder(financialFilled) }}
                  inputMode="decimal"
                  value={value?.financial ?? ""}
                  onChange={(event) => {
                    const next = normalizeDecimalPaste(event.target.value);
                    if (!isNumericDraft(next)) return;
                    setDraft((current) => ({
                      ...current,
                      [topic.assessmentTopicId]: {
                        financial: next,
                        impact: current[topic.assessmentTopicId]?.impact ?? "",
                      },
                    }));
                  }}
                />
                <input
                  aria-label={`${topic.name} ${axisLabels.impact}`}
                  style={{ ...numInputBase, width: "100%", boxSizing: "border-box", border: fieldControlBorder(impactFilled) }}
                  inputMode="decimal"
                  value={value?.impact ?? ""}
                  onChange={(event) => {
                    const next = normalizeDecimalPaste(event.target.value);
                    if (!isNumericDraft(next)) return;
                    setDraft((current) => ({
                      ...current,
                      [topic.assessmentTopicId]: {
                        financial: current[topic.assessmentTopicId]?.financial ?? "",
                        impact: next,
                      },
                    }));
                  }}
                />
              </div>
            );
          })}
        </div>
      ))}
        </div>

        <section
          className={`gs-scoring-matrix-panel${matrixRevealed ? " gs-matrix-reveal" : ""}`}
          aria-labelledby="scoring-matrix-title"
        >
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <h2
              id="scoring-matrix-title"
              style={{ margin: 0, fontSize: "var(--text-section-size)", fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"], color: "var(--foreground)" }}
            >
              {t.scoring.matrixHeading}
            </h2>
            <span role="status" style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {locallyComplete
                ? input?.resolved
                  ? t.scoring.matrixDone
                  : t.scoring.matrixResolving
                : interpolate(t.scoring.matrixScored, { done: previewTopics.length, total: totalTopics })}
            </span>
          </div>
          {/* 面板内左图右例：堆叠后面板独占整幅宽度，而 SVG 上限 480px、图例是窄清单，
              并排即可各取所需，不让任何一侧拉伸到失衡。 */}
          <div className="gs-scoring-matrix-body">
          <div style={{ marginTop: 12, maxWidth: 360 }}>
            {/* 交互预览用前端 SVG：图例切换与阈值调整即时反映；导出与工作台块预览仍用后端渲染源。 */}
            <MaterialityMatrix
              axisLabels={axisLabels}
              topics={previewTopics}
              threshold={threshold}
              visibleMaterialities={visibleMats}
              topicNames={topicNames}
              scoreMax={input?.score_scale.maximum}
            />
          </div>
          <div style={{ marginTop: 14 }}>
            {MAT_ORDER.map((materiality) => {
              const shown = visibleMats.has(materiality);
              return (
                <button
                  key={materiality}
                  type="button"
                  aria-pressed={shown}
                  onClick={() => toggleMateriality(materiality)}
                  style={{
                    display: "block",
                    width: "100%",
                    border: "none",
                    background: "transparent",
                    cursor: "pointer",
                    padding: "4px 6px",
                    borderRadius: "var(--radius-control)",
                    opacity: shown ? 1 : 0.45,
                    textAlign: "left",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--text-label-size)" }}>
                    <span
                      aria-hidden
                      style={{
                        width: 10,
                        height: 10,
                        flex: "none",
                        borderRadius: 2,
                        background: QUAD_SWATCH[materiality],
                        border: "1px solid var(--border-strong)",
                      }}
                    />
                    <span style={{ color: MAT_COLOR[materiality], marginRight: "auto" }}>{matLabels[materiality]}</span>
                    <strong>{previewCountOf(materiality)}</strong>
                  </span>
                  <span style={{ display: "block", paddingLeft: 18, fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)" }}>
                    {t.scoring.materialityDesc[materiality]}
                  </span>
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => setVisibleMats(new Set(MAT_ORDER))}
              disabled={!isFiltered}
              style={{
                display: "flex",
                width: "100%",
                padding: "5px 6px",
                border: "none",
                background: "transparent",
                color: "var(--muted-foreground)",
                fontSize: "var(--text-label-size)",
                cursor: isFiltered ? "pointer" : "default",
              }}
            >
              <span style={{ marginRight: "auto" }}>{t.scoring.legendFullResult}</span>
              <span>{previewTopics.length}</span>
            </button>
            <p style={{ margin: "6px 6px 0", fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", lineHeight: 1.6 }}>
              {t.scoring.legendHint}
            </p>
          </div>
          </div>
          {locallyComplete && input?.resolved ? (
            <>
              {/* 完成时刻：分类摘要 + 报告去向，配一次性强调动画（gs-matrix-reveal）。 */}
              <p
                style={{ margin: "14px 0 0", fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--accent)" }}
                role="status"
              >
                {t.scoring.completionPrefix}{completionSummary(input.resolved.counts, matLabels)}
                {fixedCount ? interpolate(t.scoring.legendFixedSuffix, { count: fixedCount }) : ""}。
                {t.scoring.matrixEnterSection}
              </p>
              <div style={{ marginTop: 12 }}>
                {sortedTopics.map((topic) => <ResultRow key={topic.assessmentTopicId} topic={topic} labels={matLabels} />)}
              </div>
            </>
          ) : (
            <p style={{ margin: "14px 0 0", fontSize: "var(--text-overline-size)", color: "var(--muted-foreground)", lineHeight: 1.6 }}>
              {t.scoring.matrixPreviewNote}
            </p>
          )}
        </section>
      </div>

      <CoachMarks
        stepKey="intake-scoring"
        items={[{ anchorId: "coach-scoring-skip", text: t.scoring.coachSkip }]}
      />
    </div>
  );
}
