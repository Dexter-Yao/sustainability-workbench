// ABOUTME: 新建报告可用性的回归：名额已满必须禁用并说明去删除，空列表态不得例外。
// ABOUTME: 空列表态与有数据态共用同一判定，这里钉住结论本身，两处渲染都消费它。
import { describe, expect, it } from "vitest";

import { zhHans } from "./i18n/zh-Hans";

import { reportCreateAvailability } from "./report-create-availability";

const ready = {
  creating: false,
  accountLoading: false,
  activeReportCount: 0,
  activeReportLimit: 1,
  canCreateReport: true,
} as const;

describe("reportCreateAvailability", () => {
  it("名额未满时可新建", () => {
    expect(reportCreateAvailability(ready, zhHans)).toEqual({ disabled: false, reason: "" });
  });

  it("名额已满时禁用，并告诉用户删除后可新建", () => {
    // limit=1 时，若空列表态的按钮不判名额，而名额由可见列表算出：服务端已有一份
    // 未能打开的报告时列表仍为空，按钮永远可点、永远 403，用户无从自救。
    const result = reportCreateAvailability({ ...ready, activeReportCount: 1 }, zhHans);

    expect(result.disabled).toBe(true);
    expect(result.reason).toContain("上限");
    expect(result.reason).toContain("删除");
    // 名额数字必须进文案：只说「已达上限」而不说几份，用户无从判断删几份才够。
    expect(result.reason).toContain("1 / 1");
  });

  it("上限为 null 表示不设名额，不因报告多而禁用", () => {
    const result = reportCreateAvailability(
      {
        ...ready,
        activeReportCount: 9,
        activeReportLimit: null,
      },
      zhHans,
    );

    expect(result.disabled).toBe(false);
  });

  it("账户能力未到达时禁用且不谎称名额已满", () => {
    const result = reportCreateAvailability(
      {
        ...ready,
        accountLoading: true,
        canCreateReport: undefined,
      },
      zhHans,
    );

    expect(result.disabled).toBe(true);
    expect(result.reason).toBe(zhHans.reportList.accountLoading);
  });

  it("账户无创建许可时给出账户级原因", () => {
    const result = reportCreateAvailability({ ...ready, canCreateReport: false }, zhHans);

    expect(result.disabled).toBe(true);
    expect(result.reason).toBe(zhHans.reportList.createBlockedNoPermission);
  });

  it("名额已满优先于账户许可缺失——用户能自己解决的原因先说", () => {
    const result = reportCreateAvailability(
      {
        ...ready,
        activeReportCount: 1,
        canCreateReport: false,
      },
      zhHans,
    );

    expect(result.reason).toContain("删除");
  });
});
