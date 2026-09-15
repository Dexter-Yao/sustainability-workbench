// ABOUTME: 前端与后端 API 的薄封装：配置、评分与定量结构化输入、诊断、导出与确定性派生图。
// ABOUTME: 报告生成只走报告级生成接口（report-generation-api）；本模块不承载任何模型调用入口。
import { workbookDownloadFilename } from "./product-name";
import { parseErrorResponse } from "./api-error";
import {
  parseAssessmentInput,
  parseQuantitativeMetrics,
  parseReport,
  parseStructuredInputConflict,
  parseStructuredInputMutation,
} from "./contract-parser";
import type {
  AssessmentResult,
  DerivedVisualizationSpec,
  Materiality,
  MaterialityScoreInput,
  MaterialityThreshold,
  QuantitativeMetricDraft,
  Report,
} from "./schema";
import type {
  AssessmentInputResponse,
  QuantitativeMetricsResponse,
  StructuredInputConflictResponse,
  StructuredInputMutationResponse,
} from "./report-api.generated";


export interface AssessmentCounts {
  total: number;
  dual: number;
  impact_only: number;
  financial_only: number;
  non_material: number;
}

// 后端地址由环境变量承载；本地开发缺省 8010（8000 常被占用）。
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8010";

export interface GenBlockDef {
  id: string;
}
export interface PromptConfig {
  blocks: GenBlockDef[];
  user_visible_disclosure_clause_annotations?: UserVisibleDisclosureClauseAnnotationEntry[];
}

export interface UserVisibleDisclosureClauseText {
  clauseReference: string;
  clauseOriginalText: string;
}

export interface UserVisibleDisclosureClauseAnnotationEntry {
  reportContentTopicName: string;
  reportSectionKey: string;
  mainlandStandard: "sse" | "szse" | "bse" | string;
  appendixIndexClauseReferences: string[];
  clauseOriginalTexts: UserVisibleDisclosureClauseText[];
}

/** 拉取工作台配置：可生成块身份与用户可见准则批注。
 * 该端点要求登录，必须携带访问令牌。 */
export async function fetchPromptConfig(): Promise<PromptConfig> {
  const res = await fetch(`${API_BASE}/api/prompt-config`, { headers: await authHeaders() });
  if (!res.ok) throw await parseErrorResponse(res, "工作台配置加载失败");
  return (await res.json()) as PromptConfig;
}

/** 受保护业务请求必须携带访问令牌；本地开发也不得绕过真实 Auth 边界。 */
async function authHeaders(): Promise<Record<string, string>> {
  if (typeof window === "undefined") throw new Error("认证服务未配置");
  const { accessToken } = await import("./supabase");
  const token = await accessToken();
  if (!token) throw new Error("登录状态已失效，请重新登录");
  return { Authorization: `Bearer ${token}` };
}

/** 生成端点 403 = 权益受限（配额耗尽/范围不含该议题），携带业务可读信息。 */
export class EntitlementError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "EntitlementError";
    this.code = code;
  }
}

/** 已钉住报告的契约与当前运行时契约不一致，必须显式升级后才能继续编辑。 */
export class ContractUpgradeRequiredError extends Error {
  readonly code: string;

  constructor(message?: string, code = "contract_upgrade_required") {
    super(message);
    this.name = "ContractUpgradeRequiredError";
    this.code = code;
  }
}

async function entitlementAwareError(res: Response, fallback: string): Promise<Error> {
  const apiError = await parseErrorResponse(res, fallback);
  if (res.status === 403) {
    return new EntitlementError(apiError.message, apiError.code);
  }
  return apiError;
}

export interface PutAssessmentInput {
  expected_state_seq: number;
  threshold: MaterialityThreshold;
  scores: MaterialityScoreInput[];
}

export interface PutQuantitativeMetricsInput {
  expected_state_seq: number;
  metrics: Record<string, QuantitativeMetricDraft>;
  greenhouseGasAccountingStandard?: string | null;
  greenhouseGasAccountingStandardOther?: string | null;
}

export class StructuredInputConflictError extends Error {
  readonly current: StructuredInputMutationResponse;

  constructor(conflict: StructuredInputConflictResponse) {
    super(conflict.message);
    this.name = "StructuredInputConflictError";
    this.current = conflict.current;
  }
}

/** 结构化输入错误消息：主消息 + 前若干条单元格错误，供在线校验类页面内联展示。 */
async function structuredInputError(res: Response, fallback: string): Promise<Error> {
  const apiError = await parseErrorResponse(res, fallback);
  if (!apiError.cellMessages.length) return apiError;
  return new (class extends Error {
    readonly code = apiError.code;
    readonly httpStatus = apiError.httpStatus;
  })([apiError.message, ...apiError.cellMessages].join(" "));
}

async function parseStructuredInputMutationResponse(
  res: Response,
  fallback: string,
): Promise<StructuredInputMutationResponse> {
  if (res.status === 409) {
    // 409 冲突投影为服务端权威快照；克隆响应体供 parseErrorResponse 兜底路径消费而不重复读取同一个 Response。
    const payload = await res.clone().json().catch(() => null);
    if (
      payload !== null
      && typeof payload === "object"
      && "code" in payload
      && payload.code === "report_state_conflict"
    ) {
      throw new StructuredInputConflictError(
        parseStructuredInputConflict(payload),
      );
    }
    throw await parseErrorResponse(res, fallback);
  }
  if (!res.ok) throw await structuredInputError(res, fallback);
  return parseStructuredInputMutation(await res.json());
}

function reportStructuredInputUrl(reportId: string, path: string): string {
  return `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/structured-inputs/${path}`;
}

function saveWorkbook(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** 读取当前报告的重要性目录、评分值、服务端解析结果与乐观锁序号。 */
export async function fetchAssessmentInput(
  reportId: string,
): Promise<AssessmentInputResponse> {
  const res = await fetch(reportStructuredInputUrl(reportId, "assessment"), {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await structuredInputError(res, "重要性评估加载失败");
  return parseAssessmentInput(await res.json());
}

/** 原子替换当前报告的完整重要性评分。 */
export async function putAssessmentInput(
  reportId: string,
  input: PutAssessmentInput,
): Promise<StructuredInputMutationResponse> {
  const res = await fetch(reportStructuredInputUrl(reportId, "assessment"), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(input),
    // 离开页面（pagehide/卸载）时发出的保底提交必须带 keepalive，
    // 否则浏览器会随文档一起取消这次请求，用户刚填的内容就此丢失。
    keepalive: true,
  });
  return parseStructuredInputMutationResponse(res, "重要性评分保存失败");
}

/** 下载当前报告和合同版本绑定的重要性评分模板。 */
export async function downloadAssessmentTemplate(reportId: string): Promise<void> {
  const res = await fetch(reportStructuredInputUrl(reportId, "assessment/template"), {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await structuredInputError(res, "评分模板下载失败");
  saveWorkbook(await res.blob(), workbookDownloadFilename("重要性评分表"));
}

/** 整批导入评分表；工作簿完整校验通过后才原子写入。 */
export async function importAssessmentWorkbook(
  reportId: string,
  file: File,
  expectedStateSeq: number,
  threshold: MaterialityThreshold,
): Promise<StructuredInputMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_state_seq", String(expectedStateSeq));
  form.append("financial_threshold", String(threshold.financial));
  form.append("impact_threshold", String(threshold.impact));
  const res = await fetch(reportStructuredInputUrl(reportId, "assessment/import"), {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return parseStructuredInputMutationResponse(res, "评分表导入失败");
}

/** 下载当前报告绑定的议题信息填写表模板（已预填现有回答）。 */
export async function downloadTopicQuestionsTemplate(reportId: string): Promise<void> {
  const res = await fetch(reportStructuredInputUrl(reportId, "topic-questions/template"), {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await structuredInputError(res, "议题信息表模板下载失败");
  saveWorkbook(await res.blob(), workbookDownloadFilename("议题信息填写表"));
}

/** 整批导入议题信息填写表；工作簿完整校验通过后才原子替换范围内答案。 */
export async function importTopicQuestionsWorkbook(
  reportId: string,
  file: File,
  expectedStateSeq: number,
): Promise<StructuredInputMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_state_seq", String(expectedStateSeq));
  const res = await fetch(reportStructuredInputUrl(reportId, "topic-questions/import"), {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return parseStructuredInputMutationResponse(res, "议题信息表导入失败");
}

/** 下载当前报告绑定的企业及报告基本信息表模板（已预填现有填写）。 */
export async function downloadReportBasicsTemplate(reportId: string): Promise<void> {
  const res = await fetch(reportStructuredInputUrl(reportId, "report-basics/template"), {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await structuredInputError(res, "基本信息表模板下载失败");
  saveWorkbook(await res.blob(), workbookDownloadFilename("企业及报告基本信息表"));
}

/** 整批导入企业及报告基本信息表；工作簿完整校验通过后才原子替换基础资料面。 */
export async function importReportBasicsWorkbook(
  reportId: string,
  file: File,
  expectedStateSeq: number,
): Promise<StructuredInputMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_state_seq", String(expectedStateSeq));
  const res = await fetch(reportStructuredInputUrl(reportId, "report-basics/import"), {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return parseStructuredInputMutationResponse(res, "基本信息表导入失败");
}

/** 下载账户级空白统一填报工作簿模板：不绑定报告，导入时任选目标报告（覆盖语义）。 */
export async function downloadUnifiedWorkbookBlankTemplate(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/structured-inputs/unified-workbook/blank-template`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await structuredInputError(res, "统一填报工作簿模板下载失败");
  saveWorkbook(await res.blob(), workbookDownloadFilename("统一填报工作簿模板"));
}

/** 整册导入统一填报工作簿；评分/定量整表留空视为暂不提交、保持系统内现状。 */
export async function importUnifiedWorkbook(
  reportId: string,
  file: File,
  expectedStateSeq: number,
  threshold?: MaterialityThreshold | null,
): Promise<StructuredInputMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_state_seq", String(expectedStateSeq));
  if (threshold) {
    form.append("financial_threshold", String(threshold.financial));
    form.append("impact_threshold", String(threshold.impact));
  }
  const res = await fetch(reportStructuredInputUrl(reportId, "unified-workbook/import"), {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return parseStructuredInputMutationResponse(res, "统一填报工作簿导入失败");
}

/** 导出/诊断的统一问题项，对齐后端 diagnostics.Issue（前端不再本地重算）。 */
export interface Issue {
  level: "block" | "warn";
  code: string;
  message: string;
  blockId?: string | null;
  rowId?: string | null;
  fieldKey?: string | null;
  path?: string | null;
  col?: string | null;
  readinessStageId?: string | null;
  actionHref?: string | null;
  assessmentTopicId?: string | null;
  reportSectionId?: string | null;
  sectionKey?: string | null;
  metricKey?: string | null;
}
export interface LightweightReadinessStage {
  id: "report_configuration" | "assessment_scoring" | "quantitative_metrics" | "workbench_entry";
  label: string;
  actionHref: string;
  complete: boolean;
  issueCount: number;
}
export interface LightweightReadinessIssue {
  code: string;
  message: string;
  stageId: LightweightReadinessStage["id"];
  actionHref: string;
  fieldKey?: string | null;
  path?: string | null;
  assessmentTopicId?: string | null;
  metricKey?: string | null;
}
export interface LightweightReportReadiness {
  stages: LightweightReadinessStage[];
  issues: LightweightReadinessIssue[];
  readyForWorkbench: boolean;
  firstIncompleteStageId?: LightweightReadinessStage["id"] | null;
  firstIncompleteHref?: string | null;
}
/** 单条准则披露要求在本次报告中的承载结论；轻量版只经审阅稿说明页告知，不阻断导出。 */
export interface CoverageFinding {
  code:
    | "requirement_covered"
    | "requirement_conditional_not_triggered"
    | "requirement_omitted_needs_statement"
    | "requirement_excluded_by_design"
    | "topic_requirements_pending";
  reportSectionId: string;
  requirementKey?: string | null;
  requirementTitle?: string | null;
  exclusionRationaleCode?: string | null;
  userFacingNote?: string | null;
}

/** 单条报告级披露义务在本次报告中的满足结论。 */
export interface ObligationVerdict {
  code: "satisfied" | "satisfied_via_fallback" | "attention" | "not_applicable";
  obligationKey: string;
  obligationTitle: string;
  userFacingNote?: string | null;
}

export interface DisclosureCoverageReport {
  findings: CoverageFinding[];
  obligations: ObligationVerdict[];
}

export interface Diagnostics {
  issues: Issue[];
  blocking: boolean;
  readiness?: LightweightReportReadiness | null;
  /** 准则披露覆盖判定：轻量版不进 issues、不阻断，仅供展示与审阅稿投影。 */
  coverage?: DisclosureCoverageReport | null;
}

/** 报告诊断（服务端单一真相）：与 /api/export 同一组合根，预检抽屉与导出闸同源同集。 */
export async function diagnose(reportId: string, report: Report): Promise<Diagnostics> {
  const res = await fetch(`${API_BASE}/api/reports/${encodeURIComponent(reportId)}/diagnose`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(report),
  });
  if (!res.ok) throw await parseErrorResponse(res, "诊断失败");
  return (await res.json()) as Diagnostics;
}

/** 导出 Word；必须关联当前 owner 报告，存在阻断级 issue 时后端 fail-loud(422)。 */
export async function exportReport(report: Report, reportId: string): Promise<Blob> {
  const query = `?report_id=${encodeURIComponent(reportId)}`;
  const res = await fetch(`${API_BASE}/api/export${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(report),
  });
  if (res.status === 422) {
    const data = (await res.json()) as { detail?: { issues?: Issue[] } };
    const err = new Error("EXPORT_BLOCKED") as Error & { issues: Issue[] };
    err.issues = data.detail?.issues ?? [];
    throw err;
  }
  if (!res.ok) throw await entitlementAwareError(res, "导出失败");
  return res.blob();
}

export type { QuantitativeMetricDef } from "./report-api.generated";

/** 读取当前报告的指标目录、完整草稿、缺值原因与乐观锁序号。 */
export async function fetchQuantitativeMetricsInput(
  reportId: string,
): Promise<QuantitativeMetricsResponse> {
  const res = await fetch(
    reportStructuredInputUrl(reportId, "quantitative-metrics"),
    { headers: await authHeaders() },
  );
  if (!res.ok) throw await structuredInputError(res, "定量指标加载失败");
  return parseQuantitativeMetrics(await res.json());
}

/** 原子替换当前报告的完整定量信息表。 */
export async function putQuantitativeMetricsInput(
  reportId: string,
  input: PutQuantitativeMetricsInput,
): Promise<StructuredInputMutationResponse> {
  const res = await fetch(
    reportStructuredInputUrl(reportId, "quantitative-metrics"),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify(input),
    },
  );
  return parseStructuredInputMutationResponse(res, "定量信息保存失败");
}

/** 下载当前报告和合同版本绑定的 ESG 定量信息模板。 */
export async function downloadQuantitativeMetricsTemplate(
  reportId: string,
): Promise<void> {
  const res = await fetch(
    reportStructuredInputUrl(reportId, "quantitative-metrics/template"),
    { headers: await authHeaders() },
  );
  if (!res.ok) throw await structuredInputError(res, "定量信息模板下载失败");
  saveWorkbook(await res.blob(), workbookDownloadFilename("ESG定量信息表"));
}

/** 整批导入定量信息表；全目录完整校验通过后才原子写入。 */
export async function importQuantitativeMetricsWorkbook(
  reportId: string,
  file: File,
  expectedStateSeq: number,
): Promise<StructuredInputMutationResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("expected_state_seq", String(expectedStateSeq));
  const res = await fetch(
    reportStructuredInputUrl(reportId, "quantitative-metrics/import"),
    {
      method: "POST",
      headers: await authHeaders(),
      body: form,
    },
  );
  return parseStructuredInputMutationResponse(res, "定量信息表导入失败");
}

/** 按 schema 派生规格渲染 ESG 定量指标摘要 PNG；前端预览与 Word 导出共用后端图源。 */
export async function fetchMetricSummaryImage(report: Report, spec: DerivedVisualizationSpec): Promise<Blob | null> {
  const res = await fetch(`${API_BASE}/api/visualizations/quantitative-metric-summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ report, spec }),
  });
  if (res.status === 204) return null;
  if (!res.ok) throw await parseErrorResponse(res, "指标摘要图渲染失败");
  return res.blob();
}

export interface PlanResult {
  report: Report;
  diagnostics: { reportSectionId: string | null; status: string }[];
  added: string[];
  dropped: string[];
}

/** 按报告配置与完整适用评估清单装配议题章节，并按 block id 保留正文，回报新增/丢弃章节供前端告知确认。 */
export async function plan(
  report: Report,
  expectedContractVersion?: string,
  reportId?: string,
): Promise<PlanResult> {
  const res = await fetch(`${API_BASE}/api/plan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(reportId ? await authHeaders() : {}),
    },
    body: JSON.stringify({
      ...(reportId ? { report_id: reportId } : {}),
      report,
      expected_contract_version: expectedContractVersion,
    }),
  });
  if (res.status === 409) {
    const detail = (await res.json().catch(() => null)) as { code?: string; message?: string } | null;
    if (detail?.code === "contract_upgrade_required") {
      throw new ContractUpgradeRequiredError(detail.message);
    }
  }
  if (!res.ok) throw await parseErrorResponse(res, "装配失败");
  const result = (await res.json()) as Omit<PlanResult, "report"> & {
    report: unknown;
  };
  return { ...result, report: parseReport(result.report) };
}

/** 据评估结果请后端渲染双重重要性矩阵 PNG（与导出同一渲染源，评分页/编辑台所见即所得）。
 * 可选 visibleMaterialities 为视图级过滤（仅交互预览）；不传则完整渲染。 */
export async function fetchMatrixImage(
  assessment: AssessmentResult,
  visibleMaterialities?: readonly Materiality[],
): Promise<Blob> {
  const query = visibleMaterialities && visibleMaterialities.length > 0
    ? `?visible=${visibleMaterialities.join(",")}`
    : "";
  const res = await fetch(`${API_BASE}/api/assessment/matrix${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(assessment),
  });
  if (!res.ok) throw await parseErrorResponse(res, "矩阵图渲染失败");
  return res.blob();
}
