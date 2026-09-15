// ABOUTME: 分步流末步页尾生成区的唯一共享实现（design.md §3.1）：素材清单 + 阻断项 + 显式生成按钮。
// ABOUTME: materials 路径挂在资料处理页尾，questions 路径挂在议题信息页尾；资格与状态只读服务端 preparation 投影。
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { StatusDot } from "@/components/ui/StatusDot";
import { useAccount } from "@/lib/account-context";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import type { Report } from "@/lib/schema";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { entitlementLabel } from "@/lib/entitlement-label";
import {
  fetchReportPreparation,
  type ReportFileIntake,
  type ReportPreparation,
} from "@/lib/material-workspace-api";
import {
  createReportGeneration,
  reportGenerationIntent,
  type ReportGenerationIntent,
} from "@/lib/report-generation-api";
import { fetchGenerationModelOptions } from "@/lib/report-store";
import type { GenerationModelOption } from "@/lib/report-api.generated";

/** 页尾生成区：四行紧凑清单 + 唯一 primary。资料行按传入的 file-intake 快照如实陈述。 */
/**
 * 生成阻断项的用户可见文案。
 *
 * `target_handle` 是稳定标识（`field.<field_id>`），字段名从报告的 fields 取——
 * 它由知识包下发，天然是包语言。后端下发的 `blocker.message` 恒简体，直接呈现
 * 会在英文界面混排。未识别的 handle 回落通用措辞，不透传后端串。
 */
function blockerMessage(
  blocker: { target_handle: string; message: string },
  report: Report,
  t: Dictionary,
): string {
  const fieldId = blocker.target_handle.startsWith("field.")
    ? blocker.target_handle.slice("field.".length)
    : null;
  const label = fieldId ? report.fields?.[fieldId]?.label : null;
  return label
    ? interpolate(t.generation.blockerFieldMissing, { field: label })
    : t.generation.blockerGeneric;
}

export function GenerationSection({
  intake,
  blockedFileCount,
  processing = false,
}: {
  intake: ReportFileIntake | null;
  blockedFileCount: number;
  /** 资料仍在处理（说明保存在途或服务端 phase=processing）：资料行显示处理中、按钮置灰并给出原因。 */
  processing?: boolean;
}) {
  const t = useT();
  const areaTitles = t.generation.areaTitles as Record<string, string | undefined>;
  const { report, activeReportId, activeReportCapabilities, savedAt } = useApp();
  const { snapshot: account } = useAccount();
  const router = useRouter();
  const scope = activeReportScope(activeReportCapabilities);
  const [preparation, setPreparation] = useState<ReportPreparation | null>(null);
  const [generationPending, setGenerationPending] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  // 评分未填完的一次性确认：用户看过提示后再次点击即按未评分继续生成。
  const [assessmentNoticeAcknowledged, setAssessmentNoticeAcknowledged] = useState(false);
  const generationIntentRef = useRef<ReportGenerationIntent | null>(null);
  // 可选生成模型由服务端裁定（只含凭据齐备者）；null 表示沿用服务端默认，
  // 不在客户端复制一份默认值，否则两处默认会各自漂移。
  const [modelOptions, setModelOptions] = useState<GenerationModelOption[]>([]);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchGenerationModelOptions()
      .then((options) => {
        if (cancelled) return;
        setModelOptions([...options.models]);
        setDefaultModelId(options.default_model_id);
      })
      .catch(() => {
        // 清单读取失败不阻断生成：省略 model_id 即由服务端用当前默认模型。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!activeReportId) return;
    try {
      setPreparation(await fetchReportPreparation(activeReportId));
    } catch {
      // 准备状态读取失败不阻断页面;生成按钮保持置灰,由下次轮询恢复。
    }
  }, [activeReportId]);

  // 随保存节奏重取门禁投影：若依赖只有 refresh（即 activeReportId），就只在挂载时
  // 拉一次——用户答完必答题、自动保存成功后，页尾仍写「还有 N 项需要确认」、按钮
  // 仍置灰，必须手动刷新整页才放行。左栏与报告目录都按 savedAt 重取，页尾生成区
  // 必须同节奏，否则同一屏左右两栏对同一事实各执一词。
  useEffect(() => {
    void Promise.resolve().then(refresh);
  }, [refresh, savedAt]);

  const startGeneration = useCallback(async () => {
    if (
      !activeReportId
      || !preparation
      || !scope.canGenerate
      || !preparation.generation_eligible
      || blockedFileCount > 0
      || processing
      || generationPending
    ) {
      return;
    }
    // 评分只有覆盖全部适用议题才会成为报告结论，部分填写在生成时按未评分处理。
    // 草稿照常保存，因此只在真正影响本次结果的时刻——点击生成——如实告知一次。
    if (preparation.assessment_partially_scored && !assessmentNoticeAcknowledged) {
      setAssessmentNoticeAcknowledged(true);
      return;
    }
    const intent = reportGenerationIntent(
      generationIntentRef.current,
      activeReportId,
      preparation.report_state_seq,
      () => crypto.randomUUID(),
      selectedModelId,
    );
    generationIntentRef.current = intent;
    setGenerationPending(true);
    setGenerationError(null);
    try {
      await createReportGeneration(
        intent.reportId,
        intent.reportStateSeq,
        intent.idempotencyKey,
        intent.modelId,
      );
      generationIntentRef.current = null;
      router.push("/reports/generation");
    } catch (cause) {
      console.error("Report generation start failed", cause);
      setGenerationError(t.generation.errorStart);
    } finally {
      setGenerationPending(false);
    }
  }, [
    activeReportId,
    assessmentNoticeAcknowledged,
    blockedFileCount,
    generationPending,
    preparation,
    processing,
    router,
    scope.canGenerate,
    selectedModelId,
    t,
  ]);

  if (!activeReportId || !preparation) return null;

  const materialsBlocked = blockedFileCount > 0;
  // 权益不可用（过期/未生效）是比「必填未完成」更根本的原因，必须先于阻断清单如实陈述——
  // 否则过期用户会看到「生成前还需完成必填信息」的错误指引。
  // capability 尚未到达时 canGenerate 同样为 false，但那是「还不知道」，不是「权益不可用」；
  // 必须先分流成加载态，否则等待期间会误判成权益问题。
  const entitlement = account?.entitlement ?? null;
  const disabledReason = scope.status === "loading"
    ? t.generation.entitlementLoading
    : !scope.canGenerate
    ? entitlement?.expired
      ? interpolate(t.generation.entitlementExpired, { profile: entitlementLabel(entitlement.profile_id, t) })
      : t.generation.entitlementInactive
    : !preparation.generation_eligible
      ? preparation.generation_blockers.length > 0
        // 清单渲染在按钮**之上**（本文件「生成前需要完成 N 项」区块），若文案写
        // 「见下方清单」，用户照着往下找什么也没有。方位词与
        // 实际版面必须一致，否则等于把人指向空处。
        ? interpolate(t.generation.blockedByChecklist, { count: preparation.generation_blockers.length })
        : t.generation.blockedGeneric
      : materialsBlocked
      ? interpolate(t.generation.blockedByFile, { filename: intake?.sources.find((source) => source.parse_status === "failed")?.filename ?? t.generation.unparsableFile })
      : processing
        ? t.generation.materialsProcessingHint
        : generationPending
          ? t.generation.starting
          : undefined;

  return (
    <section aria-label={t.generation.heading} style={{ borderTop: "1px solid var(--border)", paddingTop: 22 }}>
      <h2 style={{ margin: "0 0 4px", fontSize: "var(--text-section-size)", fontWeight: 600, color: "var(--foreground)" }}>{t.generation.heading}</h2>
      <p style={{ margin: "0 0 16px", fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
        {t.generation.intro}
      </p>
      <ul style={{ margin: "0 0 18px", padding: 0, listStyle: "none", display: "grid", gap: 9, maxWidth: 640 }}>
        {preparation.areas
          .filter((area) => area.id !== "materials")
          .map((area) => (
            <li key={area.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "var(--text-label-size)" }}>
              <StatusDot kind={area.status === "ready" ? "done" : area.required_for_generation ? "attention" : "pending"} />
              {/* 区块名与行动文案按服务端投影的稳定 id 取词：后端下发的 title/summary/
                  action_label 恒简体，英文界面直接渲染会混排。未登记的 id 回落后端串——
                  那是新增区块尚未登记的显式信号，不是静默降级。 */}
              <span style={{ color: "var(--foreground-secondary)", width: 150, flexShrink: 0 }}>
                {areaTitles[area.id] ?? area.title}
              </span>
              <span style={{ color: "var(--muted-foreground)", marginRight: "auto" }}>
                {area.status === "ready" ? t.generation.areaSummaryReady : t.generation.areaSummaryNeedsInput}
              </span>
              <Link href={area.href} style={{ fontSize: "var(--text-label-size)", color: "var(--accent)", textDecoration: "none" }}>
                {area.status === "ready" ? t.generation.areaActionReview : t.generation.areaActionFill}
              </Link>
            </li>
          ))}
        <li style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "var(--text-label-size)" }}>
          {materialsBlocked ? (
            <>
              <StatusDot kind="blocked" size={9} />
              <span style={{ color: "var(--foreground-secondary)", width: 150, flexShrink: 0 }}>{t.generation.materialsLabel}</span>
              <span style={{ color: "var(--destructive)", marginRight: "auto" }}>{interpolate(t.generation.materialsBlocked, { count: blockedFileCount })}</span>
              <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>{t.generation.materialsSeeAbove}</span>
            </>
          ) : processing ? (
            <>
              <StatusDot kind="active" />
              <span style={{ color: "var(--foreground-secondary)", width: 150, flexShrink: 0 }}>{t.generation.materialsLabel}</span>
              <span style={{ color: "var(--muted-foreground)", marginRight: "auto" }}>{t.generation.materialsProcessing}</span>
            </>
          ) : (
            <>
              <StatusDot kind="done" />
              <span style={{ color: "var(--foreground-secondary)", width: 150, flexShrink: 0 }}>{t.generation.materialsLabel}</span>
              <span style={{ color: "var(--muted-foreground)", marginRight: "auto" }}>
                {intake && intake.active_file_count > 0 ? interpolate(t.generation.materialsProcessed, { count: intake.active_file_count }) : t.generation.materialsNone}
              </span>
            </>
          )}
        </li>
      </ul>

      {modelOptions.length > 1 ? (
        <div style={{ margin: "0 0 16px", maxWidth: 640, display: "flex", alignItems: "center", gap: 10 }}>
          <label
            htmlFor="generation-model"
            style={{ fontSize: "var(--text-label-size)", color: "var(--foreground-secondary)", flexShrink: 0 }}
          >
            {t.generation.modelLabel}
          </label>
          <select
            id="generation-model"
            aria-label={t.generation.modelAria}
            value={selectedModelId ?? ""}
            onChange={(event) => setSelectedModelId(event.target.value || null)}
            disabled={generationPending}
            style={{
              fontSize: "var(--text-label-size)",
              padding: "5px 8px",
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: "var(--background)",
              color: "var(--foreground)",
            }}
          >
            {/* 空值＝不下发 model_id，由服务端用当前默认；默认项只标注、不在客户端硬编码。 */}
            <option value="">
              {defaultModelId
                ? `${defaultModelId}${t.generation.modelDefaultSuffix}`
                : t.generation.modelLabel}
            </option>
            {modelOptions.map((option) => (
              <option key={option.model_id} value={option.model_id}>
                {option.model_id}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {!preparation.generation_eligible && preparation.generation_blockers.length > 0 ? (
        <div
          role="alert"
          aria-label={t.generation.blockersAria}
          style={{ margin: "0 0 14px", maxWidth: 640 }}
        >
          <p style={{ margin: "0 0 8px", fontSize: "var(--text-label-size)", fontWeight: 600, color: "var(--foreground)" }}>
            {interpolate(t.generation.blockersHeading, { count: preparation.generation_blockers.length })}
          </p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 8 }}>
            {preparation.generation_blockers.map((blocker) => (
              <li
                key={blocker.target_handle}
                style={{ display: "flex", alignItems: "baseline", gap: 10, fontSize: "var(--text-label-size)", lineHeight: 1.6 }}
              >
                <StatusDot kind="attention" style={{ alignSelf: "center" }} />
                <span style={{ color: "var(--foreground-secondary)", marginRight: "auto" }}>{blockerMessage(blocker, report, t)}</span>
                <Link href={blocker.href} style={{ fontSize: "var(--text-label-size)", color: "var(--accent)", textDecoration: "none", flexShrink: 0 }}>
                  {t.generation.goComplete}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {preparation.assessment_partially_scored && assessmentNoticeAcknowledged ? (
        <p style={{ margin: "0 0 14px", fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--warning)" }} role="alert">
          {interpolate(t.generation.scoringIncomplete, {
            scored: preparation.assessment_scored_topic_count ?? 0,
            total: preparation.assessment_applicable_topic_count ?? 0,
          })}{" "}
          <Link href="/intake/scoring" style={{ color: "var(--accent)", marginLeft: 4, marginRight: 4 }}>
            {t.generation.scoringCompleteLink}
          </Link>
          {t.generation.scoringIncompleteSuffix}
        </p>
      ) : null}

      {preparation.report_update_available ? (
        <p style={{ margin: "0 0 14px", fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--warning)" }} role="status">
          {t.generation.staleNotice}
        </p>
      ) : null}

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
        <Button
          variant="primary"
          size="lg"
          disabled={Boolean(disabledReason)}
          disabledReason={disabledReason}
          onClick={() => void startGeneration()}
        >
          {generationPending
            ? t.generation.starting
            : preparation.report_update_available
              ? t.generation.updateReport
              : t.generation.generateReport}
        </Button>
      </div>
      {generationError ? (
        <div style={{ marginTop: 10 }} role="alert">
          <p style={{ margin: 0, fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>{generationError}</p>
          <Button variant="text" onClick={() => void startGeneration()}>{t.generation.retrySameRequest}</Button>
        </div>
      ) : null}
    </section>
  );
}
