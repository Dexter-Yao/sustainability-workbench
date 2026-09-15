// ABOUTME: Supabase 浏览器客户端由当前 API release 发布的公开运行时合同初始化。
// ABOUTME: 前端与 CLI 读取同一 Auth URL/anon key；浏览器永不接触服务端密钥或连接串。
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";

/** 503 = 后端刻意声明浏览器认证未配置（合法开发期降级）；其余状态视为真实初始化故障。 */
export const AUTH_NOT_CONFIGURED_HTTP_STATUS = 503;

export interface ClientRuntimeConfiguration {
  environment: string;
  supabase_project: string;
  supabase_url: string;
  supabase_anon_key: string;
  report_contract_version: string;
}

let client: SupabaseClient | null = null;
let configuration: ClientRuntimeConfiguration | null = null;
let configurationPromise: Promise<ClientRuntimeConfiguration> | null = null;

async function fetchRuntimeConfiguration(): Promise<ClientRuntimeConfiguration> {
  const response = await fetch(`${API_BASE}/api/runtime/client-config`, {
    cache: "no-store",
  });
  if (!response.ok) throw await parseErrorResponse(response, "认证运行时配置不可用");
  const payload = await response.json() as Partial<ClientRuntimeConfiguration>;
  if (
    typeof payload.supabase_url !== "string" ||
    typeof payload.supabase_anon_key !== "string" ||
    typeof payload.environment !== "string" ||
    typeof payload.supabase_project !== "string" ||
    typeof payload.report_contract_version !== "string"
  ) {
    throw new Error("认证运行时配置无效");
  }
  return payload as ClientRuntimeConfiguration;
}

export async function configureSupabase(): Promise<ClientRuntimeConfiguration> {
  if (configuration) return configuration;
  configurationPromise ??= fetchRuntimeConfiguration()
    .then((next) => {
      configuration = next;
      client = createClient(next.supabase_url, next.supabase_anon_key, {
        auth: { flowType: "implicit", detectSessionInUrl: true },
      });
      return next;
    })
    .catch((error: unknown) => {
      configurationPromise = null;
      throw error;
    });
  return configurationPromise;
}

export function supabase(): SupabaseClient {
  if (!client) throw new Error("认证运行时配置尚未加载");
  return client;
}

/** 当前会话的访问令牌；未登录返回 null。 */
export async function accessToken(): Promise<string | null> {
  await configureSupabase();
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}
