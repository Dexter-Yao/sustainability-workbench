// ABOUTME: 报告正文页验收截图：登录后打开已生成报告，拍下全文与目录、选中段的溯源面板、就地编辑、差异、撤销、窄屏抽屉与导出前检查。
// ABOUTME: 放行本页自动保存（PUT state）与遥测，仍阻断导出、生成与资料写入；另把溯源投影响应存盘供人工核对无内部标识。
// ABOUTME: 标签取自界面字典而非写死字面量——英文报告渲染英文界面（知识包决定界面语言），
// ABOUTME: 两套断言分叉会让本 spec 只能跑一种语言。语言经 SCREENSHOT_LOCALE 指定，默认简体。
import { mkdirSync, writeFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import type { Dictionary } from "../lib/i18n/dictionary";
import { en } from "../lib/i18n/en";
import { zhHans } from "../lib/i18n/zh-Hans";
import { isAuthenticationRequest, isReadOnlyRequest } from "./request-safety";

const OUT = `test-results/report-document-screenshots${process.env.SCREENSHOT_LABEL ? "-" + process.env.SCREENSHOT_LABEL : ""}`;
const ALLOW_STATE_PUT = /^\/api\/reports\/[^/]+\/state$/;
const ALLOW_TELEMETRY = /^\/api\/reports\/[^/]+\/telemetry\//;
// Derived chart previews are rendered server-side from the posted report; they write nothing.
const ALLOW_VISUALIZATION = /^\/api\/visualizations\//;

// 两处界面语言口径不同，混用会在正确的页面上超时（本 spec 实测踩过）：
//
// - **报告正文页**跟随该报告所属知识包（LocaleDerivation + lib/i18n/locale.ts）：
//   hkex_en 的报告渲染英文界面。用 `t` 断言。
// - **报告列表页**不由目标报告决定——它取「当前活跃报告」派生值，未选过时回落
//   navigator.language。Playwright 的 Chromium 报 en-US，且活跃报告未必是本次目标，
//   故列表页语言与 SCREENSHOT_LOCALE 无关。用 `tShell` 断言。
const t: Dictionary = process.env.SCREENSHOT_LOCALE === "en" ? en : (zhHans as unknown as Dictionary);
const tShell: Dictionary = (process.env.SUSTAINABILITY_DESK_E2E_BROWSER_LOCALE ?? "en").startsWith("zh")
  ? (zhHans as unknown as Dictionary)
  : en;

/** 去掉字典模板的插值占位，取可作子串匹配的固定前缀（如「撤销上一处修改（{count}）」）。 */
function stablePrefix(template: string): string {
  const cut = template.search(/[（(]?\{/);
  return (cut === -1 ? template : template.slice(0, cut)).trim();
}

test.beforeAll(() => {
  mkdirSync(OUT, { recursive: true });
});

/** Autosave and telemetry are part of the page under test; export, generation and material writes stay blocked. */
async function guardDocumentPage(page: Page): Promise<string[]> {
  const blocked: string[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const allowed =
      isReadOnlyRequest(request.method(), request.url())
      || isAuthenticationRequest(request.method(), request.url())
      || (request.method() === "PUT" && ALLOW_STATE_PUT.test(url.pathname))
      || (request.method() === "POST" && (ALLOW_TELEMETRY.test(url.pathname) || ALLOW_VISUALIZATION.test(url.pathname)));
    if (allowed) {
      await route.continue();
      return;
    }
    blocked.push(`${request.method()} ${url.pathname}`);
    await route.abort("blockedbyclient");
  });
  return blocked;
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main").first()).toBeVisible();
}

test("报告正文页：阅读、溯源、编辑、撤销、窄屏抽屉与导出前检查", async ({ page }) => {
  test.setTimeout(180_000);
  const blocked = await guardDocumentPage(page);
  // Diagnostics for a failed run: which requests failed and what the page logged.
  page.on("requestfailed", (request) => console.log(`[requestfailed] ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`));
  page.on("pageerror", (error) => console.log(`[pageerror] ${error.message}\n${(error.stack ?? "").slice(0, 1200)}`));
  page.on("console", (message) => {
    if (message.type() === "error") console.log(`[console.error] ${message.text().slice(0, 300)}`);
  });
  const provenanceResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/generations/latest/block-provenance"),
  );

  await page.goto("/reports");
  await settle(page);
  // 环境变量 SCREENSHOT_REPORT 按报告标题片段筛选（实验 CLI 建的报告标题形如
  // 「本地轻量版 E2E <run-id>」，故传 run-id 即可精确命中某次样本运行的那份报告；
  // 主体名不在列表标题里——reportDisplayTitle 优先用真实 title）。未设时取第一份已生成报告。
  const titleFragment = process.env.SCREENSHOT_REPORT ?? "";
  // 报告列表是 <ul><li>（app/reports/page.tsx:520-526），标题与操作区是 li 内的兄弟节点，
  // 故按 li 过滤才能把「某份报告的行」与「该行的按钮」绑在一起。
  const viewButton = titleFragment
    ? page.locator("li").filter({ hasText: titleFragment }).getByRole("button", { name: tShell.reportList.viewReport }).first()
    : page.getByRole("button", { name: tShell.reportList.viewReport }).first();
  await expect(viewButton).toBeVisible();
  await viewButton.click();
  await expect(page).toHaveURL(/\/reports\/document/);
  await settle(page);
  // The report context loads template, state, config and metric catalogue before the prose renders.
  const alerts = page.getByRole("alert");
  await expect
    .poll(async () => ((await page.locator(".gs-editable").count()) > 0 ? "ready" : ((await alerts.allTextContents()).join(" | ") || "loading")), {
      timeout: 60_000,
      message: "报告正文页未渲染可编辑段落",
    })
    .toBe("ready");
  await page.screenshot({ path: `${OUT}/01-document-full.png`, fullPage: true });

  // Provenance projection: keep a copy for the manual "no internal identifiers" review.
  const provenance = await provenanceResponse;
  expect(provenance.status()).toBe(200);
  const projection = await provenance.json();
  writeFileSync(`${OUT}/block-provenance.json`, JSON.stringify(projection, null, 2));
  expect(projection.blocks.length).toBeGreaterThan(10);

  // Pick an editable paragraph that has not been edited before: autosave persists edits on the
  // synthetic report, so an aborted earlier run must not change what this run asserts. Pin the
  // block id, because the "not yet edited" locator re-resolves once the dot appears.
  const dots = page.locator(`[data-block-id] [aria-label="${t.documentNodes.edited}"]`);
  const dotsBefore = await dots.count();
  const candidate = page.locator(`.gs-editable:not(:has([aria-label="${t.documentNodes.edited}"]))`).first();
  const blockId = await candidate.getAttribute("data-block-id");
  expect(blockId).toBeTruthy();
  const paragraph = page.locator(`[data-block-id="${blockId}"]`);
  await paragraph.scrollIntoViewIfNeeded();
  await paragraph.click({ position: { x: 40, y: 12 } });
  await expect(page.locator('[data-block-id][data-selected="true"]')).toHaveCount(1);
  // 限定在溯源面板内取小节标题：英文的「Basis」很短，全页匹配会命中正文里的十处普通文字
  // （strict mode violation）。桌面态面板是 aside.gs-document-aside（窄屏时改挂 SideDrawer，
  // 本用例在窄屏段只截图、不在此断言）。
  const provenancePanel = page.locator("aside.gs-document-aside");
  await expect(provenancePanel.getByText(t.provenancePanel.sectionBasis, { exact: true })).toBeVisible();
  await page.screenshot({ path: `${OUT}/02-selected-provenance.png` });

  // Edit in place, commit with Esc, expect the modified dot, the diff and autosave.
  const editedMarker = process.env.SCREENSHOT_LOCALE === "en" ? "(Reviewer note added.)" : "（人工修订补充一句。）";
  const editedNeedle = process.env.SCREENSHOT_LOCALE === "en" ? "Reviewer note" : "人工修订";
  const original = (await paragraph.textContent())?.replace(t.documentNodes.editParagraph, "").trim() ?? "";
  await paragraph.dblclick({ position: { x: 40, y: 12 } });
  const editor = page.getByLabel(t.documentNodes.editParagraph);
  await expect(editor).toBeVisible();
  await editor.press("End");
  await editor.type(editedMarker);
  await editor.scrollIntoViewIfNeeded();
  console.log(`[diag] editor=${JSON.stringify(await editor.boundingBox())} scrollY=${await page.evaluate(() => window.scrollY)} docHeight=${await page.evaluate(() => document.documentElement.scrollHeight)}`);
  await editor.screenshot({ path: `${OUT}/03-editing.png` });
  await page.screenshot({ path: `${OUT}/03b-editing-viewport.png` });
  await editor.press("Escape");
  await expect(dots).toHaveCount(dotsBefore + 1);
  await paragraph.scrollIntoViewIfNeeded();
  await expect(provenancePanel.getByText(t.provenancePanel.sectionDiff, { exact: true })).toBeVisible();
  await expect(page.locator("ins")).toContainText(editedNeedle);
  await expect(page.locator("#coach-autosave")).toHaveText(new RegExp(t.shell.autosaved), { timeout: 15_000 });
  await provenancePanel.getByText(t.provenancePanel.sectionDiff, { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/04-edited-diff.png` });

  // Undo restores the generated prose.
  await page.getByRole("button", { name: new RegExp(stablePrefix(t.reportDocument.undo)) }).click();
  await expect(dots).toHaveCount(dotsBefore);
  await expect(paragraph).toContainText(original.slice(0, 12));
  await expect(page.locator("#coach-autosave")).toHaveText(new RegExp(t.shell.autosaved), { timeout: 15_000 });
  await paragraph.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/05-undone.png` });

  // Narrow viewport: the selection carries over and the docked panel becomes a drawer.
  await page.setViewportSize({ width: 800, height: 900 });
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: `${OUT}/06-narrow-drawer.png` });
  await page.getByRole("button", { name: t.provenancePanel.close }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Export opens the pre-export checks drawer; the real export stays blocked by the guard.
  await page.getByRole("button", { name: t.reportDocument.exportWord }).click();
  // The drawer, not the page alert: a failed diagnosis renders the "checks failed" copy as an alert.
  // (Next's route announcer is an always-present empty role=alert, so filter by text.)
  await expect(page.getByRole("dialog", { name: t.checksDrawer.heading })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: stablePrefix(t.wordExport.checksFailed) })).toHaveCount(0);
  await page.screenshot({ path: `${OUT}/07-export-checks.png` });

  const unexpected = blocked.filter((entry) => !/^POST \/api\/export/.test(entry));
  expect(unexpected).toEqual([]);
});
