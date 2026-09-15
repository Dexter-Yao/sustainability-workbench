// ABOUTME: 报告核心 API 类型——由后端报告导航、持久化与状态驱动响应合同自动生成，请勿手改。
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
export type SourceLocator =
  | PdfPageLocator
  | DocxParagraphLocator
  | DocxTableLocator
  | XlsxRangeLocator
  | PptxSlideLocator
  | ImageRegionLocator;
export type TraceAvailability = "available" | "unavailable";
export type ProvenanceBasis =
  | "structured_input"
  | "validated_material"
  | "quantitative_metric"
  | "industry_disclosure_context"
  | "deterministic_report_projection"
  | "uploaded_layout_image";
export type GenerationOutcome = "ready" | "omitted" | "not_generated";
export type OmissionCode = "no_supporting_material" | "empty_table";
export type MaterialDispositionCode =
  | "supported"
  | "partially_supported"
  | "context_only"
  | "needs_attention"
  | "not_applicable"
  | "no_decision";
export type GuardrailVerdict = "accepted" | "accepted_after_retry" | "rejected" | "not_evaluated";
export type GuardrailIssueCode =
  | "ai_text_cell_empty"
  | "approximate_number_comma"
  | "empty_output"
  | "empty_variants"
  | "expanded_unit_missing"
  | "incomplete_output"
  | "internal_leak"
  | "internal_path_leak"
  | "metric_narrative_maturity"
  | "missing_display_title"
  | "missing_or_negative_statement"
  | "numeric_range_missing_percent"
  | "output_format"
  | "output_self_numbering"
  | "placeholder_output"
  | "required_cell_empty"
  | "social_sensitive_statement"
  | "table_company_subject"
  | "template_residue"
  | "title_trailing_punctuation"
  | "too_many_paragraphs_without_substantive_input"
  | "unsupported_actual_iro_classification"
  | "unsupported_formal_name"
  | "unsupported_numeric_claim"
  | "unsupported_evidence_gated_fact";
export type EvidenceSelectorKind = "explicit" | "report_section" | "material_gated";
export type EvidenceLevel = "block_facts" | "context_only" | "metric_narrative";
export type PreparationAreaId =
  | "report_identity"
  | "materiality"
  | "quantitative_metrics"
  | "topic_questions"
  | "materials";
export type PreparationAreaStatus = "needs_input" | "optional_empty" | "ready" | "processing" | "needs_attention";
export type ReportGenerationStatus = "queued" | "running" | "succeeded" | "failed" | "superseded";
export type ReportArtifactKind = "word" | "review";
export type StructuredInputStatus = "missing" | "unverified" | "stale" | "current";

/**
 * 仅用于导出一份包含全部核心响应定义的前端运行时 schema。
 */
export interface ReportApiContractBundle {
  report_summary?: ReportSummaryResponse | null;
  report_list?: ReportListResponse | null;
  report_state?: ReportStateResponse | null;
  report_lineage?: ReportLineageProjection | null;
  block_provenance?: ReportBlockProvenanceProjection | null;
  report_preparation?: ReportPreparationProjection | null;
  report_generation?: ReportGenerationProjection | null;
  internal_audit_artifacts?: InternalAuditArtifactListResponse | null;
  put_report_state?: PutReportStateResponse | null;
  assessment_input?: AssessmentInputResponse | null;
  quantitative_metrics?: QuantitativeMetricsResponse | null;
  structured_input_mutation?: StructuredInputMutationResponse | null;
  structured_input_conflict?: StructuredInputConflictResponse | null;
  rewrite_allowance?: RewriteAllowanceResponse | null;
  generation_freshness?: SectionGenerationFreshnessResponse | null;
  module_title_generation?: ModuleTitleGenerationResponse | null;
  report_profile_options?: ReportProfileOptionsResponse | null;
  generation_model_options?: GenerationModelOptionsResponse | null;
}
/**
 * 报告列表与生命周期操作共用的权威摘要。
 */
export interface ReportSummaryResponse {
  id: string;
  title: string;
  report_type: "lightweight";
  report_profile_id: string;
  language: "zh-Hans" | "zh-Hant" | "en";
  data_classification: "synthetic" | "customer";
  created_under_profile_id: string;
  contract_version: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  company_registered_name?: string | null;
}
/**
 * 报告列表响应。
 */
export interface ReportListResponse {
  reports: ReportSummaryResponse[];
}
/**
 * 报告状态快照及其乐观锁序号。
 */
export interface ReportStateResponse {
  state: StoredReportStateV4;
  state_seq: number;
  contract_version: string;
  report_profile_id: string;
  language: "zh-Hans" | "zh-Hant" | "en";
  capabilities: ReportCapabilitiesResponse;
}
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
/**
 * Account 与单份 Report 合并后的实际能力。
 */
export interface ReportCapabilitiesResponse {
  allowed_report_section_ids: string[];
  section_regeneration_limit: number;
  can_generate: boolean;
  can_regenerate_sections: boolean;
  can_export_word: boolean;
  material_agent_enabled: boolean;
  collects_materiality_assessment: boolean;
  allowed_quantitative_metric_keys: string[];
  allowed_report_artifact_kinds: ("word" | "review")[];
}
/**
 * 报告全过程的唯一公共谱系投影；阶段时间线继续由各领域进度 owner 派生。
 */
export interface ReportLineageProjection {
  report_id: string;
  report_state_seq: number;
  edges: ReportLineageEdgeProjection[];
  blocks: ReportLineageBlockProjection[];
}
/**
 * 面向同一报告授权用户的受限谱系边，不暴露内部 trace 或私有对象定位。
 */
export interface ReportLineageEdgeProjection {
  id: string;
  edge_kind:
    | "source_fragment_to_input_resolution"
    | "input_resolution_to_report_input"
    | "source_fragment_to_fact"
    | "fact_to_report_input"
    | "report_input_to_block"
    | "evidence_fact_to_requirement"
    | "requirement_to_gap"
    | "blueprint_to_block"
    | "block_to_claim"
    | "block_to_artifact";
  from_kind: string;
  from_ref: string;
  to_kind: string;
  to_ref: string;
  decision:
    | "candidate"
    | "confirmed"
    | "auto_applied"
    | "held_low_confidence"
    | "blocked_conflict"
    | "invalid"
    | "not_applicable";
  reason_code: string;
  explanation: string;
  status: "active" | "stale" | "superseded";
  source_id?: string | null;
  source_name?: string | null;
  fragment_id?: string | null;
  fragment_locator?: SourceLocator | null;
  report_state_seq?: number | null;
  created_at: string;
}
export interface PdfPageLocator {
  kind?: "pdf_page";
  page: number;
}
export interface DocxParagraphLocator {
  kind?: "docx_paragraph";
  paragraph_index: number;
}
export interface DocxTableLocator {
  kind?: "docx_table";
  table_index: number;
  row_start: number;
  row_end: number;
}
export interface XlsxRangeLocator {
  kind?: "xlsx_range";
  sheet_name: string;
  cell_range: string;
}
export interface PptxSlideLocator {
  kind?: "pptx_slide";
  slide: number;
}
export interface ImageRegionLocator {
  kind?: "image_region";
  region_label?: string;
  x?: number | null;
  y?: number | null;
  width?: number | null;
  height?: number | null;
}
/**
 * 单个报告 Block 的用户可解释摘要；详细边仍由统一列表拥有。
 */
export interface ReportLineageBlockProjection {
  block_id: string;
  status: "linked" | "no_user_provided_content" | "changed_after_generation" | "not_generated";
  source_count: number;
  input_count: number;
  generated_report_state_seq?: number | null;
}
/**
 * Per-block provenance of the latest successfully generated report revision.
 */
export interface ReportBlockProvenanceProjection {
  contract?: "sustainability_desk.block_provenance.v1";
  report_id: string;
  revision: number;
  generated_report_state_seq: number;
  generated_at: string;
  trace_availability: TraceAvailability;
  blocks: BlockProvenanceEntry[];
}
/**
 * User-safe provenance of one report block.
 */
export interface BlockProvenanceEntry {
  block_id: string;
  /**
   * @minItems 1
   */
  basis: [ProvenanceBasis, ...ProvenanceBasis[]];
  generation_outcome: GenerationOutcome;
  omission?: OmissionCode | null;
  material_disposition: MaterialDispositionCode;
  sources: BlockProvenanceSource[];
  intake_items: BlockProvenanceIntakeItem[];
  metrics: BlockProvenanceMetric[];
  attention_note?: boolean;
  generated_content?: Inline[] | null;
  run?: BlockProvenanceRun | null;
}
/**
 * One uploaded file adopted for the block, with the number of FileMaterial units taken from it.
 */
export interface BlockProvenanceSource {
  material_name: string;
  adopted_material_count: number;
}
/**
 * An intake question the block's evidence selector declares, and whether it had a substantive answer.
 */
export interface BlockProvenanceIntakeItem {
  question: string;
  answered: boolean;
}
/**
 * A quantitative metric the block actually consumed and the user actually filled in.
 */
export interface BlockProvenanceMetric {
  metric_name: string;
  value: string;
  unit?: string | null;
}
/**
 * Run facts for one block, projected from the generation trace as counts and codes only.
 */
export interface BlockProvenanceRun {
  stage_status: "succeeded" | "failed";
  attempt_count: number;
  guardrail: GuardrailVerdict;
  guardrail_issue_codes: GuardrailIssueCode[];
  evidence_selector_kind?: EvidenceSelectorKind | null;
  evidence_level?: EvidenceLevel | null;
  intake_fact_count?: number;
  metric_evidence_count?: number;
  prior_disclosure_count?: number;
}
/**
 * 轻量版准备中心唯一公共读模型。
 */
export interface ReportPreparationProjection {
  contract?: "sustainability_desk.report_preparation.v1";
  report_id: string;
  report_state_seq: number;
  generation_eligible: boolean;
  generation_blockers: PreparationBlocker[];
  areas: PreparationArea[];
  report_update_available?: boolean;
  workbench_enabled: boolean;
  primary_input_mode?: ("materials" | "questions") | null;
  assessment_partially_scored?: boolean;
  assessment_scored_topic_count?: number;
  assessment_applicable_topic_count?: number;
}
/**
 * 一项会阻断轻量版首次生成的用户可行动缺失。
 */
export interface PreparationBlocker {
  target_handle: string;
  label: string;
  message: string;
  href: string;
}
/**
 * 准备中心一个输入域的用户友好状态。
 */
export interface PreparationArea {
  id: PreparationAreaId;
  title: string;
  href: string;
  required_for_generation: boolean;
  status: PreparationAreaStatus;
  summary: string;
  action_label: string;
}
/**
 * 创建响应、轮询进度和交付页共用的报告级运行投影。
 */
export interface ReportGenerationProjection {
  contract?: "sustainability_desk.report_generation.v1";
  run_id: string;
  report_id: string;
  status: ReportGenerationStatus;
  base_report_state_seq: number;
  result_report_state_seq?: number | null;
  completed_block_count: number;
  total_block_count: number;
  summary: string;
  started_at?: string | null;
  events: ReportGenerationEvent[];
  artifacts: ReportArtifactProjection[];
  workbench_enabled: boolean;
}
/**
 * 同一运行记录派生的用户友好增量说明。
 */
export interface ReportGenerationEvent {
  sequence: number;
  event_type:
    | "queued"
    | "started"
    | "block_started"
    | "block_completed"
    | "report_saved"
    | "artifacts_ready"
    | "export_blocked"
    | "failed"
    | "superseded";
  message: string;
  current_object?: string | null;
  action_required?: boolean;
  occurred_at: string;
}
/**
 * 客户可下载的交付物句柄；内部审计包不会对普通客户开放下载。
 */
export interface ReportArtifactProjection {
  artifact_id: string;
  kind: ReportArtifactKind;
  filename: string;
  media_type: string;
  download_href: string;
}
export interface InternalAuditArtifactListResponse {
  artifacts: InternalAuditArtifactResponse[];
}
/**
 * 内部审计权限持有者的跨 Account 交付物定位投影。
 */
export interface InternalAuditArtifactResponse {
  artifact_id: string;
  report_id: string;
  report_title: string;
  account_email: string;
  filename: string;
  created_at: string;
  download_href: string;
}
/**
 * 成功持久化后的新状态序号。
 */
export interface PutReportStateResponse {
  state_seq: number;
}
/**
 * 当前报告的重要性目录、权威输入及 scoped freshness。
 */
export interface AssessmentInputResponse {
  status: StructuredInputStatus;
  state_seq: number;
  contract_version: string;
  context_fingerprint: string;
  score_scale: AssessmentScoreScale;
  topics: AssessmentCatalogTopicResponse[];
  current: MaterialityAssessmentInput | null;
  resolved: ResolvedAssessmentResponse | null;
  readiness: LightweightReportReadiness;
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
 * 由议题 Registry 与当前报告适用性共同投影的可评分议题。
 */
export interface AssessmentCatalogTopicResponse {
  assessmentTopicId: string;
  name: string;
  dimension: string;
  order: number;
  reportSectionId: string;
}
/**
 * 由 assessmentInput 与 Registry 现算的唯一展示结果。
 */
export interface ResolvedAssessmentResponse {
  reportingYear: number;
  threshold: MaterialityThreshold | null;
  counts: AssessmentCounts;
  topics: ResolvedAssessmentTopicResponse[];
}
export interface AssessmentCounts {
  dual?: number;
  impact_only?: number;
  financial_only?: number;
  non_material?: number;
  total?: number;
}
/**
 * 权威 resolved materiality 的可展示议题投影；固定议题不伪造分数。
 */
export interface ResolvedAssessmentTopicResponse {
  assessmentTopicId: string;
  name: string;
  dimension: string;
  order: number;
  reportSectionId: string | null;
  determination: "scored" | "fixed";
  materiality: "dual" | "impact" | "financial" | "non";
  financialScore?: number | null;
  impactScore?: number | null;
}
export interface LightweightReportReadiness {
  stages: LightweightReadinessStage[];
  issues: LightweightReadinessIssue[];
  readyForWorkbench: boolean;
  firstIncompleteStageId?:
    | ("report_configuration" | "assessment_scoring" | "quantitative_metrics" | "workbench_entry")
    | null;
  firstIncompleteHref?: string | null;
}
export interface LightweightReadinessStage {
  id: "report_configuration" | "assessment_scoring" | "quantitative_metrics" | "workbench_entry";
  label: string;
  actionHref: string;
  complete: boolean;
  issueCount: number;
  inputStatus: StructuredInputStatus;
}
export interface LightweightReadinessIssue {
  code: string;
  message: string;
  stageId: "report_configuration" | "assessment_scoring" | "quantitative_metrics" | "workbench_entry";
  actionHref: string;
  fieldKey?: string | null;
  path?: string | null;
  assessmentTopicId?: string | null;
  metricKey?: string | null;
}
/**
 * 当前报告的完整指标目录、权威输入及 scoped freshness。
 */
export interface QuantitativeMetricsResponse {
  status: StructuredInputStatus;
  state_seq: number;
  contract_version: string;
  context_fingerprint: string;
  catalog: QuantitativeMetricDef[];
  greenhouse_gas_accounting_standard_options: string[];
  no_value_reasons: string[];
  current: QuantitativeMetricsMeta;
  readiness: LightweightReportReadiness;
}
export interface QuantitativeMetricDef {
  key: string;
  sheet: string;
  kpiCode?: string | null;
  category: string;
  groupPath: string[];
  metricLabel: string;
  standaloneLabel?: string | null;
  unit: string;
  sumOfMetricKeys: string[];
  requiresGreenhouseGasAccountingStandard?: boolean;
  metricDefinition?: string;
  termExplanation?: string;
}
/**
 * 结构化输入原子写成功后的完整权威状态，不要求客户端拼接局部结果。
 */
export interface StructuredInputMutationResponse {
  state: StoredReportStateV4;
  state_seq: number;
  contract_version: string;
  readiness: LightweightReportReadiness;
}
/**
 * 409 冲突时返回当前权威快照，客户端只能重载而不能猜测合并。
 */
export interface StructuredInputConflictResponse {
  code?: "report_state_conflict";
  message: string;
  current: StructuredInputMutationResponse;
}
/**
 * 指定报告页面的服务端权威重写额度。
 */
export interface RewriteAllowanceResponse {
  section_key: string;
  quota: number;
  used: number;
  remaining: number;
}
/**
 * 当前模型可见输入与最近成功生成输入的比较结果。
 */
export interface SectionGenerationFreshnessResponse {
  status: "not_generated" | "fresh" | "stale";
  current_input_fingerprint: string;
  generated_input_fingerprint?: string | null;
}
/**
 * 报告模块标题原子写回后的公共响应。
 */
export interface ModuleTitleGenerationResponse {
  section_titles: {
    [k: string]: SectionDisplayTitle;
  };
  state_seq: number;
}
/**
 * 建报可选配置清单与服务端默认项。
 */
export interface ReportProfileOptionsResponse {
  profiles: ReportProfileOption[];
  default_report_profile_id: string;
}
/**
 * 建报时可选的一项报告配置：一个知识包（准则 × 语言）的产品化投影。
 *
 * 只暴露选择所需的事实。Profile 的能力字段（工作台开关、生成必填字段、合成数据要求）
 * 是服务端裁决依据，不进客户端——客户端按 id 请求，不自行解释能力。
 */
export interface ReportProfileOption {
  report_profile_id: string;
  display_name: string;
  language: "zh-Hans" | "zh-Hant" | "en";
}
/**
 * 当前环境可选的生成模型清单与服务端默认项。
 *
 * 清单只含凭据齐备者：列出一个点下去才失败的选项，等于把配置错误推迟到生成现场。
 */
export interface GenerationModelOptionsResponse {
  models: GenerationModelOption[];
  default_model_id: string;
}
/**
 * 一次生成可选的模型。
 *
 * 只暴露选择所需的事实：稳定 id 与服务商标识。**部署名与端点、密钥环境变量名
 * 一律不进客户端**——部署名是私有基础设施事实（如某资源上的具体部署），
 * 泄漏它既无助于选择，也把服务端拓扑写进了界面。
 */
export interface GenerationModelOption {
  model_id: string;
  vendor: string;
}
