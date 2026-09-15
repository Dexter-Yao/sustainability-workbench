// ABOUTME: 前端运行时报告模板加载边界，只读取无用户状态的公开契约。
// ABOUTME: 演示实例属于测试资产，不得作为新报告或服务端快照的合成基底；模块级缓存原始 JSON，每次调用重跑 parseReport。
import type { Report } from "./schema";
import { parseReport } from "./contract-parser";

interface ReportTemplateResponse {
  ok: boolean;
  json(): Promise<unknown>;
}

type ReportTemplateFetcher = (input: string) => Promise<ReportTemplateResponse>;

// 仅缓存默认 fetch 路径的原始 JSON；测试注入的 fetcher 每次都重新取回，避免用例间串扰。
let cachedContractJson: Promise<unknown> | null = null;

async function fetchContractJson(fetcher: ReportTemplateFetcher): Promise<unknown> {
  const response = await fetcher("/contract.json");
  if (!response.ok) throw new Error("报告运行时合同加载失败");
  return response.json();
}

export async function loadReportTemplate(
  fetcher: ReportTemplateFetcher = fetch,
): Promise<Report> {
  if (fetcher !== fetch) return parseReport(await fetchContractJson(fetcher));
  cachedContractJson ??= fetchContractJson(fetcher).catch((error: unknown) => {
    cachedContractJson = null;
    throw error;
  });
  return parseReport(await cachedContractJson);
}
