// ABOUTME: 基本信息页二级结构的唯一事实源：区块（二级标题）的 id、标题与必填/选填义务。
// ABOUTME: 页面 SectionTitle 标记与左栏步骤导航的二级条目同源于此；义务是合同静态事实，不随报告状态变化。

import type { Report } from "./schema";

export interface IntakeInfoSection {
  id: string;
  title: string;
  obligation: "required" | "optional";
  /** 该区块存在的前提字段；报告所属知识包未声明该字段时整块不出现。 */
  requiresField?: string;
}

/** 区块顺序即页面渲染顺序；锚点 id 与页面 section 元素一致。 */
export const INTAKE_INFO_SECTIONS: readonly IntakeInfoSection[] = [
  { id: "section-company-subject", title: "公司主体", obligation: "required" },
  { id: "section-company-profile", title: "公司简介", obligation: "required" },
  { id: "section-reporting-period", title: "报告期", obligation: "required" },
  { id: "section-disclosure-profile", title: "披露准则", obligation: "required" },
  {
    id: "section-applicable-scope",
    title: "适用范围",
    obligation: "required",
    // 科技伦理适用性只有内地包声明；港交所守则没有这一项，整块随之不出现——
    // 否则该包会显示一个标着「必填」却没有任何输入的空区块，用户永远填不完。
    requiresField: "has_technology_ethics_sensitive_activity",
  },
  { id: "section-optional-supplement", title: "选填补充", obligation: "optional" },
];

/** 本报告实际呈现的区块：前提字段未被该报告的知识包声明时整块退场。 */
export function visibleIntakeInfoSections(report: Report): readonly IntakeInfoSection[] {
  return INTAKE_INFO_SECTIONS.filter(
    (section) => !section.requiresField || section.requiresField in (report.fields ?? {}),
  );
}
