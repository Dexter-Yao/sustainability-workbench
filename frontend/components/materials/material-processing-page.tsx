// ABOUTME: 资料处理页（阶段 2/3，design.md §7.3 / README §8.6）——同页三态由服务端 file_intake.phase 决定。
// ABOUTME: 承载两道闸（闸一硬阻断/闸二软须留意）与页尾生成区；生成逻辑迁自 generation-launch-section。
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineAlert } from "@/components/ui/InlineAlert";
import { StatusDot, type StatusDotKind } from "@/components/ui/StatusDot";
import { AppShell } from "@/components/shell/AppShell";
import { GenerationSection } from "@/components/intake/generation-section";
import { useApp } from "@/lib/app-context";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { stepShortLabel } from "@/lib/i18n/intake-step-copy";
import { activeReportScope } from "@/lib/active-report-scope";
import { getIntakeSteps } from "@/lib/intake-steps";
import {
  fetchReportFileIntake,
  removeReportFile,
  updateLayoutAssetCertificateFact,
  selectReportFileIntakeSnapshot,
  type ReportFileIntake,
} from "@/lib/material-workspace-api";
import { fileAnalysisLabel, imageAnalysisLabel } from "./file-analysis-labels";

type SourceWithLabel = ReportFileIntake["sources"][number];

/** 逐份行状态词（态 A）：从 file_analysis/image_analysis.status 派生，前端不自造枚举。
 *
 * failed 是终态但不是成功——把它说成「已处理」会让用户以为资料可用，
 * 而后端生成闸只接受 succeeded/needs_attention，二者判据必须一致。 */
function processingWord(status: string | undefined, t: Dictionary): { word: string; dot: StatusDotKind } {
  if (status === "succeeded" || status === "needs_attention") {
    return { word: t.materialProcessing.statusProcessed, dot: "done" };
  }
  if (status === "failed") return { word: t.materialProcessing.statusFailed, dot: "blocked" };
  if (status === "superseded") return { word: t.materialProcessing.statusSuperseded, dot: "pending" };
  if (status === "running") return { word: t.materialProcessing.statusRunning, dot: "active" };
  return { word: t.materialProcessing.statusQueued, dot: "pending" };
}

function FileNameCell({ source }: { source: SourceWithLabel }) {
  return <strong style={{ fontSize: "var(--text-body-size)", color: "var(--foreground)", marginRight: "auto" }}>{source.source_label ?? source.filename}</strong>;
}

/** 资料适用范围全在本次报告之外时的说明行（design.md §7.3）：不是第四种状态，
 * 文案由服务端按执行范围生成，页面与审阅稿同一句。 */
function ReportScopeNoticeLine({ source }: { source: SourceWithLabel }) {
  const notice = source.file_analysis?.dossier?.report_scope_notice;
  if (!notice) return null;
  return (
    <p style={{ margin: "8px 0 0", fontSize: "var(--text-supporting-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
      {notice}
    </p>
  );
}

/** 该份资料当前所属分析链路的状态：排版素材看图片识别，语义资料看文件分析。
 *
 * 两类分析是不同事实，不能用 ?? 互相顶替——语义资料尚未入队时 file_analysis 为空，
 * 顶替成图片状态会把「从未开始」显示成别的进度。 */
function analysisStatus(source: SourceWithLabel): string | undefined {
  return source.declaration.role === "layout_asset"
    ? source.image_analysis?.status
    : source.file_analysis?.status;
}

/** 态 A：正在处理资料——逐份行 + 进度条 + 可关闭页面说明。 */
function ProcessingState({ intake }: { intake: ReportFileIntake }) {
  const t = useT();
  const activeSources = intake.sources.filter((source) => source.binding_status === "active");
  // 进度以「不再变化」为准：成功、须留意、失败与被取代都不会再推进，
  // 但只有前两者算成功，逐行状态词据此区分，进度条不谎报完成。
  const done = activeSources.filter((source) => {
    const status = analysisStatus(source);
    return (
      status === "succeeded" ||
      status === "needs_attention" ||
      status === "failed" ||
      status === "superseded"
    );
  }).length;
  const total = activeSources.length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 100;

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>{t.materialProcessing.processingHeading}</h1>
        <span style={{ marginLeft: "auto", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
          {interpolate(t.materialProcessing.processedCount, { done, total })}
        </span>
      </div>
      <div style={{ height: 4, borderRadius: "var(--radius-pill)", background: "var(--surface-sunken)" }}>
        <div style={{ height: 4, borderRadius: "var(--radius-pill)", background: "var(--accent)", width: `${percent}%`, transition: "width .2s ease" }} />
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 10 }}>
        {activeSources.map((source) => {
          const { word, dot } = processingWord(analysisStatus(source), t);
          return (
            <li key={source.binding_id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <StatusDot kind={dot} />
              <FileNameCell source={source} />
              <span style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)" }}>{word}</span>
            </li>
          );
        })}
      </ul>
      <div style={{ background: "var(--surface)", borderRadius: "var(--radius-container)", padding: "14px 16px" }}>
        <p style={{ margin: 0, fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--foreground-secondary)" }}>
          {t.materialProcessing.serverSideNote}<strong style={{ color: "var(--foreground)" }}>{t.materialProcessing.serverSideNoteStrong}</strong>{t.materialProcessing.serverSideNoteTail}
        </p>
      </div>
    </div>
  );
}

/** 闸一：解析阻断（硬）——三角 + 「无法解析 · 阻断生成」+ 重新上传/移出报告。 */
function FailedFileCard({
  source,
  reportId,
  onSnapshot,
  onReupload,
}: {
  source: SourceWithLabel;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
  onReupload: () => void;
}) {
  const t = useT();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remove = () => {
    setConfirmRemove(false);
    void removeReportFile(reportId, source.binding_id)
      .then(onSnapshot)
      .catch((cause: unknown) => {
        console.error("Remove report file failed", cause);
        setError(t.materialProcessing.errorRemove);
      });
  };
  return (
    <div style={{ border: "1px solid var(--destructive)", borderRadius: "var(--radius-container)", padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <StatusDot kind="blocked" size={9} />
        <FileNameCell source={source} />
        <Badge variant="blocked">{t.materialProcessing.unparsableBadge}</Badge>
      </div>
      <p style={{ margin: "0 0 12px", fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--foreground-secondary)" }}>
        {source.parse_failure_reason ?? t.materialProcessing.unparsableFallback}
      </p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Button variant="secondary" size="sm" onClick={onReupload}>{t.materialProcessing.reupload}</Button>
        <Button variant="destructive" size="sm" onClick={() => setConfirmRemove(true)}>{t.materialProcessing.removeFromReport}</Button>
      </div>
      {error ? (
        <p role="alert" style={{ margin: "10px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--destructive)" }}>{error}</p>
      ) : null}
      <ConfirmDialog
        open={confirmRemove}
        title={interpolate(t.materialProcessing.removeConfirmTitle, { name: source.source_label ?? source.filename })}
        description={t.materialProcessing.removeConfirmBody}
        confirmLabel={t.materialProcessing.removeFromReport}
        destructive
        onConfirm={remove}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  );
}

/** 正常一行：ok 态或 file_analysis.status==="failed"（Agent 失败，非闸一）的中性警示卡。 */
function OkFileCard({
  source,
  reportId,
  onSnapshot,
}: {
  source: SourceWithLabel;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 排版素材看图片识别，语义资料看文件分析；两类分析是不同事实，不互相顶替。
  const isLayoutAsset = source.declaration.role === "layout_asset";
  const agentFailed = isLayoutAsset
    ? source.image_analysis?.status === "failed"
    : source.parse_status == null && source.file_analysis?.status === "failed";
  const statusLabel = agentFailed
    ? (isLayoutAsset ? imageAnalysisLabel("failed", t) : fileAnalysisLabel("failed", t))
    : isLayoutAsset
      ? imageAnalysisLabel("succeeded", t)
      : t.materialProcessing.statusProcessed;

  const remove = () => {
    setConfirmRemove(false);
    void removeReportFile(reportId, source.binding_id)
      .then(onSnapshot)
      .catch((cause: unknown) => {
        console.error("Remove report file failed", cause);
        setError(t.materialProcessing.errorRemove);
      });
  };

  return (
    <div style={{ border: `1px solid ${agentFailed ? "var(--border-strong)" : "var(--border)"}`, borderRadius: "var(--radius-container)", padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <StatusDot kind={agentFailed ? "pending" : "done"} />
        <FileNameCell source={source} />
        <span style={{ fontSize: "var(--text-supporting-size)", color: agentFailed ? "var(--muted-foreground)" : "var(--muted-foreground)" }}>
          {statusLabel}
        </span>
        <span style={{ position: "relative" }}>
          <button
            type="button"
            aria-label={t.materialProcessing.moreActions}
            aria-expanded={open}
            aria-haspopup="menu"
            onClick={() => setOpen((current) => !current)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
            style={{ border: 0, background: "transparent", color: "var(--muted-foreground)", fontSize: "var(--text-glyph-size)", cursor: "pointer", padding: "0 4px", fontFamily: "inherit" }}
          >
            ⋯
          </button>
          {open ? (
            <span
              role="menu"
              style={{
                position: "absolute",
                top: "calc(100% + 4px)",
                right: 0,
                minWidth: 130,
                background: "var(--background)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-container)",
                boxShadow: "var(--shadow-overlay)",
                padding: 6,
                zIndex: 30,
              }}
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  setConfirmRemove(true);
                }}
                style={{ display: "block", width: "100%", textAlign: "left", border: 0, background: "transparent", padding: "8px 10px", borderRadius: "var(--radius-control)", fontSize: "var(--text-label-size)", color: "var(--destructive)", cursor: "pointer", fontFamily: "inherit" }}
              >
                {t.materialProcessing.removeFromReport}
              </button>
            </span>
          ) : null}
        </span>
      </div>
      <ReportScopeNoticeLine source={source} />
      <CertificateFactPanel source={source} reportId={reportId} onSnapshot={onSnapshot} />
      {error ? (
        <p role="alert" style={{ margin: "10px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--destructive)" }}>{error}</p>
      ) : null}
      <ConfirmDialog
        open={confirmRemove}
        title={interpolate(t.materialProcessing.removeConfirmTitle, { name: source.source_label ?? source.filename })}
        description={t.materialProcessing.removeConfirmBody}
        confirmLabel={t.materialProcessing.removeFromReport}
        destructive
        onConfirm={remove}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  );
}


/** 证书事实核对区：识别出的名称/发证机构/认证范围会进报告，用户须看得见也改得动。
 *
 * 三个字段各自 blur 即保存，与文件说明同型；用户改过后归属转为用户，识别重跑不再覆盖。
 * 未辨认字段以 --warning 提示补全，但不阻断生成——图片识别失败尚且不阻断，
 * 部分字段读不出更不该拦住用户。 */
function CertificateFactPanel({
  source,
  reportId,
  onSnapshot,
}: {
  source: SourceWithLabel;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
}) {
  const t = useT();
  const analysis = source.image_analysis;
  const fact = analysis?.certificate_fact;
  const assetId = analysis?.asset_id;
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  if (!fact || !assetId) return null;

  const fields: { key: "certificate_name" | "issuer" | "covered_scope"; label: string }[] = [
    { key: "certificate_name", label: t.materialProcessing.certificateName },
    { key: "issuer", label: t.materialProcessing.certificateIssuer },
    { key: "covered_scope", label: t.materialProcessing.certificateScope },
  ];
  const unreadable = new Set(fact.unreadable_fields ?? []);

  const save = (key: string, value: string) => {
    const next = {
      certificate_name: fact.certificate_name ?? "",
      issuer: fact.issuer ?? null,
      covered_scope: fact.covered_scope ?? null,
      holder_name: fact.holder_name ?? null,
      [key]: value.trim() || (key === "certificate_name" ? "" : null),
    };
    if (!String(next.certificate_name).trim()) {
      setError(t.materialProcessing.certificateNameRequired);
      return;
    }
    setError(null);
    void updateLayoutAssetCertificateFact(reportId, assetId, next as never)
      .then(onSnapshot)
      .catch((cause: unknown) => {
        console.error("Certificate fact save failed", cause);
        setError(t.materialProcessing.errorSave);
      });
  };

  return (
    <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
      <p style={{ margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
        {t.materialProcessing.certificateIntro}
      </p>
      {fields.map(({ key, label }) => {
        const stored = (fact[key] ?? "") as string;
        const value = draft[key] ?? stored;
        return (
          <label key={key} style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {label}
              {unreadable.has(key) ? (
                <span style={{ color: "var(--warning)" }}>{t.materialProcessing.certificateUnrecognised}</span>
              ) : null}
            </span>
            <input
              value={value}
              onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }))}
              onBlur={() => {
                if (value.trim() !== stored.trim()) save(key, value);
              }}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-control)",
                padding: "6px 8px",
                fontSize: "var(--text-label-size)",
                fontFamily: "inherit",
                color: "var(--foreground)",
                background: "var(--background)",
              }}
            />
          </label>
        );
      })}
      {error ? (
        <p role="alert" style={{ margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--destructive)" }}>{error}</p>
      ) : null}
    </div>
  );
}

/** 闸二：内容须留意（软）——空心环 + 「已处理 · N 项须留意 · 不影响生成」。
 * 措辞不用「待确认」：系统中不存在对应的确认动作，这批事项只是告知用户资料本身的情况
 * （口径打架、时点超出报告期、引用了未提供的文件），用户据此判断是否补充资料或修正口径。
 * attention_items 逐条结构化呈现：编号 + 情况说明一行、「提示」独立一行，
 * 条目间细分隔线；「不影响生成」只在卡片头以 Badge 声明一次，不再逐条重复进正文。
 * 同一批事项同时投影到审阅稿「资料处理说明」前置页，两处措辞必须一致。 */
function AttentionFileCard({ source }: { source: SourceWithLabel }) {
  const t = useT();
  const items = source.file_analysis?.dossier?.attention_items ?? [];
  return (
    <div style={{ border: "1px solid var(--warning)", borderRadius: "var(--radius-container)", padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: items.length ? 10 : 0 }}>
        <StatusDot kind="attention" />
        <FileNameCell source={source} />
        {/* 条目数以实际列表为准：run 终态为 needs_attention 但无 dossier 时不谎报「1 项」。 */}
        <Badge variant="attention">
          {items.length ? interpolate(t.materialProcessing.processedWithNotes, { count: items.length }) : t.materialProcessing.statusProcessed}
        </Badge>
        <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", whiteSpace: "nowrap" }}>
          {t.materialProcessing.notBlocking}
        </span>
      </div>
      {items.length ? (
        <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {items.map((item, index) => (
            <li
              key={`${item.message}-${index}`}
              style={{
                display: "grid",
                gridTemplateColumns: "18px minmax(0, 1fr)",
                gap: 8,
                padding: "8px 0",
                borderTop: index > 0 ? "1px solid var(--border)" : undefined,
              }}
            >
              <span
                aria-hidden
                style={{
                  fontSize: "var(--text-overline-size)",
                  color: "var(--warning)",
                  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
                  lineHeight: 1.9,
                }}
              >
                {index + 1}
              </span>
              <div style={{ display: "grid", gap: 3, minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--foreground-secondary)" }}>
                  {item.message}
                </p>
                <p style={{ margin: 0, fontSize: "var(--text-supporting-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
                  <strong style={{ color: "var(--foreground-secondary)", fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"] }}>
                    {t.materialProcessing.hint}
                  </strong>
                  {"　"}
                  {item.next_action}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      <ReportScopeNoticeLine source={source} />
    </div>
  );
}

/** 态 B：结果与修复——两道闸卡片列表。 */
function ReviewedFileList({
  intake,
  reportId,
  onSnapshot,
  onReupload,
}: {
  intake: ReportFileIntake;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
  onReupload: () => void;
}) {
  const activeSources = intake.sources.filter((source) => source.binding_status === "active");
  return (
    <div style={{ display: "grid", gap: 10 }}>
      {activeSources.map((source) => {
        if (source.parse_status === "failed") {
          return (
            <FailedFileCard
              key={source.binding_id}
              source={source}
              reportId={reportId}
              onSnapshot={onSnapshot}
              onReupload={onReupload}
            />
          );
        }
        if (source.parse_status === "ok_with_attention") {
          return <AttentionFileCard key={source.binding_id} source={source} />;
        }
        return (
          <OkFileCard key={source.binding_id} source={source} reportId={reportId} onSnapshot={onSnapshot} />
        );
      })}
    </div>
  );
}

export function MaterialProcessingPage() {
  const t = useT();
  const { activeReportId, activeReportCapabilities } = useApp();
  const scope = activeReportScope(activeReportCapabilities);
  const router = useRouter();
  const refreshSequence = useRef(0);
  const [intake, setIntake] = useState<ReportFileIntake | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const applySnapshot = useCallback(
    (incoming: ReportFileIntake) => {
      if (!activeReportId) return;
      setIntake((current) => selectReportFileIntakeSnapshot(current, incoming, activeReportId));
    },
    [activeReportId],
  );

  const refresh = useCallback(async () => {
    const requestSequence = ++refreshSequence.current;
    if (!activeReportId || !scope.materialAgentEnabled) {
      setLoading(false);
      return;
    }
    try {
      const next = await fetchReportFileIntake(activeReportId);
      if (requestSequence !== refreshSequence.current) return;
      applySnapshot(next);
      setMessage(null);
    } catch (cause) {
      if (requestSequence !== refreshSequence.current) return;
      console.error("Material processing status load failed", cause);
      setMessage(t.materialProcessing.errorLoadStatus);
    } finally {
      if (requestSequence === refreshSequence.current) setLoading(false);
    }
  }, [activeReportId, applySnapshot, scope.materialAgentEnabled, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const phase = intake?.phase ?? null;
  useEffect(() => {
    if (phase !== "processing") return;
    const timer = window.setInterval(() => { void refresh(); }, 2_500);
    return () => window.clearInterval(timer);
  }, [phase, refresh]);

  const stepScope = {
    collectsMaterialityAssessment: scope.collectsMaterialityAssessment,
    materialAgentEnabled: scope.materialAgentEnabled,
  };
  // 本页只存在于 materials 路径上；步骤位置按该路径解析，不随填报方式加载态漂移。
  const steps = getIntakeSteps(stepScope, "materials");
  const uploadStep = steps.find((step) => step.href === "/materials");

  const activeSources = intake?.sources.filter((source) => source.binding_status === "active") ?? [];
  const blockedSources = activeSources.filter((source) => source.parse_status === "failed");
  const okCount = activeSources.filter((source) => source.parse_status !== "failed").length;

  return (
    <AppShell screenId="material-processing" screenLabel="资料处理" contentMaxWidth={1000}>
      <main style={{ display: "grid", gap: 20, padding: "26px 0" }}>
        {!activeReportId ? <p role="alert">{t.materialProcessing.selectReportFirst}</p> : null}
        {activeReportId && loading ? <p role="status">{t.materialProcessing.loadingStatus}</p> : null}
        {message ? (
          <p role="alert" style={{ margin: 0, fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>{message}</p>
        ) : null}

        {intake && phase === "processing" ? <ProcessingState intake={intake} /> : null}

        {intake && phase === "draft" && activeSources.length > 0 ? (
          <div style={{ display: "grid", gap: 12 }}>
            <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>{t.materialProcessing.notSubmittedHeading}</h1>
            <p style={{ margin: 0, fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--muted-foreground)" }}>
              {t.materialProcessing.notSubmittedBody}
            </p>
            <div>
              <Button variant="secondary" onClick={() => router.push("/materials")}>
                {uploadStep ? interpolate(t.materialProcessing.backTo, { step: stepShortLabel(t, uploadStep.key) }) : t.materialProcessing.backToUpload}
              </Button>
            </div>
          </div>
        ) : null}

        {intake && (phase === "reviewed" || (phase == null && intake.active_file_count === 0)) ? (
          <div style={{ display: "grid", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>{t.materialProcessing.heading}</h1>
              {activeSources.length > 0 ? (
                <span style={{ marginLeft: "auto", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                  {interpolate(t.materialProcessing.usableCount, { total: activeSources.length, ok: okCount })}
                </span>
              ) : null}
            </div>
            {/* 二选一路径的更改入口（design.md §3.1：所选路径的每一页页顶）。
                这一页恰是 materials 路径的默认落点——上传后被推进本页，
                下次「继续编制」也直接落这里（resume-target.ts）：缺了它用户会停在
                没有出口的一页，误以为路径被永久锁死。 */}
            {scope.status === "ready" ? (
              <p style={{ margin: "-8px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                {t.materialProcessing.switchPrefix}
                <Link href="/intake/input-path" style={{ color: "var(--accent)", textDecoration: "none", margin: "0 2px" }}>
                  {t.materialProcessing.switchLink}
                </Link>
                {t.materialProcessing.switchSuffix}
              </p>
            ) : null}
            {/* 解析结果由计数 chip 与逐文件卡片自陈；无法解析的处置指引归下方 InlineAlert 一处。 */}
            {activeSources.length === 0 ? (
              <p style={{ margin: 0, fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
                {t.materialProcessing.noMaterials}
              </p>
            ) : null}

            {blockedSources.length > 0 ? (
              <InlineAlert variant="error">
                <strong style={{ color: "var(--foreground)" }}>{interpolate(t.materialProcessing.blockedStrong, { count: blockedSources.length })}</strong>
                {t.materialProcessing.blockedTail}
              </InlineAlert>
            ) : null}

            {activeSources.length > 0 ? (
              <ReviewedFileList
                intake={intake}
                reportId={activeReportId!}
                onSnapshot={applySnapshot}
                onReupload={() => router.push("/materials")}
              />
            ) : null}

            <GenerationSection intake={intake} blockedFileCount={blockedSources.length} />
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}
