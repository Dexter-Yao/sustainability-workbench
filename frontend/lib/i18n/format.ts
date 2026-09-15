// ABOUTME: 按界面语言格式化日期与数字；替换散落的硬编码 "zh-CN"。
// ABOUTME(en): Locale-aware date and number formatting, replacing hardcoded "zh-CN" call sites.
import { intlLocale, type UiLocale } from "./locale";

export function formatDate(value: string | number | Date, locale: UiLocale): string {
  return new Date(value).toLocaleDateString(intlLocale(locale));
}

export function formatDateTime(value: string | number | Date, locale: UiLocale): string {
  return new Date(value).toLocaleString(intlLocale(locale));
}

export function formatNumber(value: number, locale: UiLocale): string {
  return value.toLocaleString(intlLocale(locale));
}
