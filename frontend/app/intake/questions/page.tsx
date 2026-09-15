// ABOUTME: 议题信息直填分步页（questions 路径末步，两版共用）——按议题分组回答引导问题，答案直接写回 Report.intakeItems。
// ABOUTME: 议题分组之后是该路径唯一的图片素材区（只开放 layout_asset）；页尾承载生成区（与资料处理页同源实现），图片识别进行中时置灰。
"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GenerationSection } from "@/components/intake/generation-section";
import { FileIntakeRoleSection } from "@/components/materials/file-intake-role-section";
import { TopicIntakeField } from "@/components/editor/topic-intake-field";
import { StandardsClauseAnnotation } from "@/components/editor/standards-clause-annotation";
import { LoadingState } from "@/components/ui/LoadingState";
import { WorkbookChannel, type WorkbookChannelNote } from "@/components/intake/workbook-channel";
import { downloadTopicQuestionsTemplate, importTopicQuestionsWorkbook } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepKey } from "@/lib/intake-steps";
import { stepLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { findUserVisibleDisclosureClauseAnnotationEntry } from "@/lib/user-visible-disclosure-clause-annotations";
import {
  fetchReportFileIntake,
  fetchReportPreparation,
  selectReportFileIntakeSnapshot,
  type ReportFileIntake,
  type ReportPreparation,
} from "@/lib/material-workspace-api";
import type { IntakeItem, Report, Section } from "@/lib/schema";

interface TopicGroup {
  reportSectionId: string;
  title: string;
  items: IntakeItem[];
}

function answerPresent(answer: IntakeItem["answer"]): boolean {
  if (answer === null || answer === undefined) return false;
  if (Array.isArray(answer)) return answer.length > 0;
  return String(answer).trim().length > 0;
}

/** 按报告章节树顺序收集议题分组；front_* 报告级题（公司简介、治理三题）归基本信息页，不在此重复。
 *
 * `excludedKeys` 是已在页顶「生成前需要确认」平铺的必答题，不在折叠分组里重复出现。
 */
function topicGroups(report: Report, excludedKeys: ReadonlySet<string>): TopicGroup[] {
  const sectionsInOrder: { reportSectionId: string; title: string }[] = [];
  const walk = (sections: Section[]) => {
    for (const section of sections ?? []) {
      if (section.reportSectionId) {
        sectionsInOrder.push({ reportSectionId: section.reportSectionId, title: section.title });
      }
      if (section.children?.length) walk(section.children);
    }
  };
  walk(report.sections ?? []);
  const itemsByScope = new Map<string, IntakeItem[]>();
  for (const item of report.intakeItems ?? []) {
    if (!item.contentScopeId) continue;
    if (excludedKeys.has(item.key)) continue;
    const bucket = itemsByScope.get(item.contentScopeId);
    if (bucket) bucket.push(item);
    else itemsByScope.set(item.contentScopeId, [item]);
  }
  const seen = new Set<string>();
  const groups: TopicGroup[] = [];
  for (const section of sectionsInOrder) {
    if (seen.has(section.reportSectionId)) continue;
    seen.add(section.reportSectionId);
    const items = itemsByScope.get(section.reportSectionId);
    if (items?.length) {
      groups.push({ reportSectionId: section.reportSectionId, title: section.title, items });
    }
  }
  return groups;
}

/** 议题分组折叠行：与「选填补充」同一套可供性 token（▸/▾、sunken 底、hover accent-subtle）。 */
function TopicGroupSection({ group }: { group: TopicGroup }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const { report, config } = useApp();
  // 准则依据按议题级呈现：一道题往往对应多条条款，逐题标注既标不准也解释不了什么；
  // 条款原文取已标注「用户可见」的附录索引批注，不碰生成侧的内部披露要求库。
  const clauseEntry = report
    ? findUserVisibleDisclosureClauseAnnotationEntry(
        config?.user_visible_disclosure_clause_annotations,
        report,
        { reportSectionKey: group.reportSectionId },
      )
    : null;
  const answered = group.items.filter((item) => answerPresent(item.answer)).length;
  return (
    <section>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          width: "100%",
          textAlign: "left",
          border: "1px solid var(--border)",
          borderRadius: 6,
          background: hovered ? "var(--accent-subtle)" : "var(--surface-sunken)",
          padding: "12px 14px",
          cursor: "pointer",
          fontFamily: "var(--font-sans)",
        }}
      >
        <span style={{ fontSize: "var(--text-body-size)", fontWeight: 500, color: "var(--foreground)", marginRight: "auto" }}>
          <span style={{ marginRight: 6 }}>{open ? "▾" : "▸"}</span>
          {group.title}
        </span>
        <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", fontWeight: 400, flexShrink: 0 }}>
          {interpolate(t.questions.answeredOf, { done: answered, total: group.items.length })}
        </span>
      </button>
      {open ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "16px 2px 8px" }}>
          <StandardsClauseAnnotation entry={clauseEntry} />
          {group.items.map((item) => (
            <TopicIntakeField key={item.key} item={item} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function IntakeQuestionsPage() {
  const t = useT();
  const { report, activeReportId, activeReportCapabilities, savedAt } = useApp();
  const scope = activeReportScope(activeReportCapabilities);
  const [intake, setIntake] = useState<ReportFileIntake | null>(null);
  const [preparation, setPreparation] = useState<ReportPreparation | null>(null);
  const [workbookNote, setWorkbookNote] = useState<WorkbookChannelNote | null>(null);
  // 图片素材区任一填空 blur 保存在途时，生成区按处理中置灰，避免生成先于说明落库。
  const [savingCount, setSavingCount] = useState(0);
  const handleSavingChange = useCallback((delta: number) => {
    setSavingCount((current) => Math.max(0, current + delta));
  }, []);
  const refreshSequence = useRef(0);

  // 必答义务的唯一判据来自服务端准备投影；取不到时按「无必答」渲染，
  // 由页尾生成区的阻断项如实兜底，不在本页复制判定。
  useEffect(() => {
    if (!activeReportId) return;
    let active = true;
    void fetchReportPreparation(activeReportId).then(
      (snapshot) => {
        if (active) setPreparation(snapshot);
      },
      () => {
        // 准备投影读取失败不阻断填写；生成区自身会重试并给出权威阻断。
      },
    );
    return () => {
      active = false;
    };
    // 与页尾生成区同源同节奏：随保存重取，否则「生成前需要确认」区会停留在
    // 进页那一刻的判定，用户答完仍看到旧的未完成计数。
  }, [activeReportId, savedAt]);

  // 图片素材区与生成区的资料行共用同一份 file-intake 快照（用户也可能在切换填报方式前上传过语义资料）。
  // 所有快照（首载、轮询、blur 保存、上传、移出/恢复）统一经序号守卫落地，乱序响应不回退界面。
  const applySnapshot = useCallback(
    (incoming: ReportFileIntake) => {
      if (!activeReportId) return;
      setIntake((current) => selectReportFileIntakeSnapshot(current, incoming, activeReportId));
    },
    [activeReportId],
  );
  const refreshIntake = useCallback(async () => {
    if (!activeReportId) return;
    const requestSequence = ++refreshSequence.current;
    try {
      const snapshot = await fetchReportFileIntake(activeReportId);
      if (requestSequence === refreshSequence.current) applySnapshot(snapshot);
    } catch {
      // 资料快照取不到时生成区显示「无上传资料」，不阻断本页问题填写。
    }
  }, [activeReportId, applySnapshot]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshIntake(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshIntake]);

  // 图片识别在说明保存成功时入队、在服务端进行；本页是 questions 路径唯一的素材页，
  // 处理中按资料处理页同一节奏轮询，直到服务端 phase 离开 processing。
  const phase = intake?.phase ?? null;
  const hasUploading = intake?.sources.some((source) => source.admission_status !== "admitted") === true;
  useEffect(() => {
    if (phase !== "processing" && !hasUploading) return;
    const timer = window.setInterval(() => { void refreshIntake(); }, 2_500);
    return () => window.clearInterval(timer);
  }, [hasUploading, phase, refreshIntake]);

  // 生成前必答的议题问题平铺在页顶，不藏进折叠分组：
  // 它们阻断生成，用户必须一眼看见。
  //
  // 「是否存在必答义务」只认服务端准备投影的 required_for_generation：合同里
  // requiredBefore=generation 是**收集侧**声明，报告带着这三道气候题，
  // 但其范围并不把它们判为生成义务。若在前端按合同字段自行判定，就会凭空多出
  // 一个「生成前需要确认」区，而后端根本不会因它阻断——展示与门槛读了两侧事实。
  const topicQuestionsRequired =
    preparation?.areas.find((area) => area.id === "topic_questions")
      ?.required_for_generation ?? false;
  const requiredItems = useMemo(
    () =>
      topicQuestionsRequired
        ? (report?.intakeItems ?? []).filter(
            (item) => item.contentScopeId && item.requiredBefore === "generation",
          )
        : [],
    [report, topicQuestionsRequired],
  );
  const requiredKeys = useMemo(
    () => new Set(requiredItems.map((item) => item.key)),
    [requiredItems],
  );
  const groups = useMemo(
    () => (report ? topicGroups(report, requiredKeys) : []),
    [report, requiredKeys],
  );

  if (!report || scope.status !== "ready") {
    return <LoadingState type="content" />;
  }

  const blockedFileCount = intake
    ? intake.sources.filter(
        (source) => source.binding_status === "active" && source.parse_status === "failed",
      ).length
    : 0;

  return (
    <div style={{ maxWidth: 760, display: "grid", gap: 24 }}>
      <header>
        {/* 页标题派生自步骤声明（intakeStepLabel），与左栏/页脚导航同源。 */}
        <h1 style={{ margin: "20px 0 4px", fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>
          {stepLabel(t, intakeStepKey("/intake/questions"))}
        </h1>
        <p style={{ fontSize: "var(--text-label-size)", lineHeight: 1.7, color: "var(--muted-foreground)", margin: 0 }}>
          {requiredItems.length > 0
            ? t.questions.introRequired
            : t.questions.introOptional}
        </p>
        <p style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", margin: "8px 0 0" }}>
          {t.questions.switchPrefix}
          <Link href="/intake/input-path" style={{ color: "var(--accent)", textDecoration: "none", margin: "0 2px" }}>
            {t.questions.switchLink}
          </Link>
          {t.questions.switchSuffix}
        </p>
      </header>
      {/* Excel 双通道：与评分/定量页同一形态与命名模式（design.md §3.1）。 */}
      <div>
        <WorkbookChannel
          tableLabel={t.questions.tableLabel}
          onDownload={downloadTopicQuestionsTemplate}
          onImport={importTopicQuestionsWorkbook}
          onNote={setWorkbookNote}
          successText={t.questions.importSucceeded}
        />
        {workbookNote ? (
          <div
            role={workbookNote.kind === "error" ? "alert" : "status"}
            style={{
              padding: "10px 0",
              color: workbookNote.kind === "error" ? "var(--destructive)" : "var(--accent)",
              fontSize: "var(--text-label-size)",
            }}
          >
            {workbookNote.text}
          </div>
        ) : null}
      </div>
      {requiredItems.length > 0 ? (
        <section aria-label={t.questions.mustConfirmHeading}>
          <h2 style={{ fontSize: "var(--text-label-size)", fontWeight: 600, color: "var(--foreground)", margin: "0 0 4px" }}>
            {t.questions.mustConfirmHeading}
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {requiredItems.map((item) => (
              <TopicIntakeField key={item.key} item={item} />
            ))}
          </div>
        </section>
      ) : null}
      {groups.length > 0 ? (
        <div style={{ display: "grid", gap: 10 }}>
          {groups.map((group) => (
            <TopicGroupSection key={group.reportSectionId} group={group} />
          ))}
        </div>
      ) : null}
      {/* questions 路径唯一的素材入口：只开放图片素材（design.md §3.5），语义资料入口唯一在 /materials。 */}
      {scope.materialAgentEnabled && intake && activeReportId ? (
        <div style={{ display: "grid", gap: 12 }}>
          <FileIntakeRoleSection
            role="layout_asset"
            intake={intake}
            reportId={activeReportId}
            onSnapshot={applySnapshot}
            onSavingChange={handleSavingChange}
            showAnalysisStatus
          />
          <p style={{ margin: 0, fontSize: "var(--text-supporting-size)", lineHeight: 1.7, color: "var(--muted-foreground)" }}>
            {t.questions.imageCaptionNote}
          </p>
        </div>
      ) : null}
      <GenerationSection
        intake={intake}
        blockedFileCount={blockedFileCount}
        processing={savingCount > 0 || phase === "processing"}
      />
    </div>
  );
}
