// ABOUTME: 可选的 Playwright 登录态建立步骤，只从环境变量读取测试账户并保存浏览器会话。
// ABOUTME: 配置不含凭据；远程目标必须通过 config 的显式非生产授权门禁。
import { mkdirSync } from "node:fs";

import { expect, test as setup, type Response } from "@playwright/test";

import { guardBusinessWrites } from "./request-safety";

const authStatePath = "test-results/.auth/user.json";

setup("使用环境变量中的测试账户建立会话", async ({ page }) => {
  const email = process.env.SUSTAINABILITY_DESK_E2E_EMAIL;
  const password = process.env.SUSTAINABILITY_DESK_E2E_PASSWORD;
  if (!email || !password) {
    throw new Error("auth-setup 只应在完整测试账户环境变量存在时运行");
  }
  const blocked = await guardBusinessWrites(page);

  await page.goto("/login");
  await page.getByLabel("邮箱").fill(email);
  // 精确匹配：密码框旁的「显示密码」眼睛开关 aria-label 也含「密码」，
  // 非精确匹配会命中两个元素而 strict mode 报错。
  await page.getByLabel("密码", { exact: true }).fill(password);
  const isAccountResponse = (response: Response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/account";
  };
  let accountResponse = page.waitForResponse(isAccountResponse);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  let response = await accountResponse;
  for (let attempt = 1; response.status() !== 200 && attempt < 3; attempt += 1) {
    accountResponse = page.waitForResponse(isAccountResponse);
    await page.reload();
    response = await accountResponse;
  }
  expect(response.status()).toBe(200);
  expect(blocked).toEqual([]);

  mkdirSync("test-results/.auth", { recursive: true });
  await page.context().storageState({ path: authStatePath });
});
