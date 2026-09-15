// ABOUTME: 定性信息（二选一）页（第 4 步，报告级二选一）：上传资料由 AI 解析，或直接回答议题引导问题；与「定量信息」步相对应。
// ABOUTME: 选择是报告级事实，落 StoredReportStateV4.meta.primaryInputMode、经服务端 preparation 投影下发；只改分步流编排，不改写任何已填输入。
"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

import { LoadingState } from "@/components/ui/LoadingState";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepKey } from "@/lib/intake-steps";
import { stepLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { getReportState } from "@/lib/report-store";
import {
  fetchMaterialWorkspace,
  updateReportPrimaryInputMode,
  MaterialWorkspaceConflictError,
  type MaterialWorkspaceSnapshot,
  type PrimaryInputMode,
} from "@/lib/material-workspace-api";

const PATH_TARGET: Record<PrimaryInputMode, string> = {
  questions: "/intake/questions",
  materials: "/materials",
};

function PathChoiceButton({
  pressed,
  disabled,
  onClick,
  title,
  description,
}: {
  pressed: boolean;
  disabled: boolean;
  onClick: () => void;
  title: string;
  description: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "grid",
        gap: 6,
        padding: "18px 20px",
        textAlign: "left",
        border: `1px solid ${pressed ? "var(--accent)" : "var(--border)"}`,
        borderRadius: "var(--radius-control)",
        background: pressed ? "var(--accent-subtle)" : "var(--background)",
        boxShadow: pressed ? "inset 0 0 0 1px var(--accent)" : undefined,
        color: "var(--foreground)",
        cursor: disabled ? "wait" : "pointer",
        opacity: disabled ? 0.72 : 1,
        fontFamily: "inherit",
      }}
    >
      <strong style={{ fontSize: "var(--text-body-size)" }}>{title}</strong>
      <span style={{ color: "var(--muted-foreground)", fontSize: "var(--text-label-size)", lineHeight: 1.6 }}>
        {description}
      </span>
    </button>
  );
}

export default function IntakeInputPathPage() {
  const t = useT();
  const router = useRouter();
  const { activeReportId, activeReportCapabilities, applyAuthoritativeReportState } = useApp();
  const scope = activeReportScope(activeReportCapabilities);
  const [snapshot, setSnapshot] = useState<MaterialWorkspaceSnapshot | null>(null);
  const [busyMode, setBusyMode] = useState<PrimaryInputMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 两个版本共用同一次二选一；无资料解析能力时不存在可选择的 materials 路径，
  // 直接进入议题信息直填。
  useEffect(() => {
    if (scope.status !== "ready") return;
    if (!scope.materialAgentEnabled) router.replace("/intake/questions");
  }, [scope, router]);

  useEffect(() => {
    if (!activeReportId) return;
    let active = true;
    void fetchMaterialWorkspace(activeReportId).then(
      (workspace) => {
        if (active) setSnapshot(workspace);
      },
      (cause: unknown) => {
        console.error("Primary input mode load failed", cause);
        if (active) setError(t.inputPath.errorLoad);
      },
    );
    return () => {
      active = false;
    };
  }, [activeReportId, t]);

  if (!activeReportId || scope.status !== "ready" || !scope.materialAgentEnabled) {
    return <LoadingState type="content" />;
  }

  const currentMode = snapshot?.report_primary_input_mode ?? null;

  const choose = async (mode: PrimaryInputMode) => {
    if (!snapshot) return;
    if (mode === currentMode) {
      router.push(PATH_TARGET[mode]);
      return;
    }
    setBusyMode(mode);
    setError(null);
    try {
      await updateReportPrimaryInputMode(activeReportId, mode, snapshot.report_state_seq);
      // 该端点写 meta.primaryInputMode 并使报告 state_seq +1，但它返回的是资料工作区
      // 快照、不含完整 StoredReportState。若本页把返回值整个丢弃，会造成两级损坏：
      //   ① app-context 的 stateSeq 仍是旧值 → 问答页首次自动保存 CAS 失败 409 →
      //      冲突暂停 → 此后每一次勾选只留在内存、永不落库；
      //   ② 即便序号对上，authoritativeBaseline 里仍没有 primaryInputMode，
      //      下一次自动保存会以该基线重建 state 并把刚写入的填报方式覆盖回 null——
      //      于是 preparation 投影认为用户从未二选一，「生成前需要确认」区不渲染、
      //      气候必答题也不阻断，用户既看不到题也过不了门禁。
      // 因此必须回读服务端权威 state 并整体replace 本地基线，只同步序号不够。
      const authoritative = await getReportState(activeReportId);
      await applyAuthoritativeReportState(authoritative.state, authoritative.state_seq);
      router.push(PATH_TARGET[mode]);
    } catch (cause) {
      if (cause instanceof MaterialWorkspaceConflictError) {
        setError(interpolate(t.inputPath.errorConflict, { reason: cause.message }));
        try {
          setSnapshot(await fetchMaterialWorkspace(activeReportId));
        } catch {
          // 刷新失败保留冲突提示，用户重试时再取。
        }
      } else {
        console.error("Primary input mode save failed", cause);
        setError(t.inputPath.errorSave);
      }
      setBusyMode(null);
    }
  };

  return (
    <div style={{ maxWidth: 680 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "20px 0 4px" }}>
        {/* 页标题派生自步骤声明（intakeStepLabel）；「二选一」备注是本步特有的页内装饰。 */}
        <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
          {stepLabel(t, intakeStepKey("/intake/input-path"))}
        </h1>
        {/* 二选一备注紧跟标题：用户常不知道资料上传与回答问题两条路径互斥。 */}
        <span
          style={{
            fontSize: "var(--text-overline-size)",
            fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
            color: "var(--muted-foreground)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-pill)",
            padding: "2px 10px",
            whiteSpace: "nowrap",
          }}
        >
          {t.inputPath.badge}
        </span>
      </div>
      <p style={{ fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--muted-foreground)", margin: "0 0 20px" }}>
        {t.inputPath.intro}
      </p>
      {snapshot === null && !error ? (
        <p role="status" style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)" }}>
          {t.inputPath.loading}
        </p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          <PathChoiceButton
            pressed={currentMode === "materials"}
            disabled={busyMode !== null}
            onClick={() => void choose("materials")}
            title={t.inputPath.materialsTitle}
            description={t.inputPath.materialsDescription}
          />
          <PathChoiceButton
            pressed={currentMode === "questions"}
            disabled={busyMode !== null}
            onClick={() => void choose("questions")}
            title={t.inputPath.questionsTitle}
            description={t.inputPath.questionsDescription}
          />
          {currentMode === "materials" ? (
            <p style={{ margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", lineHeight: 1.6 }}>
              {t.inputPath.keepUploadedNote}
            </p>
          ) : null}
        </div>
      )}
      {error ? (
        <p role="alert" style={{ marginTop: 12, fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
