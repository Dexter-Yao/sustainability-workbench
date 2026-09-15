// ABOUTME: 议题工作纸派生层测试，确保分议题填写与生成只读取 Report 契约。
// ABOUTME: 以气候议题真实形态覆盖内容清单、H3 分区、显隐与前四章隔离。
import { describe, expect, it } from "vitest";

import {
  deriveReportSectionSummaries,
  generatableBlocksForReportSection,
  intakeItemReady,
  reportSectionWorkpaperSections,
  unassignedReportSectionIntakeItems,
  updateIntakeItem,
} from "./report-section-flow";
import type { Block, IntakeItem, Report, Section } from "./schema";

const intakeItems: IntakeItem[] = [
  {
    key: "climate.q_governance_roles",
    contentScopeId: "climate_change",
    prompt: "贵公司是否有人员或部门负责应对气候变化、节能降耗或温室气体减排相关工作，并形成职责分工或内部协同安排？",
    kind: "single_select",
    options: ["设有专门部门或岗位", "由相关部门或人员兼管", "管理层直接负责", "由现有人员结合职责推进"],
    answer: "管理层直接负责",
  },
  {
    key: "climate.q_climate_risk_choices",
    contentScopeId: "climate_change",
    prompt: "您认为以下哪些气候相关风险会对公司产生影响？请在物理风险和转型风险中各至少选择一项。",
    kind: "multi_select",
    options: ["台风", "极端高温", "碳定价与排放监管政策变化", "消费者偏好转变风险"],
    optionGroups: [
      { key: "physical_risk", label: "物理风险", minSelections: 1, options: ["台风", "极端高温"] },
      {
        key: "transition_risk",
        label: "转型风险",
        minSelections: 1,
        options: ["碳定价与排放监管政策变化", "消费者偏好转变风险"],
      },
    ],
    collectionPriority: "core",
    answer: ["台风", "消费者偏好转变风险"],
  },
  {
    key: "climate.q_climate_opportunity_choices",
    contentScopeId: "climate_change",
    prompt: "您认为以下哪些气候相关机遇会对公司产生影响？请至少选择一项。",
    kind: "multi_select",
    options: ["运营资源效率提升机遇", "低碳产品方案开发机遇", "低碳转型新市场与绿色金融机遇"],
    collectionPriority: "core",
    answer: ["运营资源效率提升机遇"],
  },
  {
    key: "climate.q_strategy_content",
    contentScopeId: "climate_change",
    prompt: "贵公司在应对气候变化方面有哪些战略方向、管理目标、行动计划或重点工作？",
    kind: "text",
    answer: "推进节能设备改造和资源效率提升。",
  },
  {
    key: "climate.q_training_activities",
    contentScopeId: "climate_change",
    prompt: "贵公司是否开展过应对气候变化、节能降耗或温室气体减排相关的培训或活动？",
    kind: "single_select",
    options: ["是", "否", "不确定"],
    collectionPriority: "recommended",
  },
];

function para(id: string, inputKeys: string[], blockType: Block["blockType"] = "generative"): Block {
  return {
    id,
    type: "paragraph",
    blockType,
    source: "ai",
    state: id === "climate.gov_structure" ? "ready" : "ready",
    generation: {
      task: { focus: id },
      inputs: { evidence: { kind: "explicit", intakeItems: inputKeys } },
    },
    content: [{ kind: "text", text: id }],
  };
}

function table(id: string, inputKeys: string[]): Block {
  return {
    id,
    type: "table",
    blockType: "generative",
    source: "ai",
    generation: {
      task: { focus: id },
      inputs: { evidence: { kind: "explicit", intakeItems: inputKeys } },
    },
    table: {
      colDefs: [{ key: "name", header: "名称", cellType: "text" }],
      children: [{ headerRow: true, children: [{ type: "th", value: "名称" }] }],
    },
  };
}

function climateSection(): Section {
  return {
    key: "climate_change",
    title: "应对气候变化",
    headingLevel: 2,
    reportSectionId: "climate_change",
    blocks: [],
    children: [
      {
        key: "climate.gov",
        title: "治理",
        headingLevel: 3,
        blocks: [
          { id: "climate.gov_regulatory_note", type: "paragraph", blockType: "slot", source: "template" },
          para("climate.gov_structure", ["climate.q_governance_roles"]),
        ],
      },
      {
        key: "climate.strategy",
        title: "战略",
        headingLevel: 3,
        blocks: [
          {
            id: "climate.strategy_identification",
            type: "paragraph",
            blockType: "fixed",
            source: "template",
            content: [{ kind: "text", text: "strategy intro" }],
          },
          table("climate.strategy_physical_risk", ["climate.q_strategy_content", "climate.q_climate_risk_choices"]),
          table("climate.strategy_transition_risk", ["climate.q_strategy_content", "climate.q_climate_risk_choices"]),
          table("climate.strategy_opportunity", ["climate.q_strategy_content", "climate.q_climate_opportunity_choices"]),
        ],
      },
      {
        key: "climate.iro",
        title: "影响、风险与机遇管理",
        headingLevel: 3,
        blocks: [
          {
            ...para("climate.iro_reduction_practice", ["climate.q_strategy_content"]),
            appears_when: {
              all: [
                {
                  path: "intakeItems.climate.q_strategy_content",
                  op: "contains_any",
                  value: ["节能", "减排", "资源效率"],
                },
              ],
            },
          },
          {
            ...para("climate.iro_training", ["climate.q_training_activities"], "constrained"),
            appears_when: { all: [{ path: "intakeItems.climate.q_training_activities", op: "eq", value: "是" }] },
          },
        ],
      },
      {
        key: "climate.metrics",
        title: "指标与目标",
        headingLevel: 3,
        blocks: [
          {
            id: "climate.metrics_quantitative_summary",
            type: "image",
            blockType: "fixed",
            source: "derived",
            image: {
              derivedVisualization: {
                kind: "quantitative_metric_summary",
                metricKeys: ["economic_environment_r04"],
              },
            },
          },
          {
            ...para("climate.metrics_emissions_methodology", [], "constrained"),
            generation: {
              task: { focus: "climate.metrics_emissions_methodology" },
              inputs: {
                evidence: {
                  kind: "explicit",
                  quantitativeMetrics: ["economic_environment_r04"],
                },
              },
            },
          },
        ],
      },
    ],
  };
}

function reportWith(items = intakeItems): Report {
  return {
    title: "测试报告",
    fields: {},
    intakeItems: items,
    sections: [
      {
        key: "about_report",
        title: "关于本报告",
        headingLevel: 1,
        blocks: [
          {
            id: "about.opening",
            type: "paragraph",
            blockType: "generative",
            source: "ai",
            generation: { task: { focus: "about.opening" } },
          },
        ],
      },
      {
        key: "environmental_sustainability",
        title: "环境可持续",
        headingLevel: 1,
        reportModuleId: "environmental_sustainability",
        blocks: [],
        children: [climateSection()],
      },
    ],
  };
}

describe("report section flow 派生层", () => {
  it("按 reportSectionId 汇总气候议题内容清单与可生成块，不混入前四章", () => {
    const topics = deriveReportSectionSummaries(reportWith());

    expect(topics).toHaveLength(1);
    expect(topics[0]).toMatchObject({
      reportSectionId: "climate_change",
      title: "应对气候变化",
      intakeTotal: 5,
      intakeAnswered: 4,
      generationTotal: 6,
      generationReady: 3,
    });
    expect(generatableBlocksForReportSection(reportWith(), "climate_change").map((block) => block.id)).not.toContain(
      "about.opening",
    );
  });

  it("report_section selector 将 H2 全部内容清单投影到摘要工作纸和 readiness", () => {
    const topic: Section = {
      ...climateSection(),
      children: [],
      conciseDisclosure: {
        ...para("climate_change.concise_summary", []),
        generation: {
          task: { focus: "climate_change.concise_summary" },
          inputs: { evidence: { kind: "report_section" } },
        },
      },
    };
    const report = reportWith();
    report.sections[1].children = [topic];

    const workpaper = reportSectionWorkpaperSections(report, "climate_change");
    expect(workpaper).toHaveLength(1);
    expect(workpaper[0].intakeItems.map((item) => item.key)).toEqual(
      intakeItems.map((item) => item.key),
    );
  });

  it("按气候 H3 派生工作纸分区，左侧题目包含隐藏块显隐条件依赖", () => {
    const sections = reportSectionWorkpaperSections(reportWith(), "climate_change");
    expect(sections.map((section) => section.section.key)).toEqual([
      "climate.gov",
      "climate.strategy",
      "climate.iro",
      "climate.metrics",
    ]);
    expect(sections.map((section) => section.intakeItems.map((item) => item.key))).toEqual([
      ["climate.q_governance_roles"],
      ["climate.q_climate_risk_choices", "climate.q_climate_opportunity_choices", "climate.q_strategy_content"],
      ["climate.q_strategy_content", "climate.q_training_activities"],
      [],
    ]);
    expect(sections[2].blocks.map((block) => block.id)).not.toContain("climate.iro_training");
    expect(sections[3].blocks.map((block) => block.id)).toEqual([
      "climate.metrics_quantitative_summary",
      "climate.metrics_emissions_methodology",
    ]);
  });

  it("识别当前可见分区未消费的议题题目，供工作纸补充内容区展示", () => {
    const report = reportWith([
      ...intakeItems,
      {
        key: "climate.q_unassigned",
        contentScopeId: "climate_change",
        prompt: "未绑定到当前块的补充题",
        kind: "text",
      },
    ]);

    expect(unassignedReportSectionIntakeItems(report, "climate_change").map((item) => item.key)).toEqual([
      "climate.q_unassigned",
    ]);
  });

  it("intakeItems 条件变化后，气候显隐矩阵即时变化", () => {
    const answered = reportWith(
      intakeItems.map((item) =>
        item.key === "climate.q_training_activities" ? { ...item, answer: "是" } : item,
      ),
    );
    const ids = reportSectionWorkpaperSections(answered, "climate_change")
      .flatMap((section) => section.blocks)
      .map((block) => block.id);

    expect(ids).toContain("climate.iro_training");
    expect(ids).toContain("climate.metrics_emissions_methodology");
    expect(ids).not.toContain("climate.metrics_targets");
  });

  it("选择题答案必须来自 options，补充说明可独立构成 ready", () => {
    expect(intakeItemReady(intakeItems[0])).toBe(true);
    expect(intakeItemReady({ ...intakeItems[0], answer: "自行填写选项" })).toBe(false);
    expect(intakeItemReady({ ...intakeItems[1], answer: ["台风", "自行填写选项"] })).toBe(false);
    expect(intakeItemReady({ ...intakeItems[1], answer: ["台风"], supplement: "补充说明。" })).toBe(false);
    const training = intakeItems.find((item) => item.key === "climate.q_training_activities")!;
    expect(intakeItemReady({ ...training, supplement: "覆盖生产班组。" })).toBe(true);
  });




  it("更新 intakeItem 时保持其他题目与 Report 结构不变", () => {
    const report = reportWith();
    const next = updateIntakeItem(report, "climate.q_training_activities", { answer: "是", supplement: "覆盖生产班组。" });
    const item = next.intakeItems.find((entry) => entry.key === "climate.q_training_activities");

    expect(item).toMatchObject({ answer: "是", supplement: "覆盖生产班组。" });
    expect(next.sections).toBe(report.sections);
    expect(report.intakeItems.find((entry) => entry.key === "climate.q_training_activities")?.answer).toBeUndefined();
  });


  it("气候风险与机遇题使用分组必选合同，不再包含负向选项", () => {
    const risk = intakeItems.find((item) => item.key === "climate.q_climate_risk_choices")!;
    const opportunity = intakeItems.find((item) => item.key === "climate.q_climate_opportunity_choices")!;

    expect(risk.collectionPriority).toBe("core");
    expect(risk.optionGroups?.map((group) => [group.key, group.minSelections])).toEqual([
      ["physical_risk", 1],
      ["transition_risk", 1],
    ]);
    expect(risk.options).not.toContain("暂未识别明显气候相关风险");
    expect(risk.options).not.toContain("不确定");
    expect(opportunity.collectionPriority).toBe("core");
    expect(opportunity.options).not.toContain("暂未识别明显气候相关机遇");
    expect(opportunity.options).not.toContain("不确定");
  });
});
