// ABOUTME: 资料工作区 HTTP 响应的运行时解析边界，拒绝不符合后端公共投影合同的数据。
// ABOUTME: 所有资料 API 客户端必须先经此处解析，再将 typed projection 交给组件和状态层。

import Ajv, { type ErrorObject, type ValidateFunction } from "ajv";

import schema from "./material-workspace.schema.json";
import type {
  ReportFileIntakeProjection,
  MaterialSourceContentProjection,
  MaterialWorkspaceProjection,
} from "./material-workspace.generated";

const schemaId = "sustainability_desk.material-workspace.api.v1";
const ajv = new Ajv({ allErrors: true, strict: true });
ajv.addFormat(
  "uuid",
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
);
ajv.addFormat("date-time", {
  type: "string",
  validate: (value: string) => (
    /^\d{4}-\d{2}-\d{2}T/.test(value)
    && Number.isFinite(Date.parse(value))
  ),
});
ajv.addSchema(schema, schemaId);

const validateWorkspace: ValidateFunction<MaterialWorkspaceProjection> = ajv.compile({
  $ref: `${schemaId}#/$defs/MaterialWorkspaceProjection`,
});
const validateSourceContent: ValidateFunction<MaterialSourceContentProjection> = ajv.compile({
  $ref: `${schemaId}#/$defs/MaterialSourceContentProjection`,
});
const validateReportFileIntake: ValidateFunction<ReportFileIntakeProjection> = ajv.compile({
  $ref: `${schemaId}#/$defs/ReportFileIntakeProjection`,
});

function contractError(name: string, errors: ErrorObject[] | null | undefined): Error {
  const detail = errors
    ?.slice(0, 3)
    .map((error) => `${error.instancePath || "/"} ${error.message ?? "不符合合同"}`)
    .join("；");
  return new Error(`${name}响应不符合资料工作区合同${detail ? `：${detail}` : ""}`);
}

function parseContract<T>(
  name: string,
  validate: ValidateFunction<T>,
  value: unknown,
): T {
  if (!validate(value)) throw contractError(name, validate.errors);
  return value as T;
}

export function parseMaterialWorkspace(value: unknown): MaterialWorkspaceProjection {
  return parseContract("资料工作区", validateWorkspace, value);
}

export function parseMaterialSourceContent(
  value: unknown,
): MaterialSourceContentProjection {
  return parseContract("资料清洗内容", validateSourceContent, value);
}

export function parseReportFileIntake(value: unknown): ReportFileIntakeProjection {
  return parseContract("报告文件准入", validateReportFileIntake, value);
}
