// ABOUTME: 产品账户 API 合同：当前账户的权益与能力投影、首次引导已读状态。
// ABOUTME: 认证令牌仅用于调用后端；浏览器不从 Auth metadata 或 JWT claims 推断任何权益。
import { API_BASE } from "./api";
import { parseErrorResponse } from "./api-error";
import { accessToken } from "./supabase";

export interface AccountCapabilities {
  // 复用生成类型，不维护平行副本——档位改名时此处随 schema 自动跟随。
  allowed_report_section_ids: string[];
  section_regeneration_limit: number;
  can_create_report: boolean;
  /** 活跃报告上限；列表页据此在达限时预先置灰「新建报告」。 */
  active_report_limit: number;
  can_generate: boolean;
  can_regenerate_sections: boolean;
  can_export_word: boolean;
  material_agent_enabled: boolean;
  can_edit_existing: boolean;
  allowed_quantitative_metric_keys: string[];
  allowed_report_artifact_kinds: Array<"word" | "review">;
}

export interface AccountSnapshot {
  account: {
    id: string;
    email: string | null;
    organization_name: string | null;
    status: string;
    registered_at: string;
    last_active_at: string | null;
    /** 首次引导 coach mark 的已读步骤集（design.md §6.1）；旧后端缺省时视为空。 */
    onboarding_seen?: string[];
  };
  entitlement: {
    grant_id: string;
    profile_id: string;
    starts_at: string;
    ends_at: string | null;
    expired: boolean;
  };
  capabilities: AccountCapabilities;
}

async function accountApiFetch(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (cause) {
    throw new Error("无法连接账户服务，请检查网络后重试", { cause });
  }
}

async function bearerHeaders(): Promise<Record<string, string>> {
  const token = await accessToken();
  if (!token) throw new Error("登录状态已失效，请重新登录");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export async function fetchCurrentAccount(): Promise<AccountSnapshot> {
  const res = await accountApiFetch(`${API_BASE}/api/account`, { headers: await bearerHeaders() });
  if (!res.ok) throw await parseErrorResponse(res, "账户信息加载失败");
  return (await res.json()) as AccountSnapshot;
}

/** 全量替换首次引导已读步骤；空数组即「重新开启引导」。 */
export async function putOnboardingSeen(steps: string[]): Promise<string[]> {
  const res = await accountApiFetch(`${API_BASE}/api/account/onboarding-seen`, {
    method: "PUT",
    headers: await bearerHeaders(),
    body: JSON.stringify({ steps }),
  });
  if (!res.ok) throw await parseErrorResponse(res, "引导状态保存失败");
  const payload = (await res.json()) as { onboarding_seen: string[] };
  return payload.onboarding_seen;
}
