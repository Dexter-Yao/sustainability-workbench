// ABOUTME: 账户错误文案边界的回归：typed detail 必须成为可读中文，上游原文与内部标识不得上屏。
// ABOUTME: 驱动真实 parseErrorResponse，钉住「后端 detail 是对象」这一形态（否则会渲染成 [object Object]）。
import { describe, expect, it } from "vitest";

import { accountErrorMessage } from "./account-error-message";
import { ApiError, parseErrorResponse } from "./api-error";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("accountErrorMessage", () => {
  it("typed detail 经解析后是中文文案，不是 [object Object]", async () => {
    // 后端 api_error() 把 detail 填成 {code, message}；若解析器把它
    // 当字符串取出，new Error(对象) 会使界面显示 [object Object]。
    const error = await parseErrorResponse(
      jsonResponse(
        { detail: { code: "weak_password", message: "密码还需要至少 8 个字符" } },
        422,
      ),
      "暂时无法完成注册",
    );
    const message = accountErrorMessage(error, "暂时无法完成注册");

    expect(message).not.toContain("[object Object]");
    expect(message).toBe("密码强度不足，请按页面提示重新设置");
  });

  it("按稳定 code 出文案，不转述后端 message", async () => {
    const error = await parseErrorResponse(
      jsonResponse({ detail: { code: "auth_service_unavailable", message: "GoTrue upstream 502" } }, 502),
      "暂时无法完成注册",
    );

    expect(accountErrorMessage(error, "暂时无法完成注册")).toBe("认证服务暂时不可用，请稍后重试");
  });

  it("5xx 不呈现后端原文——那类消息是给运维看的", () => {
    const error = new ApiError({
      message: "Internal Server Error: asyncpg UniqueViolationError on accounts_phone_uidx",
      code: "http_500",
      httpStatus: 500,
    });
    const message = accountErrorMessage(error, "暂时无法完成注册");

    expect(message).toBe("服务暂时不可用，请稍后重试");
    expect(message).not.toContain("asyncpg");
    expect(message).not.toContain("accounts_phone_uidx");
  });

  it("4xx 的中文 detail 是面向用户的，按原样呈现", async () => {
    const error = await parseErrorResponse(
      jsonResponse({ detail: "验证码不正确或已过期，请重新获取" }, 422),
      "暂时无法完成注册",
    );

    expect(accountErrorMessage(error, "暂时无法完成注册")).toBe("验证码不正确或已过期，请重新获取");
  });

  it("非 JSON body 与未知错误都落到调用方给的中文兜底", async () => {
    const error = await parseErrorResponse(new Response("<html>502</html>", { status: 502 }), "暂时无法发送验证码");

    expect(accountErrorMessage(error, "暂时无法发送验证码")).toBe("服务暂时不可用，请稍后重试");
    expect(accountErrorMessage({ nope: true }, "暂时无法发送验证码")).toBe("暂时无法发送验证码");
  });
});
