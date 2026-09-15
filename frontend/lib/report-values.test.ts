// ABOUTME: 报告级结构化事实解析测试，保护披露准则与附录路径在前端显示层一致。
// ABOUTME: 只验证确定性派生，不测试后端诊断或导出。
import { describe, expect, it } from "vitest";

import { reportRefLabel, resolveReportRef, selectedStandardNamesText } from "./report-values";
import type { Report } from "./schema";

const report: Report = {
  title: "t",
  fields: {},
  intakeItems: [],
  disclosureProfile: {
    mainlandStandard: "bse",
    includesHongKongExchangeGuide: true,
    additionalDisclosureReferences: ["《企业可持续披露准则——基本准则（试行）》"],
  },
  appendixPackage: {
    externalAssuranceReport: { isIncluded: false, fileLabel: null },
    readerFeedbackContactInformation: { address: "addr", email: "esg@example.com", phone: "0577" },
  },
  sections: [],
};

describe("report values", () => {
  it("从 DisclosureProfile 派生准则展示文本", () => {
    const text = selectedStandardNamesText(report);
    expect(text).toContain("北京证券交易所");
    expect(text).toContain("香港联合交易所有限公司");
    expect(text).toContain("企业可持续披露准则");
  });

  it("解析 appendixPackage 引用路径", () => {
    expect(resolveReportRef("appendixPackage.readerFeedbackContactInformation.email", report)).toBe("esg@example.com");
  });

  it("空引用以业务名称占位，不泄露内部路径", () => {
    expect(reportRefLabel("appendixPackage.readerFeedbackContactInformation.email", report)).toBe("读者反馈邮箱");
    expect(reportRefLabel("assessment.topics.internal_key", report)).toBe("待填写信息");
  });
});
