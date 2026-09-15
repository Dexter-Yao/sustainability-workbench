// ABOUTME: 报告状态快照类型——由后端 StoredReportStateV4 严格领域合同自动生成，请勿手改。
// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。

export type BlockState = "pending" | "generating" | "ready" | "locked" | "failed" | "omitted";
export type QuantitativeNoValueReason = "not_collected" | "not_available" | "not_applicable" | "will_supplement";
export type PrimaryInputMode = "materials" | "questions";
export type StakeholderType =
  | "government_regulators"
  | "shareholders_investors"
  | "customers"
  | "management"
  | "employees"
  | "suppliers"
  | "partners"
  | "community_public";
export type EngagementMethodKind = "communication_channel" | "participation_mechanism" | "collaboration_activity";
export type Mark = "bold" | "italic" | "underline";

/**
 * V4 严格状态边界；不接受旧缺失策略，未完成输入交由 readiness 处理。
 */
export interface StoredReportStateV4 {
  version: 4;
  fields: {
    [k: string]: string | number | null;
  };
  intakeItems: {
    [k: string]: StoredIntakeAnswer;
  };
  assessmentInput?: MaterialityAssessmentInput | null;
  disclosureProfile?: DisclosureProfile | null;
  appendixPackage?: AppendixPackage | null;
  meta?: StoredReportMetaV4 | null;
  stakeholderEngagement?: StakeholderEngagementProfile | null;
  sectionTitles: {
    [k: string]: SectionDisplayTitle;
  };
  generatedBlocks: {
    [k: string]: StoredGeneratedBlock;
  };
  tableBlocks: {
    [k: string]: StoredTableBlock;
  };
  imageBlocks: {
    [k: string]: StoredImageBlock;
  };
  structuredInputFreshness?: StructuredInputFreshness;
  companyBusinessSummary?: StoredCompanyBusinessSummary | null;
}
/**
 * 用户答案快照项：只保留实例答案，不接受题目结构。
 */
export interface StoredIntakeAnswer {
  answer?: string | string[] | null;
  supplement?: string | null;
}
/**
 * 重要性评估的持久化输入；固定分类与计数均不在此重复保存。
 */
export interface MaterialityAssessmentInput {
  reportingYear: number;
  threshold: MaterialityThreshold;
  scores: MaterialityScoreInput[];
}
export interface MaterialityThreshold {
  financial: number;
  impact: number;
}
/**
 * 用户为一个 scored 评分议题提供的原始双重重要性输入。
 */
export interface MaterialityScoreInput {
  assessmentTopicId: string;
  financialScore: number;
  impactScore: number;
  iroItems?: IROItem[] | null;
}
export interface IROItem {
  kind: "impact" | "risk" | "opportunity";
  description?: string | null;
  classes?: string[] | null;
  valueChain?: string[] | null;
  timeHorizon?: string[] | null;
  state?: BlockState | null;
}
/**
 * 报告级披露配置（SSOT §3.D）：大陆准则单选，港交所与其他文件为附加参考。
 */
export interface DisclosureProfile {
  mainlandStandard?: "sse" | "szse" | "bse";
  includesHongKongExchangeGuide?: boolean;
  additionalDisclosureReferences: string[];
}
/**
 * 附录事实包：独立于议题与前四章正文，供附录章节、诊断与导出使用。
 */
export interface AppendixPackage {
  externalAssuranceReport?: ExternalAssuranceReport;
  readerFeedbackContactInformation?: ReaderFeedbackContactInformation;
}
/**
 * 外部鉴证报告附件事实：只记录是否纳入及对外展示标签。
 */
export interface ExternalAssuranceReport {
  isIncluded?: boolean;
  fileLabel?: string | null;
}
/**
 * 读者反馈固定文本所需联系方式。
 */
export interface ReaderFeedbackContactInformation {
  address?: string | null;
  email?: string | null;
  phone?: string | null;
}
/**
 * V4 报告级状态；缺失处置由输入义务与 Block 合同拥有。
 */
export interface StoredReportMetaV4 {
  quantitativeMetrics?: QuantitativeMetricsMeta;
  materialityStrategy?: "complete_coverage" | null;
  primaryInputMode?: PrimaryInputMode | null;
}
/**
 * ESG 定量数据表的受控形状：指标草稿字典 + 温室气体核算标准。
 */
export interface QuantitativeMetricsMeta {
  metrics: {
    [k: string]: QuantitativeMetricDraft;
  };
  greenhouseGasAccountingStandard?: string | null;
  greenhouseGasAccountingStandardOther?: string | null;
}
/**
 * 单个 ESG 定量指标的用户填写值（report.meta.quantitativeMetrics.metrics 的元素）；形状受控。
 */
export interface QuantitativeMetricDraft {
  value?: string | null;
  noValueReason?: QuantitativeNoValueReason | null;
  department?: string | null;
  note?: string | null;
}
/**
 * 利益相关方沟通的 parse-first 真相；表格、诊断与 Word 均由此确定性投影。
 */
export interface StakeholderEngagementProfile {
  scopeAssessmentTopicIds: string[];
  entries: StakeholderEngagementEntry[];
}
/**
 * 一类稳定利益相关方对应的适用议题与沟通方式引用。
 */
export interface StakeholderEngagementEntry {
  stakeholderType: StakeholderType;
  assessmentTopicIds: string[];
  methodIds: string[];
  customMethods: CustomEngagementMethod[];
}
/**
 * 用户补充的沟通、参与或合作方式；类别用于确定性排序，正文只呈现 label。
 */
export interface CustomEngagementMethod {
  kind: EngagementMethodKind;
  label: string;
}
/**
 * 章节的实例级用户可见标题；稳定导航标题仍由 Section.title 拥有。
 */
export interface SectionDisplayTitle {
  text: string;
  origin: "generated" | "user";
  inputFingerprint: string;
}
/**
 * 生成段落快照项：仅允许正文与生命周期状态。
 */
export interface StoredGeneratedBlock {
  content?: Inline[] | null;
  state?: BlockState | null;
}
export interface Inline {
  kind: "text" | "ref";
  text?: string | null;
  ref?: string | null;
  fallback?: string | null;
  marks?: Mark[] | null;
}
/**
 * 表格实例快照项：表头和列合同仍由运行时模板提供。
 *
 * ``state="omitted"`` 与空行共同表示本轮没有足以形成数据行的用户资料；
 * 该处置是报告状态的一部分，不能由导出器临时猜测。
 */
export interface StoredTableBlock {
  children: StoredTableRow[];
  state?: BlockState | null;
}
/**
 * 表格用户行快照：结构、generation 与 appears_when 均由运行时模板拥有。
 */
export interface StoredTableRow {
  type?: "tr";
  headerRow?: boolean;
  state?: BlockState | null;
  origin?: StoredRowOrigin | null;
  children: StoredTableCell[];
}
/**
 * AI 定行的可重生成事实；不包含行级生成规格。
 */
export interface StoredRowOrigin {
  from?: "ai" | "user";
  theme?: string | null;
  category?: string | null;
  driver_hint?: string | null;
}
/**
 * 表格单元格快照：保留用户值，不接受 Plate 文本骨架或列合同。
 */
export interface StoredTableCell {
  type?: "td" | "th";
  colKey?: string | null;
  value?: string | string[] | null;
  options?: string[] | null;
  colSpan?: number;
  rowSpan?: number;
  cellState?: BlockState | null;
}
/**
 * 素材图片承载位快照项：仅保存按序放置的资产引用，题注与替代文本归资产 owner。
 */
export interface StoredImageBlock {
  layoutAssetIds: string[];
  state?: "ready";
}
/**
 * V4 只保存最近一次成功导入所对应的上下文，不复制工作簿内容。
 */
export interface StructuredInputFreshness {
  assessmentContextFingerprint?: string | null;
  quantitativeMetricsContextFingerprint?: string | null;
}
/**
 * 公司业务摘要快照项：派生值与其来源指纹同体保存。
 *
 * 指纹取自压缩来源 `company_profile`；来源变化即摘要过期，须重算。
 * 值与指纹分开保存会让两者可能不一致，故合为一项。
 */
export interface StoredCompanyBusinessSummary {
  text: string;
  sourceFingerprint: string;
}
