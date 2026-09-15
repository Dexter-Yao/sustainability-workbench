// ABOUTME: 报告逐块溯源投影的受保护读取客户端；响应先经后端同源合同解析，浏览器不推断任何溯源事实。
// ABOUTME(en): Protected read client for the per-block provenance projection; responses are parsed by the shared contract.

import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";
import { parseBlockProvenance } from "./contract-parser";
import type { BlockProvenanceEntry, ReportBlockProvenanceProjection } from "./report-api.generated";
import { accessToken } from "./supabase";

export type { BlockProvenanceEntry, ReportBlockProvenanceProjection };

export class ReportNotGeneratedError extends Error {
  readonly code = "report_not_generated";
}

export async function fetchBlockProvenance(reportId: string): Promise<ReportBlockProvenanceProjection> {
  const token = await accessToken();
  if (!token) throw new Error("登录状态已失效，请重新登录");
  const response = await fetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/generations/latest/block-provenance`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (response.status === 404) throw new ReportNotGeneratedError("报告尚未成功生成");
  if (!response.ok) throw await parseErrorResponse(response, "无法读取报告溯源信息");
  return parseBlockProvenance(await response.json());
}

/** Index entries by block id for O(1) lookup from the document. */
export function provenanceByBlock(
  projection: ReportBlockProvenanceProjection | null,
): Map<string, BlockProvenanceEntry> {
  return new Map((projection?.blocks ?? []).map((entry) => [entry.block_id, entry]));
}
