// ABOUTME: 界面语言的类型与解析边界；界面语言是用户属性，与报告内容语言正交。
// ABOUTME(en): UI locale type and resolution. The UI locale is a user preference, orthogonal to a
// ABOUTME(en): report's content language: one may draft a Traditional Chinese report in an English UI.
import { reportLanguageFor, type ReportLanguage } from "../package-language";

/** 界面语言。繁体界面尚未提供，繁体报告落到简体界面（见 docs/todos.md）。 */
export type UiLocale = "zh-Hans" | "en";

export const UI_LOCALES: readonly UiLocale[] = ["zh-Hans", "en"];

/** `<html lang>` 用的 BCP 47 标签。英文取 en-HK：目标市场是香港，与后端 WORD_LANGUAGE_TAGS 一致。 */
const HTML_LANG: Record<UiLocale, string> = { "zh-Hans": "zh-CN", en: "en-HK" };

/** 日期与数字格式化用的 locale 标签，与 `<html lang>` 同源。 */
export function intlLocale(locale: UiLocale): string {
  return HTML_LANG[locale];
}

export function htmlLang(locale: UiLocale): string {
  return HTML_LANG[locale];
}

export function isUiLocale(value: unknown): value is UiLocale {
  return typeof value === "string" && (UI_LOCALES as readonly string[]).includes(value);
}

/**
 * 报告内容语言 → 界面语言的默认值。
 *
 * 只在用户从未显式选过语言时使用：选过之后界面语言就是用户属性，不再被报告覆盖。
 * 繁体报告落到简体界面——繁简是两种语言而非转写，但简体界面比英文界面更接近繁体用户。
 */
export function defaultUiLocaleFor(language: ReportLanguage): UiLocale {
  return language === "en" ? "en" : "zh-Hans";
}

/** 报告所属知识包 → 界面语言默认值。 */
export function uiLocaleForPackage(knowledgePackageId: string | null | undefined): UiLocale {
  return defaultUiLocaleFor(reportLanguageFor(knowledgePackageId));
}
