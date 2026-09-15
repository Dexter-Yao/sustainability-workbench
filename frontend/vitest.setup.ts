// ABOUTME: 单元测试环境的界面语言基线：钉死简体中文，让既有中文断言不受语言切换影响。
// ABOUTME(en): Pins the UI locale to Simplified Chinese for unit tests so existing assertions stay valid.
// ABOUTME: 既有断言验证的是组件行为（渲染了什么、点击做了什么），不是文案本身；
// ABOUTME: 漏译由 e2e 的英文界面扫描专门负责，不靠单测顺带发现。
import { LOCALE_STORAGE_KEY } from "./lib/i18n/locale-storage";

const BASELINE = JSON.stringify({ locale: "zh-Hans", source: "explicit" });

// happy-dom 之外的环境（纯 node 测试）没有 localStorage，跳过即可：
// 那些测试不渲染组件，取不到 LocaleProvider。
try {
  globalThis.localStorage?.setItem(LOCALE_STORAGE_KEY, BASELINE);
} catch {
  // 环境不提供存储时按默认语言运行，不阻断测试。
}
