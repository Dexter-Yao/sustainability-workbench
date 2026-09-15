// ABOUTME: 报告与状态快照的服务端存取——JWT 走 Supabase 会话；快照载荷是 StoredReportStateV4，结构模板仍由前端合成。
// ABOUTME: putReportState 携带 base_seq 乐观锁；409 抛 StateConflictError 由调用方决定重载策略。
import { parseErrorResponse } from "./api-error";
import { API_BASE } from "./api";
import {
  parseGenerationModelOptions,
  parsePutReportState,
  parseReportList,
  parseReportProfileOptions,
  parseReportState,
  parseReportSummary,
  parseStoredReportStateValue,
} from "./contract-parser";
import type { StoredReportStateV4 } from "./stored-report-state";
import { accessToken } from "./supabase";
import type {
  GenerationModelOptionsResponse,
  ReportProfileOption,
  ReportProfileOptionsResponse,
  ReportStateResponse as ServerReportState,
  ReportSummaryResponse as ReportSummary,
} from "./report-api.generated";

export type { ReportProfileOption, ReportSummary, ServerReportState };

export class StateConflictError extends Error {
  readonly code = "report_state_conflict";
}
export class ReportNotFoundError extends Error {
  readonly code = "report_not_found";
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await accessToken();
  if (!token) throw new Error("未登录");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export async function listReports(): Promise<ReportSummary[]> {
  const res = await fetch(`${API_BASE}/api/reports`, { headers: await authHeaders() });
  if (!res.ok) throw await parseErrorResponse(res, "报告列表加载失败");
  return parseReportList(await res.json()).reports;
}

/**
 * 可创建的报告类型只有 lightweight 一种。与后端 DEFAULT_CUSTOMER_REPORT_TYPE 同源，
 * 创建端点只接受本值；调用点不各自写字面值。
 */
export const DEFAULT_CUSTOMER_REPORT_TYPE: ReportSummary["report_type"] = "lightweight";

/** 建报可选的报告配置清单；省略 reportProfileId 时由服务端选默认项。 */
export async function fetchReportProfileOptions(): Promise<ReportProfileOptionsResponse> {
  const res = await fetch(`${API_BASE}/api/reports/profiles`, { headers: await authHeaders() });
  if (!res.ok) throw await parseErrorResponse(res, "报告类型清单加载失败");
  return parseReportProfileOptions(await res.json());
}

/** 当前环境可选的生成模型清单；只含凭据齐备者，默认项由服务端给出。 */
export async function fetchGenerationModelOptions(): Promise<GenerationModelOptionsResponse> {
  const res = await fetch(`${API_BASE}/api/reports/generation-models`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw await parseErrorResponse(res, "生成模型清单加载失败");
  return parseGenerationModelOptions(await res.json());
}

export async function createReport(
  reportType: ReportSummary["report_type"] = DEFAULT_CUSTOMER_REPORT_TYPE,
  title?: string,
  reportProfileId?: string,
): Promise<ReportSummary> {
  const res = await fetch(`${API_BASE}/api/reports`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({
      report_type: reportType,
      ...(title ? { title } : {}),
      ...(reportProfileId ? { report_profile_id: reportProfileId } : {}),
    }),
  });
  if (!res.ok) throw await parseErrorResponse(res, "新建报告失败");
  return parseReportSummary(await res.json());
}

export async function archiveReport(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/reports/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok && res.status !== 204) throw await parseErrorResponse(res, "归档报告失败");
}

export async function getReportState(id: string): Promise<ServerReportState> {
  const res = await fetch(
    `${API_BASE}/api/reports/${encodeURIComponent(id)}/state`,
    { headers: await authHeaders() },
  );
  if (res.status === 404) throw new ReportNotFoundError("报告不存在或已归档");
  if (!res.ok) throw await parseErrorResponse(res, "报告状态加载失败");
  return parseReportState(await res.json());
}

export async function putReportState(
  id: string,
  state: StoredReportStateV4,
  baseSeq: number,
): Promise<number> {
  const parsedState = parseStoredReportStateValue(state);
  const res = await fetch(`${API_BASE}/api/reports/${encodeURIComponent(id)}/state`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify({ state: parsedState, base_seq: baseSeq }),
  });
  if (res.status === 409) throw new StateConflictError("状态快照已在别处更新");
  if (!res.ok) throw await parseErrorResponse(res, "报告状态保存失败");
  return parsePutReportState(await res.json()).state_seq;
}

const CURRENT_REPORT_KEY_PREFIX = "sustainability-desk:current-report-id:";
const currentReportListeners = new Set<() => void>();

function currentReportKey(accountId: string): string {
  return `${CURRENT_REPORT_KEY_PREFIX}${accountId}`;
}

export function currentReportId(accountId: string): string | null {
  return window.localStorage.getItem(currentReportKey(accountId));
}

export function setCurrentReportId(accountId: string, id: string | null): void {
  const key = currentReportKey(accountId);
  if (currentReportId(accountId) === id) return;
  if (id === null) window.localStorage.removeItem(key);
  else window.localStorage.setItem(key, id);
  for (const listener of currentReportListeners) listener();
}

export function subscribeCurrentReportId(accountId: string, listener: () => void): () => void {
  const key = currentReportKey(accountId);
  const handleStorage = (event: StorageEvent) => {
    if (event.key === key) listener();
  };
  currentReportListeners.add(listener);
  window.addEventListener("storage", handleStorage);
  return () => {
    currentReportListeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}
