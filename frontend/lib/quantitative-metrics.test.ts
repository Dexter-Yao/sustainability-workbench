// ABOUTME: ESG 定量信息收集写回测试，锁定内部采集数据与正式附录表的边界。
// ABOUTME: 页面可保存采集部门等内部信息，但导出的附录表只保留对外 KPI 字段。
import { describe, expect, it } from "vitest";

import {
  APPENDIX_METRICS_BLOCK_ID,
  hasQuantitativeMetricValue,
  derivedSumValue,
  isDerivedSumMetric,
  projectQuantitativeMetricRows,
  standaloneMetricLabel,
  updateGreenhouseGasAccountingStandard,
  updateQuantitativeMetricDraft,
} from "./quantitative-metrics";
import type { QuantitativeMetricDef } from "./api";
import type { GsTableRow, Report } from "./schema";

const GHG_SCOPE_ONE_METRIC: QuantitativeMetricDef = {
  key: "economic_environment_r04",
  sheet: "经济+环境",
  category: "应对气候变化",
  groupPath: ["应对气候变化", "碳排放"],
  metricLabel: "范围一：温室气体排放总量",
  unit: "吨二氧化碳当量",
  sumOfMetricKeys: [],
  requiresGreenhouseGasAccountingStandard: true,
  metricDefinition: "",
  termExplanation: "",
};

function appendixReport(): Report {
  return {
    title: "测试报告",
    fields: {},
    intakeItems: [],
    sections: [
      {
        key: "report_appendix",
        title: "附录",
        headingLevel: 1,
        blocks: [
          {
            id: APPENDIX_METRICS_BLOCK_ID,
            type: "table",
            blockType: "fixed",
            source: "template",
            table: {
              colDefs: [
                { key: "category", header: "指标层级" },
                { key: "metric", header: "指标名称" },
                { key: "unit", header: "单位" },
                { key: "value", header: "报告年度数值" },
                { key: "remark", header: "备注" },
              ],
              children: [
                {
                  headerRow: true,
                  children: [
                    { type: "th", value: "指标层级" },
                    { type: "th", value: "指标名称" },
                    { type: "th", value: "单位" },
                    { type: "th", value: "报告年度数值" },
                    { type: "th", value: "备注" },
                  ],
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

function firstDataRow(report: Report): GsTableRow {
  const row = report.sections[0].blocks[0].table?.children.find((item) => !item.headerRow);
  if (!row) throw new Error("missing data row");
  return row;
}

function cellValue(row: GsTableRow, colKey: string): string {
  const value = row.children.find((cell) => cell.colKey === colKey)?.value;
  return typeof value === "string" ? value : "";
}

describe("quantitative metrics", () => {
  const GHG_TOTAL_METRIC: QuantitativeMetricDef = {
    ...GHG_SCOPE_ONE_METRIC,
    key: "economic_environment_r07",
    metricLabel: "温室气体排放总量",
    standaloneLabel: "温室气体排放总量（范围一+范围二）",
    sumOfMetricKeys: ["economic_environment_r04", "economic_environment_r05"],
  };

  it("求和派生指标由目录声明识别，不硬编码 key", () => {
    expect(isDerivedSumMetric(GHG_TOTAL_METRIC)).toBe(true);
    expect(isDerivedSumMetric(GHG_SCOPE_ONE_METRIC)).toBe(false);
  });

  it("来源填齐才产出派生值，缺一项则保持无值", () => {
    expect(derivedSumValue(GHG_TOTAL_METRIC, {
      economic_environment_r04: { value: "200" },
      economic_environment_r05: { value: "300" },
    })).toBe("500");
    expect(derivedSumValue(GHG_TOTAL_METRIC, {
      economic_environment_r04: { value: "200" },
    })).toBeNull();
  });

  it("派生值恒为纯十进制——服务端只接受该形态，科学计数法会让整批保存 422", () => {
    // 派生值不经 finalizeDecimalDraft 复核，addDecimalStrings 是它进入载荷前的唯一收敛点。
    const strict = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
    const cases: Array<[string, string, string]> = [
      ["200", "2000", "2200"],
      ["0.1", "0.2", "0.3"],
      // 旧实现 String(total / factor) 在此产出 "3e-7" / "3e-8"，被服务端拒收。
      ["0.0000001", "0.0000002", "0.0000003"],
      ["0.00000001", "0.00000002", "0.00000003"],
      ["1.005", "2.005", "3.01"],
      // 旧实现经 Number() 丢精度得 ...680；BigInt 定点保住末位。
      ["123456789012345678", "1", "123456789012345679"],
      ["1.50", "2.50", "4"],
      ["-1.5", "2.5", "1"],
    ];
    for (const [scopeOne, scopeTwo, expected] of cases) {
      const total = derivedSumValue(GHG_TOTAL_METRIC, {
        economic_environment_r04: { value: scopeOne },
        economic_environment_r05: { value: scopeTwo },
      });
      expect(total, `${scopeOne}+${scopeTwo}`).toBe(expected);
      expect(strict.test(total!), `${scopeOne}+${scopeTwo} -> ${total}`).toBe(true);
    }
  });

  it("十进制求和不引入二进制浮点误差", () => {
    expect(derivedSumValue(GHG_TOTAL_METRIC, {
      economic_environment_r04: { value: "0.1" },
      economic_environment_r05: { value: "0.2" },
    })).toBe("0.3");
  });

  it("脱离 Excel 层级展示时使用完整指标名称", () => {
    expect(standaloneMetricLabel({
      ...GHG_SCOPE_ONE_METRIC,
      metricLabel: "境内",
      standaloneLabel: "已授权专利项目数（境内）",
    })).toBe("已授权专利项目数（境内）");
  });

  it("空值不算填写，零值与普通数值均算填写", () => {
    const metrics = [GHG_SCOPE_ONE_METRIC];
    const base = appendixReport();
    const withZero = updateQuantitativeMetricDraft(
      base,
      GHG_SCOPE_ONE_METRIC,
      { value: "0" },
      metrics,
    );

    expect(hasQuantitativeMetricValue(base, GHG_SCOPE_ONE_METRIC.key)).toBe(false);
    expect(hasQuantitativeMetricValue(withZero, GHG_SCOPE_ONE_METRIC.key)).toBe(true);
  });

  it("写回正式附录表时不导出内部采集部门和 Excel 填写说明", () => {
    const visibleMetrics = [GHG_SCOPE_ONE_METRIC];
    const withStandard = updateGreenhouseGasAccountingStandard(
      appendixReport(),
      "《温室气体核算体系》（GHG Protocol）",
      visibleMetrics,
    );
    const next = updateQuantitativeMetricDraft(
      withStandard,
      GHG_SCOPE_ONE_METRIC,
      { value: "12.5", department: "运营部", note: "按厂区边界统计" },
      visibleMetrics,
    );

    expect(next.meta?.quantitativeMetrics).toMatchObject({
      metrics: { [GHG_SCOPE_ONE_METRIC.key]: { department: "运营部" } },
    });
    const row = firstDataRow(next);
    expect(cellValue(row, "metric")).toBe("范围一：温室气体排放总量");
    expect(cellValue(row, "value")).toBe("12.5");
    expect(cellValue(row, "remark")).toBe("核算标准：《温室气体核算体系》（GHG Protocol）；按厂区边界统计");
    expect(JSON.stringify(row)).not.toContain("运营部");
    expect(JSON.stringify(row)).not.toContain("仅轻量版");
  });

  it("未填写报告年度数值的指标不写入正式附录表", () => {
    const next = projectQuantitativeMetricRows(appendixReport(), [GHG_SCOPE_ONE_METRIC]);

    expect(next.sections[0].blocks[0].table?.children.filter((row) => !row.headerRow)).toEqual([]);
  });

  it("清空指标草稿后删除该指标 key", () => {
    const filled = updateQuantitativeMetricDraft(
      appendixReport(),
      GHG_SCOPE_ONE_METRIC,
      { value: "0" },
      [GHG_SCOPE_ONE_METRIC],
    );
    const cleared = updateQuantitativeMetricDraft(
      filled,
      GHG_SCOPE_ONE_METRIC,
      { value: "" },
      [GHG_SCOPE_ONE_METRIC],
    );

    expect(filled.meta?.quantitativeMetrics?.metrics[GHG_SCOPE_ONE_METRIC.key]?.value).toBe("0");
    expect(cleared.meta?.quantitativeMetrics?.metrics[GHG_SCOPE_ONE_METRIC.key]).toBeUndefined();
  });
});
