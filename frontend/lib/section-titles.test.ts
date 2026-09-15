// ABOUTME: 动态标题前端合同测试，覆盖显示标题解析和正文变更后的显式重新确认。
// ABOUTME: 指纹只由标题任务输入派生，不依赖编辑器状态或持久化实现。
import { describe, expect, it } from "vitest";

import type { Report, Section } from "./schema";
import { resolvedDisplayTitle, updateSectionDisplayTitle } from "./section-titles";

function h4Report(body = "当前正文"): Report {
  return {
    title: "测试报告",
    fields: {},
    intakeItems: [],
    sections: [{
      key: "module",
      title: "稳定模块名",
      headingLevel: 1,
      reportModuleId: "environmental_sustainability",
      blocks: [],
      children: [{
        key: "section",
        title: "固定 H2",
        headingLevel: 2,
        reportSectionId: "climate_change",
        blocks: [],
        children: [{
          key: "pillar",
          title: "治理",
          headingLevel: 3,
          blocks: [],
          children: [{
            key: "paragraph_unit",
            title: "失效回退标题",
            headingLevel: 4,
            titleGeneration: { sourceBlockId: "paragraph", guidance: "概括正文" },
            blocks: [{
              id: "paragraph",
              type: "paragraph",
              blockType: "generative",
              source: "ai",
              content: [{ kind: "text", text: body }],
            }],
          }],
        }],
      }],
    }],
  };
}

function findSection(report: Report, key: string): Section {
  const visit = (sections: Section[]): Section | undefined => {
    for (const section of sections) {
      if (section.key === key) return section;
      const child = visit(section.children ?? []);
      if (child) return child;
    }
  };
  const section = visit(report.sections);
  if (!section) throw new Error(`missing section: ${key}`);
  return section;
}

describe("section title contract", () => {
  it("按 displayTitle、titleContent、稳定 title 的顺序解析用户可见标题", () => {
    const report = h4Report();
    const section = findSection(report, "paragraph_unit");
    expect(resolvedDisplayTitle(section, report)).toBe("失效回退标题");
    expect(resolvedDisplayTitle({ ...section, titleContent: [{ kind: "text", text: "模板标题" }] }, report)).toBe("模板标题");
    expect(resolvedDisplayTitle({
      ...section,
      displayTitle: { text: "实例标题", origin: "generated", inputFingerprint: "abc" },
    }, report)).toBe("实例标题");
  });

  it("编辑标题时记录当前直属正文指纹并标记为用户标题", async () => {
    const updated = await updateSectionDisplayTitle(h4Report(), "paragraph_unit", "  用户标题  ");
    expect(findSection(updated, "paragraph_unit").displayTitle).toMatchObject({
      text: "用户标题",
      origin: "user",
    });
    expect(findSection(updated, "paragraph_unit").displayTitle?.inputFingerprint).toMatch(/^[0-9a-f]{64}$/);
  });

  it("正文变化后保留当前标题会用新正文指纹重新确认", async () => {
    const initial = await updateSectionDisplayTitle(h4Report(), "paragraph_unit", "当前标题");
    const previousFingerprint = findSection(initial, "paragraph_unit").displayTitle?.inputFingerprint;
    const changed = h4Report("正文已经修改");
    findSection(changed, "paragraph_unit").displayTitle = findSection(initial, "paragraph_unit").displayTitle;

    const retained = await updateSectionDisplayTitle(changed, "paragraph_unit", "当前标题");
    const retainedTitle = findSection(retained, "paragraph_unit").displayTitle;
    expect(retainedTitle?.text).toBe("当前标题");
    expect(retainedTitle?.inputFingerprint).not.toBe(previousFingerprint);
  });

  it("H1 标题指纹随下属 H4 标题或正文指纹变化", async () => {
    const withH4Title = await updateSectionDisplayTitle(h4Report(), "paragraph_unit", "段落标题");
    const first = await updateSectionDisplayTitle(withH4Title, "module", "模块标题");
    const firstFingerprint = findSection(first, "module").displayTitle?.inputFingerprint;

    const changed = h4Report("变化后的正文");
    const withRetainedH4 = await updateSectionDisplayTitle(changed, "paragraph_unit", "段落标题");
    const second = await updateSectionDisplayTitle(withRetainedH4, "module", "模块标题");
    expect(findSection(second, "module").displayTitle?.inputFingerprint).not.toBe(firstFingerprint);
  });
});
