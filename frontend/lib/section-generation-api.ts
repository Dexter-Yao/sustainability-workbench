// ABOUTME: 整节重写的受保护 API 客户端：发起重写、查新鲜度，响应先经后端同源合同解析。
// ABOUTME: 额度、批次模式与阻断判定都由服务端裁决；浏览器按 id 请求，不自行解释能力。
"use client";

import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";
import { parseSectionGeneration } from "./contract-parser";
import type { Report } from "./schema";
import type { SectionGenerationResponse } from "./section-generation.generated";
import { accessToken } from "./supabase";

export type SectionGeneration = SectionGenerationResponse;

/** 一次重写意图：同一章节与同一 state_seq 内重试复用幂等键，输入变化才换新键。 */
export interface SectionRewriteIntent {
  reportId: string;
  sectionKey: string;
  baseStateSeq: number;
  idempotencyKey: string;
}

export function sectionRewriteIntent(
  current: SectionRewriteIntent | null,
  reportId: string,
  sectionKey: string,
  baseStateSeq: number,
  createIdempotencyKey: () => string,
): SectionRewriteIntent {
  if (
    current?.reportId === reportId
    && current.sectionKey === sectionKey
    && current.baseStateSeq === baseStateSeq
  ) {
    return current;
  }
  return { reportId, sectionKey, baseStateSeq, idempotencyKey: createIdempotencyKey() };
}

async function bearerHeaders(): Promise<Record<string, string>> {
  const token = await accessToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function sectionUrl(reportId: string, sectionKey: string, suffix: string): string {
  return `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/sections/${encodeURIComponent(sectionKey)}${suffix}`;
}

/**
 * 重写整节。
 *
 * 服务端会重新裁定门禁：本节含按资料出具的内容而报告尚无资料快照时返回 422，
 * 额度用尽返回 403，已有进行中批次或 state_seq 过期返回 409——这些都不在客户端预判。
 */
export async function regenerateSection(
  reportId: string,
  sectionKey: string,
  report: Report,
  baseStateSeq: number,
  idempotencyKey: string,
): Promise<SectionGeneration> {
  const response = await fetch(sectionUrl(reportId, sectionKey, "/generations"), {
    method: "POST",
    headers: await bearerHeaders(),
    body: JSON.stringify({
      report,
      base_state_seq: baseStateSeq,
      idempotency_key: idempotencyKey,
    }),
  });
  if (!response.ok) {
    throw await parseErrorResponse(response, "无法重写本节");
  }
  return parseSectionGeneration(await response.json());
}
