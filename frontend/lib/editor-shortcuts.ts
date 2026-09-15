// ABOUTME: 工作台键盘流的唯一定义源——快捷键目录 + Mac/Windows 修饰键渲染 + 按键匹配，供底部固定条、说明面板与键盘处理共用。
// ABOUTME: 只产出可显示符号与可匹配的动作 id，不承载键盘行为；行为在工作台 DocPane 内消费。design.md §5.5 / dc.html §04。

export type Platform = "mac" | "windows";

/** 快捷键描述用的按键记号：方向键、修饰键与主键。 */
export type KeyToken = "up" | "down" | "mod" | "shift" | "enter" | "esc" | "z" | "s" | "?";

/** 动作 id——选择/编辑流与通用动作。 */
export type ShortcutId = "select" | "edit" | "done" | "undo" | "save" | "help";

export interface ShortcutDef {
  id: ShortcutId;
  group: "select_edit" | "common";
  keys: KeyToken[];
  label: string;
}

/** 按键流唯一目录（design.md §5.5 常用键、dc.html §04 快捷键面板）。 */
export const SHORTCUTS: ShortcutDef[] = [
  { id: "select", group: "select_edit", keys: ["up", "down"], label: "选择上一段 / 下一段" },
  { id: "edit", group: "select_edit", keys: ["enter"], label: "编辑当前选中的段落" },
  { id: "done", group: "select_edit", keys: ["esc"], label: "完成编辑，回到选择" },
  { id: "undo", group: "common", keys: ["mod", "z"], label: "撤销上一步编辑" },
  { id: "save", group: "common", keys: ["mod", "s"], label: "立即保存（平时已自动保存）" },
  { id: "help", group: "common", keys: ["?"], label: "随时打开 / 关闭本说明" },
];

const SYMBOL: Record<KeyToken, Record<Platform, string>> = {
  up: { mac: "↑", windows: "↑" },
  down: { mac: "↓", windows: "↓" },
  mod: { mac: "⌘", windows: "Ctrl" },
  shift: { mac: "⇧", windows: "Shift" },
  enter: { mac: "↵", windows: "Enter" },
  esc: { mac: "esc", windows: "Esc" },
  z: { mac: "Z", windows: "Z" },
  s: { mac: "S", windows: "S" },
  "?": { mac: "?", windows: "?" },
};

/** 把按键记号按平台渲染为可显示串，如 Mac「⌘ ⇧ ↵」/ Windows「Ctrl Shift Enter」。 */
export function renderKeys(keys: KeyToken[], platform: Platform): string {
  return keys.map((token) => SYMBOL[token][platform]).join(" ");
}

export interface ShortcutEvent {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
}

const MODIFIER_TOKENS: KeyToken[] = ["mod", "shift"];

/** 浏览器事件键名 → 主键记号；非主键返回 null。 */
function eventMainToken(key: string): KeyToken | null {
  switch (key) {
    case "ArrowUp":
      return "up";
    case "ArrowDown":
      return "down";
    case "Enter":
      return "enter";
    case "Escape":
      return "esc";
    case "z":
    case "Z":
      return "z";
    case "s":
    case "S":
      return "s";
    case "?":
      return "?";
    default:
      return null;
  }
}

/**
 * 把按键事件匹配为动作 id（无匹配返回 null）。
 * mod 按平台映射（Mac=⌘/metaKey，Windows=Ctrl/ctrlKey）；目录即匹配规则的唯一来源。
 */
export function matchShortcut(event: ShortcutEvent, platform: Platform): ShortcutId | null {
  const token = eventMainToken(event.key);
  if (!token) return null;
  const modActive = platform === "mac" ? event.metaKey : event.ctrlKey;

  for (const sc of SHORTCUTS) {
    const mainKeys = sc.keys.filter((k) => !MODIFIER_TOKENS.includes(k));
    if (!mainKeys.includes(token)) continue;
    const needsMod = sc.keys.includes("mod");
    if (needsMod !== modActive) continue;
    // 「?」常需物理 Shift 才能输入，忽略其 shift 状态；其余动作要求 shift 精确匹配。
    if (token !== "?") {
      const needsShift = sc.keys.includes("shift");
      if (event.shiftKey !== needsShift) continue;
    }
    return sc.id;
  }
  return null;
}

/** 客户端探测操作系统键位（仅在浏览器调用；SSR 由调用方给稳定初值后于挂载时校正）。 */
export function detectPlatform(): Platform {
  if (typeof navigator === "undefined") return "mac";
  const ua = navigator.userAgent ?? "";
  const uaPlatform = (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
  const haystack = `${uaPlatform} ${ua}`.toLowerCase();
  return haystack.includes("mac") ? "mac" : "windows";
}
