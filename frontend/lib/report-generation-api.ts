// ABOUTME: 轻量版报告级显式生成、真实运行轮询与客户交付物下载的受保护 API 客户端。
// ABOUTME: 所有响应先经后端同源合同解析；浏览器不推断内部阶段，也不请求内部审计包。

import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";
import { parseReportGeneration } from "./contract-parser";
import type {
  ReportArtifactProjection,
  ReportGenerationProjection,
  ReportGenerationStatus,
} from "./report-api.generated";
import { accessToken } from "./supabase";

export type ReportGeneration = ReportGenerationProjection;
export type ReportGenerationArtifact = ReportArtifactProjection;
export type CustomerReportGenerationArtifact = ReportArtifactProjection & {
  kind: "word" | "review";
};
export interface ReportGenerationIntent {
  reportId: string;
  reportStateSeq: number;
  /** 本次意图选定的生成模型；null 表示沿用服务端默认。 */
  modelId: string | null;
  idempotencyKey: string;
}

export function reportGenerationIntent(
  current: ReportGenerationIntent | null,
  reportId: string,
  reportStateSeq: number,
  createIdempotencyKey: () => string,
  modelId?: string | null,
): ReportGenerationIntent {
  // 模型是意图的一部分：服务端幂等比对含 model_id，若换模型仍复用同一把幂等键，
  // 请求会以「幂等键已用于其他输入」被拒，或在比对放宽时静默拿回旧模型的运行。
  const nextModelId = modelId ?? null;
  if (
    current?.reportId === reportId
    && current.reportStateSeq === reportStateSeq
    && (current.modelId ?? null) === nextModelId
  ) {
    return current;
  }
  return {
    reportId,
    reportStateSeq,
    modelId: nextModelId,
    idempotencyKey: createIdempotencyKey(),
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

function reportUrl(reportId: string, suffix: string): string {
  return `${API_BASE}/api/reports/${encodeURIComponent(reportId)}${suffix}`;
}

function parseCustomerReportGeneration(value: unknown): ReportGeneration {
  const generation = parseReportGeneration(value);
  return {
    ...generation,
    artifacts: customerVisibleArtifacts(generation),
  };
}

export async function createReportGeneration(
  reportId: string,
  baseReportStateSeq: number,
  idempotencyKey: string,
  modelId?: string | null,
): Promise<ReportGeneration> {
  const response = await fetch(reportUrl(reportId, "/generations"), {
    method: "POST",
    headers: await bearerHeaders(),
    body: JSON.stringify({
      base_report_state_seq: baseReportStateSeq,
      idempotency_key: idempotencyKey,
      // 省略即由服务端用当前默认模型；给出时必须是服务端判定可选的注册 id。
      ...(modelId ? { model_id: modelId } : {}),
    }),
  });
  if (!response.ok) {
    throw await parseErrorResponse(response, "无法发起报告生成");
  }
  return parseCustomerReportGeneration(await response.json());
}

export async function fetchLatestReportGeneration(
  reportId: string,
): Promise<ReportGeneration | null> {
  const response = await fetch(reportUrl(reportId, "/generations/latest"), {
    headers: await bearerHeaders(false),
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw await parseErrorResponse(response, "无法读取最新报告生成记录");
  }
  return parseCustomerReportGeneration(await response.json());
}

export async function fetchReportGeneration(
  reportId: string,
  runId: string,
): Promise<ReportGeneration> {
  const response = await fetch(
    reportUrl(reportId, `/generations/${encodeURIComponent(runId)}`),
    { headers: await bearerHeaders(false) },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response, "无法读取报告生成进度");
  }
  return parseCustomerReportGeneration(await response.json());
}

export function isReportGenerationActive(
  status: ReportGenerationStatus,
): boolean {
  return status === "queued" || status === "running";
}

export function customerVisibleArtifacts(
  generation: ReportGeneration,
): CustomerReportGenerationArtifact[] {
  return generation.artifacts.filter(
    (artifact): artifact is CustomerReportGenerationArtifact => (
      artifact.kind === "word" || artifact.kind === "review"
    ),
  );
}

export async function downloadReportGenerationArtifact(
  artifact: ReportGenerationArtifact,
): Promise<Blob> {
  const response = await fetch(`${API_BASE}${artifact.download_href}`, {
    headers: await bearerHeaders(false),
  });
  if (!response.ok) {
    throw await parseErrorResponse(response, "无法下载报告交付物");
  }
  return response.blob();
}
