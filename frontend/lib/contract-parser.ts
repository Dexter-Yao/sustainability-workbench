// ABOUTME: 前端关键领域合同的统一 Ajv parse-first 边界。
// ABOUTME: Report 与 StoredReportStateV4 均先按后端同源 JSON Schema 验证，再进入业务代码。
import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020";

import reportSchema from "./report.schema.json";
import reportApiSchema from "./report-api.schema.json";
import sectionGenerationSchema from "./section-generation.schema.json";
import storedReportStateSchema from "./stored-report-state.schema.json";
import type { Report } from "./schema";
import type { SectionGenerationResponse } from "./section-generation.generated";
import type {
  AssessmentInputResponse,
  GenerationModelOptionsResponse,
  PutReportStateResponse,
  QuantitativeMetricsResponse,
  ReportApiContractBundle,
  ReportGenerationProjection,
  ReportListResponse,
  ReportProfileOptionsResponse,
  ReportStateResponse,
  ReportBlockProvenanceProjection,
  ReportLineageProjection,
  ReportPreparationProjection,
  ReportSummaryResponse,
  StructuredInputConflictResponse,
  StructuredInputMutationResponse,
  InternalAuditArtifactListResponse,
} from "./report-api.generated";
import type { StoredReportStateV4 } from "./stored-report-state.generated";

const ajv = new Ajv2020({
  allErrors: true,
  strict: true,
  strictTypes: false,
  validateFormats: false,
});
const storedStateAjv = new Ajv2020({
  allErrors: true,
  strict: false,
  useDefaults: true,
  validateFormats: false,
});

const validateReport = ajv.compile(reportSchema) as ValidateFunction<Report>;
const validateStoredReportState = storedStateAjv.compile(
  storedReportStateSchema,
) as ValidateFunction<StoredReportStateV4>;
const validateReportApi = ajv.compile(
  reportApiSchema,
) as ValidateFunction<ReportApiContractBundle>;
// 整节生成是独立导出的合同（非 report-api bundle），故单独编译一个校验器。
const validateSectionGeneration = ajv.compile(
  sectionGenerationSchema,
) as ValidateFunction<SectionGenerationResponse>;

export class ContractValidationError extends Error {
  readonly errors: ErrorObject[];

  constructor(contractName: string, errors: ErrorObject[] | null | undefined) {
    const first = errors?.[0];
    const location = first?.instancePath || "/";
    const detail = first?.message ? `：${location} ${first.message}` : "";
    const separator = /[A-Za-z0-9]$/.test(contractName) ? " " : "";
    super(`${contractName}${separator}不符合合同${detail}`);
    this.name = "ContractValidationError";
    this.errors = errors ? [...errors] : [];
  }
}

function parseContract<T>(
  contractName: string,
  validate: ValidateFunction<T>,
  value: unknown,
): T {
  if (!validate(value)) {
    throw new ContractValidationError(contractName, validate.errors);
  }
  return value;
}

export function parseReport(value: unknown): Report {
  return parseContract("Report", validateReport, value);
}

export function parseStoredReportStateValue(value: unknown): StoredReportStateV4 {
  return parseContract("报告状态快照", validateStoredReportState, value);
}

function parseReportApiField<
  K extends keyof ReportApiContractBundle,
  T extends NonNullable<ReportApiContractBundle[K]>,
>(field: K, value: unknown): T {
  const parsed = parseContract(
    "ReportApi",
    validateReportApi,
    { [field]: value },
  );
  return parsed[field] as T;
}

export function parseReportSummary(value: unknown): ReportSummaryResponse {
  return parseReportApiField("report_summary", value);
}

export function parseReportList(value: unknown): ReportListResponse {
  return parseReportApiField("report_list", value);
}

export function parseReportProfileOptions(value: unknown): ReportProfileOptionsResponse {
  return parseReportApiField("report_profile_options", value);
}

export function parseGenerationModelOptions(
  value: unknown,
): GenerationModelOptionsResponse {
  return parseReportApiField("generation_model_options", value);
}

export function parseSectionGeneration(value: unknown): SectionGenerationResponse {
  return parseContract("整节生成结果", validateSectionGeneration, value);
}

export function parseReportState(value: unknown): ReportStateResponse {
  return parseReportApiField("report_state", value);
}

export function parseReportLineage(value: unknown): ReportLineageProjection {
  return parseReportApiField("report_lineage", value);
}

export function parseBlockProvenance(value: unknown): ReportBlockProvenanceProjection {
  return parseReportApiField("block_provenance", value);
}

export function parseReportPreparation(
  value: unknown,
): ReportPreparationProjection {
  return parseReportApiField("report_preparation", value);
}

export function parseReportGeneration(
  value: unknown,
): ReportGenerationProjection {
  return parseReportApiField("report_generation", value);
}

export function parsePutReportState(value: unknown): PutReportStateResponse {
  return parseReportApiField("put_report_state", value);
}

export function parseAssessmentInput(value: unknown): AssessmentInputResponse {
  return parseReportApiField("assessment_input", value);
}

export function parseQuantitativeMetrics(
  value: unknown,
): QuantitativeMetricsResponse {
  return parseReportApiField("quantitative_metrics", value);
}

export function parseStructuredInputMutation(
  value: unknown,
): StructuredInputMutationResponse {
  return parseReportApiField("structured_input_mutation", value);
}

export function parseStructuredInputConflict(
  value: unknown,
): StructuredInputConflictResponse {
  return parseReportApiField("structured_input_conflict", value);
}

export function parseInternalAuditArtifacts(
  value: unknown,
): InternalAuditArtifactListResponse {
  return parseReportApiField("internal_audit_artifacts", value);
}
