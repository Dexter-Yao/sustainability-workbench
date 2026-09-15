// ABOUTME: 资料工作区 API 类型——由后端 Pydantic 公共投影合同自动生成，请勿手改。
// ABOUTME: 重新生成：后端 python -m sustainability_desk.material.intake.schema_export，前端 npm run gen:schema。

export type MaterialSourceStatus =
  | "uploading"
  | "queued"
  | "processing"
  | "ready"
  | "needs_attention"
  | "failed"
  | "deleted";
export type SourceLocator =
  | PdfPageLocator
  | DocxParagraphLocator
  | DocxTableLocator
  | XlsxRangeLocator
  | PptxSlideLocator
  | ImageRegionLocator;
export type MaterialSourceReviewPosture = "reviewed_accepted" | "excluded_by_user";
export type AssertionBasis = "material_evidence" | "user_assertion";
export type ProposalStatus = "proposed" | "accepted" | "rejected" | "applied" | "stale";
export type MaterialFactStatus = "candidate" | "confirmed" | "conflicted" | "rejected" | "stale";
export type MaterialFactConfirmationMethod = "deterministic" | "user";
export type PrimaryInputMode = "materials" | "questions";
export type MaterialIngressStatus = "accepted" | "reused" | "rejected";
export type MaterialIngressReasonCode =
  | "admitted"
  | "duplicate_reused"
  | "duplicate_declaration_conflict"
  | "binding_removed"
  | "file_rejected"
  | "storage_failed"
  | "upload_failed";
export type ReportFileRole = "semantic_material" | "layout_asset";
export type MaterialKind = "pdf" | "docx" | "xlsx" | "pptx" | "png" | "jpeg" | "webp";

/**
 * 前端生成类型使用的资料 API 合同集合；不作为业务请求载荷。
 */
export interface MaterialApiContracts {
  workspace: MaterialWorkspaceProjection;
  source_content: MaterialSourceContentProjection;
  file_declaration: UserFileDeclaration;
  report_file_intake: ReportFileIntakeProjection;
}
export interface MaterialWorkspaceProjection {
  id: string;
  report_id: string;
  adapter_id: string;
  contract_version: string;
  state_seq: number;
  projection_seq: number;
  report_state_seq: number;
  sources: MaterialSourceProjection[];
  messages: MaterialMessageProjection[];
  clarifications: MaterialClarificationProjection[];
  proposals: MaterialProposalProjection[];
  facts: MaterialFactProjection[];
  gaps: MaterialGapProjection[];
  topic_primary_input_modes: {
    [k: string]: PrimaryInputMode;
  };
  report_primary_input_mode?: PrimaryInputMode | null;
  scope_summaries: MaterialScopeSummaryProjection[];
  ingress_receipts?: MaterialIngressReceipt[];
}
export interface MaterialSourceProjection {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  scope: MaterialScopeProjection;
  content_availability: "available" | "not_extracted";
  status: MaterialSourceStatus;
  error_stage?: string | null;
  error_message?: string | null;
  error_next_action?: string | null;
  can_retry: boolean;
  parse_result: MaterialParseResultProjection;
  normalized_material_fingerprint?: string | null;
  normalized_material?: NormalizedMaterialProjection | null;
  processing_steps: MaterialProcessingStepProjection[];
  current_review_decision?: MaterialSourceReviewProjection | null;
  created_at: string;
  updated_at: string;
}
export interface MaterialScopeProjection {
  kind: "profile" | "topics" | "uncertain" | "report";
  report_section_ids: string[];
}
/**
 * 单份资料的脱敏 parse-first 结果摘要，不携带清洗正文或对象路径。
 */
export interface MaterialParseResultProjection {
  status: "not_started" | "available" | "failed";
  fragment_count: number;
  fragment_kinds: ("text" | "table" | "image_observation")[];
  summary: string;
}
export interface NormalizedMaterialProjection {
  segments: NormalizedSegmentProjection[];
  review_markdown: string;
  quality_flags: string[];
}
export interface NormalizedSegmentProjection {
  id: string;
  kind: "text" | "table" | "image_observation";
  locator: SourceLocator;
  text?: string | null;
  markdown?: string | null;
  quality_flags: string[];
}
export interface PdfPageLocator {
  kind: "pdf_page";
  page: number;
}
export interface DocxParagraphLocator {
  kind: "docx_paragraph";
  paragraph_index: number;
}
export interface DocxTableLocator {
  kind: "docx_table";
  table_index: number;
  row_start: number;
  row_end: number;
}
export interface XlsxRangeLocator {
  kind: "xlsx_range";
  sheet_name: string;
  cell_range: string;
}
export interface PptxSlideLocator {
  kind?: "pptx_slide";
  slide: number;
}
export interface ImageRegionLocator {
  kind: "image_region";
  region_label?: string;
  x?: number | null;
  y?: number | null;
  width?: number | null;
  height?: number | null;
}
export interface MaterialProcessingStepProjection {
  id: string;
  stage: string;
  method?: string | null;
  model?: string | null;
  route?: string | null;
  status: string;
  quality_flags: string[];
  created_at: string;
}
/**
 * 客户安全的当前复核结果；内部身份、指纹和操作员理由不出边界。
 */
export interface MaterialSourceReviewProjection {
  decision: MaterialSourceReviewPosture;
  reason?: string | null;
}
export interface MaterialMessageProjection {
  id: string;
  role: "user" | "assistant";
  content: string;
  scope_id: string;
  created_at: string;
}
export interface MaterialClarificationProjection {
  id: string;
  scope_id: string;
  question: string;
  options: ClarificationOptionProjection[];
  allow_free_text: boolean;
  status: "open" | "answered" | "dismissed";
  answer?: string | null;
  created_at: string;
}
export interface ClarificationOptionProjection {
  value: string;
  label: string;
  description?: string | null;
}
export interface MaterialProposalProjection {
  id: string;
  scope_id: string;
  report_section_id?: string | null;
  target_key: string;
  target_label: string;
  target_kind: "text" | "single_select" | "multi_select";
  target_options: string[];
  target_option_groups: MaterialOptionGroupProjection[];
  question?: string | null;
  current_answer?: string | string[] | null;
  current_supplement?: string | null;
  proposed_answer: string | string[];
  proposed_supplement?: string | null;
  basis: AssertionBasis;
  explanation: string;
  evidence_refs: MaterialEvidenceProjection[];
  fact_claim_ids: string[];
  processing_summary: string;
  status: ProposalStatus;
  stale_reason?: string | null;
  target_value_fingerprint: string;
}
export interface MaterialOptionGroupProjection {
  key: string;
  label: string;
  options: string[];
  min_selections: number;
}
export interface MaterialEvidenceProjection {
  source_id: string;
  source_name: string;
  segment_id: string;
  locator: SourceLocator;
  excerpt?: string | null;
}
export interface MaterialFactProjection {
  id: string;
  semantic_key: string;
  label: string;
  scope_id: string;
  report_section_id?: string | null;
  value: string | string[];
  supplement?: string | null;
  effective_period?: string | null;
  rationale: string;
  basis: AssertionBasis;
  evidence_refs: MaterialEvidenceProjection[];
  status: MaterialFactStatus;
  confirmation_method?: MaterialFactConfirmationMethod | null;
  version: number;
  stale_reason?: string | null;
}
export interface MaterialGapProjection {
  id: string;
  scope_id: string;
  report_section_id?: string | null;
  kind: "missing" | "conflict" | "unparseable" | "needs_judgment";
  title: string;
  description: string;
  source_ids: string[];
  status: "open" | "resolved" | "dismissed" | "stale";
}
export interface MaterialScopeSummaryProjection {
  scope_id: string;
  label: string;
  report_section_id?: string | null;
  source_count: number;
  ready_count: number;
  pending_proposal_count: number;
  accepted_proposal_count: number;
  gap_count: number;
}
/**
 * 由准入事实和当前 Source 状态派生的人类可见收据。
 */
export interface MaterialIngressReceipt {
  receipt_id?: string;
  batch_id: string;
  filename: string;
  status: MaterialIngressStatus;
  reason_code: MaterialIngressReasonCode;
  source_id?: string | null;
  sha256?: string | null;
  message: string;
  next_action: string;
}
export interface MaterialSourceContentProjection {
  source_id: string;
  normalized_material: NormalizedMaterialProjection | null;
}
/**
 * 用户对一份原文件的权威说明，不推断资料是否最终被报告采用。
 *
 * description 与 layout_asset 的 asset_title 允许为空串，表示用户选择先上传、
 * 后补充说明；一旦非空，仍必须满足 10–140 字（说明）或 1–140 字（素材标题）的
 * 权威长度约束。空说明不是故障态，是"待补充"这一合法用户分支。
 */
export interface UserFileDeclaration {
  description: string;
  role: ReportFileRole;
  /**
   * @minItems 1
   * @maxItems 24
   */
  topic_tags: [string, ...string[]];
  asset_title?: string | null;
}
/**
 * 报告准备中心的文件准入 SSOT 投影。
 */
export interface ReportFileIntakeProjection {
  report_id: string;
  projection_seq: number;
  policy: ReportFileIngressPolicy;
  active_file_count: number;
  sources: ReportFileSourceProjection[];
  ingress_receipts?: MaterialIngressReceipt[];
  material_set_confirmation: MaterialSetConfirmationProjection;
  phase?: "draft" | "processing" | "reviewed";
}
/**
 * 报告文件入口的唯一公开准入策略，前端只能投影不可自行复制。
 */
export interface ReportFileIngressPolicy {
  max_files_per_report: number;
  max_file_bytes: number;
  max_pdf_pages: number;
  description_min_chars: number;
  description_max_chars: number;
  asset_title_max_chars: number;
  semantic_material_kinds: MaterialKind[];
  layout_asset_kinds: MaterialKind[];
  semantic_material_extensions: string[];
  layout_asset_extensions: string[];
  topic_tags: ReportFileTopicTag[];
}
/**
 * 用户可选的文件主题标签；标签值由服务端领域目录而非前端枚举提供。
 */
export interface ReportFileTopicTag {
  id: string;
  label: string;
  kind: "auxiliary" | "report_area" | "report_section";
}
/**
 * 轻量版准备中心使用的文件投影，不暴露旧资料工作区的用途、范围或解析正文。
 */
export interface ReportFileSourceProjection {
  binding_id: string;
  source_id: string;
  binding_status: "active" | "removed" | "superseded";
  filename: string;
  source_label?: string | null;
  content_type: string;
  size_bytes: number;
  sha256: string;
  declaration: UserFileDeclarationRevision;
  admission_status: "admitted" | "failed";
  error_message?: string | null;
  file_analysis?: ReportFileAnalysisProjection | null;
  image_analysis?: ReportFileImageAnalysisProjection | null;
  parse_status?: ("ok" | "failed" | "ok_with_attention") | null;
  parse_failure_reason?: string | null;
  created_at: string;
  updated_at: string;
}
/**
 * 一项不可变的用户文件声明修订；当前声明由 Binding 的最高 revision 派生。
 */
export interface UserFileDeclarationRevision {
  description: string;
  role: ReportFileRole;
  /**
   * @minItems 1
   * @maxItems 24
   */
  topic_tags: [string, ...string[]];
  asset_title?: string | null;
  revision_id: string;
  binding_id: string;
  revision: number;
  declared_at: string;
}
/**
 * 当前文件的 File Agent 生命周期与受限 Dossier 视图。
 */
export interface ReportFileAnalysisProjection {
  status: "queued" | "running" | "succeeded" | "needs_attention" | "failed" | "superseded";
  dossier?: ReportFileDossierProjection | null;
}
/**
 * FileDossier 的客户可见投影，保持文件级来源边界。
 */
export interface ReportFileDossierProjection {
  relevance: "relevant" | "not_relevant";
  relevance_reason: string;
  applicable_scope_count: number;
  attention_items?: ReportFileAttentionProjection[];
  report_scope?: ("within_report" | "outside_report") | null;
  report_scope_notice?: string | null;
}
/**
 * 一项面向上传者的资料澄清提示，不暴露内部判断代码。
 */
export interface ReportFileAttentionProjection {
  message: string;
  next_action: string;
}
/**
 * 排版素材的图片识别生命周期与受限资产视图；题注/替代文本归资产 owner。
 */
export interface ReportFileImageAnalysisProjection {
  status: "queued" | "running" | "succeeded" | "failed" | "superseded";
  asset_id?: string | null;
  caption?: string | null;
  category?: string | null;
  placement_scope_id?: string | null;
  certificate_fact?: CertificateFactProjection | null;
}
/**
 * 证书事实的用户可见投影；字段与入口解析同名，供资料处理页核对与更正。
 */
export interface CertificateFactProjection {
  certificate_name?: string;
  issuer?: string | null;
  covered_scope?: string | null;
  holder_name?: string | null;
  unreadable_fields: string[];
}
/**
 * 资料集确认状态；确认后才对 active 语义资料入队 File Agent。
 */
export interface MaterialSetConfirmationProjection {
  status: "not_required" | "pending_description" | "required" | "confirmed";
  confirmed_at?: string | null;
  pending_description_count: number;
}
