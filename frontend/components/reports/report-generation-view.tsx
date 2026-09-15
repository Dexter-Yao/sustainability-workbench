// ABOUTME: 报告级真实运行记录的用户友好进度、异常与客户交付物只读视图。
// ABOUTME: 运行记录是定高滚动框并自动跟随最新事件（用户上翻时不打断），页面主体不随事件增多变长。
// ABOUTME: 版面顺序由运行状态派生：成功且有交付物时交付区升到页首，用户无须下滚。
// ABOUTME: 组件直接展示服务端事件文案，不识别内部生成阶段，且永不渲染 internal_audit。
"use client";

import Link from "next/link";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { formatDateTime } from "@/lib/i18n/format";
import { useLocale, useT } from "@/lib/i18n/locale-context";
import { useEffect, useRef, type UIEvent } from "react";

import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Collapse } from "@/components/ui/Collapse";
import { StatusDot, type StatusDotKind } from "@/components/ui/StatusDot";
import {
  customerVisibleArtifacts,
  isReportGenerationActive,
  type ReportGeneration,
  type ReportGenerationArtifact,
} from "@/lib/report-generation-api";
import {
  REPORT_DOCUMENT_PATH,
} from "@/lib/report-navigation-labels";
import { ArtifactIcon } from "./artifact-icon";

/** 运行记录滚动框：定高、自动跟随最新事件；用户主动上翻查看历史时暂停跟随，翻回底部恢复。 */
function EventLog({ events }: { events: ReportGeneration["events"] }) {
  const { locale } = useLocale();
  const listRef = useRef<HTMLOListElement | null>(null);
  const followLatest = useRef(true);

  useEffect(() => {
    const node = listRef.current;
    if (node && followLatest.current) node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const handleScroll = (event: UIEvent<HTMLOListElement>) => {
    const node = event.currentTarget;
    followLatest.current = node.scrollHeight - node.scrollTop - node.clientHeight < 32;
  };

  return (
    <ol
      ref={listRef}
      onScroll={handleScroll}
      aria-live="polite"
      className="mt-2 grid gap-4"
      style={{ maxHeight: 300, overflowY: "auto", paddingRight: 6 }}
    >
      {events.map((event) => (
        <li
          key={event.sequence}
          className="grid gap-1 border-l border-[color:var(--border-strong)] pl-4"
        >
          <p style={{ fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--foreground-secondary)" }}>
            {event.message}
          </p>
          <div
            className="flex flex-wrap gap-x-4 gap-y-1"
            style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}
          >
            {event.current_object && !event.message.includes(event.current_object) ? (
              <span>{event.current_object}</span>
            ) : null}
            <time dateTime={event.occurred_at}>
              {formatDateTime(event.occurred_at, locale)}
            </time>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** 运行状态措辞随界面语言；判定始终依据 typed 枚举。 */
function statusLabel(status: ReportGeneration["status"], t: Dictionary): string {
  const labels: Record<ReportGeneration["status"], string> = {
    queued: t.generationView.statusQueued,
    running: t.generationView.statusRunning,
    succeeded: t.generationView.statusSucceeded,
    failed: t.generationView.statusFailed,
    superseded: t.generationView.statusSuperseded,
  };
  return labels[status];
}

const STATUS_BADGE_VARIANT: Record<ReportGeneration["status"], BadgeVariant> = {
  queued: "neutral",
  running: "generating",
  succeeded: "success",
  failed: "blocked",
  superseded: "attention",
};

export function artifactLabel(artifact: ReportGenerationArtifact, t: Dictionary): string {
  if (artifact.kind === "word") return t.generationView.artifactWord;
  return artifact.media_type.includes("wordprocessingml.document")
    ? t.generationView.artifactReview
    : t.generationView.artifactReviewLegacy;
}

export function reportGenerationProgress(
  generation: ReportGeneration,
): number {
  if (generation.status === "succeeded") return 100;
  return Math.min(
    100,
    Math.max(
      0,
      Math.round(
        (generation.completed_block_count / generation.total_block_count) * 100,
      ),
    ),
  );
}

type StageState = "done" | "active" | "attention" | "pending";

type Stage = { label: string; state: StageState };

/** 从服务端公开事件合同派生四段叙事；不识别任何内部 pipeline 阶段名。 */
export function reportGenerationStages(generation: ReportGeneration, t: Dictionary): Stage[] {
  const types = new Set(generation.events.map((event) => event.event_type));
  const saved = types.has("report_saved");
  const delivered = types.has("artifacts_ready");
  const exportBlocked = types.has("export_blocked");
  const halted =
    generation.status === "failed" || generation.status === "superseded";
  const generating =
    generation.status === "running" || generation.status === "queued";
  return [
    // 服务端门禁保证：生成运行存在时全部资料已处理完成。
    { label: t.generationView.stageMaterials, state: "done" },
    {
      label: t.generationView.stageSections,
      state:
        saved || delivered
          ? "done"
          : generating
            ? "active"
            : halted
              ? "attention"
              : "pending",
    },
    {
      label: t.generationView.stageSave,
      state: saved ? "done" : generating ? "pending" : halted ? "attention" : "pending",
    },
    {
      label: t.generationView.stageDeliver,
      state: delivered ? "done" : exportBlocked ? "attention" : "pending",
    },
  ];
}

const STAGE_DOT_KIND: Record<StageState, StatusDotKind> = {
  done: "done",
  active: "active",
  attention: "attention",
  pending: "pending",
};

function elapsedLabel(generation: ReportGeneration, t: Dictionary): string | null {
  if (!generation.started_at) return null;
  const start = new Date(generation.started_at).getTime();
  const lastEvent = generation.events[generation.events.length - 1];
  const end =
    generation.status === "running" || generation.status === "queued"
      ? Date.now()
      : lastEvent
        ? new Date(lastEvent.occurred_at).getTime()
        : Date.now();
  const totalSeconds = Math.max(0, Math.round((end - start) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0
    ? interpolate(t.generationView.durationMinutes, { minutes, seconds })
    : interpolate(t.generationView.durationSeconds, { seconds });
}

export function ReportGenerationView({
  generation,
  refreshing,
  error,
  downloadingArtifactId,
  updateAvailable = false,
  entryHref = "/intake/info",
  onRefresh,
  onDownload,
}: {
  generation: ReportGeneration;
  refreshing: boolean;
  error: string | null;
  downloadingArtifactId: string | null;
  /** 生成完成后输入再次变化（preparation 投影的 report_update_available）。 */
  updateAvailable?: boolean;
  /** 分步流生成入口（末步页）；准备概览页已废除。 */
  entryHref?: string;
  onRefresh: () => void;
  onDownload: (artifact: ReportGenerationArtifact) => void;
}) {
  const t = useT();
  const progress = reportGenerationProgress(generation);
  const customerArtifacts = customerVisibleArtifacts(generation);
  const actionableEvents = generation.events.filter(
    (event) => event.action_required,
  );
  const stages = reportGenerationStages(generation, t);
  const elapsed = elapsedLabel(generation, t);
  // 成功且确有交付物：交付物是用户此刻唯一关心的结果，升到页首直陈；
  // 成功但零交付物（导出闸阻断）保持原顺序——「需要你处理」必须在交付区之前。
  const deliveryFirst =
    generation.status === "succeeded" && customerArtifacts.length > 0;

const progressSection = (

      <section
        className="border-b border-[color:var(--border)] py-6"
        aria-labelledby="generation-progress-title"
      >
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2
              id="generation-progress-title"
              style={{ margin: 0, fontSize: "var(--text-section-size)", fontWeight: 600, color: "var(--foreground)" }}
            >
              {t.generationView.currentProgress}
            </h2>
            <p className="mt-2" style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)" }}>
              {interpolate(t.generationView.completedBlocks, { done: generation.completed_block_count, total: generation.total_block_count })}
            </p>
          </div>
          <span style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)" }}>
            {progress}%
          </span>
        </div>
        <div
          className="mt-4 h-1.5 overflow-hidden rounded-full bg-[color:var(--surface-sunken)]"
          role="progressbar"
          aria-label={t.generationView.progressAria}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <div
            className="h-full rounded-full bg-[color:var(--accent)] transition-[width]"
            style={{ width: `${progress}%` }}
          />
        </div>
        {refreshing ? (
          <p
            className="mt-3"
            style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}
            role="status"
          >
            {t.generationView.fetchingLatest}
          </p>
        ) : null}
        {error ? (
          <div className="mt-4 flex flex-wrap items-center gap-3" role="alert">
            <p style={{ fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>{error}</p>
            <Button variant="text" size="sm" onClick={onRefresh}>
              {t.generationView.refetch}
            </Button>
          </div>
        ) : null}
      </section>
  );

  const actionableSection = actionableEvents.length ? (
        <section
          className="border-b border-[color:var(--border)] py-6"
          aria-labelledby="generation-actions-title"
        >
          <h2
            id="generation-actions-title"
            style={{ margin: 0, fontSize: "var(--text-section-size)", fontWeight: 600, color: "var(--foreground)" }}
          >
            {t.generationView.needsAttention}
          </h2>
          <ul className="mt-3 grid gap-3">
            {actionableEvents.map((event) => (
              <li
                key={event.sequence}
                className="border-l-2 border-[color:var(--warning)] pl-4"
                style={{ fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--foreground-secondary)" }}
              >
                <p>{event.message}</p>
                {event.current_object ? (
                  <p style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                    {interpolate(t.generationView.relatedObject, { object: event.current_object })}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          <Link
            href={entryHref}
            className="mt-4 inline-block underline underline-offset-4"
            style={{ fontSize: "var(--text-label-size)", color: "var(--warning)" }}
          >
            {t.generationView.backToFill}
          </Link>
        </section>
      
  ) : null;

  const logSection = (

      <section
        className="border-b border-[color:var(--border)] py-6"
        aria-labelledby="generation-events-title"
      >
        <Collapse
          label={t.generationView.runLog}
          consequenceNote={interpolate(t.generationView.eventCount, { count: generation.events.length })}
          defaultOpen={isReportGenerationActive(generation.status)}
        >
          <div className="flex items-center justify-end">
            <Button variant="text" size="sm" onClick={onRefresh}>
              {t.generationView.refresh}
            </Button>
          </div>
          <EventLog events={generation.events} />
        </Collapse>
      </section>
  );

  const deliverySection = generation.status === "succeeded" ? (
            <section
      className={deliveryFirst ? "gs-delivery-enter py-6" : "py-6"}
      aria-labelledby="generation-delivery-title"
    >
          <h2
            id="generation-delivery-title"
            style={{ margin: 0, fontSize: "var(--text-section-size)", fontWeight: 600, color: "var(--foreground)" }}
          >
            {t.generationView.downloadArtifacts}
          </h2>
          {updateAvailable ? (
            <p
              className="mt-2"
              style={{ fontSize: "var(--text-label-size)", lineHeight: 1.75, color: "var(--warning)" }}
              role="status"
            >
              {t.generationView.staleNotice}
              <Link href={entryHref} className="underline underline-offset-4">
                {t.generationView.staleNoticeLink}
              </Link>
              {t.generationView.staleNoticeTail}
            </p>
          ) : null}
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {customerArtifacts.map((artifact) => (
              <li
                key={artifact.artifact_id}
                className="flex items-center gap-4 p-4"
                style={{
                  border: "1px solid var(--accent-subtle-border)",
                  background: "var(--success-surface)",
                  borderRadius: "var(--radius-container)",
                }}
              >
                <ArtifactIcon kind={artifact.kind} />
                <div className="min-w-0" style={{ flex: 1 }}>
                  <p style={{ fontSize: "var(--text-body-size)", fontWeight: 600, color: "var(--foreground)" }}>
                    {artifactLabel(artifact, t)}
                  </p>
                  <p
                    className="mt-1 truncate"
                    style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}
                  >
                    {artifact.filename}
                  </p>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={downloadingArtifactId === artifact.artifact_id}
                  disabledReason={
                    downloadingArtifactId === artifact.artifact_id ? t.generationView.downloading : undefined
                  }
                  onClick={() => onDownload(artifact)}
                >
                  {downloadingArtifactId === artifact.artifact_id
                    ? t.generationView.downloadingLabel
                    : t.generationView.download}
                </Button>
              </li>
            ))}
          </ul>
          {customerArtifacts.length === 0 ? (
            <p className="mt-4" style={{ fontSize: "var(--text-label-size)", color: "var(--warning)" }}>
              {actionableEvents.length
                ? t.generationView.noArtifactsBlocked
                : t.generationView.noArtifactsPending}
            </p>
          ) : null}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Link
              href={entryHref}
              className="no-underline"
              style={{
                fontSize: "var(--text-body-size)",
                fontWeight: 500,
                color: "var(--accent)",
                padding: "7px 4px",
              }}
            >
              {t.generationView.amendEntries}
            </Link>
            <Link
              href={REPORT_DOCUMENT_PATH}
              className="no-underline"
              style={{
                border: "1px solid var(--border-strong)",
                borderRadius: "var(--radius-control)",
                padding: "7px 14px",
                fontSize: "var(--text-body-size)",
                fontWeight: 500,
                color: "var(--foreground-secondary)",
              }}
            >
              {t.shell.readAndReviseReport}
            </Link>
          </div>
        </section>
      
  ) : null;

  // 版面顺序随运行状态派生：成功且有交付物时交付区升到页首（一次进入动画提示），
  // 其余状态维持「进度 → 待处理 → 记录 → 交付」原序。
  return (
    <>
            <header className="border-b border-[color:var(--border)] pb-6">
        <div className="flex flex-wrap items-center gap-3">
          <p style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
            {t.generationView.reportLabel}
          </p>
          <Badge variant={STATUS_BADGE_VARIANT[generation.status]}>
            {statusLabel(generation.status, t)}
          </Badge>
          {elapsed ? (
            <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {interpolate(t.generationView.elapsed, { duration: elapsed })}
            </span>
          ) : null}
        </div>
        <h1 style={{ margin: "8px 0 0", fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
          {t.shell.reportGenerationPage}
        </h1>
        <p
          className="mt-3 max-w-3xl"
          style={{ fontSize: "var(--text-body-size)", lineHeight: 1.7, color: "var(--foreground-secondary)" }}
        >
          {generation.summary}
        </p>
        <ol className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2" aria-label={t.generationView.flowAria}>
          {stages.map((stage) => (
            <li key={stage.label} className="flex items-center gap-2">
              <StatusDot kind={STAGE_DOT_KIND[stage.state]} />
              <span
                style={{
                  fontSize: "var(--text-label-size)",
                  color:
                    stage.state === "pending"
                      ? "var(--muted-foreground)"
                      : "var(--foreground-secondary)",
                }}
              >
                {stage.label}
                {stage.state === "active" ? t.generationView.stageActive : null}
              </span>
            </li>
          ))}
        </ol>
      </header>

      {deliveryFirst ? deliverySection : null}
      {progressSection}
      {actionableSection}
      {logSection}
      {deliveryFirst ? null : deliverySection}
      {generation.status === "failed" || generation.status === "superseded" ? (
        <footer className="py-6">
          <Link
            href={entryHref}
            className="no-underline"
            style={{
              border: "1px solid var(--border-strong)",
              borderRadius: "var(--radius-control)",
              padding: "7px 14px",
              fontSize: "var(--text-body-size)",
              fontWeight: 500,
              color: "var(--foreground-secondary)",
            }}
          >
            {t.generationView.backToFlow}
          </Link>
        </footer>
      ) : null}
    </>
  );
}
