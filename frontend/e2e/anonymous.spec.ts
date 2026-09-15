// ABOUTME: 匿名浏览器烟测，覆盖公开登录入口的语义、标签与无写入边界。
// ABOUTME: 本测试不需要账户，不调用模型，也不向任何业务端点提交数据。
import { expect, test } from "@playwright/test";

import { guardBusinessWrites } from "./request-safety";

test("匿名用户看到可理解且可键盘操作的登录入口", async ({ page }) => {
  const blocked = await guardBusinessWrites(page);
  await page.goto("/login");

  await expect(page.locator('[data-screen-id="login"]')).toBeVisible();
  const heading = page.getByRole("heading", { name: /^登录 / });
  if (await heading.count()) {
    await expect(heading).toBeVisible();
    // 只有邮箱与密码两个字段；密码用精确匹配，避免命中「显示密码」开关的 aria-label。
    await expect(page.getByLabel("邮箱")).toBeVisible();
    await expect(page.getByLabel("密码", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "登录" })).toBeDisabled();
  } else {
    await expect(page.getByText(/认证服务未配置/)).toBeVisible();
  }
  expect(blocked).toEqual([]);
});

test("每屏至多一个 primary 按钮（design.md §9.2 规则⑤）", async ({ page }) => {
  await guardBusinessWrites(page);
  await page.goto("/login");
  await expect(page.locator('[data-screen-id="login"]')).toBeVisible();
  // Button 原语给每个按钮盖 data-gs-button-variant 章；同一路由渲染树中 primary 至多一个。
  expect(await page.locator('[data-gs-button-variant="primary"]').count()).toBeLessThanOrEqual(1);
});
