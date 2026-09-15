// ABOUTME: 字典类型：由简体基准字典的结构反推，英文字典按此逐 key 补齐。
// ABOUTME(en): Dictionary shape derived from the Simplified Chinese baseline; other locales must match it.
// ABOUTME: 缺 key、拼错 key 在 `npm run build` 的 tsc 阶段即失败——漏译不做运行期回落，
// ABOUTME: 回落会把漏译变成静默降级，恰是演示时最不能出现的形态。
import type { zhHans } from "./zh-Hans";

/** 把 `as const` 的字面量类型放宽成 string，否则其它语言的字典无法满足该类型。 */
type DeepWiden<T> = T extends string ? string : { [K in keyof T]: DeepWiden<T[K]> };

export type Dictionary = DeepWiden<typeof zhHans>;

/**
 * 占位替换。带插值的文案以 `{name}` 声明，调用方给出同名值。
 *
 * 不做本地化数字或日期格式化——那由 `format.ts` 按 locale 处理后再传进来。
 */
export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match,
  );
}
