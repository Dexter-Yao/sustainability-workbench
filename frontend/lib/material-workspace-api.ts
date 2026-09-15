// ABOUTME: 资料工作区前端合同与受保护 API 客户端，保持资料状态独立于 Report/AppProvider；报告文件上传经 XMLHttpRequest 回报进度，非浏览器环境自动回退 fetch。
// ABOUTME: 浏览器只投影服务端 workspace snapshot；上传、提案决策和按范围写入均由后端裁决。

import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";
import {
  parseReportLineage,
  parseReportPreparation,
} from "./contract-parser";
import {
  parseMaterialSourceContent,
  parseMaterialWorkspace,
  parseReportFileIntake,
} from "./material-workspace-contract";
import type {
  MaterialClarificationProjection,
  MaterialEvidenceProjection,
  MaterialFactProjection,
  MaterialGapProjection,
  MaterialIngressReceipt,
  MaterialMessageProjection,
  MaterialProposalProjection,
  MaterialScopeProjection,
  MaterialScopeSummaryProjection,
  MaterialSourceProjection,
  MaterialWorkspaceProjection,
  NormalizedMaterialProjection,
  NormalizedSegmentProjection,
  PrimaryInputMode,
  SourceLocator,
  ReportFileIntakeProjection,
  UserFileDeclaration,
} from "./material-workspace.generated";
import type {
  ReportLineageProjection,
  ReportPreparationProjection,
} from "./report-api.generated";
import { accessToken } from "./supabase";

export type {
  MaterialSourceStatus,
  PrimaryInputMode,
  SourceLocator,
} from "./material-workspace.generated";

export const MATERIAL_MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MATERIAL_MAX_BATCH_FILES = 10;
export const MATERIAL_SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"] as const;
export const MATERIAL_CONVERSION_EXTENSIONS = [".doc", ".xls"] as const;

export type MaterialScopeKind = MaterialScopeProjection["kind"];
export type ClarificationStatus = MaterialClarificationProjection["status"];
export type MaterialProposalStatus = MaterialProposalProjection["status"];
export type MaterialScope = MaterialScopeProjection;
export type NormalizedSegment = NormalizedSegmentProjection;
export type NormalizedMaterial = NormalizedMaterialProjection;
export type ProcessingStep = MaterialSourceProjection["processing_steps"][number];
export type MaterialSource = MaterialSourceProjection;
export type MaterialEvidenceRef = MaterialEvidenceProjection;
export type InputProposal = MaterialProposalProjection;
export type MaterialFact = MaterialFactProjection;
export type MaterialGap = MaterialGapProjection;
export type ClarificationRequest = MaterialClarificationProjection;
export type MaterialMessage = MaterialMessageProjection;
export type MaterialScopeSummary = MaterialScopeSummaryProjection;
export type MaterialWorkspaceSnapshot = MaterialWorkspaceProjection;
export type MaterialIngressReceiptProjection = MaterialIngressReceipt;
export type ReportFileIntake = ReportFileIntakeProjection;
export type ReportPreparation = ReportPreparationProjection;
export type ReportFileDeclaration = UserFileDeclaration;
export type ReportFileDeclarationInput = Omit<UserFileDeclaration, "topic_tags"> & {
  topic_tags: string[];
};

export interface MaterialIngressBatchProjection {
  batchId: string | null;
  receipts: MaterialIngressReceiptProjection[];
  receivedCount: number;
  rejectedReceipts: MaterialIngressReceiptProjection[];
}

export class MaterialWorkspaceConflictError extends Error {}

export function selectMaterialWorkspaceSnapshot(
  current: MaterialWorkspaceSnapshot | null,
  incoming: MaterialWorkspaceSnapshot,
  reportId: string,
): MaterialWorkspaceSnapshot | null {
  if (incoming.report_id !== reportId) return current;
  if (
    current?.report_id === reportId
    && (
      incoming.projection_seq < current.projection_seq
      || incoming.report_state_seq < current.report_state_seq
    )
  ) return current;
  if (
    current?.report_id === reportId
    && incoming.projection_seq === current.projection_seq
    && incoming.report_state_seq === current.report_state_seq
  ) {
    const currentReceipts = JSON.stringify(current.ingress_receipts ?? []);
    const incomingReceipts = JSON.stringify(incoming.ingress_receipts ?? []);
    return currentReceipts === incomingReceipts ? current : incoming;
  }
  return incoming;
}

/**
 * 只接受较新的报告文件准入快照:blur 保存、移出/恢复与 2.5s 轮询的响应可能乱序到达,
 * 以服务端 projection_seq 丢弃旧响应;同序号内容不同视为服务端侧信息更新,取 incoming。
 */
export function selectReportFileIntakeSnapshot(
  current: ReportFileIntake | null,
  incoming: ReportFileIntake,
  reportId: string,
): ReportFileIntake | null {
  if (incoming.report_id !== reportId) return current;
  if (current?.report_id !== reportId) return incoming;
  if (incoming.projection_seq < current.projection_seq) return current;
  if (incoming.projection_seq === current.projection_seq) {
    return JSON.stringify(incoming) === JSON.stringify(current)
      ? current
      : incoming;
  }
  return incoming;
}

export function projectLatestMaterialIngressBatch(
  snapshot: MaterialWorkspaceSnapshot,
): MaterialIngressBatchProjection {
  const receipts = snapshot.ingress_receipts ?? [];
  const batchId = receipts.at(-1)?.batch_id ?? null;
  const batchReceipts = batchId
    ? receipts.filter((receipt) => receipt.batch_id === batchId)
    : [];
  return {
    batchId,
    receipts: batchReceipts,
    receivedCount: batchReceipts.filter(
      (receipt) => receipt.status === "accepted" || receipt.status === "reused",
    ).length,
    rejectedReceipts: batchReceipts.filter(
      (receipt) => receipt.status === "rejected",
    ),
  };
}

async function bearerHeaders(json = true): Promise<Record<string, string>> {
  const token = await accessToken();
  if (!token) throw new Error("登录状态已失效，请重新登录");
  return {
    Authorization: `Bearer ${token}`,
    ...(json ? { "Content-Type": "application/json" } : {}),
  };
}

/** 409 语义统一映射为可识别的工作区冲突错误；消息来自 parseErrorResponse 的领域投影。 */
async function conflictError(response: Response, fallback: string): Promise<MaterialWorkspaceConflictError> {
  return new MaterialWorkspaceConflictError((await parseErrorResponse(response, fallback)).message);
}

async function materialApiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (cause) {
    throw new Error("无法连接资料工作区，请检查网络后重试", { cause });
  }
}

/**
 * 以 XMLHttpRequest 提交表单并回报上传进度；仅在浏览器环境可用。
 * 返回值形状与 fetch Response 对齐，复用同一套错误语义解析。
 */
async function xhrUploadFetch(
  url: string,
  form: FormData,
  headers: Record<string, string>,
  onProgress?: (ratio: number) => void,
): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    for (const [key, value] of Object.entries(headers)) xhr.setRequestHeader(key, value);
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      };
    }
    xhr.onload = () => {
      resolve(new Response(xhr.responseText, { status: xhr.status }));
    };
    xhr.onerror = () => reject(new Error("无法连接资料工作区，请检查网络后重试"));
    xhr.send(form);
  });
}

function supportsXhrUpload(): boolean {
  return typeof XMLHttpRequest !== "undefined";
}

export async function updateTopicPrimaryInputMode(
  reportId: string,
  reportSectionId: string,
  primaryInputMode: PrimaryInputMode,
  baseWorkspaceStateSeq: number,
): Promise<MaterialWorkspaceSnapshot> {
  const response = await materialApiFetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/material-topics/${encodeURIComponent(reportSectionId)}/primary-input-mode`,
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify({
        primary_input_mode: primaryInputMode,
        base_workspace_state_seq: baseWorkspaceStateSeq,
      }),
    },
  );
  if (response.status === 409) {
    throw await conflictError(response, "资料工作区已更新");
  }
  if (!response.ok) {
    throw await parseErrorResponse(response, "议题收集路径保存失败");
  }
  return parseMaterialWorkspace(await response.json());
}

/** 保存报告级填报方式二选一；只改分步流编排，不改写任何已填输入。 */
/** 报告级填报方式二选一；CAS 基线是报告状态（该事实落报告，与生成闸、导出闸同源）。 */
export async function updateReportPrimaryInputMode(
  reportId: string,
  primaryInputMode: PrimaryInputMode,
  baseReportStateSeq: number,
): Promise<MaterialWorkspaceSnapshot> {
  const response = await materialApiFetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/primary-input-mode`,
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify({
        primary_input_mode: primaryInputMode,
        base_report_state_seq: baseReportStateSeq,
      }),
    },
  );
  if (response.status === 409) {
    throw await conflictError(response, "报告已更新");
  }
  if (!response.ok) {
    throw await parseErrorResponse(response, "填报方式保存失败");
  }
  return parseMaterialWorkspace(await response.json());
}

async function materialRequest(url: string, init?: RequestInit): Promise<unknown> {
  const response = await materialApiFetch(url, init);
  if (response.status === 409) throw await conflictError(response, "资料提案已失效");
  if (!response.ok) throw await parseErrorResponse(response, "资料工作区操作失败");
  return response.json();
}

async function materialWorkspaceRequest(
  url: string,
  init?: RequestInit,
): Promise<MaterialWorkspaceSnapshot> {
  return parseMaterialWorkspace(await materialRequest(url, init));
}

async function reportFileIntakeRequest(
  url: string,
  init?: RequestInit,
): Promise<ReportFileIntake> {
  return parseReportFileIntake(await materialRequest(url, init));
}

function reportUrl(reportId: string, suffix: string): string {
  return `${API_BASE}/api/reports/${encodeURIComponent(reportId)}${suffix}`;
}

export async function fetchMaterialWorkspace(reportId: string): Promise<MaterialWorkspaceSnapshot> {
  return materialWorkspaceRequest(reportUrl(reportId, "/material-workspace"), { headers: await bearerHeaders(false) });
}

export async function fetchReportFileIntake(reportId: string): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(reportUrl(reportId, "/file-intake"), {
    headers: await bearerHeaders(false),
  });
}

export async function fetchReportPreparation(
  reportId: string,
): Promise<ReportPreparation> {
  return parseReportPreparation(
    await materialRequest(reportUrl(reportId, "/preparation"), {
      headers: await bearerHeaders(false),
    }),
  );
}

export async function uploadReportFiles(
  reportId: string,
  files: File[],
  declarations: ReportFileDeclarationInput[],
  onProgress?: (ratio: number) => void,
): Promise<ReportFileIntake> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("declarations", JSON.stringify(declarations));
  const url = reportUrl(reportId, "/file-intake/files");
  const headers = await bearerHeaders(false);
  const response = supportsXhrUpload()
    ? await xhrUploadFetch(url, form, headers, onProgress)
    : await materialApiFetch(url, { method: "POST", headers, body: form });
  if (response.status === 409) {
    throw await conflictError(response, "资料提案已失效");
  }
  if (!response.ok) throw await parseErrorResponse(response, "资料工作区操作失败");
  return parseReportFileIntake(await response.json());
}

export async function updateReportFileDeclaration(
  reportId: string,
  bindingId: string,
  declaration: ReportFileDeclarationInput,
  expectedRevision: number,
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/file-intake/files/${encodeURIComponent(bindingId)}`),
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify({ declaration, expected_revision: expectedRevision }),
    },
  );
}

/**
 * 更新文件展示名（source_label）；与文件说明分属两个填空，各自独立 PATCH 与并发校验。
   */
export async function updateReportFileSourceLabel(
  reportId: string,
  bindingId: string,
  sourceLabel: string,
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/file-intake/files/${encodeURIComponent(bindingId)}/label`),
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify({ source_label: sourceLabel }),
    },
  );
}

/** 用户改写素材图片题注；归属转为用户，识别重跑不再覆盖。 */
export async function updateLayoutAssetCaption(
  reportId: string,
  assetId: string,
  caption: string,
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/layout-assets/${encodeURIComponent(assetId)}/caption`),
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify({ caption }),
    },
  );
}

/** 用户更正证书事实；归属转为用户，识别重跑不再覆盖。 */
export async function updateLayoutAssetCertificateFact(
  reportId: string,
  assetId: string,
  fact: {
    certificate_name: string;
    issuer?: string | null;
    covered_scope?: string | null;
    holder_name?: string | null;
  },
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/layout-assets/${encodeURIComponent(assetId)}/certificate-fact`),
    {
      method: "PATCH",
      headers: await bearerHeaders(),
      body: JSON.stringify(fact),
    },
  );
}

export async function removeReportFile(
  reportId: string,
  bindingId: string,
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/file-intake/files/${encodeURIComponent(bindingId)}/remove`),
    { method: "POST", headers: await bearerHeaders(false) },
  );
}

export async function restoreReportFile(
  reportId: string,
  bindingId: string,
): Promise<ReportFileIntake> {
  return reportFileIntakeRequest(
    reportUrl(reportId, `/file-intake/files/${encodeURIComponent(bindingId)}/restore`),
    { method: "POST", headers: await bearerHeaders(false) },
  );
}

/**
 * 用户显式确认资料集齐备；说明未齐时服务端返回 409，前端据 parseErrorResponse 展示真实原因。
 */
export async function confirmMaterialSet(reportId: string): Promise<ReportFileIntake> {
  const response = await materialApiFetch(reportUrl(reportId, "/file-intake/confirm"), {
    method: "POST",
    headers: await bearerHeaders(false),
  });
  if (!response.ok) throw await parseErrorResponse(response, "资料集确认失败");
  return parseReportFileIntake(await response.json());
}

export async function fetchMaterialSourceContent(
  reportId: string,
  sourceId: string,
): Promise<NormalizedMaterial | null> {
  const response = await materialApiFetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/material-sources/${encodeURIComponent(sourceId)}/content`,
    { headers: await bearerHeaders(false) },
  );
  if (!response.ok) throw await parseErrorResponse(response, "清洗内容加载失败");
  const payload = parseMaterialSourceContent(await response.json());
  return payload.normalized_material;
}

export async function updateMaterialSourceMetadata(reportId: string, sourceId: string, scope: MaterialScope): Promise<MaterialWorkspaceSnapshot> {
  return materialWorkspaceRequest(reportUrl(reportId, `/material-sources/${encodeURIComponent(sourceId)}`), {
    method: "PATCH",
    headers: await bearerHeaders(),
    body: JSON.stringify({ scope_kind: scope.kind, report_section_ids: scope.report_section_ids }),
  });
}

export async function deleteMaterialSource(reportId: string, sourceId: string): Promise<MaterialWorkspaceSnapshot> {
  return materialWorkspaceRequest(reportUrl(reportId, `/material-sources/${encodeURIComponent(sourceId)}`), {
    method: "DELETE",
    headers: await bearerHeaders(false),
  });
}

/**
 * 报告谱系由服务端从资料、受控输入与报告收据派生；浏览器不组合或推断证据关系。
 */
export async function getReportLineage(
  reportId: string,
): Promise<ReportLineageProjection> {
  return parseReportLineage(await materialRequest(
    reportUrl(reportId, "/report-lineage"),
    { headers: await bearerHeaders() },
  ));
}

export function validateMaterialFiles(files: Array<Pick<File, "name" | "size">>): string | null {
  if (!files.length) return "请选择至少一份资料。";
  if (files.length > MATERIAL_MAX_BATCH_FILES) return `每批最多上传 ${MATERIAL_MAX_BATCH_FILES} 份资料。`;
  for (const file of files) {
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if ((MATERIAL_CONVERSION_EXTENSIONS as readonly string[]).includes(extension)) {
      return `${file.name} 暂不支持，请先转换为 ${extension === ".doc" ? ".docx" : ".xlsx"}。`;
    }
    if (!(MATERIAL_SUPPORTED_EXTENSIONS as readonly string[]).includes(extension)) {
      return `${file.name} 的格式不受支持。可上传 PDF、DOCX、XLSX、PNG、JPG/JPEG。`;
    }
    if (file.size > MATERIAL_MAX_FILE_BYTES) return `${file.name} 超过单文件 20MB 限制。`;
  }
  return null;
}

export function materialSourceMatchesScope(source: MaterialSource, scope: MaterialScope): boolean {
  if (scope.kind === "report") return true;
  if (scope.kind === "topics") {
    return source.scope.kind === "topics"
      && scope.report_section_ids.some((id) => source.scope.report_section_ids.includes(id));
  }
  return source.scope.kind === scope.kind;
}

export function locatorLabel(locator: SourceLocator): string {
  if (locator.kind === "pdf_page" && locator.page) return `第 ${locator.page} 页`;
  if (locator.kind === "docx_paragraph" && locator.paragraph_index != null) return `第 ${locator.paragraph_index} 段`;
  if (locator.kind === "docx_table" && locator.table_index != null) {
    const rows = locator.row_start != null
      ? `第 ${locator.row_start}${locator.row_end != null && locator.row_end !== locator.row_start ? `–${locator.row_end}` : ""} 行`
      : "";
    return [`表格 ${locator.table_index}`, rows].filter(Boolean).join(" · ");
  }
  if (locator.kind === "xlsx_range") return [locator.sheet_name, locator.cell_range].filter(Boolean).join(" · ") || "工作表";
  return "region_label" in locator && locator.region_label
    ? `图片区域 ${locator.region_label}`
    : "整张图片";
}
