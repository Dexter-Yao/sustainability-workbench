// ABOUTME: 自动保存态文案的唯一实现（design.md §3.1「保存态渲染在内容区右上」）。
// ABOUTME: 冲突暂停必须先于 saving/savedAt 判定——它是「写不进去」，不是「还没开始写」。
"use client";

import type { Dictionary } from "@/lib/i18n/dictionary";

/**
 * 保存态措辞的单一事实源。
 *
 * 为什么必须先看 `conflictPending`：冲突暂停分支在 `setSaving(true)` **之前**就
 * return（`lib/app-context.tsx` 的自动保存 effect），于是 `saving` 恒 false、
 * `savedAt` 停在上一次成功保存的时刻。只看后两者会持续显示「已自动保存」，
 * 而用户的每一次输入其实都只留在内存里——必答题的作答会因此丢失，
 * 用户随即被生成门禁挡住。
 *
 * 保存态是用户判断「我填的东西在不在」的唯一常驻依据，不得报喜不报忧。
 */
export function saveStateLabel({
  conflictPending,
  saving,
  savedAt,
  copy,
}: {
  conflictPending: boolean;
  saving: boolean;
  savedAt: number | null;
  /** 措辞按界面语言；判定顺序与语言无关，仍由上面三个 typed 事实决定。 */
  copy: Dictionary["shell"];
}): string {
  if (conflictPending) return copy.savePending;
  if (saving) return copy.saving;
  if (!savedAt) return copy.autosaveOn;
  return copy.autosaved;
}
