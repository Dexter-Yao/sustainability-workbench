// ABOUTME: 界面语言偏好的本机存储边界，并提供首帧内联脚本以避免语言闪烁。
// ABOUTME(en): Device-local UI locale preference plus the head script that resolves it before first paint.
import { isUiLocale, type UiLocale } from "./locale";

/** 与 AppShell 的 nav-collapsed 同一命名惯例。不按 accountId 分片：界面语言是设备偏好。 */
export const LOCALE_STORAGE_KEY = "sustainability-desk:ui-locale";

/** 首帧脚本写在根元素上的属性；Provider 初值从这里读，保证 SSR 首帧与客户端一致。 */
export const LOCALE_DATASET_ATTRIBUTE = "data-ui-locale";

/**
 * 语言来源。
 *
 * `explicit` = 用户在界面上选过：此后任何报告都不再改写它，界面语言是用户属性。
 * `derived` = 尚未选过：跟随当前报告所属知识包的语言。
 */
export type LocaleSource = "explicit" | "derived";

export interface StoredLocale {
  locale: UiLocale;
  source: LocaleSource;
}

export function readStoredLocale(): StoredLocale | null {
  try {
    const raw = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { locale, source } = parsed as { locale?: unknown; source?: unknown };
    if (!isUiLocale(locale)) return null;
    return { locale, source: source === "explicit" ? "explicit" : "derived" };
  } catch {
    // 隐私模式、禁用站点数据或损坏的值：按「未选过」处理，不阻断渲染。
    return null;
  }
}

export function writeStoredLocale(value: StoredLocale): void {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // 存不下只影响下次访问的默认值，不影响本次会话。
  }
}

/**
 * 首帧内联脚本：在 hydration 之前把界面语言写到根元素。
 *
 * `app/layout.tsx` 是 Server Component，读不到 localStorage；不在首帧定下语言，
 * 页面会先以默认语言画一遍再纠正，截图与演示都会拍到这一帧。
 *
 * 内容是编译期常量、无用户输入。解析顺序必须与 `resolveInitialLocale` 一致——
 * 两处分叉会让首帧与 Provider 初值不同，反而制造闪烁。
 */
export const LOCALE_BOOTSTRAP_SCRIPT = `(function(){try{
var raw=localStorage.getItem(${JSON.stringify(LOCALE_STORAGE_KEY)});
var locale=null;
if(raw){var v=JSON.parse(raw);if(v&&(v.locale==="en"||v.locale==="zh-Hans"))locale=v.locale;}
if(!locale)locale=(navigator.language||"").toLowerCase().indexOf("zh")===0?"zh-Hans":"en";
document.documentElement.setAttribute(${JSON.stringify(LOCALE_DATASET_ATTRIBUTE)},locale);
document.documentElement.lang=locale==="en"?"en-HK":"zh-CN";
}catch(e){}})()`;

/**
 * Provider 的初值：优先读首帧脚本写下的属性，其次自行解析。
 *
 * 读属性而非直接读 localStorage，是为了与首帧渲染的那一版严格一致。
 */
export function resolveInitialLocale(): StoredLocale {
  if (typeof document !== "undefined") {
    const stamped = document.documentElement.getAttribute(LOCALE_DATASET_ATTRIBUTE);
    if (isUiLocale(stamped)) {
      return { locale: stamped, source: readStoredLocale()?.source ?? "derived" };
    }
  }
  const stored = readStoredLocale();
  if (stored) return stored;
  const browser = typeof navigator === "undefined" ? "" : navigator.language.toLowerCase();
  return { locale: browser.startsWith("zh") ? "zh-Hans" : "en", source: "derived" };
}
