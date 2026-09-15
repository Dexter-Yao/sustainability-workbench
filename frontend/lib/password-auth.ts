// ABOUTME: 浏览器端密码登录边界：邮箱与密码，经认证提供方的稳定 code 分类可行动错误。
// ABOUTME: 按认证提供方稳定 code/name 分类可行动错误，同时合并可能暴露账户状态的底层原因。
import { isAuthApiError, isAuthRetryableFetchError } from "@supabase/supabase-js";

import type { Dictionary } from "./i18n/dictionary";

type PasswordCredentialsInput = { email: string; password: string };

interface PasswordAuthPort {
  signInWithPassword(credentials: PasswordCredentialsInput): Promise<{ error: unknown | null }>;
}

export type AccountCredentials = { identifier: string; kind: "email"; password: string };

export type AccountPasswordSignInResult =
  | { status: "authenticated" }
  | { status: "invalid_credentials" }
  | { status: "account_unavailable" }
  | { status: "rate_limited" }
  | { status: "network_error" }
  | { status: "service_error" };

const ACCOUNT_UNAVAILABLE_CODES = new Set([
  "email_not_confirmed",
  "user_banned",
]);

function classifyAuthError(error: unknown): AccountPasswordSignInResult {
  if (isAuthRetryableFetchError(error)) return { status: "network_error" };
  if (isAuthApiError(error)) {
    if (error.code === "invalid_credentials") return { status: "invalid_credentials" };
    if (error.code === "over_request_rate_limit") return { status: "rate_limited" };
    if (error.code === "request_timeout") return { status: "network_error" };
    if (error.code && ACCOUNT_UNAVAILABLE_CODES.has(error.code)) return { status: "account_unavailable" };
    return { status: "service_error" };
  }
  if (error instanceof Error && error.name === "AuthInvalidCredentialsError") {
    return { status: "invalid_credentials" };
  }
  return { status: "service_error" };
}

/** 登录失败的用户可见文案；措辞按界面语言，判定仍只依据 typed status，不匹配文案。 */
export function signInErrorMessage(
  result: AccountPasswordSignInResult,
  copy: Dictionary["login"],
): string | null {
  switch (result.status) {
    case "authenticated":
      return null;
    case "invalid_credentials":
      return copy.invalidCredentials;
    case "account_unavailable":
      return copy.accountUnavailable;
    case "rate_limited":
      return copy.rateLimited;
    case "network_error":
      return copy.networkError;
    case "service_error":
      return copy.serviceError;
  }
}

export async function signInWithAccountPassword(
  auth: PasswordAuthPort,
  credentials: AccountCredentials,
): Promise<AccountPasswordSignInResult> {
  const input: PasswordCredentialsInput = {
    email: credentials.identifier.trim().toLowerCase(),
    password: credentials.password,
  };
  try {
    const { error } = await auth.signInWithPassword(input);
    return error === null ? { status: "authenticated" } : classifyAuthError(error);
  } catch (error) {
    return error instanceof TypeError ? { status: "network_error" } : classifyAuthError(error);
  }
}
