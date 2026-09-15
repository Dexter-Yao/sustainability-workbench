// ABOUTME: 诊断问题跳转决策回归——每类阻断都必须给出可执行去处（滚动候选或导航），
// ABOUTME: 且配置/章节/就绪类问题分别落到基本信息锚点、报告正文页章节锚点与 actionHref。
import { describe, expect, it } from "vitest";

import type { Issue } from "./api";
import { resolveIssueJump } from "./issue-jump";

function issue(partial: Partial<Issue>): Issue {
  return { level: "block", code: "test", message: "测试", ...partial } as Issue;
}

describe("resolveIssueJump", () => {
  it("字段与块问题优先给出报告正文页内滚动候选", () => {
    const plan = resolveIssueJump(issue({ fieldKey: "year", blockId: "b.ref" }));
    expect(plan.scrollSelectors).toEqual(['[data-field="year"]', '[data-block-id="b.ref"]']);
  });

  it("配置类 path 落到基本信息页锚点", () => {
    for (const path of [
      "appendixPackage.externalAssuranceReport.fileLabel",
      "disclosureProfile.mainlandStandard",
      "fields.company_registered_name.value",
    ]) {
      expect(resolveIssueJump(issue({ path })).fallbackHref).toBe(`/intake/info#config-${path.replaceAll(".", "-")}`);
    }
  });

  it("章节标题类 path 落到报告正文页的章节锚点", () => {
    const plan = resolveIssueJump(issue({ path: "sections.climate_change.displayTitle" }));
    expect(plan.fallbackHref).toBe("/reports/document#section-climate_change");
  });

  it("无 path 的就绪类问题回落到服务端 actionHref", () => {
    const plan = resolveIssueJump(issue({ actionHref: "/intake/scoring" }));
    expect(plan.fallbackHref).toBe("/intake/scoring");
  });

  it("完全无定位信息时无跳转去处", () => {
    expect(resolveIssueJump(issue({}))).toEqual({ scrollSelectors: [], fallbackHref: null });
  });
});
