// ABOUTME: 保存态措辞的判定顺序回归：冲突暂停必须先于 saving/savedAt。
// ABOUTME: 顺序写反会让界面在「写不进去」时显示「已自动保存」，用户会因此丢答案。
import { describe, expect, it } from "vitest";
import { zhHans } from "@/lib/i18n/zh-Hans";

import { saveStateLabel } from "./save-state-label";

describe("saveStateLabel", () => {
  it("冲突暂停优先于一切：即使有 savedAt 也必须说未保存", () => {
    // 缺陷形态：暂停分支在 setSaving(true) 之前 return，saving 恒 false、
    // savedAt 停在上次成功保存，只看后两者就会持续报「已自动保存」。
    expect(
      saveStateLabel({ conflictPending: true, saving: false, savedAt: 1_700_000_000_000, copy: zhHans.shell }),
    ).toBe("未保存：本页修改尚未写入，请先加载最新内容");
  });

  it("冲突暂停优先于 saving", () => {
    expect(saveStateLabel({ conflictPending: true, saving: true, savedAt: null, copy: zhHans.shell })).toBe(
      "未保存：本页修改尚未写入，请先加载最新内容",
    );
  });

  it("正常态按 saving → savedAt → 未保存过 的顺序陈述", () => {
    expect(saveStateLabel({ conflictPending: false, saving: true, savedAt: null, copy: zhHans.shell })).toBe("保存中…");
    expect(
      saveStateLabel({ conflictPending: false, saving: false, savedAt: 1_700_000_000_000, copy: zhHans.shell }),
    ).toBe("已自动保存");
    expect(saveStateLabel({ conflictPending: false, saving: false, savedAt: null, copy: zhHans.shell })).toBe(
      "自动保存已开启",
    );
  });
});
