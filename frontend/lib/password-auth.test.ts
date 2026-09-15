// ABOUTME: 产品账户密码登录边界测试——邮箱与密码。
// ABOUTME: 锁定输入规范化、认证错误分类与不暴露具体账户状态的界面消息。
import { AuthApiError, AuthRetryableFetchError } from "@supabase/supabase-js";
import { describe, expect, it, vi } from "vitest";

import { en } from "./i18n/en";
import { zhHans } from "./i18n/zh-Hans";
import { signInErrorMessage, signInWithAccountPassword } from "./password-auth";

describe("signInWithAccountPassword", () => {
  it("trims the email and delegates password authentication", async () => {
    const signInWithPassword = vi.fn().mockResolvedValue({ error: null });
    await expect(
      signInWithAccountPassword(
        { signInWithPassword },
        { identifier: "  colleague@example.com ", kind: "email", password: "secret" },
      ),
    ).resolves.toEqual({ status: "authenticated" });
    expect(signInWithPassword).toHaveBeenCalledWith({
      email: "colleague@example.com",
      password: "secret",
    });
  });


  it.each([
    [new AuthApiError("Invalid login credentials", 400, "invalid_credentials"), "invalid_credentials"],
    [new AuthApiError("Too many requests", 429, "over_request_rate_limit"), "rate_limited"],
    [new AuthApiError("Email not confirmed", 400, "email_not_confirmed"), "account_unavailable"],
    [new AuthRetryableFetchError("Service temporarily unavailable", 503), "network_error"],
    [new AuthApiError("Unexpected failure", 500, "unexpected_failure"), "service_error"],
  ] as const)("classifies provider errors", async (error, status) => {
    const signInWithPassword = vi.fn().mockResolvedValue({ error });
    await expect(
      signInWithAccountPassword(
        { signInWithPassword },
        { identifier: "colleague@example.com", kind: "email", password: "secret" },
      ),
    ).resolves.toEqual({ status });
  });

  it("does not reveal why an account is unavailable", () => {
    // 断言取自字典而非字面量：文案随界面语言变化，而「两种失败给出各自固定文案、
    // 不透露账号是否存在」这条边界与语言无关，两种语言都必须成立。
    for (const copy of [zhHans.login, en.login]) {
      expect(signInErrorMessage({ status: "account_unavailable" }, copy)).toBe(copy.accountUnavailable);
      expect(signInErrorMessage({ status: "invalid_credentials" }, copy)).toBe(copy.invalidCredentials);
      expect(signInErrorMessage({ status: "authenticated" }, copy)).toBeNull();
    }
  });
});
