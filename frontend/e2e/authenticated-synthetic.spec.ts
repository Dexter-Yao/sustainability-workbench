// ABOUTME: 登录态合成报告只读链路骨架，验证报告入口及可选资料工作区，不创建或修改数据。
// ABOUTME: SUSTAINABILITY_DESK_E2E_SYNTHETIC_REPORT_ID 只允许指向专用合成报告；请求守卫阻断全部业务写入。
import { expect, test } from "@playwright/test";
import { zhHans } from "../lib/i18n/zh-Hans";

import { guardBusinessWrites } from "./request-safety";

test("登录账户可读取报告入口，且链路不产生业务写入", async ({ page }) => {
  const blocked = await guardBusinessWrites(page);
  const syntheticReportId = process.env.SUSTAINABILITY_DESK_E2E_SYNTHETIC_REPORT_ID;

  if (syntheticReportId) {
    await page.addInitScript((reportId) => {
      window.localStorage.setItem("sustainability-desk:current-report-id", reportId);
    }, syntheticReportId);
    await page.goto("/materials");
    await expect(
      page.locator('[data-screen-id^="material-workspace"]'),
    ).toBeVisible();

  } else {
    await page.goto("/reports");
    await expect(page.locator('[data-screen-id="report-list"]')).toBeVisible();
    // 标题派生自同一事实源：硬编码标签会在更名后让用例静默失效——
    // 列表页标题的唯一真相在界面字典；e2e 默认界面语言为简体（见 playwright.config）。
    await expect(
      page.getByRole("heading", { name: zhHans.shell.allReports }),
    ).toBeVisible();
  }

  expect(blocked).toEqual([]);
});
