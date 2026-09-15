// ABOUTME: 用户可见准则批注派生测试，确保附录索引条款原文按报告配置选择。
// ABOUTME: 批注链路不读取内部 Prompt 披露要求，披露详略不影响用户可见条款。
import { describe, expect, it } from "vitest";

import { findUserVisibleDisclosureClauseAnnotationEntry } from "./user-visible-disclosure-clause-annotations";
import type { UserVisibleDisclosureClauseAnnotationEntry } from "./api";
import type { Report } from "./schema";

const entries: UserVisibleDisclosureClauseAnnotationEntry[] = [
  {
    reportContentTopicName: "应对气候变化",
    reportSectionKey: "climate_change",
    mainlandStandard: "sse",
    appendixIndexClauseReferences: ["第二十条"],
    clauseOriginalTexts: [{ clauseReference: "第二十条", clauseOriginalText: "上交所原文" }],
  },
  {
    reportContentTopicName: "应对气候变化",
    reportSectionKey: "climate_change",
    mainlandStandard: "szse",
    appendixIndexClauseReferences: ["第二十条"],
    clauseOriginalTexts: [{ clauseReference: "第二十条", clauseOriginalText: "深交所原文" }],
  },
];

function report(mainlandStandard: "sse" | "szse"): Report {
  return {
    title: "t",
    fields: {},
    intakeItems: [],
    sections: [],
    disclosureProfile: {
      mainlandStandard,
      includesHongKongExchangeGuide: false,
      additionalDisclosureReferences: [],
    },
  };
}

describe("user visible disclosure clause annotations", () => {
  it("按大陆准则选择用户可见批注条款", () => {
    const entry = findUserVisibleDisclosureClauseAnnotationEntry(entries, report("szse"), {
      reportSectionKey: "climate_change",
    });
    expect(entry?.clauseOriginalTexts[0].clauseOriginalText).toBe("深交所原文");
  });

  it("批注条款只随大陆准则选择变化（双档移除后无其他档位输入）", () => {
    const sse = findUserVisibleDisclosureClauseAnnotationEntry(entries, report("sse"), {
      reportSectionKey: "climate_change",
    });
    const szse = findUserVisibleDisclosureClauseAnnotationEntry(entries, report("szse"), {
      reportSectionKey: "climate_change",
    });
    expect(sse?.clauseOriginalTexts[0].clauseOriginalText).toBe("上交所原文");
    expect(szse?.clauseOriginalTexts[0].clauseOriginalText).toBe("深交所原文");
    expect(sse).not.toEqual(szse);
  });
});
