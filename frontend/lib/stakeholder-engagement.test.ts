// ABOUTME: 利益相关方 Profile 前端解析与不可变编辑测试，确保标签操作不产生第二份表格事实。
// ABOUTME: 覆盖多对多、受控方式、自定义方式和缺失议题诊断，不涉及模型或行业推断。
import { describe, expect, it } from "vitest";

import type { StakeholderEngagementProfile } from "./schema";
import {
  addCustomStakeholderMethod,
  missingStakeholderTopicIds,
  orderedStakeholderMethodLabels,
  orderedStakeholderTopicLabels,
  parseStakeholderEngagementProfile,
  removeCustomStakeholderMethod,
  toggleStakeholderMethod,
  toggleStakeholderTopic,
} from "./stakeholder-engagement";

function profile(): StakeholderEngagementProfile {
  return {
    scopeAssessmentTopicIds: ["climate_change", "technology_ethics"],
    entries: [
      { stakeholderType: "government_regulators", assessmentTopicIds: ["climate_change"], methodIds: ["regulatory_communication"], customMethods: [] },
      { stakeholderType: "shareholders_investors", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "customers", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "management", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "employees", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "suppliers", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "partners", assessmentTopicIds: [], methodIds: [], customMethods: [] },
      { stakeholderType: "community_public", assessmentTopicIds: [], methodIds: [], customMethods: [] },
    ],
  };
}

describe("stakeholder engagement profile", () => {
  it("同一议题可跨多个利益相关方选择，并准确报告未覆盖议题", () => {
    const base = profile();
    const withManagement = toggleStakeholderTopic(base, "management", "climate_change");
    const complete = toggleStakeholderTopic(withManagement, "partners", "technology_ethics");

    expect(base.entries[3].assessmentTopicIds).toEqual([]);
    expect(complete.entries[0].assessmentTopicIds).toContain("climate_change");
    expect(complete.entries[3].assessmentTopicIds).toContain("climate_change");
    expect(missingStakeholderTopicIds(complete)).toEqual([]);
  });

  it("方式只能用于目录允许的对象，自定义方式按类别去重并可删除", () => {
    const base = profile();
    expect(toggleStakeholderMethod(base, "suppliers", "industry_exchange")).toBe(base);

    const selected = toggleStakeholderMethod(base, "partners", "industry_exchange");
    const custom = addCustomStakeholderMethod(selected, "partners", { kind: "collaboration_activity", label: "  区域协作计划  " });
    const duplicate = addCustomStakeholderMethod(custom, "partners", { kind: "collaboration_activity", label: "区域协作计划" });
    expect(duplicate.entries[6].methodIds).toContain("industry_exchange");
    expect(duplicate.entries[6].customMethods).toEqual([{ kind: "collaboration_activity", label: "区域协作计划" }]);

    const removed = removeCustomStakeholderMethod(duplicate, "partners", { kind: "collaboration_activity", label: "区域协作计划" });
    expect(removed.entries[6].customMethods).toEqual([]);
  });

  it("快照解析拒绝对象顺序、未知议题或错误方式归属", () => {
    const valid = profile();
    expect(parseStakeholderEngagementProfile(valid)).toEqual(valid);

    const wrongOrder = structuredClone(valid);
    [wrongOrder.entries[0], wrongOrder.entries[1]] = [wrongOrder.entries[1], wrongOrder.entries[0]];
    expect(parseStakeholderEngagementProfile(wrongOrder)).toBeUndefined();

    const unknownTopic = structuredClone(valid);
    unknownTopic.entries[0].assessmentTopicIds.push("unknown_topic");
    expect(parseStakeholderEngagementProfile(unknownTopic)).toBeUndefined();

    const wrongMethod = structuredClone(valid);
    wrongMethod.entries[5].methodIds.push("industry_exchange");
    expect(parseStakeholderEngagementProfile(wrongMethod)).toBeUndefined();
  });

  it("投影按议题目录和方式类别排序，受控方式先于同类自定义方式", () => {
    expect(orderedStakeholderTopicLabels(["technology_ethics", "climate_change"])).toEqual([
      "应对气候变化",
      "科技伦理",
    ]);
    expect(orderedStakeholderMethodLabels({
      stakeholderType: "partners",
      assessmentTopicIds: [],
      methodIds: ["project_cooperation", "industry_exchange", "joint_working_group"],
      customMethods: [{ kind: "participation_mechanism", label: "区域议事机制" }],
    })).toEqual(["行业交流", "联合工作组", "区域议事机制", "项目合作"]);
  });
});
