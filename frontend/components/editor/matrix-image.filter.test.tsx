// ABOUTME: MatrixImage 视图过滤回归：全分类隐藏时占位不发请求；过滤参数透传后端渲染。
// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const fetchMatrixImage = vi.fn<(...args: unknown[]) => Promise<never>>();
fetchMatrixImage.mockRejectedValue(new Error("no network in test"));
vi.mock("@/lib/api", () => ({ fetchMatrixImage: (...args: unknown[]) => fetchMatrixImage(...args) }));

import { MatrixImage } from "./matrix-image";
import type { AssessmentResult } from "@/lib/schema";

const assessment: AssessmentResult = {
  reportingYear: 2026,
  threshold: { financial: 4, impact: 4 },
  topics: [
    { assessmentTopicId: "t1", determination: "scored", materiality: "dual", financialScore: 4.5, impactScore: 4.5 },
    { assessmentTopicId: "t4", determination: "scored", materiality: "non", financialScore: 2, impactScore: 2 },
  ],
};

afterEach(() => {
  cleanup();
  fetchMatrixImage.mockClear();
});

it("全分类隐藏时占位且不发请求", () => {
  render(<MatrixImage assessment={assessment} visibleMaterialities={[]} />);
  expect(screen.getByText(/已隐藏全部分类/)).toBeTruthy();
  expect(fetchMatrixImage).not.toHaveBeenCalled();
});

it("过滤参数透传后端渲染", async () => {
  render(<MatrixImage assessment={assessment} visibleMaterialities={["dual"]} />);
  await waitFor(() => expect(fetchMatrixImage).toHaveBeenCalledWith(assessment, ["dual"]));
});
