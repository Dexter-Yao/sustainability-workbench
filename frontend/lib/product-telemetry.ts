// ABOUTME: 产品使用观测的前端上报边界——页面到达与前端错误，失败静默不打扰用户。
// ABOUTME: 只上报 screenId 与受控错误类型；错误消息与堆栈留在控制台，不发往服务端。
import { API_BASE } from "./api";

/** 与后端 ScreenId 枚举同集；新增页面须两侧同步。 */
export type TelemetryScreenId =
  | "report-config"
  | "materiality-scoring"
  | "quantitative-intake"
  | "input-path"
  | "topic-questions"
  | "materials-upload"
  | "materials-processing"
  | "report-document"
  | "report-generation"
  | "reports";

export type FrontendErrorKind =
  | "render_error"
  | "unhandled_rejection"
  | "runtime_error"
  | "chunk_load_error";

/** 观测不得改变产品行为：取不到令牌或请求失败都静默返回。 */
async function post(reportId: string, path: string, body: unknown): Promise<void> {
  try {
    if (typeof window === "undefined") return;
    const { accessToken } = await import("./supabase");
    const token = await accessToken();
    if (!token) return;
    await fetch(
      `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/telemetry/${path}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
        keepalive: true,
      },
    );
  } catch {
    // 观测失败不提示、不重试、不影响用户当前操作。
  }
}

export function reportPageReached(reportId: string, screenId: TelemetryScreenId): void {
  void post(reportId, "page-reached", { screen_id: screenId });
}

export function reportPageError(
  reportId: string,
  screenId: TelemetryScreenId,
  kind: FrontendErrorKind,
): void {
  void post(reportId, "page-error", { screen_id: screenId, kind });
}

/** 依错误形态归档：具体消息可能含用户填写的企业信息，不出浏览器。 */
export function classifyError(error: unknown): FrontendErrorKind {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  if (/ChunkLoadError|Loading chunk|dynamically imported module/i.test(text)) {
    return "chunk_load_error";
  }
  return "runtime_error";
}
