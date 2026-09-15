// ABOUTME: 前端 schema 类型——由后端 Pydantic Report 模型经 report.schema.json 自动生成，请勿手改。
// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。

export type FieldType = "string" | "number" | "year" | "month" | "date" | "email" | "percent" | "url" | "enum";
export type Source = "template" | "user_input" | "derived" | "user_doc" | "assessment" | "ai";
export type RequiredBefore = "workbench" | "generation" | "export";
export type InputDefaultRule = "previous_calendar_year" | "reporting_year_start" | "reporting_year_end";
export type BlockState = "pending" | "generating" | "ready" | "locked" | "failed" | "omitted";
export type Materiality = "dual" | "impact" | "financial" | "non";
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
export type Pillar = "governance" | "strategy" | "iro_management" | "metrics_targets";
export type NodeType = "paragraph" | "table" | "image";
export type BlockType = "fixed" | "slot" | "constrained" | "generative";
export type GenerationEvidenceSelector =
  | ExplicitGenerationEvidenceSelector
  | ReportSectionGenerationEvidenceSelector
  | MaterialGatedGenerationEvidenceSelector;
export type QuantitativeNoValueReason = "not_collected" | "not_available" | "not_applicable" | "will_supplement";

export interface Report {
  title: string;
  fields: {
    [k: string]: Field;
  };
  inputGuidance?: {
    [k: string]: InputGuidance;
  } | null;
  intakeItems: IntakeItem[];
  assessmentScoreScale?: AssessmentScoreScale | null;
  assessmentVocabulary?: AssessmentVocabulary | null;
  quantitativeMetricsVocabulary?: QuantitativeMetricsVocabulary | null;
  assessmentInput?: MaterialityAssessmentInput | null;
  assessment?: AssessmentResult | null;
  disclosureProfile?: DisclosureProfile | null;
  appendixPackage?: AppendixPackage;
  stakeholderEngagement?: StakeholderEngagementProfile | null;
  sections: Section[];
  meta?: ReportMeta | null;
  knowledgePackageId?: string | null;
}
export interface Field {
  key: string;
  label: string;
  type: FieldType;
  source: Source;
  value?: string | number | null;
  required?: boolean;
  requiredBefore?: RequiredBefore | null;
  options?: string[] | null;
  computed?: {
    [k: string]: unknown;
  } | null;
  appears_when?: Condition | null;
}
export interface Condition {
  all?: ConditionRule[] | null;
  any?: ConditionRule[] | null;
}
export interface ConditionRule {
  path: string;
  op: "eq" | "ne" | "exists" | "not_exists" | "gt" | "in" | "contains_any";
  value?: unknown;
}
/**
 * 用户填写体验合同：说明文字与新建报告默认规则，不承载模型或生成约束。
 *
 * helpText 与 termExplanation 是同一输入项面向用户的两段受控投影，按 design.md §2.2.1
 * 的归位判据分工：helpText 承载「填对这一项所必需的」（填什么/怎么填/条件依赖/直接后果），
 * 常驻页面；termExplanation 承载术语解释与准则背景，折进 ⓘ。两段都直接写给用户看，
 * 不得使用「用户……」这类第三人称或作者视角措辞。
 *
 * 三段皆可缺省：标签已自明的输入项不写 helpText——复述标签只是让用户多读一行而得不到
 * 新信息（design.md §2.2.1）。条目可仅为 defaultRule 或 termExplanation 而存在。
 */
export interface InputGuidance {
  helpText?: string | null;
  termExplanation?: string | null;
  defaultRule?: InputDefaultRule | null;
}
/**
 * 内容清单项（SSOT §3.B）：分议题内容清单的一道题 + 用户答案（定义与答案合一，仿 Field）。
 *
 * 模板态 answer 为空，实例 Report 才带 answer；结构化答案为真相源，文本化仅在 build_model_context。
 */
export interface IntakeItem {
  key: string;
  contentScopeId: string;
  prompt: string;
  kind: "text" | "single_select" | "multi_select";
  options?: string[] | null;
  generationOptionLabels?: {
    [k: string]: string;
  } | null;
  optionGroups?: IntakeOptionGroup[] | null;
  hint?: string | null;
  termExplanation?: string | null;
  generationBoundary?: string | null;
  minChars?: number | null;
  maxChars?: number | null;
  collectionPriority?: "core" | "recommended" | "optional";
  requiredBefore?: RequiredBefore | null;
  answer?: string | string[] | null;
  supplement?: string | null;
}
/**
 * 内容清单选择题选项分组；用于同一道题内表达分组最小选择要求。
 */
export interface IntakeOptionGroup {
  key: string;
  label: string;
  options: string[];
  minSelections?: number;
}
/**
 * 双重重要性原始评分尺度：模板声明，导入、录入和 Report 校验共同使用。
 */
export interface AssessmentScoreScale {
  minimumExclusive: number;
  maximum: number;
  multipleOf: number;
  financialMaterialityDefinition?: string;
  financialMaterialityExplanation?: string;
  impactMaterialityDefinition?: string;
  impactMaterialityExplanation?: string;
}
/**
 * Display vocabulary of the materiality assessment, owned by the package contract.
 *
 * Materiality categories, matrix axis names, IRO kinds and impact classes are rendered into
 * tables, charts and model context from here; code branches on the typed slots, never on the words.
 */
export interface AssessmentVocabulary {
  materiality: MaterialityLabels;
  materialityAxes: MaterialityAxisLabels;
  iroKind: IroKindLabels;
  impactClass: ImpactClassLabels;
}
export interface MaterialityLabels {
  dual: string;
  impact: string;
  financial: string;
  non: string;
}
export interface MaterialityAxisLabels {
  financial: string;
  impact: string;
}
export interface IroKindLabels {
  impact: string;
  risk: string;
  opportunity: string;
  risk_opportunity: string;
}
export interface ImpactClassLabels {
  actual_positive: string;
  potential_positive: string;
  potential_negative: string;
}
/**
 * Package-owned wording of the quantitative metrics table that is validated or printed.
 *
 * The greenhouse gas accounting standard is a controlled choice: the option list and the "other"
 * sentinel must exist in the package's language, so they are contract data rather than code.
 */
export interface QuantitativeMetricsVocabulary {
  greenhouseGasAccountingStandards: string[];
  otherStandardLabel: string;
  accountingStandardRemarkTemplate: string;
  remarkSeparator: string;
  noValueReasonLabels: {
    [k: string]: string;
  };
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
export interface AssessmentResult {
  reportingYear: number;
  topics: (ScoredAssessmentResult | FixedAssessmentResult)[];
  threshold?: MaterialityThreshold | null;
}
export interface ScoredAssessmentResult {
  assessmentTopicId: string;
  determination?: "scored";
  materiality: Materiality;
  financialScore: number;
  impactScore: number;
  iroItems?: IROItem[] | null;
}
export interface FixedAssessmentResult {
  assessmentTopicId: string;
  determination?: "fixed";
  materiality: Materiality;
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
export interface Section {
  key: string;
  title: string;
  titleContent?: Inline[] | null;
  displayTitle?: SectionDisplayTitle | null;
  titleGeneration?: SectionTitleGeneration | null;
  headingLevel?: 1 | 2 | 3 | 4;
  pillar?: Pillar | null;
  reportModuleId?: string | null;
  required?: boolean;
  standardRef?: string | null;
  appears_when?: Condition | null;
  reportSectionId?: string | null;
  conciseDisclosure?: Block | null;
  blocks: Block[];
  children?: Section[] | null;
}
export interface Inline {
  kind: "text" | "ref";
  text?: string | null;
  ref?: string | null;
  fallback?: string | null;
  marks?: Mark[] | null;
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
 * H4 标题生产者声明；标题与其直属段落正文由同一次调用返回。
 */
export interface SectionTitleGeneration {
  sourceBlockId: string;
  guidance: string;
}
export interface Block {
  id: string;
  type: NodeType;
  blockType: BlockType;
  source: Source;
  state?: BlockState | null;
  styleRole?: string | null;
  content?: Inline[] | null;
  footnote?: Inline[] | null;
  table?: GsTable | null;
  image?: ImageModel | null;
  generation?: GenerationSpec | null;
  appears_when?: Condition | null;
  placeholderNotice?: string | null;
  required?: boolean;
  recommended?: boolean;
  listType?: ("ordered" | "unordered") | null;
}
/**
 * 表格 = Plate table 节点形态（table/tr/td/th + 合并 colSpan/rowSpan）+ 业务属性（列规格/受控值/行态）。前后端共用一套：前端渲染受控单元格、Report 直接作真相，后端据此 LLM 生成 / 校验 / 导出。
 */
export interface GsTable {
  type?: "table";
  colDefs: GsColDef[];
  caption?: string | null;
  disclaimer?: string | null;
  firstColumnNarrow?: boolean;
  layoutProfile?: "risk_response_matrix" | null;
  iroKind?: ("risk" | "opportunity" | "risk_and_opportunity") | null;
  columnWidthWeights?: {
    [k: string]: number;
  } | null;
  rowSource?: "user" | "assessment_topics" | "assessment_iro" | "stakeholder_engagement" | "certificate_facts";
  children: GsTableRow[];
}
/**
 * 表格列规格：挂在 GsTable.colDefs（整列共享）；单元格经 colKey 引用其类型/选项/生成指引。
 */
export interface GsColDef {
  key: string;
  header: string;
  cellType?: "text" | "single_select" | "multi_select" | "ai_text";
  options?: string[] | null;
  required?: boolean;
  genHint?: string | null;
  presetFullCoverage?: boolean;
  subjectTerm?: "company" | null;
}
/**
 * 行 = Plate tr 节点 + 业务属性。
 */
export interface GsTableRow {
  type?: "tr";
  headerRow?: boolean;
  state?: BlockState | null;
  origin?: RowOrigin | null;
  generation?: GenerationSpec | null;
  appears_when?: Condition | null;
  children: GsTableCell[];
}
/**
 * AI 定行的 RowSeed 复现快照：单行重生成据此还原 seed（SSOT §3.C/§8）。from 区分 AI 定行 / 用户加行。
 */
export interface RowOrigin {
  from?: "ai" | "user";
  theme?: string | null;
  category?: string | null;
  driver_hint?: string | null;
}
/**
 * 模型生成合同；任务、证据与输出约束均须显式声明。
 */
export interface GenerationSpec {
  task: GenerationTask;
  inputs?: GenerationInputs;
  templateResidueBans?: string[] | null;
  evidenceGatedFacts?: string[] | null;
  targetChars?: [unknown, unknown] | null;
  rowCount?: [unknown, unknown] | null;
  fixedRowSeeds?: FixedRowSeed[] | null;
  presetRowSelection?: PresetRowSelection | null;
  referenceCatalog?: CatalogReference[] | null;
  rowExpansion?: RowExpansion | null;
  rowMode?: ("preset_catalog" | "adaptive_catalog" | "expanded_rows") | null;
  producesConclusion?: "topic_iro" | null;
  standardDisclosureRequirementKeys?: string[] | null;
  simplifiedWritingGuidance?: string[] | null;
  disclosureStance?: "standard" | "risk_disclosure";
}
/**
 * 生成块的唯一任务合同；不从正文占位或块类型反向推断。
 */
export interface GenerationTask {
  mode?: "standard" | "metric_narrative";
  focus: string;
  noFactGuidance?: string | null;
}
/**
 * 生成输入合同：证据选择与额外主体字段分离，不允许未消费的配置静默通过。
 */
export interface GenerationInputs {
  evidence: GenerationEvidenceSelector;
  fields?: string[];
}
/**
 * 显式证据选择器：生成块只读取声明的内容清单项和定量指标。
 */
export interface ExplicitGenerationEvidenceSelector {
  kind: "explicit";
  intakeItems?: string[];
  quantitativeMetrics?: string[];
}
/**
 * 报告章节证据选择器：摘要块继承所属 H2 的用户输入与指标目录。
 */
export interface ReportSectionGenerationEvidenceSelector {
  kind: "report_section";
}
/**
 * 证据门控选择器：块的存在性由证据判定，缺证据时整块受控省略而非方向性生成。
 *
 * 判定为「或」语义：Mapping 判定 supported/partially_supported 的文件资料，或声明的
 * intakeItems 中存在实质答案，任一满足块即出具；两者皆无时生成编排直接置
 * ``state="omitted"``，随 renderability 从正文与目录消失。纯材料门控是
 * intakeItems 为空的退化形态。
 */
export interface MaterialGatedGenerationEvidenceSelector {
  kind: "material_gated";
  intakeItems?: string[];
}
/**
 * 固定表格行种子：用于由契约声明表格行主题，生成链只补全文本内容。
 *
 * preset_catalog 表：theme=行名称锚点、category=类型（并发分组键）、referenceImpact=该行潜在影响参考口径
 * （仅供模型参考改写、不照抄，不作为正文预设）。
 */
export interface FixedRowSeed {
  theme: string;
  category?: string | null;
  driver_hint?: string | null;
  referenceImpact?: string | null;
}
/**
 * preset_catalog 行显隐合同：由结构化内容清单选择确定可生成的固定行。
 */
export interface PresetRowSelection {
  intakeItemKey: string;
  selectionMode?: "selected_only";
  unansweredBehavior?: "hide_all_rows" | "show_all_rows";
}
/**
 * adaptive_catalog 的典型参考条目：仅供前置一步据企业业务取舍/补充生成适用锚点，不强制、不作正文预设。
 *
 * category=分组类型（并发分组键，如风险/机遇）、name=条目名称、reference=典型内容/影响参考口径（供参照改写、不照抄）。
 * 与 FixedRowSeed（preset_catalog 的固定行锚点）是两个不同概念：一为参考、一为固定。
 */
export interface CatalogReference {
  category: string;
  name: string;
  reference?: string | null;
}
/**
 * 把一个业务行展开成多个披露子行的契约声明（如 IRO 表每议题＝影响行 + 风险机遇行）。
 *
 * sharedColumnKeys 每业务行只填一次、跨子行 rowSpan 合并；units 有序，顺序即表内子行顺序。
 * 与 preset_catalog 的「多业务行归一分组」方向相反，故为独立 rowMode，不复用锚点列序约定。
 */
export interface RowExpansion {
  sharedColumnKeys: string[];
  units: RowExpansionUnit[];
}
/**
 * 一个业务行内的一个披露子行：绑定本子行独占填写的列，并可在列级 options 内收窄候选。
 *
 * key 进结构化输出 schema 作字段名（不进 prompt）；label 是模型可见的子行名称（如「影响描述」）。
 */
export interface RowExpansionUnit {
  key: string;
  label: string;
  columnKeys: string[];
  optionsNarrowing?: {
    [k: string]: string[];
  } | null;
  genHintOverride?: {
    [k: string]: string;
  } | null;
}
/**
 * 单元格 = Plate td/th 节点 + 业务属性。受控值存 value（保结构化类型）；options 可在单元格级覆盖列级（如 IRO 影响行/风险机遇行选项不同）。
 */
export interface GsTableCell {
  type?: "td" | "th";
  colKey?: string | null;
  value?: string | string[] | null;
  options?: string[] | null;
  colSpan?: number;
  rowSpan?: number;
  cellState?: BlockState | null;
  children?: {
    [k: string]: unknown;
  }[];
}
export interface ImageModel {
  caption?: string | null;
  placeholder?: string | null;
  derivedVisualization?: DerivedVisualizationSpec | null;
  evidenceAssetId?: string | null;
  layoutAssetSlot?: boolean;
  layoutAssetIds?: string[] | null;
}
/**
 * 由结构化 Report 数据确定性派生的可视化规格；模型不生成可视化正文。
 */
export interface DerivedVisualizationSpec {
  kind: "quantitative_metric_summary";
  metricKeys: string[];
  featuredMetricKeys?: string[] | null;
  displayMode?: "auto" | "highlight_cards" | "compact_cards" | "summary_table";
  groupBy?: "category" | "groupPath" | "none";
  emptyBehavior?: "hide" | "placeholder";
}
/**
 * Report.meta 的 typed 契约，承载定量数据与重要性组织策略。
 */
export interface ReportMeta {
  quantitativeMetrics?: QuantitativeMetricsMeta;
  materialityStrategy?: "complete_coverage" | null;
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
