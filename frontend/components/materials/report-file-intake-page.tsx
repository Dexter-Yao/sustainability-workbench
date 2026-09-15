// ABOUTME: 上传资料页（阶段 1，design.md §3.5 / §7.3）——两个独立上传区「报告资料」「图片素材」，投放即声明角色；不显示任何处理结果。
// ABOUTME: 本页只是 owner：拉取快照、序号守卫、合计上限与页脚导航；上传、填空与列表归 FileIntakeRoleSection。点「下一步」时才触发 confirmMaterialSet。
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { CoachMarks } from "@/components/onboarding/CoachMarks";
import { Button } from "@/components/ui/Button";
import { AppShell } from "@/components/shell/AppShell";
import { useApp } from "@/lib/app-context";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { stepShortLabel } from "@/lib/i18n/intake-step-copy";
import { activeReportScope } from "@/lib/active-report-scope";
import { getIntakeSteps, resolveIntakeStep } from "@/lib/intake-steps";
import {
  confirmMaterialSet,
  fetchReportFileIntake,
  MaterialWorkspaceConflictError,
  selectReportFileIntakeSnapshot,
  type ReportFileIntake,
} from "@/lib/material-workspace-api";
import { FileIntakeRoleSection, sizeLabel } from "./file-intake-role-section";

const COACH_DESCRIPTION_ANCHOR = "coach-materials-description";

export function ReportFileIntakePage() {
  const t = useT();
  const { activeReportId, activeReportCapabilities } = useApp();
  const scope = activeReportScope(activeReportCapabilities);
  const pathname = usePathname();
  const router = useRouter();
  const refreshSequence = useRef(0);
  const [intake, setIntake] = useState<ReportFileIntake | null>(null);
  const [loading, setLoading] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // 任一填空 blur 保存 in-flight 时,导航提交暂不可点,避免确认先于声明落库被 409。
  const [savingCount, setSavingCount] = useState(0);
  const handleSavingChange = useCallback((delta: number) => {
    setSavingCount((current) => Math.max(0, current + delta));
  }, []);
  // 所有服务端快照(轮询、blur 保存、移出/恢复、上传、确认)统一经序号守卫落地,
  // 消除响应乱序时旧快照覆盖新快照的竞态。
  const applySnapshot = useCallback(
    (incoming: ReportFileIntake) => {
      if (!activeReportId) return;
      setIntake((current) =>
        selectReportFileIntakeSnapshot(current, incoming, activeReportId),
      );
    },
    [activeReportId],
  );
  const intakeReady = useMemo(
    () => Boolean(activeReportId && intake && scope.materialAgentEnabled),
    [activeReportId, intake, scope.materialAgentEnabled],
  );

  const refresh = useCallback(async () => {
    const requestSequence = ++refreshSequence.current;
    if (!activeReportId || !scope.materialAgentEnabled) {
      setIntake(null);
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
      console.error("File intake load failed", cause);
      setMessage(t.materialUpload.errorLoad);
    } finally {
      if (requestSequence === refreshSequence.current) setLoading(false);
    }
  }, [activeReportId, applySnapshot, scope.materialAgentEnabled, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  // 本页不展示处理进度；只在有文件处于上传中的极短窗口内刷新一次，确认上传落库。
  const hasUploading = intake?.sources.some((source) => source.admission_status !== "admitted") === true;
  useEffect(() => {
    if (!hasUploading) return;
    const timer = window.setInterval(() => { void refresh(); }, 2_500);
    return () => window.clearInterval(timer);
  }, [hasUploading, refresh]);

  // 本页只存在于 materials 路径上；步骤位置按该路径解析，不随填报方式加载态漂移。
  const steps = useMemo(() => getIntakeSteps(scope, "materials"), [scope]);
  const stepInfo = useMemo(() => resolveIntakeStep(pathname, steps), [pathname, steps]);

  const activeSources = intake?.sources.filter((source) => source.binding_status === "active") ?? [];
  // 两类角色同计：缺说明的图片与缺说明的语义资料同级阻断（design.md §3.4）。
  const missingDescriptionCount = activeSources.filter(
    (source) => !source.declaration.description.trim(),
  ).length;

  /** 前往资料处理页。说明补齐时服务端已自动入队解析，本按钮通常只是导航。
   *
   * 仍保留一次兜底确认：并发改动或自动入队失败会让指纹回到 required，
   * 此时用户点击应当把资料集推进到处理态，而不是停在 draft 形态无从下手。 */
  const advanceToProcessing = useCallback(async () => {
    if (!activeReportId || !intake) return;
    setAdvancing(true);
    setMessage(null);
    try {
      if (intake.material_set_confirmation.status === "required") {
        try {
          const next = await confirmMaterialSet(activeReportId);
          applySnapshot(next);
        } catch (cause) {
          if (cause instanceof MaterialWorkspaceConflictError) {
            // 服务端投影已变化（如另一处并发编辑）：刷新后按最新状态重试一次。
            const refreshed = await fetchReportFileIntake(activeReportId);
            applySnapshot(refreshed);
            if (refreshed.material_set_confirmation.status === "required") {
              await confirmMaterialSet(activeReportId);
            }
          } else {
            throw cause;
          }
        }
      }
      router.push("/materials/processing");
    } catch (cause) {
      console.error("Material set confirm failed", cause);
      setMessage(t.materialUpload.errorConfirm);
    } finally {
      setAdvancing(false);
    }
  }, [activeReportId, applySnapshot, intake, router, t]);

  const savingInFlight = savingCount > 0;
  const disabledReason = missingDescriptionCount > 0
    ? interpolate(t.materialUpload.missingDescription, { count: missingDescriptionCount })
    : savingInFlight
      ? t.materialUpload.savingChanges
      : advancing
        ? t.materialUpload.submitting
        : undefined;

  return (
    <AppShell screenId="materials-workspace" screenLabel="资料入口" contentMaxWidth={1000}>
      <main style={{ display: "grid", gap: 28, padding: "26px 0" }}>
        <header style={{ display: "grid", gap: 4 }}>
          <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>{t.materialUpload.heading}</h1>
          <p style={{ margin: 0, maxWidth: 720, fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
            <strong style={{ color: "var(--foreground-secondary)" }}>{t.materialUpload.confirmBeforeNext}</strong>
          </p>
          {/* 二选一路径的更改入口（design.md §3.1：两条路径页顶低调链接）；两版共用。
              它是 materials 路径用户的自解出口：切回直填即可自行作答议题必答题。 */}
          {scope.status === "ready" ? (
            <p style={{ margin: "4px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
              {t.materialUpload.switchPrefix}
              <Link href="/intake/input-path" style={{ color: "var(--accent)", textDecoration: "none", margin: "0 2px" }}>
                {t.materialUpload.switchLink}
              </Link>
              {t.materialUpload.switchSuffix}
            </p>
          ) : null}
          {/* 合计上限只在页头说明一次；各区白名单在区内自陈（design.md §3.5）。 */}
          {intakeReady && intake ? (
            <p style={{ margin: "4px 0 0", fontSize: "var(--text-supporting-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
              {interpolate(t.materialUpload.policyLine, {
                maxFiles: intake.policy.max_files_per_report,
                maxSize: sizeLabel(intake.policy.max_file_bytes),
                maxPages: intake.policy.max_pdf_pages,
              })}
            </p>
          ) : null}
        </header>

        {!activeReportId ? <p role="alert">{t.materialUpload.selectReportFirst}</p> : null}
        {activeReportId && scope.status === "loading" ? <p role="status">{t.materialUpload.loadingScope}</p> : null}
        {activeReportId && scope.status === "ready" && !scope.materialAgentEnabled ? <p role="alert">{t.materialUpload.agentDisabled}</p> : null}
        {activeReportId && loading ? <p role="status">{t.materialUpload.loadingPolicy}</p> : null}

        {message ? (
          <p role="alert" style={{ margin: 0, fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>
            {message}
          </p>
        ) : null}

        {intakeReady && intake ? (
          <>
            <CoachMarks
              stepKey="materials-upload"
              items={[{ anchorId: COACH_DESCRIPTION_ANCHOR, text: t.materialUpload.coachDescription }]}
            />
            <FileIntakeRoleSection
              role="semantic_material"
              intake={intake}
              reportId={activeReportId!}
              onSnapshot={applySnapshot}
              onSavingChange={handleSavingChange}
              coachAnchorId={COACH_DESCRIPTION_ANCHOR}
            />
            <FileIntakeRoleSection
              role="layout_asset"
              intake={intake}
              reportId={activeReportId!}
              onSnapshot={applySnapshot}
              onSavingChange={handleSavingChange}
            />
          </>
        ) : null}
      </main>

      {intake ? (
        <footer style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, borderTop: "1px solid var(--border)", padding: "20px 0" }}>
          {stepInfo?.previous ? (
            <Button variant="text" onClick={() => router.push(stepInfo.previous!.href)}>
              {interpolate(t.shell.previousStep, { step: stepShortLabel(t, stepInfo.previous.key) })}
            </Button>
          ) : (
            <Button variant="text" onClick={() => router.push("/reports")}>
              {t.materialUpload.backToReports}
            </Button>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            {missingDescriptionCount > 0 ? (
              <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--warning)" }}>
                {interpolate(t.materialUpload.missingDescription, { count: missingDescriptionCount })}
              </span>
            ) : activeSources.length > 0 ? (
              // 说明补齐即自动开始解析，用户不必再点一次「开始处理」；此处如实告知已在进行。
              // 没有任何文件时不显示——「资料已在处理中」对空清单是失实陈述。
              <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
                {t.materialUpload.processingNote}
              </span>
            ) : null}
            <Button
              variant="primary"
              disabled={Boolean(disabledReason)}
              disabledReason={disabledReason}
              onClick={() => void advanceToProcessing()}
            >
              {advancing ? t.materialUpload.submitting : t.materialUpload.nextStep}
            </Button>
          </div>
        </footer>
      ) : null}
    </AppShell>
  );
}
