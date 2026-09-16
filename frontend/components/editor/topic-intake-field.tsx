// ABOUTME: 分议题内容清单字段控件，直接读写 Report.intakeItems 的 answer 与 supplement。
// ABOUTME: 选择题只允许 options 内取值，补充说明与结构化答案一并保留为生成事实。
"use client";

import { type CSSProperties } from "react";

import { useApp } from "@/lib/app-context";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { updateIntakeItem } from "@/lib/report-section-flow";
import type { IntakeItem } from "@/lib/schema";

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-control)",
  background: "var(--background)",
  color: "var(--foreground)",
  fontSize: 13,
  lineHeight: 1.55,
  padding: "6px 8px",
};

function answerValue(item: IntakeItem): string {
  return typeof item.answer === "string" ? item.answer : "";
}

function answerArray(item: IntakeItem): string[] {
  return Array.isArray(item.answer) ? item.answer : [];
}

export function TopicIntakeField({ item }: { item: IntakeItem }) {
  const t = useT();
  const { setReport } = useApp();
  const onPatch = (patch: Partial<Pick<IntakeItem, "answer" | "supplement">>) => {
    setReport((report) => {
      const current = (report.intakeItems ?? []).find((entry) => entry.key === item.key) ?? item;
      return updateIntakeItem(report, item.key, {
        answer: patch.answer === undefined ? current.answer ?? null : patch.answer,
        supplement: patch.supplement === undefined ? current.supplement ?? null : patch.supplement,
      });
    });
  };

  return (
    <div data-intake-key={item.key} style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
      <label style={{ display: "block", fontSize: 13, fontWeight: 500, lineHeight: 1.55, color: "var(--foreground)", marginBottom: 6 }}>
        {item.prompt}
        {item.collectionPriority === "core" ? <span style={{ color: "var(--muted-foreground)" }}>{t.topicIntake.priority}</span> : null}
      </label>
      {item.hint ? (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", lineHeight: 1.6, margin: "-2px 0 8px" }}>
          {item.hint}
        </div>
      ) : null}
      {item.kind === "single_select" ? (
        <select value={answerValue(item)} onChange={(event) => onPatch({ answer: event.target.value || null })} style={inputStyle}>
          <option value="">{t.topicIntake.notSelected}</option>
          {(item.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : null}
      {item.kind === "multi_select" ? <MultiSelectOptions item={item} onPatch={onPatch} /> : null}
      {item.kind === "text" ? (
        <>
          <textarea
            value={answerValue(item)}
            onChange={(event) => onPatch({ answer: event.target.value })}
            rows={4}
            maxLength={item.maxChars ?? undefined}
            style={{ ...inputStyle, resize: "vertical" }}
          />
          {item.maxChars ? (
            <div style={{ marginTop: 4, fontSize: 12, textAlign: "right", color: "var(--muted-foreground)" }}>
              {answerValue(item).length} / {item.maxChars} {t.topicIntake.charCountSuffix}
            </div>
          ) : null}
        </>
      ) : null}
      {item.kind !== "text" ? (
        <label style={{ display: "block", marginTop: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--foreground)", marginBottom: 5 }}>
            {t.topicIntake.supplementLabel}
          </div>
          <textarea
            value={item.supplement ?? ""}
            onChange={(event) => onPatch({ supplement: event.target.value })}
            rows={2}
            maxLength={item.maxChars ?? undefined}
            style={{ ...inputStyle, resize: "vertical" }}
          />
        </label>
      ) : null}
    </div>
  );
}

function OptionCheckbox({
  option,
  item,
  onPatch,
}: {
  option: string;
  item: IntakeItem;
  onPatch: (patch: Partial<Pick<IntakeItem, "answer" | "supplement">>) => void;
}) {
  const value = answerArray(item);
  const checked = value.includes(option);
  return (
    <label style={{ display: "flex", alignItems: "flex-start", gap: 7, fontSize: 13, lineHeight: 1.45 }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onPatch({ answer: checked ? value.filter((entry) => entry !== option) : [...value, option] })}
        style={{ marginTop: 2 }}
      />
      <span>{option}</span>
    </label>
  );
}

// optionGroups 存在时按组呈现:组内最少选择数是合同约束(input_obligations 按组判定完成),必须让用户看得见。
function MultiSelectOptions({
  item,
  onPatch,
}: {
  item: IntakeItem;
  onPatch: (patch: Partial<Pick<IntakeItem, "answer" | "supplement">>) => void;
}) {
  const t = useT();
  const groups = item.optionGroups ?? [];
  if (groups.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {(item.options ?? []).map((option) => (
          <OptionCheckbox key={option} option={option} item={item} onPatch={onPatch} />
        ))}
      </div>
    );
  }
  const grouped = new Set(groups.flatMap((group) => group.options ?? []));
  const ungrouped = (item.options ?? []).filter((option) => !grouped.has(option));
  const selected = new Set(answerArray(item));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {groups.map((group) => {
        const min = group.minSelections ?? 0;
        const met = (group.options ?? []).filter((option) => selected.has(option)).length >= min;
        return (
          <div key={group.key} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--foreground)" }}>
              {group.label}
              {min > 0 ? (
                <span style={{ marginLeft: 6, fontWeight: 400, color: met ? "var(--muted-foreground)" : "var(--warning)" }}>
                  {interpolate(t.topicIntake.minSelections, { count: min })}
                </span>
              ) : null}
            </div>
            {(group.options ?? []).map((option) => (
              <OptionCheckbox key={option} option={option} item={item} onPatch={onPatch} />
            ))}
          </div>
        );
      })}
      {ungrouped.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {ungrouped.map((option) => (
            <OptionCheckbox key={option} option={option} item={item} onPatch={onPatch} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
