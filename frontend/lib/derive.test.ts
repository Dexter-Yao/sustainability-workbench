// ABOUTME: 文档投影测试：守住 Report 结构到正文页节点的推导——准则批注位置、编号标签、受控省略与可编辑判定。
import { describe, expect, it } from "vitest";

import { deriveDocument, editableBlockIds, selectableBlockIds } from "./derive";
import type { Report, Section } from "./schema";

const climateSection: Section = {
  key: "climate_change",
  title: "应对气候变化",
  headingLevel: 2,
  reportSectionId: "climate_change",
  blocks: [],
  children: [
    { key: "climate.gov", title: "治理", headingLevel: 3, blocks: [] },
    { key: "climate.strategy", title: "战略", headingLevel: 3, blocks: [] },
  ],
};

const energySection: Section = {
  key: "energy_management",
  title: "能源管理",
  headingLevel: 2,
  reportSectionId: "energy_management",
  blocks: [],
};

const sustainabilityManagementSection: Section = {
  key: "sustainability_mgmt",
  title: "可持续发展管理",
  headingLevel: 1,
  blocks: [],
};

function report(): Report {
  return {
    title: "t",
    fields: {},
    intakeItems: [],
    sections: [
      sustainabilityManagementSection,
      {
        key: "env",
        title: "环境信息披露",
        headingLevel: 1,
        blocks: [],
        children: [climateSection, energySection],
      },
    ],
    disclosureProfile: {
      mainlandStandard: "sse",
      includesHongKongExchangeGuide: false,
      additionalDisclosureReferences: [],
    },
  };
}

describe("deriveDocument standards annotation", () => {
  it("在议题 H2 与可持续发展管理章节插入用户可见准则批注", () => {
    const nodes = deriveDocument(report());
    const annotations = nodes.filter((node) => node.type === "standards_clause_annotation");
    expect(annotations).toEqual([
      { type: "standards_clause_annotation", sectionKey: "sustainability_mgmt" },
      { type: "standards_clause_annotation", sectionKey: "climate_change" },
      { type: "standards_clause_annotation", sectionKey: "energy_management" },
    ]);
  });

  it("推导整份报告并为标题携带章节 key 与层级", () => {
    const headings = deriveDocument(report()).filter((node) => node.type === "heading");
    expect(headings.map((node) => [node.sectionKey, node.level])).toEqual([
      ["sustainability_mgmt", 1],
      ["env", 1],
      ["climate_change", 2],
      ["climate.gov", 3],
      ["climate.strategy", 3],
      ["energy_management", 2],
    ]);
  });
});

describe("deriveDocument 证据门控省略与可编辑判定", () => {
  it("state=omitted 的块不渲染，单块 H4 不留孤立标题；恢复后照常出现", () => {
    const gated: Section = {
      key: "waste.iro.evidence",
      title: "危险废弃物委托处置",
      headingLevel: 4,
      blocks: [
        { id: "waste.iro_evidence", type: "paragraph", blockType: "generative", source: "ai", state: "omitted" },
      ],
    } as Section;
    const pillar: Section = {
      key: "waste.iro",
      title: "影响、风险与机遇管理",
      headingLevel: 3,
      blocks: [
        {
          id: "waste.iro_main",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          state: "ready",
          content: [{ kind: "text", text: "主段正文" }],
        },
        { id: "waste.fixed", type: "paragraph", blockType: "fixed", source: "template", content: [{ kind: "text", text: "固定表述" }] },
        { id: "waste.table", type: "table", blockType: "generative", source: "ai", table: { colDefs: [], children: [] } },
        { id: "waste.slot", type: "image", blockType: "fixed", source: "template", image: { placeholder: "流程图", layoutAssetSlot: true, layoutAssetIds: [] } },
      ],
      children: [gated],
    } as Section;
    const rpt = {
      title: "t",
      fields: {},
      intakeItems: [],
      sections: [{ key: "waste", title: "废弃物管理", headingLevel: 2, blocks: [], children: [pillar] }],
    } as unknown as Report;

    const omittedNodes = deriveDocument(rpt);
    expect(omittedNodes.some((n) => n.type === "paragraph" && n.blockId === "waste.iro_evidence")).toBe(false);
    expect(omittedNodes.some((n) => n.type === "heading" && n.sectionKey === "waste.iro.evidence")).toBe(false);
    expect(editableBlockIds(omittedNodes)).toEqual(["waste.iro_main"]);
    // Empty image carrier slots are not part of the document.
    expect(selectableBlockIds(omittedNodes)).toEqual(["waste.iro_main", "waste.fixed", "waste.table"]);

    gated.blocks[0].state = "ready";
    const restoredNodes = deriveDocument(rpt);
    expect(restoredNodes.some((n) => n.type === "paragraph" && n.blockId === "waste.iro_evidence")).toBe(true);
    expect(restoredNodes.some((n) => n.type === "heading" && n.sectionKey === "waste.iro.evidence")).toBe(true);
  });
});
