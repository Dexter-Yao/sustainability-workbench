// ABOUTME: 定量信息整批提交载荷构造纯逻辑测试：留空项记为默认无数值原因。
import { describe, expect, it } from "vitest";

import { buildMetricsPayload, isAnswered } from "./draft-metrics";
import type { QuantitativeMetricDef } from "@/lib/report-api.generated";

function metric(key: string): QuantitativeMetricDef {
  return {
    key,
    sheet: "环境",
    category: "能源",
    groupPath: [],
    metricLabel: key,
    standaloneLabel: null,
    unit: "吨",
    requiresGreenhouseGasAccountingStandard: false,
    metricDefinition: "",
    termExplanation: "",
  } as unknown as QuantitativeMetricDef;
}

describe("isAnswered", () => {
  it("空字符串或 undefined 视为未填", () => {
    expect(isAnswered(undefined)).toBe(false);
    expect(isAnswered({ value: "" })).toBe(false);
    expect(isAnswered({ value: "  " })).toBe(false);
  });

  it("非空 value 视为已填", () => {
    expect(isAnswered({ value: "12" })).toBe(true);
  });
});

describe("buildMetricsPayload", () => {
  const identity = (v: string) => v;

  it("catalog 内每一项都出现在结果中", () => {
    const catalog = [metric("a"), metric("b")];
    const payload = buildMetricsPayload(catalog, {}, identity);
    expect(Object.keys(payload)).toEqual(["a", "b"]);
  });

  it("留空项记为默认无数值原因，已有 noValueReason 保留", () => {
    const catalog = [metric("a"), metric("b")];
    const payload = buildMetricsPayload(
      catalog,
      { b: { noValueReason: "not_applicable" } },
      identity,
    );
    expect(payload.a).toEqual({ value: null, noValueReason: "not_collected", department: null, note: null });
    expect(payload.b).toEqual({ value: null, noValueReason: "not_applicable", department: null, note: null });
  });

  it("已填值项 noValueReason 置空，department/note 去除首尾空白", () => {
    const catalog = [metric("a")];
    const payload = buildMetricsPayload(
      catalog,
      { a: { value: "12", noValueReason: "not_collected", department: "  财务部  ", note: " 备注 " } },
      identity,
    );
    expect(payload.a).toEqual({ value: "12", noValueReason: null, department: "财务部", note: "备注" });
  });
});
