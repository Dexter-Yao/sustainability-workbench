// ABOUTME: Playwright 请求安全策略的确定性合同测试。
// ABOUTME: 只读计算 POST 可运行；生成、导出、资料与报告写入必须继续被阻断。
import { expect, test } from "@playwright/test";

import {
  isAuthenticationRequest,
  isReadOnlyRequest,
} from "./request-safety";

test("只放行明确列举的只读 POST", () => {
  const origin = "http://127.0.0.1:3000";

  expect(isReadOnlyRequest("POST", `${origin}/api/plan`)).toBe(true);
  expect(
    isReadOnlyRequest(
      "POST",
      `${origin}/api/reports/report-1/sections/climate/generation-freshness`,
    ),
  ).toBe(true);

  expect(
    isReadOnlyRequest(
      "POST",
      `${origin}/api/reports/report-1/sections/climate/generations`,
    ),
  ).toBe(false);
  expect(
    isReadOnlyRequest("PUT", `${origin}/api/reports/report-1/state`),
  ).toBe(false);
  expect(
    isReadOnlyRequest("POST", `${origin}/api/reports/report-1/materials`),
  ).toBe(false);
  expect(
    isReadOnlyRequest("POST", `${origin}/api/reports/report-1/export`),
  ).toBe(false);
  expect(
    isReadOnlyRequest("POST", "https://evil.example/api/plan"),
  ).toBe(false);
  expect(
    isAuthenticationRequest(
      "POST",
      "https://evil.example/auth/v1/token",
    ),
  ).toBe(false);
});

test("只放行当前配置的认证服务 origin", () => {
  const configured = process.env.SUSTAINABILITY_DESK_E2E_AUTH_ORIGIN
    ?? "http://127.0.0.1:54321";
  expect(configured).toBeTruthy();
  if (!configured) throw new Error("测试环境未加载认证服务 origin");

  expect(
    isAuthenticationRequest(
      "POST",
      new URL("/auth/v1/token?grant_type=password", configured).toString(),
    ),
  ).toBe(true);
});
