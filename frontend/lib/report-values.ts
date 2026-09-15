// ABOUTME: 报告级结构化事实的前端派生与引用解析，镜像后端 contract/report_values.py。
// ABOUTME: 仅从 Report 读取展示值，不维护副本，不参与 prompt 拼装。
import { selectedStandardNames } from "./disclosure-basis";
import { listSeparatorFor, reportLanguageFor } from "./package-language";
import type { Report } from "./schema";

const REPORT_REF_LABELS: Record<string, string> = {
  "disclosureProfile.basisStatement": "报告编制依据",
  "disclosureProfile.selectedStandardNames": "适用披露准则",
  "appendixPackage.externalAssuranceReport.fileLabel": "外部鉴证报告文件",
  "appendixPackage.readerFeedbackContactInformation.address": "读者反馈通信地址",
  "appendixPackage.readerFeedbackContactInformation.email": "读者反馈邮箱",
  "appendixPackage.readerFeedbackContactInformation.phone": "读者反馈电话",
  "assessment.counts.dual": "双重重要性议题数量",
  "assessment.counts.impact_only": "影响重要性议题数量",
  "assessment.counts.financial_only": "财务重要性议题数量",
  "assessment.counts.non_material": "非重要性议题数量",
  "assessment.applicableTopicCount": "本报告披露议题数量",
};

export function selectedStandardNamesText(report: Report): string {
  return selectedStandardNames(report).join(listSeparatorFor(report.knowledgePackageId));
}

export function disclosureBasisStatement(report: Report): string {
  return selectedStandardNamesText(report);
}

function appendixValue(path: string, report: Report): unknown {
  const pkg = report.appendixPackage;
  if (path === "appendixPackage.externalAssuranceReport.isIncluded") return pkg?.externalAssuranceReport?.isIncluded ?? false;
  if (path === "appendixPackage.externalAssuranceReport.fileLabel") {
    return pkg?.externalAssuranceReport?.fileLabel ?? null;
  }
  if (path === "appendixPackage.readerFeedbackContactInformation.address") return pkg?.readerFeedbackContactInformation?.address ?? null;
  if (path === "appendixPackage.readerFeedbackContactInformation.email") return pkg?.readerFeedbackContactInformation?.email ?? null;
  if (path === "appendixPackage.readerFeedbackContactInformation.phone") return pkg?.readerFeedbackContactInformation?.phone ?? null;
  return null;
}

function disclosureValue(path: string, report: Report): unknown {
  const profile = report.disclosureProfile;
  if (path === "disclosureProfile.mainlandStandard") return profile?.mainlandStandard ?? "sse";
  if (path === "disclosureProfile.includesHongKongExchangeGuide") return profile?.includesHongKongExchangeGuide ?? false;
  if (path === "disclosureProfile.additionalDisclosureReferences") return profile?.additionalDisclosureReferences ?? [];
  if (path === "disclosureProfile.selectedStandardNames") return selectedStandardNamesText(report);
  if (path === "disclosureProfile.basisStatement") return disclosureBasisStatement(report);
  return null;
}

export function resolveReportRef(ref: string | null | undefined, report: Report): unknown {
  if (!ref) return null;
  if (ref.startsWith("disclosureProfile.")) return disclosureValue(ref, report);
  if (ref.startsWith("appendixPackage.")) return appendixValue(ref, report);
  // assessment.* 由 report-document/document-nodes 的 assessmentValue 现算：议题范围是
  // 知识包属性（上交所 24 个、港交所 16 个），任何前端基数都必然对某个包写错。
  return report.fields[ref]?.value ?? null;
}

/** 报告正文中的空引用使用业务名称占位，绝不把内部路径暴露给用户。 */
export function reportRefLabel(ref: string | null | undefined, report: Report): string {
  if (!ref) return "待填写信息";
  return report.fields[ref]?.label ?? REPORT_REF_LABELS[ref] ?? "待填写信息";
}

/**
 * 报告正文里的引用显示值。
 *
 * 分隔符与布尔字面量都随报告所属知识包的语言：英文正文里的「A、B」与「是」是中文标点和
 * 中文词，不是英文报告该有的形态。
 */
export function reportValueToText(value: unknown, report: Report): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item).trim())
      .filter(Boolean)
      .join(listSeparatorFor(report.knowledgePackageId));
  }
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "boolean") return booleanText(value, report);
  return String(value);
}

/** 布尔字段在正文中的显示词，按报告所属包的语言。 */
function booleanText(value: boolean, report: Report): string {
  const language = reportLanguageFor(report.knowledgePackageId);
  if (language === "en") return value ? "Yes" : "No";
  if (language === "zh-Hant") return value ? "是" : "否";
  return value ? "是" : "否";
}
