// ABOUTME: intake 步骤序列回归——固定四步，第 4 步「定性信息」恒在，所选路径的页面作为其二级条目；
// ABOUTME: 另覆盖最长前缀匹配（防 /materials 误吞 /materials/processing）与生成入口解析。
import { describe, expect, it } from "vitest";

import { generationEntryHref, getIntakeSteps, intakeStepKey, intakeStepScreenLabel, matchIntakeStepIndex, resolveIntakeStep } from "./intake-steps";

const FULL_SCOPE = { collectsMaterialityAssessment: true, materialAgentEnabled: true };

describe("getIntakeSteps", () => {
  it("未选择填报方式时第 4 步为填报方式选择", () => {
    const steps = getIntakeSteps(FULL_SCOPE);
    expect(steps.map((step) => step.href)).toEqual([
      "/intake/info",
      "/intake/scoring",
      "/intake/metrics",
      "/intake/input-path",
    ]);
  });

  it("materials 路径：一级仍是定性信息，两页作为其二级条目", () => {
    // 路径页面是第 4 步的下级，不是替代它的同级步骤——一级标签不得随路径漂移，
    // 否则用户看不出这些页面同属「定性信息」，也失去回到二选一页的入口。
    const steps = getIntakeSteps(FULL_SCOPE, "materials");
    expect(steps.map((step) => step.href)).toEqual([
      "/intake/info",
      "/intake/scoring",
      "/intake/metrics",
      "/intake/input-path",
    ]);
    expect(steps[3].key).toBe("inputPath");
    expect(steps[3].sections).toEqual([
      { href: "/materials", key: "materialUpload" },
      { href: "/materials/processing", key: "materialProcessing" },
    ]);
  });

  it("questions 路径：一级仍是定性信息，议题信息作为其二级条目", () => {
    const steps = getIntakeSteps(FULL_SCOPE, "questions");
    expect(steps.map((step) => step.href)).toEqual([
      "/intake/info",
      "/intake/scoring",
      "/intake/metrics",
      "/intake/input-path",
    ]);
    expect(steps[3].sections).toEqual([{ href: "/intake/questions", key: "topicQuestions" }]);
  });

  it("无资料 Agent 时二级仍是议题信息——它承载生成区，不能让入口落到 gateway", () => {
    const steps = getIntakeSteps({ ...FULL_SCOPE, materialAgentEnabled: false });
    expect(steps.map((step) => step.href)).toEqual([
      "/intake/info",
      "/intake/scoring",
      "/intake/metrics",
      "/intake/input-path",
    ]);
    expect(steps[3].sections).toEqual([{ href: "/intake/questions", key: "topicQuestions" }]);
  });

  it("总步数恒为 4：路径选择不改变步骤编号", () => {
    for (const mode of [null, "questions", "materials"] as const) {
      expect(getIntakeSteps(FULL_SCOPE, mode)).toHaveLength(4);
    }
  });

  it("评分收集关闭时步骤序列不含评分页", () => {
    const steps = getIntakeSteps({ collectsMaterialityAssessment: false, materialAgentEnabled: true });
    expect(steps.map((step) => step.href)).not.toContain("/intake/scoring");
  });
});

describe("matchIntakeStepIndex / resolveIntakeStep", () => {
  const steps = getIntakeSteps(FULL_SCOPE, "materials");

  it("二级页面归属第 4 步：/materials 与 /materials/processing 都高亮定性信息", () => {
    // 二级条目一并参与匹配，否则停在路径页时左栏无步骤高亮。
    expect(matchIntakeStepIndex("/materials", steps)).toBe(3);
    expect(matchIntakeStepIndex("/materials/processing", steps)).toBe(3);
    expect(matchIntakeStepIndex("/intake/input-path", steps)).toBe(3);
  });

  it("resolveIntakeStep 在末步上 next 为 null、previous 为定量信息", () => {
    const info = resolveIntakeStep("/materials/processing", steps);
    expect(info?.current.href).toBe("/intake/input-path");
    expect(info?.previous?.href).toBe("/intake/metrics");
    expect(info?.next).toBeNull();
  });

  it("已选路径时「下一步」直达路径首页，不折返二选一 gateway", () => {
    const info = resolveIntakeStep("/intake/metrics", steps);
    expect(info?.next?.href).toBe("/materials");
    // 未选路径时仍指向 gateway——那正是他该做的下一件事。
    const unchosen = getIntakeSteps(FULL_SCOPE);
    expect(resolveIntakeStep("/intake/metrics", unchosen)?.next?.href).toBe("/intake/input-path");
  });

  it("questions 路径上二级页面归属第 4 步、previous 为定量信息", () => {
    const questionSteps = getIntakeSteps(FULL_SCOPE, "questions");
    const info = resolveIntakeStep("/intake/questions", questionSteps);
    // current 是一级步骤本身（定性信息）；二级页面只决定归属，不成为 current。
    expect(info?.current.href).toBe("/intake/input-path");
    expect(info?.previous?.href).toBe("/intake/metrics");
    expect(info?.next).toBeNull();
  });

  it("未匹配任何步骤返回 -1 / null", () => {
    expect(matchIntakeStepIndex("/reports", steps)).toBe(-1);
    expect(resolveIntakeStep("/reports", steps)).toBeNull();
  });
});

describe("步骤声明的路由映射（key 供字典取词，screenLabel 是恒中文的遥测标识）", () => {
  it("已登记路由一律返回声明标签", () => {
    expect(intakeStepKey("/intake/info")).toBe("reportBasics");
    expect(intakeStepScreenLabel("/intake/info")).toBe("企业及报告基本信息");
    expect(intakeStepKey("/intake/scoring")).toBe("materialityScoring");
    expect(intakeStepScreenLabel("/intake/scoring")).toBe("议题重要性评分");
    expect(intakeStepKey("/intake/metrics")).toBe("quantitative");
    expect(intakeStepScreenLabel("/intake/metrics")).toBe("ESG 定量信息");
    expect(intakeStepKey("/intake/input-path")).toBe("inputPath");
    expect(intakeStepScreenLabel("/intake/input-path")).toBe("定性信息");
    expect(intakeStepKey("/intake/questions")).toBe("topicQuestions");
    expect(intakeStepScreenLabel("/intake/questions")).toBe("议题信息填写");
    expect(intakeStepKey("/materials")).toBe("materialUpload");
    expect(intakeStepScreenLabel("/materials")).toBe("上传资料");
    expect(intakeStepKey("/materials/processing")).toBe("materialProcessing");
    expect(intakeStepScreenLabel("/materials/processing")).toBe("资料处理");
  });

  it("未登记路由 fail-loud", () => {
    expect(() => intakeStepKey("/intake/unknown")).toThrow();
  });
});

describe("generationEntryHref", () => {
  it("materials 路径生成入口指向 /materials/processing", () => {
    expect(generationEntryHref(FULL_SCOPE, "materials")).toBe("/materials/processing");
  });

  it("questions 路径生成入口指向 /intake/questions", () => {
    expect(generationEntryHref(FULL_SCOPE, "questions")).toBe("/intake/questions");
  });

  it("未选择填报方式时生成入口兜底为填报方式选择页", () => {
    expect(generationEntryHref(FULL_SCOPE)).toBe("/intake/input-path");
  });

  it("无资料 Agent 时生成入口为议题信息直填页（当前序列末步）", () => {
    expect(generationEntryHref({ ...FULL_SCOPE, materialAgentEnabled: false })).toBe(
      "/intake/questions",
    );
  });
});
