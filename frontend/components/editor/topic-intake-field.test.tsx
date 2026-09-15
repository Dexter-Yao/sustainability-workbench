// ABOUTME: 议题内容清单字段控件的渲染回归:optionGroups 分组约束必须对用户可见。
// ABOUTME: mock app-context 边界,控件本体真实渲染;覆盖分组标签、最少选择数提示与未分组回退。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IntakeItem } from "@/lib/schema";

const setReport = vi.fn();
vi.mock("@/lib/app-context", () => ({
  useApp: () => ({ setReport }),
}));

import { TopicIntakeField } from "@/components/editor/topic-intake-field";

function riskItem(answer: string[] | null = null): IntakeItem {
  return {
    key: "climate.q_climate_risk_choices",
    prompt: "您认为以下哪些气候相关风险会对公司产生影响？",
    kind: "multi_select",
    options: ["台风", "暴雨", "碳定价与排放监管政策变化"],
    optionGroups: [
      { key: "physical_risk", label: "物理风险", minSelections: 1, options: ["台风", "暴雨"] },
      { key: "transition_risk", label: "转型风险", minSelections: 1, options: ["碳定价与排放监管政策变化"] },
    ],
    answer,
  } as IntakeItem;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TopicIntakeField optionGroups", () => {
  it("按组渲染选项并显示最少选择数约束", () => {
    render(<TopicIntakeField item={riskItem()} />);
    expect(screen.getByText("物理风险")).toBeTruthy();
    expect(screen.getByText("转型风险")).toBeTruthy();
    expect(screen.getAllByText("至少选择 1 项")).toHaveLength(2);
    expect(screen.getByLabelText("台风")).toBeTruthy();
    expect(screen.getByLabelText("碳定价与排放监管政策变化")).toBeTruthy();
  });

  it("勾选选项经 setReport 回写答案", () => {
    render(<TopicIntakeField item={riskItem()} />);
    fireEvent.click(screen.getByLabelText("台风"));
    expect(setReport).toHaveBeenCalledTimes(1);
  });

  it("无 optionGroups 时保持扁平清单", () => {
    const flat = {
      key: "climate.q_climate_opportunity_choices",
      prompt: "机遇",
      kind: "multi_select",
      options: ["资源效率提升", "低碳产品与服务"],
      answer: null,
    } as IntakeItem;
    render(<TopicIntakeField item={flat} />);
    expect(screen.queryByText("至少选择 1 项")).toBeNull();
    expect(screen.getByLabelText("资源效率提升")).toBeTruthy();
  });
});
