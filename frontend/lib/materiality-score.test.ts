// ABOUTME: 双重重要性评分前端投影测试，锁定模板尺度的开闭区间与小数精度。
// ABOUTME: 后端导入与上游输入另有同尺度验证；此处只覆盖浏览器提交前的解析边界。
import { describe, expect, it } from "vitest";
import { zhHans } from "./i18n/zh-Hans";

import { materialityScoreGuidance, materialityScoreStep, parseMaterialityScore, type AssessmentScoreScale } from "./materiality-score";

const scale: AssessmentScoreScale = { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 };

describe("materiality score", () => {
  it("仅接受 (0, 5] 内且最多一位小数的评分", () => {
    expect(parseMaterialityScore("0.1", scale)).toBe(0.1);
    expect(parseMaterialityScore("3.5", scale)).toBe(3.5);
    expect(parseMaterialityScore("5", scale)).toBe(5);
    expect(parseMaterialityScore("0", scale)).toBeNull();
    expect(parseMaterialityScore("-0.5", scale)).toBeNull();
    expect(parseMaterialityScore("5.1", scale)).toBeNull();
    expect(parseMaterialityScore("3.55", scale)).toBeNull();
  });

  it("从模板尺度派生输入步长与用户说明", () => {
    expect(materialityScoreStep(scale)).toBe(0.1);
    expect(materialityScoreGuidance(scale, zhHans)).toBe("评分须大于 0 且小于等于 5；最多保留 1 位小数。");
  });
});
