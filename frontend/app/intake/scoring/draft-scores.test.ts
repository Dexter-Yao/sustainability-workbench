// ABOUTME: 重要性识别页 draftScores 过滤纯逻辑测试：只提交两维都已填且解析通过的行。
import { describe, expect, it } from "vitest";

import { draftScores } from "./draft-scores";

const SCALE = { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 };

function topics(ids: string[]) {
  return ids.map((id) => ({
    assessmentTopicId: id,
    name: id,
    dimension: "E",
    order: 0,
    reportSectionId: null as unknown as string,
  }));
}

describe("draftScores", () => {
  it("input 为空时返回空数组", () => {
    expect(draftScores(null, {})).toEqual([]);
  });

  it("只提交两维都已填且解析通过的行", () => {
    const input = { topics: topics(["a", "b", "c"]), score_scale: SCALE };
    const draft = {
      a: { financial: "4", impact: "4.5" },
      b: { financial: "3", impact: "" },
      c: { financial: "", impact: "" },
    };

    expect(draftScores(input, draft)).toEqual([
      { assessmentTopicId: "a", financialScore: 4, impactScore: 4.5 },
    ]);
  });

  it("非法数值（超出量表）被视为未填，行被排除", () => {
    const input = { topics: topics(["a"]), score_scale: SCALE };
    const draft = { a: { financial: "99", impact: "4" } };

    expect(draftScores(input, draft)).toEqual([]);
  });

  it("空草稿返回空数组", () => {
    const input = { topics: topics(["a", "b"]), score_scale: SCALE };
    expect(draftScores(input, {})).toEqual([]);
  });
});
