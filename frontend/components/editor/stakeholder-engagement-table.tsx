// ABOUTME: 利益相关方沟通 Profile 的专用三线表编辑器，稳定对象只读，议题与方式以克制标签选择。
// ABOUTME: 组件只修改 typed Profile；显示行由目录 ID 投影，不写回或解析 GsTable 中文单元格。
"use client";

import { useState, type CSSProperties, type FormEvent, type ReactNode } from "react";

import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { useReport } from "@/lib/report-context";
import type { EngagementMethodKind, StakeholderEngagementProfile, StakeholderType } from "@/lib/schema";
import {
  STAKEHOLDER_CATALOG,
  addCustomStakeholderMethod,
  missingStakeholderTopicIds,
  orderedStakeholderMethodLabels,
  orderedStakeholderTopicLabels,
  removeCustomStakeholderMethod,
  toggleStakeholderMethod,
  toggleStakeholderTopic,
} from "@/lib/stakeholder-engagement";

// 方式类别名随界面语言变化，故按 t 派生；id 是数据键，任何语言下都不变。
function kinds(t: Dictionary): { id: EngagementMethodKind; label: string }[] {
  return [
    { id: "communication_channel", label: t.stakeholderTable.kindCommunicationChannel },
    { id: "participation_mechanism", label: t.stakeholderTable.kindParticipationMechanism },
    { id: "collaboration_activity", label: t.stakeholderTable.kindCollaborationActivity },
  ];
}

const cell: CSSProperties = {
  padding: "9px 10px",
  borderBottom: "1px solid var(--border-strong)",
  verticalAlign: "top",
  lineHeight: 1.55,
};
const header: CSSProperties = {
  ...cell,
  background: "var(--surface)",
  color: "var(--muted-foreground)",
  fontWeight: 600,
  textAlign: "center",
  borderTop: "1.5px solid var(--border-strong)",
  borderBottom: "1.5px solid var(--border-strong)",
};
const chip: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 24,
  margin: "2px 5px 2px 0",
  padding: "1px 7px",
  border: "1px solid var(--border)",
  borderRadius: 6,
  background: "var(--background)",
  color: "var(--foreground-secondary)",
  fontFamily: "var(--font-sans)",
  fontSize: 12,
};

function ToggleOption({ selected, label, onClick }: { selected: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      style={{
        ...chip,
        cursor: "pointer",
        borderColor: selected ? "var(--accent-subtle-border)" : "var(--border)",
        background: selected ? "var(--accent-subtle)" : "var(--background)",
        color: selected ? "var(--accent-hover)" : "var(--foreground-secondary)",
      }}
    >
      {label}
    </button>
  );
}

function EditorPopover({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details style={{ position: "relative", display: "inline-block", marginTop: 4, fontFamily: "var(--font-sans)" }}>
      <summary style={{ cursor: "pointer", color: "var(--accent)", fontSize: 12, listStyle: "none" }}>{label}</summary>
      <div style={{ position: "absolute", zIndex: 30, top: "calc(100% + 5px)", right: 0, width: 340, maxHeight: 360, overflowY: "auto", padding: 12, border: "1px solid var(--border)", borderRadius: 8, background: "var(--background)", boxShadow: "var(--shadow-overlay)" }}>
        {children}
      </div>
    </details>
  );
}

function CustomMethodInput({ kind, onAdd }: { kind: EngagementMethodKind; onAdd: (label: string) => void }) {
  const t = useT();
  const [value, setValue] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const label = value.trim();
    if (!label) return;
    onAdd(label);
    setValue("");
  };
  return (
    <form onSubmit={submit} style={{ display: "flex", gap: 6, marginTop: 6 }}>
      <input
        aria-label={interpolate(t.stakeholderTable.addCustomLabel, {
          kind: kinds(t).find((item) => item.id === kind)?.label ?? t.stakeholderTable.addCustomFallbackKind,
        })}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={t.stakeholderTable.addCustomPlaceholder}
        style={{ minWidth: 0, flex: 1, border: "1px solid var(--border)", borderRadius: 6, padding: "6px 8px", color: "var(--foreground)", background: "var(--background)", fontSize: 12 }}
      />
      <button type="submit" style={{ border: "1px solid var(--border)", borderRadius: 6, background: "var(--background)", color: "var(--accent)", padding: "4px 9px", cursor: "pointer", fontSize: 12 }}>{t.stakeholderTable.addCustomSubmit}</button>
    </form>
  );
}

function TopicEditor({ profile, stakeholderType }: { profile: StakeholderEngagementProfile; stakeholderType: StakeholderType }) {
  const t = useT();
  const { updateStakeholderEngagement } = useReport();
  const entry = profile.entries.find((item) => item.stakeholderType === stakeholderType)!;
  return (
    <>
      <div>{orderedStakeholderTopicLabels(entry.assessmentTopicIds).map((label) => <span key={label} style={chip}>{label}</span>)}</div>
      <EditorPopover label={t.stakeholderTable.editTopics}>
        {(["环境", "社会", "治理"] as const).map((dimension) => {
          const topics = STAKEHOLDER_CATALOG.topics.filter((topic) => topic.dimension === dimension && profile.scopeAssessmentTopicIds.includes(topic.id));
          if (!topics.length) return null;
          return (
            <section key={dimension} style={{ marginBottom: 10 }}>
              <h4 style={{ margin: "0 0 5px", fontSize: 12, color: "var(--foreground)" }}>{dimension}</h4>
              <div>{topics.map((topic) => <ToggleOption key={topic.id} label={topic.label} selected={entry.assessmentTopicIds.includes(topic.id)} onClick={() => updateStakeholderEngagement((current) => toggleStakeholderTopic(current, stakeholderType, topic.id))} />)}</div>
            </section>
          );
        })}
      </EditorPopover>
    </>
  );
}

function MethodEditor({ profile, stakeholderType }: { profile: StakeholderEngagementProfile; stakeholderType: StakeholderType }) {
  const t = useT();
  const { updateStakeholderEngagement } = useReport();
  const entry = profile.entries.find((item) => item.stakeholderType === stakeholderType)!;
  const labels = orderedStakeholderMethodLabels(entry);
  return (
    <>
      <div>{labels.map((label, index) => <span key={`${label}:${index}`} style={chip}>{label}</span>)}</div>
      <EditorPopover label={t.stakeholderTable.editMethods}>
        {kinds(t).map((kind) => {
          const methods = STAKEHOLDER_CATALOG.methods.filter((method) => method.kind === kind.id && method.allowedStakeholderTypes.includes(stakeholderType));
          const custom = entry.customMethods.filter((method) => method.kind === kind.id);
          return (
            <section key={kind.id} style={{ marginBottom: 12 }}>
              <h4 style={{ margin: "0 0 5px", fontSize: 12, color: "var(--foreground)" }}>{kind.label}</h4>
              <div>{methods.map((method) => <ToggleOption key={method.id} label={method.label} selected={entry.methodIds.includes(method.id)} onClick={() => updateStakeholderEngagement((current) => toggleStakeholderMethod(current, stakeholderType, method.id))} />)}</div>
              {custom.length ? <div>{custom.map((method) => <button type="button" key={method.label} onClick={() => updateStakeholderEngagement((current) => removeCustomStakeholderMethod(current, stakeholderType, method))} title={t.stakeholderTable.removeCustomMethod} style={{ ...chip, cursor: "pointer" }}>{method.label} ×</button>)}</div> : null}
              <CustomMethodInput kind={kind.id} onAdd={(label) => updateStakeholderEngagement((current) => addCustomStakeholderMethod(current, stakeholderType, { kind: kind.id, label }))} />
            </section>
          );
        })}
      </EditorPopover>
    </>
  );
}

export function StakeholderEngagementTable() {
  const t = useT();
  const { report, preview } = useReport();
  const profile = report.stakeholderEngagement;
  if (!profile) return <div style={{ color: "var(--muted-foreground)", fontSize: 13 }}>{t.stakeholderTable.scopePending}</div>;
  const missing = missingStakeholderTopicIds(profile);
  return (
    <div contentEditable={false} style={{ fontFamily: "var(--font-serif)", fontSize: 13 }}>
      {!preview && missing.length ? <div role="alert" style={{ marginBottom: 8, paddingLeft: 8, borderLeft: "2px solid var(--warning)", color: "var(--muted-foreground)", fontFamily: "var(--font-sans)", fontSize: 12 }}>{interpolate(t.stakeholderTable.missingTopics, { count: missing.length })}</div> : null}
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed", borderBottom: "1.5px solid var(--border-strong)" }}>
        <colgroup><col style={{ width: "18%" }} /><col style={{ width: "41%" }} /><col style={{ width: "41%" }} /></colgroup>
        <thead><tr><th style={header}>{t.stakeholderTable.columnStakeholder}</th><th style={header}>{t.stakeholderTable.columnTopics}</th><th style={header}>{t.stakeholderTable.columnMethods}</th></tr></thead>
        <tbody>
          {STAKEHOLDER_CATALOG.stakeholders.map((stakeholder) => {
            const entry = profile.entries.find((item) => item.stakeholderType === stakeholder.id)!;
            return (
              <tr key={stakeholder.id}>
                <td style={{ ...cell, color: "var(--muted-foreground)", whiteSpace: "nowrap", textAlign: "center" }}>{stakeholder.label}</td>
                <td style={cell}>{preview ? orderedStakeholderTopicLabels(entry.assessmentTopicIds).join("、") : <TopicEditor profile={profile} stakeholderType={stakeholder.id} />}</td>
                <td style={cell}>{preview ? orderedStakeholderMethodLabels(entry).join("、") : <MethodEditor profile={profile} stakeholderType={stakeholder.id} />}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
