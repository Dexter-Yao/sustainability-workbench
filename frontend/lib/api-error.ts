// ABOUTME: 后端错误响应的统一解析边界，把 detail 的多种形态收敛为携带 code 的 ApiError。
// ABOUTME: 页面据 code 与 message 给出准确提示；解析细节不散落到各 API client。

/** 后端 HTTP 错误的领域投影；code 缺失时以 http_<status> 兜底,保证可程序判定。 */
export class ApiError extends Error {
  readonly code: string;
  readonly httpStatus: number;
  readonly cellMessages: readonly string[];

  constructor(options: {
    message: string;
    code: string;
    httpStatus: number;
    cellMessages?: readonly string[];
  }) {
    super(options.message);
    this.name = "ApiError";
    this.code = options.code;
    this.httpStatus = options.httpStatus;
    this.cellMessages = options.cellMessages ?? [];
  }
}

interface DetailObject {
  code?: unknown;
  message?: unknown;
  errors?: unknown;
}

/**
 * 元数据页是模板身份载体，工作簿里对用户隐藏；把它当作单元格定位报给用户，
 * 等于让用户去一个他看不到的表里找一个内部字段。这类错误只呈现文案本身。
 */
const INTERNAL_WORKBOOK_SHEET = "_模板元数据";

function cellMessagesFrom(errors: unknown): string[] {
  if (!Array.isArray(errors)) return [];
  const composed = errors
    .map((item) => {
      if (item === null || typeof item !== "object" || !("message" in item) || typeof item.message !== "string") {
        return "";
      }
      const message = item.message.trim();
      if (!message) return "";
      const sheet = "sheet" in item && typeof item.sheet === "string" ? item.sheet.trim() : "";
      const column = "column" in item && typeof item.column === "string" ? item.column.trim() : "";
      const row = "row" in item && typeof item.row === "number" ? item.row : null;
      const location =
        sheet && sheet !== INTERNAL_WORKBOOK_SHEET && column && row !== null ? `${sheet} ${column}${row}` : "";
      return location ? `${location}：${message}` : message;
    })
    .filter(Boolean);
  // 同一句文案可能由多条元数据错误同时产出（模板整体过期时四类都会命中）；
  // 重复三遍不增加信息，只让提示更难读。
  return [...new Set(composed)].slice(0, 3);
}

/**
 * 解析后端错误响应的全部既有形态：
 * `{detail: string}`、`{detail: {code, message, errors[]}}`、`{detail: [{loc, msg}]}`（FastAPI 请求体校验）、
 * 顶层 `{code, message}`、非 JSON body。
 */
export async function parseErrorResponse(res: Response, fallback: string): Promise<ApiError> {
  const payload = (await res.json().catch(() => null)) as
    | { detail?: string | DetailObject | unknown[]; code?: unknown; message?: unknown; errors?: unknown }
    | null;
  const httpStatus = res.status;
  const fallbackCode = `http_${httpStatus}`;

  if (typeof payload?.detail === "string") {
    return new ApiError({ message: payload.detail, code: fallbackCode, httpStatus });
  }
  if (Array.isArray(payload?.detail)) {
    // FastAPI 请求体校验失败：detail 是 [{loc, msg, input}]。字段路径与 input 片段是内部细节，
    // 不进用户可见文案；但整句吞成「HTTP 422」会让缺哪个字段既不可见也不可诊断，
    // 故只把字段路径写入控制台（不带 input）。
    const paths = payload.detail
      .map((item) =>
        item !== null && typeof item === "object" && "loc" in item && Array.isArray(item.loc)
          ? item.loc.map(String).join(".")
          : "",
      )
      .filter(Boolean);
    if (paths.length) {
      console.error("请求体不符合服务端合同，字段：", paths.join("、"));
    }
    return new ApiError({
      message: `${fallback}：提交的数据不符合服务端合同。`,
      code: "request_body_invalid",
      httpStatus,
    });
  }
  if (payload?.detail && typeof payload.detail === "object") {
    const detail = payload.detail;
    if (typeof detail.message === "string") {
      return new ApiError({
        message: detail.message,
        code: typeof detail.code === "string" ? detail.code : fallbackCode,
        httpStatus,
        cellMessages: cellMessagesFrom(detail.errors),
      });
    }
  }
  if (typeof payload?.message === "string") {
    return new ApiError({
      message: payload.message,
      code: typeof payload.code === "string" ? payload.code : fallbackCode,
      httpStatus,
      cellMessages: cellMessagesFrom(payload.errors),
    });
  }
  return new ApiError({ message: `${fallback}：HTTP ${httpStatus}`, code: fallbackCode, httpStatus });
}

/** 服务端拒绝当前令牌（401）= 会话已过期；恢复动作是重新登录，而非刷新重试。 */
export function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.httpStatus === 401;
}

/** 供"固定引导 +（真实原因）"文案使用；永不抛错。 */
export function describeError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  const text = String(error ?? "").trim();
  return text || "未知错误";
}
