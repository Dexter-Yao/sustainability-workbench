// ABOUTME: localStorage 持久化快照的 parse-first 测试，确保浏览器只保存用户状态而非 Report 结构。
// ABOUTME: 当前 instance/contract 是章节与块结构真相源；非 V4 快照一律拒绝，不维护旧状态迁移。
import { describe, expect, it } from "vitest";

import {
  applyStoredStateToTemplate,
  parseLocalStoredReportState,
  parseStoredReportState,
  reportToStoredReportState,
  serializeStoredReportState,
  STORED_REPORT_STATE_VERSION,
  type StoredReportStateV4,
} from "./stored-report-state";
import type { Report } from "./schema";

const template: Report = {
  title: "template",
  fields: {
    company: { key: "company", label: "公司", type: "string", source: "user_input", value: "" },
    report_year: { key: "report_year", label: "年度", type: "year", source: "user_input", value: null },
  },
  intakeItems: [
    {
      key: "climate.q1",
      contentScopeId: "climate_change",
      prompt: "是否开展气候治理？",
      kind: "single_select",
      options: ["是", "否"],
    },
  ],
  disclosureProfile: {
    mainlandStandard: "sse",
    includesHongKongExchangeGuide: false,
    additionalDisclosureReferences: [],
  },
  appendixPackage: {
    externalAssuranceReport: { isIncluded: false, fileLabel: null },
    readerFeedbackContactInformation: { address: null, email: null, phone: null },
  },
  sections: [
    {
      key: "about_report",
      title: "关于本报告",
      headingLevel: 1,
      blocks: [
        {
          id: "about.basis",
          type: "paragraph",
          blockType: "fixed",
          source: "template",
          content: [{ kind: "text", text: "本报告主要遵循" }],
        },
        {
          id: "about.generated",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          state: "ready",
          content: [{ kind: "text", text: "模板草稿" }],
        },
        {
          id: "about.table",
          type: "table",
          blockType: "generative",
          source: "ai",
          table: {
            colDefs: [{ key: "name", header: "名称" }],
            children: [{ headerRow: true, children: [{ type: "th", colKey: "name", value: "名称" }] }],
          },
        },
        {
          id: "appendix.esg_key_performance_metrics",
          type: "table",
          blockType: "fixed",
          source: "derived",
          table: {
            colDefs: [{ key: "metric", header: "指标" }],
            children: [{ headerRow: true, children: [{ type: "th", colKey: "metric", value: "指标" }] }],
          },
        },
      ],
    },
  ],
};

function editedReport(): Report {
  return {
    ...template,
    fields: {
      ...template.fields,
      company: { ...template.fields.company, value: "晟原精密" },
    },
    intakeItems: [{ ...template.intakeItems[0], answer: "是", supplement: "董事会定期审议。" }],
    meta: { quantitativeMetrics: { metrics: {} } },
    sections: [
      {
        key: "about_report",
        title: "关于本报告",
        headingLevel: 1,
        blocks: [
          {
            id: "about.basis_note",
            type: "paragraph",
            blockType: "slot",
            source: "template",
            styleRole: "source_note",
            content: [{ kind: "text", text: "编制依据按所选准则合成；AI 不得改写。" }],
          },
          {
            id: "about.generated",
            type: "paragraph",
            blockType: "generative",
            source: "ai",
            state: "ready",
            content: [{ kind: "text", text: "用户当前正文" }],
          },
          {
            id: "about.table",
            type: "table",
            blockType: "generative",
            source: "ai",
            state: "ready",
            table: {
              colDefs: [{ key: "name", header: "名称" }],
              children: [
                { headerRow: true, children: [{ type: "th", colKey: "name", value: "名称" }] },
                { state: "ready", children: [{ type: "td", colKey: "name", value: "用户行" }] },
              ],
            },
          },
        ],
      },
    ],
  };
}

describe("StoredReportStateV4", () => {
  it("保存快照不包含 Report 结构字段或内部块元数据", () => {
    const raw = serializeStoredReportState(editedReport());
    const stored = JSON.parse(raw);

    expect(stored.version).toBe(STORED_REPORT_STATE_VERSION);
    expect(raw).not.toContain('"sections"');
    expect(raw).not.toContain('"blockType"');
    expect(raw).not.toContain('"source"');
    expect(raw).not.toContain('"generation"');
    expect(raw).not.toContain('"styleRole"');
    expect(raw).not.toContain("about.basis_note");
    expect(raw).not.toContain("AI 不得改写");
  });

  it("旧版本状态明确拒绝，不迁移用户状态或表格缓存", () => {
    const raw = JSON.stringify({
      version: 1,
      fields: { company: "旧公司" },
      generatedBlocks: { "about.generated": { content: [{ kind: "text", text: "旧正文" }] } },
      tableBlocks: { "about.table": { children: [{ children: [{ type: "td", colKey: "name", value: "旧表行" }] }] } },
    });
    expect(() => parseStoredReportState(raw)).toThrow("不支持的报告状态版本");
  });

  it("本地旧版本状态只标记为待废弃，不读取或迁移其中内容", () => {
    const result = parseLocalStoredReportState(JSON.stringify({
      version: 3,
      fields: { company: "不得恢复的旧公司" },
      generatedBlocks: {
        "about.generated": { content: [{ kind: "text", text: "不得恢复的旧正文" }] },
      },
    }));

    expect(result).toEqual({ state: null, discardedObsoleteVersion: true });
  });

  it("当前版本遇到未知或损坏嵌套字段时 fail-loud", () => {
    expect(() => parseStoredReportState(JSON.stringify({
      version: 4,
      fields: { company: "示例", invalid: { nested: true } },
      intakeItems: { "climate.q1": { answer: "是", ignored: "丢弃" } },
      generatedBlocks: {
        "about.generated": { content: [{ kind: "text", text: "可恢复", ignored: true }], state: "ready" },
        malformed: { content: [{ kind: "unknown" }] },
      },
      unknown: "丢弃",
    }))).toThrow("报告状态快照不符合合同");
  });

  it("V4 不再接受已删除的全局缺失内容策略", () => {
    expect(() => parseStoredReportState(JSON.stringify({
      version: 4,
      meta: { missingContentPolicy: "no_user_provided_content" },
    }))).toThrow("报告状态快照不符合合同");
  });

  it("损坏 JSON 不再静默回退为空状态", () => {
    expect(() => parseStoredReportState("{not-json")).toThrow("报告状态快照不是有效 JSON");
  });

  it("只应用同源 schema 声明的领域默认值", () => {
    const state = parseStoredReportState(JSON.stringify({ version: 4 }));

    expect(state).toEqual({
      version: 4,
      fields: {},
      intakeItems: {},
      assessmentInput: null,
      disclosureProfile: null,
      appendixPackage: null,
      meta: null,
      stakeholderEngagement: null,
      sectionTitles: {},
      generatedBlocks: {},
      tableBlocks: {},
      imageBlocks: {},
      companyBusinessSummary: null,
    });
  });

  it("保留评估阈值、IRO 明细和表格行的重生成来源", () => {
    const state = parseStoredReportState(JSON.stringify({
      version: 4,
      fields: {},
      intakeItems: {},
      assessmentInput: {
        reportingYear: 2025,
        threshold: { financial: 3, impact: 4 },
        scores: [{
          assessmentTopicId: "climate_change",
          financialScore: 5,
          impactScore: 4,
          iroItems: [{ kind: "risk", description: "极端天气影响", classes: ["气候"], state: "ready" }],
        }],
      },
      generatedBlocks: {},
      tableBlocks: {
        "about.table": {
          children: [{
            children: [{ type: "td", colKey: "name", value: "气候风险" }],
            origin: { from: "ai", theme: "气候风险", category: "风险", driver_hint: "极端天气" },
          }],
        },
      },
    }));

    const restored = applyStoredStateToTemplate(template, state);
    const score = restored.assessmentInput?.scores[0];
    const table = restored.sections[0].blocks.find((block) => block.id === "about.table")?.table;

    expect(restored.assessmentInput).toMatchObject({ threshold: { financial: 3, impact: 4 } });
    expect(score?.iroItems).toEqual([{
      kind: "risk",
      description: "极端天气影响",
      classes: ["气候"],
      valueChain: null,
      timeHorizon: null,
      state: "ready",
    }]);
    expect(table?.children[0]?.origin).toEqual({ from: "ai", theme: "气候风险", category: "风险", driver_hint: "极端天气" });
  });

  it("部分附录事实不覆盖模板中的其他附录默认值", () => {
    const state = parseStoredReportState(JSON.stringify({
      version: 4,
      fields: {},
      intakeItems: {},
      generatedBlocks: {},
      tableBlocks: {},
      imageBlocks: {},
      appendixPackage: { externalAssuranceReport: { isIncluded: true, fileLabel: "鉴证报告.pdf" } },
    }));

    const restored = applyStoredStateToTemplate(template, state);

    expect(restored.appendixPackage?.externalAssuranceReport).toEqual({ isIncluded: true, fileLabel: "鉴证报告.pdf" });
    expect(restored.appendixPackage?.readerFeedbackContactInformation).toEqual({ address: null, email: null, phone: null });
  });

  it("当前 V4 快照投影时仍以模板结构为准", () => {
    const state = reportToStoredReportState(editedReport());
    state.generatedBlocks["removed.block"] = { content: [{ kind: "text", text: "旧块" }] };
    const report = applyStoredStateToTemplate(template, state);
    const serializedReport = JSON.stringify(report);

    expect(serializedReport).toContain("用户当前正文");
    expect(serializedReport).not.toContain("removed.block");
    expect(serializedReport).not.toContain("旧块");
  });

  it("保留自动建报零行表格的合同省略状态，不恢复模板表头", () => {
    const state = parseStoredReportState(JSON.stringify({
      version: 4,
      fields: {},
      intakeItems: {},
      generatedBlocks: {},
      tableBlocks: {
        "about.table": { children: [], state: "omitted" },
      },
    }));

    const restored = applyStoredStateToTemplate(template, state);
    const block = restored.sections[0]?.blocks.find((item) => item.id === "about.table");

    expect(block?.state).toBe("omitted");
    expect(block?.table?.children).toEqual([]);
  });

  it("定量指标的信息搜集部门随用户状态快照往返保存", () => {
    const report: Report = {
      ...template,
      meta: {
        quantitativeMetrics: {
          metrics: {
            economic_environment_r04: {
              value: "12.5",
              department: "运营部",
              note: "按厂区边界统计",
            },
          },
        },
      },
    };

    const restored = applyStoredStateToTemplate(
      template,
      parseStoredReportState(serializeStoredReportState(report)),
    );

    expect(restored.meta?.quantitativeMetrics?.metrics.economic_environment_r04).toEqual({
      value: "12.5",
      noValueReason: null,
      department: "运营部",
      note: "按厂区边界统计",
    });
  });

  it("派生 KPI 表行不进入快照，也不接受旧快照的表格缓存", () => {
    const report: Report = {
      ...template,
      sections: [{
        ...template.sections[0],
        blocks: template.sections[0].blocks.map((block) =>
          block.id === "appendix.esg_key_performance_metrics"
            ? {
                ...block,
                table: {
                  ...block.table!,
                  children: [
                    ...block.table!.children,
                    { children: [{ type: "td", colKey: "metric", value: "缓存指标" }] },
                  ],
                },
              }
            : block,
        ),
      }],
    };
    const state = reportToStoredReportState(report);
    expect(state.tableBlocks["appendix.esg_key_performance_metrics"]).toBeUndefined();
    state.tableBlocks["appendix.esg_key_performance_metrics"] = {
      children: [{ children: [{ type: "td", colKey: "metric", value: "旧快照指标" }] }],
    };

    const restored = applyStoredStateToTemplate(template, state);
    const derivedTable = restored.sections[0].blocks.find((block) => block.id === "appendix.esg_key_performance_metrics")?.table;

    expect(JSON.stringify(derivedTable)).not.toContain("缓存指标");
    expect(JSON.stringify(derivedTable)).not.toContain("旧快照指标");
  });


  it("利益相关方 Profile 独立往返，派生表格行不进入 tableBlocks", () => {
    const report: Report = {
      ...template,
      stakeholderEngagement: {
        scopeAssessmentTopicIds: ["climate_change"],
        entries: [
          { stakeholderType: "government_regulators", assessmentTopicIds: ["climate_change"], methodIds: ["regulatory_communication"], customMethods: [] },
          { stakeholderType: "shareholders_investors", assessmentTopicIds: [], methodIds: [], customMethods: [] },
          { stakeholderType: "customers", assessmentTopicIds: [], methodIds: [], customMethods: [] },
          { stakeholderType: "management", assessmentTopicIds: [], methodIds: [], customMethods: [] },
          { stakeholderType: "employees", assessmentTopicIds: [], methodIds: [], customMethods: [] },
          { stakeholderType: "suppliers", assessmentTopicIds: [], methodIds: [], customMethods: [] },
          { stakeholderType: "partners", assessmentTopicIds: [], methodIds: [], customMethods: [{ kind: "collaboration_activity", label: "区域协作计划" }] },
          { stakeholderType: "community_public", assessmentTopicIds: [], methodIds: [], customMethods: [] },
        ],
      },
      sections: [{
        ...template.sections[0],
        blocks: [...template.sections[0].blocks, {
          id: "sm.stakeholder_table",
          type: "table",
          blockType: "slot",
          source: "user_input",
          table: {
            rowSource: "stakeholder_engagement",
            colDefs: [{ key: "stk_party", header: "利益相关方" }],
            children: [{ headerRow: true, children: [{ type: "th", value: "利益相关方" }] }, { children: [{ colKey: "stk_party", value: "旧缓存行" }] }],
          },
        }],
      }],
    };

    const state = reportToStoredReportState(report);
    expect(state.tableBlocks["sm.stakeholder_table"]).toBeUndefined();
    expect(state.stakeholderEngagement?.entries[6].customMethods[0].label).toBe("区域协作计划");

    const restored = applyStoredStateToTemplate(template, parseStoredReportState(JSON.stringify(state)));
    expect(restored.stakeholderEngagement).toEqual(report.stakeholderEngagement);
  });
});

describe("buildStoredReportStatePayload 未投影内容保全", () => {
  it("议题章节的生成正文与素材放置不因窄投影保存被抹掉;投影内条目以投影为准", async () => {
    const { buildStoredReportStatePayload } = await import("./stored-report-state");
    const template: Report = {
      title: "保全测试",
      sections: [
        {
          key: "company_intro",
          title: "关于公司",
          headingLevel: 1,
          blocks: [
            { id: "company_intro.body", type: "paragraph", blockType: "constrained", source: "ai", content: [{ kind: "text", text: "投影内容" }], state: "ready" },
            { id: "company_intro.layout_assets", type: "image", blockType: "slot", source: "user_input", image: { layoutAssetSlot: true, layoutAssetIds: ["11111111-1111-4111-8111-111111111111"] } },
          ],
        },
      ],
    } as unknown as Report;
    const baseline = {
      version: 4,
      fields: {},
      intakeItems: {},
      assessmentInput: null,
      disclosureProfile: null,
      appendixPackage: null,
      meta: null,
      stakeholderEngagement: null,
      sectionTitles: { climate_change: { content: [{ kind: "text", text: "议题标题" }] } },
      generatedBlocks: {
        "company_intro.body": { content: [{ kind: "text", text: "服务端旧正文" }], state: "ready" },
        "innovation_driven.iro_innovation_work_measures": { content: [{ kind: "text", text: "议题正文" }], state: "ready" },
      },
      tableBlocks: {},
      imageBlocks: {
        "innovation_driven.layout_assets": { layoutAssetIds: ["22222222-2222-4222-8222-222222222222"], state: "ready" },
      },
    } as unknown as StoredReportStateV4;

    const payload = buildStoredReportStatePayload(template, baseline);
    // 投影之外:议题内容与放置保全
    expect(payload.generatedBlocks["innovation_driven.iro_innovation_work_measures"]).toEqual(
      baseline.generatedBlocks["innovation_driven.iro_innovation_work_measures"],
    );
    expect(payload.imageBlocks["innovation_driven.layout_assets"]).toEqual(
      baseline.imageBlocks["innovation_driven.layout_assets"],
    );
    expect(payload.sectionTitles["climate_change"]).toEqual(baseline.sectionTitles["climate_change"]);
    // 投影之内:以当前投影为准,不被基线旧值覆盖
    expect(payload.generatedBlocks["company_intro.body"]?.content?.[0]?.text).toBe("投影内容");
    expect(payload.imageBlocks["company_intro.layout_assets"]?.layoutAssetIds).toEqual([
      "11111111-1111-4111-8111-111111111111",
    ]);
    // 无基线时行为不变
    const bare = buildStoredReportStatePayload(template, null);
    expect(bare.generatedBlocks["innovation_driven.iro_innovation_work_measures"]).toBeUndefined();
  });

  it("后端派生的公司业务摘要不因前端整体保存被抹掉", async () => {
    const { buildStoredReportStatePayload } = await import("./stored-report-state");
    const template: Report = { title: "业务摘要保全", sections: [] } as unknown as Report;
    const summary = {
      text: "公司主营精密电子元器件与连接器的研发、制造与销售。",
      sourceFingerprint: "a".repeat(64),
    };
    const baseline = {
      version: 4,
      fields: {},
      intakeItems: {},
      assessmentInput: null,
      disclosureProfile: null,
      appendixPackage: null,
      meta: null,
      stakeholderEngagement: null,
      sectionTitles: {},
      generatedBlocks: {},
      tableBlocks: {},
      imageBlocks: {},
      companyBusinessSummary: summary,
    } as unknown as StoredReportStateV4;

    // 摘要由后端在生成前派生,前端 Report 不承载它;整体 PUT 须原样带回。
    expect(buildStoredReportStatePayload(template, baseline).companyBusinessSummary).toEqual(summary);
    expect(buildStoredReportStatePayload(template, null).companyBusinessSummary).toBeNull();
  });

  it("基线中不在当前投影键集内的 intake 答案不因窄投影保存被抹掉", async () => {
    const { buildStoredReportStatePayload } = await import("./stored-report-state");
    const template: Report = {
      title: "intake 保全测试",
      intakeItems: [
        {
          key: "climate.q1",
          contentScopeId: "climate_change",
          prompt: "是否开展气候治理？",
          kind: "single_select",
          options: ["是", "否"],
          answer: "是",
        },
      ],
      sections: [],
    } as unknown as Report;
    const baseline = {
      version: 4,
      fields: {},
      intakeItems: {
        "climate.q1": { answer: "否", supplement: null },
        "innovation_driven.iro_work_measures": { answer: "已建立专项小组", supplement: null },
      },
      assessmentInput: null,
      disclosureProfile: null,
      appendixPackage: null,
      meta: null,
      stakeholderEngagement: null,
      sectionTitles: {},
      generatedBlocks: {},
      tableBlocks: {},
      imageBlocks: {},
    } as unknown as StoredReportStateV4;

    const payload = buildStoredReportStatePayload(template, baseline);

    // 投影内答案以当前投影为准,不被基线旧值覆盖
    expect(payload.intakeItems["climate.q1"]).toEqual({ answer: "是", supplement: null });
    // 投影之外(当前装配不含该议题)的答案保全,不被整体覆写抹掉
    expect(payload.intakeItems["innovation_driven.iro_work_measures"]).toEqual(
      baseline.intakeItems["innovation_driven.iro_work_measures"],
    );
  });
});


describe("编排事实与报告内容的边界（meta）", () => {
  // primaryInputMode 是报告级编排事实，落状态 meta 供生成闸与导出闸共同裁定；
  // Report 合同 extra="forbid"，把它带进 Report.meta 会让 /api/plan 整体 422，
  // 编制页只剩一行「装配失败」。两个方向都要钉住。
  const stateWithMode = parseStoredReportState(
    JSON.stringify({
      version: STORED_REPORT_STATE_VERSION,
      meta: {
        quantitativeMetrics: { metrics: {} },
        materialityStrategy: null,
        primaryInputMode: "questions",
      },
    }),
  ) as StoredReportStateV4;

  it("投影进 Report.meta 时剔除编排字段", () => {
    const report = applyStoredStateToTemplate(template, stateWithMode);
    expect(report.meta).toBeTruthy();
    expect("primaryInputMode" in (report.meta as object)).toBe(false);
    // 报告内容字段照常投影。
    expect(report.meta?.quantitativeMetrics).toBeTruthy();
  });

  it("整体 PUT 不得把编排字段抹掉（与 companyBusinessSummary 同语义）", () => {
    const report = applyStoredStateToTemplate(template, stateWithMode);
    const payload = JSON.parse(serializeStoredReportState(report, stateWithMode));
    expect(payload.meta.primaryInputMode).toBe("questions");
  });

  it("投影快照不得把编排默认值写回运行时 Report.meta", () => {
    // 快照校验开着 useDefaults，会把 schema 默认值原地写进被校验对象；快照的 meta 若与
    // 运行时 Report.meta 同一引用，首次自动保存后 Report.meta 就多出 primaryInputMode: null，
    // 此后 diagnose / plan / export 一律 422。
    const report = applyStoredStateToTemplate(template, stateWithMode);
    reportToStoredReportState(report);
    serializeStoredReportState(report, stateWithMode);
    expect("primaryInputMode" in (report.meta as object)).toBe(false);
  });
});
