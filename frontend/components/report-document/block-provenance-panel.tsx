// ABOUTME: 所选块的溯源面板：生成结果、内容依据、资料/填写/指标依据、生成记录与相对生成稿的差异，全部由稳定 code 经文案表投影。
// ABOUTME: 它是用户安全投影的只读面板，不是「来源与报告助手」栏——没有对话、生成或改写动作。
// ABOUTME(en): Read-only provenance panel for the selected block, rendered from stable codes through the copy map.
// ABOUTME(en): A user-safe projection, not an assistant pane: no chat, generation or rewrite actions.
"use client";

import type { CSSProperties, ReactNode } from "react";

import { inlineText } from "@/lib/block-edits";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import type { BlockProvenanceEntry, ReportBlockProvenanceProjection } from "@/lib/block-provenance-api";
import {
  basisLabel,
  dispositionLabel,
  evidenceLevelLabel,
  guardrailIssueLabel,
  guardrailVerdictLabel,
  omissionLabel,
  outcomeLabel,
  selectorLabel,
  traceUnavailableCopy,
} from "@/lib/block-provenance-copy";
import { textDiff } from "@/lib/text-diff";

const overline: CSSProperties = {
  fontSize: "var(--text-overline-size)",
  color: "var(--muted-foreground)",
  letterSpacing: "0.04em",
  margin: "0 0 6px",
};
const body: CSSProperties = {
  fontSize: "var(--text-label-size)",
  lineHeight: 1.7,
  color: "var(--foreground-secondary)",
  margin: 0,
};
const muted: CSSProperties = { ...body, color: "var(--muted-foreground)" };
const list: CSSProperties = { ...body, paddingLeft: 16, margin: 0 };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ padding: "12px 0", borderTop: "1px solid var(--border)" }}>
      <p style={overline}>{title}</p>
      {children}
    </section>
  );
}

function DiffView({ generated, current }: { generated: string; current: string }) {
  const t = useT();
  const segments = textDiff(generated, current);
  if (segments === null) return <p style={muted}>{t.provenancePanel.longDiff}</p>;
  return (
    <p style={{ ...body, fontFamily: "var(--font-serif)" }}>
      {segments.map((segment, index) => {
        if (segment.kind === "equal") return <span key={index}>{segment.text}</span>;
        if (segment.kind === "insert") {
          return (
            <ins key={index} style={{ textDecoration: "none", color: "var(--field-foreground)", background: "var(--field-background)" }}>
              {segment.text}
            </ins>
          );
        }
        return (
          <del key={index} style={{ color: "var(--muted-foreground)" }}>
            {segment.text}
          </del>
        );
      })}
    </p>
  );
}

export function BlockProvenancePanel({
  entry,
  currentText,
  projection,
  loading,
  error,
  onClose,
  onRestore,
}: {
  entry: BlockProvenanceEntry | null;
  /** Current prose of the selected block, from the local Report (the truth for edits). */
  currentText: string | null;
  projection: ReportBlockProvenanceProjection | null;
  /** 把该块恢复成生成稿；省略即不提供该动作（如只读场景）。 */
  onRestore?: (blockId: string) => void;
  loading: boolean;
  error: string | null;
  onClose?: () => void;
}) {
  const t = useT();
  return (
    <div style={{ fontFamily: "var(--font-sans)", padding: "0 16px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", padding: "14px 0" }}>
        <strong id="block-provenance-title" style={{ fontSize: "var(--text-subsection-size)", color: "var(--foreground)", marginRight: "auto" }}>{t.provenancePanel.heading}</strong>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label={t.provenancePanel.close}
            data-drawer-initial-focus
            style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: "var(--text-glyph-size)", color: "var(--muted-foreground)" }}
          >
            ✕
          </button>
        ) : null}
      </div>
      {error ? <p role="alert" style={{ ...body, color: "var(--destructive)" }}>{error}</p> : null}
      {!entry ? (
        <p style={muted}>{loading ? t.provenancePanel.loading : t.provenancePanel.empty}</p>
      ) : (
        <PanelBody entry={entry} currentText={currentText} projection={projection} onRestore={onRestore} />
      )}
    </div>
  );
}

function PanelBody({
  entry,
  currentText,
  projection,
  onRestore,
}: {
  entry: BlockProvenanceEntry;
  currentText: string | null;
  projection: ReportBlockProvenanceProjection | null;
  onRestore?: (blockId: string) => void;
}) {
  const t = useT();
  const generatedText = entry.generated_content ? inlineText(entry.generated_content) : null;
  const edited = generatedText !== null && currentText !== null && generatedText !== currentText;
  const run = entry.run ?? null;
  return (
    <>
      <Section title={t.provenancePanel.sectionOutcome}>
        <p style={body}>{outcomeLabel(entry.generation_outcome, t)}</p>
        {entry.omission ? <p style={muted}>{omissionLabel(entry.omission, t)}</p> : null}
      </Section>
      <Section title={t.provenancePanel.sectionBasis}>
        <ul style={list}>
          {entry.basis.map((code) => (
            <li key={code}>{basisLabel(code, t)}</li>
          ))}
        </ul>
      </Section>
      {entry.generation_outcome !== "not_generated" ? (
        <>
          <Section title={t.provenancePanel.sectionMaterial}>
            <p style={body}>{dispositionLabel(entry.material_disposition, t)}</p>
            {entry.sources.length ? (
              <ul style={list}>
                {entry.sources.map((source) => (
                  <li key={source.material_name}>
                    {source.material_name}
                    <span style={{ color: "var(--muted-foreground)" }}>{interpolate(t.provenancePanel.adoptedMaterials, { count: source.adopted_material_count })}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {entry.attention_note ? <p style={muted}>{t.provenancePanel.attentionNote}</p> : null}
          </Section>
          <Section title={t.provenancePanel.sectionIntake}>
            {entry.intake_items.length ? (
              <ul style={list}>
                {entry.intake_items.map((item) => (
                  <li key={item.question}>
                    {item.question}
                    <span style={{ color: item.answered ? "var(--success)" : "var(--muted-foreground)" }}>　{item.answered ? t.provenancePanel.answered : t.provenancePanel.unanswered}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={muted}>{t.provenancePanel.noIntake}</p>
            )}
          </Section>
          <Section title={t.provenancePanel.sectionMetric}>
            {entry.metrics.length ? (
              <ul style={list}>
                {entry.metrics.map((metric) => (
                  <li key={metric.metric_name}>
                    {metric.metric_name}：{metric.value}
                    {metric.unit ?? ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={muted}>{t.provenancePanel.noMetric}</p>
            )}
          </Section>
          <Section title={t.provenancePanel.sectionRun}>
            {projection?.trace_availability === "unavailable" ? (
              <p style={muted}>{traceUnavailableCopy(t)}</p>
            ) : run ? (
              <ul style={list}>
                <li>{run.stage_status === "succeeded" ? t.provenancePanel.stageDone : t.provenancePanel.stageNotDone}{interpolate(t.provenancePanel.attemptCount, { count: run.attempt_count })}</li>
                <li>
                  {guardrailVerdictLabel(run.guardrail, t)}
                  {run.guardrail_issue_codes.length ? `（${run.guardrail_issue_codes.map((code) => guardrailIssueLabel(code, t)).join(t.materials.listSeparator)}）` : ""}
                </li>
                {run.evidence_level ? <li>{evidenceLevelLabel(run.evidence_level, t)}</li> : null}
                {run.evidence_selector_kind ? <li>{selectorLabel(run.evidence_selector_kind, t)}</li> : null}
                <li>
                  {interpolate(t.provenancePanel.modelSaw, { facts: run.intake_fact_count ?? 0, metrics: run.metric_evidence_count ?? 0 })}
                </li>
              </ul>
            ) : (
              <p style={muted}>{t.provenancePanel.noModelCall}</p>
            )}
          </Section>
          <Section title={t.provenancePanel.sectionDiff}>
            {generatedText === null ? (
              <p style={muted}>{t.provenancePanel.notParagraph}</p>
            ) : edited && currentText !== null ? (
              <>
                <DiffView generated={generatedText} current={currentText} />
                {/* 生成稿基线来自冻结 revision，随溯源投影发到浏览器，故刷新后仍可恢复——
                    而内存里的撤销日志刷新即失。恢复本身也走一次编辑提交，可被撤销。 */}
                {onRestore ? (
                  <button
                    type="button"
                    onClick={() => onRestore(entry.block_id)}
                    style={{
                      marginTop: 8,
                      border: "1px solid var(--border)",
                      background: "var(--background)",
                      color: "var(--foreground-secondary)",
                      borderRadius: "var(--radius-control)",
                      fontSize: "var(--text-label-size)",
                      padding: "4px 10px",
                      cursor: "pointer",
                    }}
                  >
                    {t.provenancePanel.restoreGenerated}
                  </button>
                ) : null}
              </>
            ) : (
              <p style={muted}>{t.provenancePanel.sameAsGenerated}</p>
            )}
          </Section>
        </>
      ) : (
        <Section title={t.provenancePanel.sectionRun}>
          <p style={muted}>{t.provenancePanel.deterministicBlock}</p>
        </Section>
      )}
    </>
  );
}
