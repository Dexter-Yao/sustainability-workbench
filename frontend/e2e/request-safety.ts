// ABOUTME: Playwright E2E 请求安全守卫，允许页面读取与认证换取会话，但阻断业务写入。
// ABOUTME: 合成链路不得调用生成、Judge、导出或修改报告、资料和账户状态。
import type { Page } from "@playwright/test";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const READ_ONLY_POST_PATHS = [
  /^\/api\/plan$/,
  /^\/api\/reports\/[^/]+\/diagnose$/,
  /^\/api\/reports\/[^/]+\/sections\/[^/]+\/generation-freshness$/,
  // 产品观测（page-reached / page-error）不是业务写入：payload 是受控枚举、不承载用户数据，
  // 只往 report_events 落一条观测事件，不改报告、资料或账户状态。且由 AppShell 在每个报告上下文页面自动上报，
  // 浏览器旅程无法回避——阻断它只会让只读用例误报「产生了业务写入」。
  /^\/api\/reports\/[^/]+\/telemetry\/(page-reached|page-error)$/,
];

function configuredOrigins(values: Array<string | undefined>): Set<string> {
  return new Set(
    values
      .filter((value): value is string => Boolean(value))
      .map((value) => new URL(value).origin),
  );
}

const BUSINESS_ORIGINS = configuredOrigins([
  process.env.SUSTAINABILITY_DESK_E2E_BASE_URL ?? "http://127.0.0.1:3000",
  process.env.SUSTAINABILITY_DESK_E2E_API_ORIGIN,
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8010",
]);
const AUTH_ORIGINS = configuredOrigins([
  process.env.SUSTAINABILITY_DESK_E2E_AUTH_ORIGIN,
  "http://127.0.0.1:54321",
]);

export function isAuthenticationRequest(
  method: string,
  urlValue: string,
): boolean {
  const url = new URL(urlValue);
  return (
    method === "POST"
    && AUTH_ORIGINS.has(url.origin)
    && url.pathname.endsWith("/auth/v1/token")
  );
}

export function isReadOnlyRequest(method: string, urlValue: string): boolean {
  const url = new URL(urlValue);
  if (SAFE_METHODS.has(method)) return true;
  // Next dev 开发工具的内部端点（如 /__nextjs_original-stack-frames）只存在于 dev server，
  // 与业务无关；不放行会把 dev overlay 噪音误记为业务写入。
  if (url.pathname.startsWith("/__nextjs")) return true;
  return (
    method === "POST"
    && BUSINESS_ORIGINS.has(url.origin)
    && READ_ONLY_POST_PATHS.some((pattern) => pattern.test(url.pathname))
  );
}

export async function guardBusinessWrites(page: Page): Promise<string[]> {
  const blocked: string[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (
      isReadOnlyRequest(request.method(), request.url())
      || isAuthenticationRequest(request.method(), request.url())
    ) {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    blocked.push(`${request.method()} ${url.pathname}`);
    await route.abort("blockedbyclient");
  });
  return blocked;
}
