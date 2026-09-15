// ABOUTME: 前端用户输入的类型约束，按 Report Field.type 派生控件属性与写入校验。
// ABOUTME: 草稿层允许键入中间态；严格层守住 Report 写入与提交边界，两层不得混用。

import type { FieldType } from "./schema";

const STRICT_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const DECIMAL_DRAFT = /^-?\d*\.?\d*$/;
const YEAR = /^\d{4}$/;
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const PHONE = /^[\d+()\-\s]*$/;
// ASCII 商务邮箱语法；与后端 is_valid_contact_email 经 backend/tests/fixtures/email_validation_golden.json 对齐。
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

export interface FieldInputAttributes {
  type: "date" | "email" | "month" | "text" | "url";
  inputMode?: "decimal" | "numeric";
  min?: number | string;
  max?: number | string;
  pattern?: string;
}

/** HTML 控件只反映既有 Field 类型，不在页面层猜测字段业务含义。 */
export function fieldInputAttributes(type: FieldType): FieldInputAttributes {
  switch (type) {
    case "number":
      return { type: "text", inputMode: "decimal", pattern: "-?[0-9]*[.]?[0-9]*" };
    case "percent":
      return { type: "text", inputMode: "decimal", pattern: "[0-9]*[.]?[0-9]*" };
    case "year":
      return { type: "text", inputMode: "numeric", pattern: "[0-9]*" };
    case "month":
      return { type: "month" };
    case "date":
      return { type: "date" };
    case "email":
      return { type: "email" };
    case "url":
      return { type: "url" };
    default:
      return { type: "text" };
  }
}

/** 严格层：只有完整合法值（或清空）允许写入 Report 并同步服务端契约。 */
export function isFieldValueAllowed(type: FieldType, value: string): boolean {
  if (value === "") return true;
  switch (type) {
    case "number":
      return STRICT_NUMBER.test(value);
    case "percent": {
      if (!STRICT_NUMBER.test(value)) return false;
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed >= 0 && parsed <= 100;
    }
    case "year":
      return YEAR.test(value) && Number(value) >= 1900 && Number(value) <= 9999;
    case "month":
      return MONTH.test(value);
    case "date":
      if (!DATE.test(value)) return false;
      {
        const parsed = new Date(`${value}T00:00:00Z`);
        return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
      }
    case "email":
      return EMAIL.test(value);
    default:
      return true;
  }
}

/** 草稿层：允许受控输入的键入中间态（如 "3."、"-"、"202"、"2026-0"），完整性由严格层与服务端契约把关。 */
export function isFieldDraftAllowed(type: FieldType, value: string): boolean {
  switch (type) {
    case "number":
      return DECIMAL_DRAFT.test(value);
    case "percent": {
      if (!DECIMAL_DRAFT.test(value)) return false;
      const parsed = Number(value);
      return Number.isNaN(parsed) || parsed <= 100;
    }
    case "year":
      return /^\d{0,4}$/.test(value);
    case "month":
      return /^[\d-]*$/.test(value) && value.length <= 7;
    case "date":
      return /^[\d-]*$/.test(value) && value.length <= 10;
    default:
      return true;
  }
}

/** ESG 定量指标与评分的键入草稿：允许十进制中间态；单位、说明文字仍被拒绝。 */
export function isDecimalDraft(value: string): boolean {
  return DECIMAL_DRAFT.test(value);
}

/** 评分输入使用同一十进制草稿语法，范围与步长由 assessmentScoreScale 在提交层判断。 */
export function isNumericDraft(value: string): boolean {
  return isDecimalDraft(value);
}

/** 粘贴清洗：全角数字/符号转半角，去千分位逗号与空白；不剥离单位或说明文字。 */
export function normalizeDecimalPaste(value: string): string {
  return value
    .replace(/[０-９]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
    .replace(/．/g, ".")
    .replace(/[－—–]/g, "-")
    .replace(/[,，\s]/g, "");
}

/** 提交收敛：把十进制草稿收敛为严格值；无法收敛（"-"、"." 或非数值）视作未填写。 */
export function finalizeDecimalDraft(value: string): string {
  const trimmed = value.trim();
  if (trimmed === "") return "";
  if (STRICT_NUMBER.test(trimmed)) return trimmed;
  if (!DECIMAL_DRAFT.test(trimmed)) return "";
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return "";
  const canonical = String(parsed);
  return STRICT_NUMBER.test(canonical) ? canonical : "";
}

/** 电话不是数学数值，允许国家区号和分隔符，但不允许字母或自然语言。 */
export function isPhoneInput(value: string): boolean {
  return PHONE.test(value);
}
