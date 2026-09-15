// ABOUTME: 表单行唯一实现（design.md §4.0.2）：label/required/hint(ⓘ)/inlineHint/control/counter/error
// ABOUTME: 槽位固定；inlineHint 位于标签与控件之间——先读怎么填再动手填，不必填完回头找；
// ABOUTME: hint 与 inlineHint 可并存但须各承载一类信息，复述同一件事时 dev 报错；
// ABOUTME: 未填状态用边框表达，禁止背景色暗示；禁用态整行降透明并强制陈述原因（design.md §4.0.2）。
"use client";

import { createContext, useContext, useId, type CSSProperties, type ReactNode } from "react";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { Hint } from "./Hint";

export type FieldCounter = { count: number; max: number; min?: number };

/** 同组内是否有字段带常驻说明。有则无说明的字段也留出等高空位，使控件落在同一基线上。 */
const FieldGroupReservesGuidance = createContext(false);

/**
 * 并排字段组：组内任一字段有常驻说明时，其余字段保留等高空位以对齐控件。
 *
 * 对齐必须由组决定而非字段自身——字段看不到兄弟节点。整组都没有说明时不留空位，
 * 避免平白多出一条空隙。
 */
export function FieldGroup({
  reserveGuidanceSpace,
  children,
  style,
}: {
  /** 通常传「组内是否存在非空 inlineHint」。 */
  reserveGuidanceSpace: boolean;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <FieldGroupReservesGuidance.Provider value={reserveGuidanceSpace}>
      <div style={style}>{children}</div>
    </FieldGroupReservesGuidance.Provider>
  );
}

/** control 边框：未填加深（--field-empty-border），已填还原 --border。禁止用背景色暗示填写状态。 */
export function fieldControlBorder(filled: boolean): string {
  return `1px solid ${filled ? "var(--border)" : "var(--field-empty-border)"}`;
}

/** 必填星标（design.md §4 表单）：比标签字号略大并加粗，醒目但不浮夸；全应用唯一实现。 */
export const requiredStarStyle: CSSProperties = {
  color: "var(--destructive)",
  fontSize: "var(--text-subsection-size)",
  fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
  lineHeight: 1,
};

export function FieldRow({
  label,
  required = false,
  hint,
  inlineHint,
  counter,
  error,
  disabled = false,
  disabledReason,
  htmlFor,
  labelId,
  meta,
  children,
  style,
}: {
  label: ReactNode;
  required?: boolean;
  /** ⓘ 浮层内容（非必需信息：背景/系统用途/术语）。可与 inlineHint 并存，但不得复述它。 */
  hint?: string | null;
  /** 控件下方常驻一句 hint（必需信息：怎么填/条件依赖/直接后果）。可与 hint 并存。 */
  inlineHint?: string | null;
  counter?: FieldCounter;
  error?: string | null;
  /** 控件不可写入。整行降透明；必须同时给出 disabledReason。 */
  disabled?: boolean;
  /** 禁用原因，渲染在 inlineHint 槽位并转 --warning 色。置灰而不说明原因是主要困惑源。 */
  disabledReason?: string | null;
  htmlFor?: string;
  labelId?: string;
  /** 标签行右侧元信息（如「全部选填」）。 */
  meta?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const t = useT();
  const hintId = useId();
  const reservesGuidanceSpace = useContext(FieldGroupReservesGuidance);
  // design.md §4.0.2：置灰必须说明原因，与 Button 的 disabledReason 同源。
  if (process.env.NODE_ENV !== "production" && disabled && !disabledReason?.trim()) {
    console.error(
      `design.md §4.0.2 违规：字段「${typeof label === "string" ? label : ""}」禁用但未提供 disabledReason。`,
    );
  }

  // design.md §2.2.1：并存允许，复述不允许——两段说的是同一件事时，用户读两遍得不到新信息。
  if (process.env.NODE_ENV !== "production" && hint && inlineHint && hint.trim() === inlineHint.trim()) {
    console.error(
      `design.md §2.2.1 违规：字段「${typeof label === "string" ? label : ""}」的 ⓘ 与 inlineHint 内容相同；两者须各承载一类信息。`,
    );
  }

  // 说明在控件之上：读完「怎么填」再落笔。报错留在控件之下——它针对的是已输入的内容。
  // 组内他人有说明而本字段没有时，渲染等高占位，使同排控件对齐（占位对无障碍不可见）。
  const guidanceStyle: CSSProperties = {
    margin: "0 0 5px",
    fontSize: "var(--text-supporting-size)",
    color: "var(--muted-foreground)",
    lineHeight: 1.6,
  };
  // 禁用原因优先占据 inlineHint 槽位：控件已经不能填了，「怎么填」不再是此刻的信息。
  const guidance = disabled && disabledReason ? (
    <p style={{ ...guidanceStyle, color: "var(--warning)" }}>{disabledReason}</p>
  ) : inlineHint ? (
    <p style={guidanceStyle}>{inlineHint}</p>
  ) : reservesGuidanceSpace ? (
    <p aria-hidden style={{ ...guidanceStyle, visibility: "hidden" }}>
      &nbsp;
    </p>
  ) : null;

  const belowLeft = error ? (
    <span
      role="alert"
      style={{ fontSize: "var(--text-supporting-size)", color: "var(--destructive)", lineHeight: 1.6 }}
    >
      {error}
    </span>
  ) : null;

  const counterUnmet = counter && counter.min !== undefined && counter.count < counter.min;

  return (
    <div style={{ minWidth: 0, ...(disabled ? { opacity: 0.4 } : null), ...style }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
        <label
          id={labelId}
          htmlFor={htmlFor}
          style={{
            fontSize: "var(--text-label-size)",
            fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
            color: "var(--foreground)",
          }}
        >
          {label}
        </label>
        {required ? (
          <span aria-hidden style={requiredStarStyle}>
            *
          </span>
        ) : null}
        {hint ? <Hint content={hint} id={hintId} /> : null}
        {meta ? (
          <span
            style={{
              fontSize: "var(--text-supporting-size)",
              color: "var(--muted-foreground)",
              marginLeft: "auto",
            }}
          >
            {meta}
          </span>
        ) : null}
      </div>
      {guidance}
      {children}
      {belowLeft || counter ? (
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 5 }}>
          <span style={{ marginRight: "auto", minWidth: 0 }}>{belowLeft}</span>
          {counter ? (
            <span
              style={{
                fontSize: "var(--text-supporting-size)",
                color: counterUnmet ? "var(--destructive)" : "var(--muted-foreground)",
                whiteSpace: "nowrap",
              }}
            >
              {counter.count} / {counter.max}
              {counterUnmet ? interpolate(t.reportConfig.counterAtLeast, { min: counter.min ?? 0 }) : ""}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
