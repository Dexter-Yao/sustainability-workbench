// ABOUTME: 登录态整页直开报告路由的门禁竞态回归——localStorage 已有报告指针时不得被弹回 /reports。
// ABOUTME: 只读链路：读取账户与报告列表、写入本地指针、直开 /intake/info；请求守卫阻断全部业务写入。
import { expect, test, type Response } from "@playwright/test";

import { guardBusinessWrites } from "./request-safety";

const pathOf = (response: Response) => new URL(response.url()).pathname;

test("登录态整页直开 /intake/info 不被弹回报告列表（账户加载竞态回归）", async ({ page }) => {
  const blocked = await guardBusinessWrites(page);

  // 只读取账户 id 与既有报告 id，不创建数据。
  const accountResponse = page.waitForResponse(
    (response) => pathOf(response) === "/api/account" && response.status() === 200,
  );
  const reportsResponse = page.waitForResponse(
    (response) => pathOf(response) === "/api/reports" && response.status() === 200,
  );
  await page.goto("/reports");
  const account = await (await accountResponse).json();
  const accountId: unknown = account?.account?.id;
  expect(typeof accountId).toBe("string");
  const reports = await (await reportsResponse).json();
  const reportId: unknown = reports?.reports?.[0]?.id;
  test.skip(
    typeof reportId !== "string",
    "账户当前没有报告，无法验证直开报告路由；无指针弹回侧已由 lib 单元测试覆盖",
  );

  // 复现原始缺陷场景：当前报告指针已在 localStorage，整页加载报告路由。
  await page.evaluate(
    ([key, value]) => window.localStorage.setItem(key, value),
    [`sustainability-desk:current-report-id:${String(accountId)}`, String(reportId)] as const,
  );
  await page.goto("/intake/info");

  // 修复前门禁会在账户解析完成前 router.replace("/reports")；修复后应等待解析并渲染本页。
  await expect(
    page.getByRole("heading", { name: "企业及报告基本信息" }),
  ).toBeVisible({ timeout: 15_000 });
  expect(new URL(page.url()).pathname).toBe("/intake/info");
  expect(blocked).toEqual([]);
});

test("已持有会话访问 /login 仍显示登录表单（多账号切换入口回归）", async ({ page }) => {
  // 「已有会话即静默跳转」会把已登录用户直接弹进工作台，多账号用户因此
  // 失去输入另一套凭据的入口。该约束只靠一行注释与 design.md 一句话守着，
  // 本用例即那道执行性防护。
  const blocked = await guardBusinessWrites(page);

  await page.goto("/login");

  // 关键断言：停在 /login，不被弹走。
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.locator('[data-screen-id="login"]')).toBeVisible();
  // 表单本身必须可用，否则「停在页面上」也换不了账号。
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
  await expect(page.getByLabel("邮箱")).toBeVisible();

  expect(blocked).toEqual([]);
});
