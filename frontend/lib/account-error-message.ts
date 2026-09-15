// ABOUTME: 账户链路错误的用户可见文案边界：按后端稳定 code 决定说什么，不转述后端原文。
// ABOUTME: 账户链路各入口共用本表；上游英文与内部标识只进 console，不进界面。
import { ApiError } from "./api-error";

/** 后端 typed 契约里账户链路会出现的稳定 code；未列出的一律走通用兜底。 */
const MESSAGE_BY_CODE: Record<string, string> = {
  weak_password: "密码强度不足，请按页面提示重新设置",
  auth_service_unavailable: "认证服务暂时不可用，请稍后重试",
  active_report_limit_reached: "活跃报告已达上限，删除不再需要的报告后可新建",
};

/** HTTP 层面的通用处置：这些状态下后端 message 往往是给运维看的，不适合直接呈现。 */
const MESSAGE_BY_STATUS: Record<number, string> = {
  500: "服务暂时不可用，请稍后重试",
  502: "服务暂时不可用，请稍后重试",
  503: "服务暂时不可用，请稍后重试",
  504: "服务响应超时，请稍后重试",
};

/**
 * 把一个抛出的错误解析成可直接呈现的中文文案。
 *
 * 判定顺序是「先 code、再状态码、最后才是后端 message」：code 是领域事实，
 * 状态码决定该不该信任后端文案，而 message 只有在后端确实给出面向用户的中文时才使用。
 * 直接呈现 `error.message` 会让异常消息隐式变成用户契约——后端往异常里加一个标识符，
 * 界面立刻泄露（例如账户 UUID 经 `detail=str(exc)` 显示成错误提示）。
 */
export function accountErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    const byCode = MESSAGE_BY_CODE[cause.code];
    if (byCode) return byCode;
    const byStatus = MESSAGE_BY_STATUS[cause.httpStatus];
    if (byStatus) return byStatus;
    // 4xx 是用户可纠正的输入问题，后端此处给的是面向用户的中文。
    if (cause.httpStatus >= 400 && cause.httpStatus < 500 && cause.message.trim()) {
      return cause.message.trim();
    }
    return fallback;
  }
  // 网络中断等本地错误由调用侧构造，文案已是中文；其余一律兜底。
  if (cause instanceof Error && !(cause instanceof ApiError) && cause.message.trim()) {
    return cause.message.trim();
  }
  return fallback;
}
