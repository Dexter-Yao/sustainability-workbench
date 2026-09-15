// ABOUTME: 矩阵预览纯函数回归：增量预览分类与后端 assessment_classify 同源（边界值守护），
// ABOUTME: 空态画布常驻（四象限底色 + 阈值十字 + 提示），不因零散点退场。
// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { classifyPreviewMateriality, MaterialityMatrix } from "./matrix";

const THRESHOLD = { financial: 4, impact: 4 };

describe("classifyPreviewMateriality（与后端 classify_materiality 同源）", () => {
  it("四象限归属：阈值上沿为重要（>=）", () => {
    expect(classifyPreviewMateriality(4.5, 4.5, THRESHOLD)).toBe("dual");
    expect(classifyPreviewMateriality(4.5, 3, THRESHOLD)).toBe("financial");
    expect(classifyPreviewMateriality(3, 4.5, THRESHOLD)).toBe("impact");
    expect(classifyPreviewMateriality(3, 3, THRESHOLD)).toBe("non");
  });

  it("恰等于阈值判为重要（与后端一致）", () => {
    expect(classifyPreviewMateriality(4, 4, THRESHOLD)).toBe("dual");
    expect(classifyPreviewMateriality(4, 2, THRESHOLD)).toBe("financial");
    expect(classifyPreviewMateriality(2, 4, THRESHOLD)).toBe("impact");
  });

  it("阈值调整即时改变归属", () => {
    expect(classifyPreviewMateriality(3.5, 3.5, THRESHOLD)).toBe("non");
    expect(classifyPreviewMateriality(3.5, 3.5, { financial: 3, impact: 3 })).toBe("dual");
  });
});

describe("矩阵空态画布", () => {
  it("零散点仍绘制四象限底色、阈值十字与空态提示", () => {
    const html = renderToStaticMarkup(
      <MaterialityMatrix axisLabels={{ financial: "财务重要性", impact: "影响重要性" }} topics={[]} threshold={THRESHOLD} scoreMax={5} />,
    );
    expect(html).toContain('role="img"');
    for (const materiality of ["dual", "financial", "impact", "non"]) {
      expect(html, `缺少 ${materiality} 象限底色`).toContain(`data-quadrant="${materiality}"`);
    }
    expect(html).toContain("完成议题评分后，议题将实时落入对应象限");
  });
});
