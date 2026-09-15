// ABOUTME: 版面验收截图：登录后逐页拍下收资界面，供人工核对对齐、面包屑与拖放区。
// ABOUTME: 除「新建报告」外沿用 request-safety 守卫阻断业务写入；产出 PNG，不做断言式视觉比对。
import { mkdirSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { isAuthenticationRequest, isReadOnlyRequest } from "./request-safety";

/**
 * 本 spec 是唯一允许新建报告的用例：既有报告均为旧契约，打开只得到升级提示页，
 * 拍不到收资界面。放行仅限「新建报告」这一条链路，生成、导出、资料写入仍被守卫阻断。
 *
 * 建报是两步：`POST /api/reports` 建库行，`PUT /api/reports/{id}/state` 写入合同默认值
 * （`lib/report-create.ts` 的唯一实现）。只放行第一步会让第二步抛错，进而跳过
 * `router.push("/intake/info")`——页面停在报告列表，截到的不是收资界面。
 */
const ALLOW_CREATE = /^\/api\/reports$/;
const ALLOW_INITIAL_STATE = /^\/api\/reports\/[^/]+\/state$/;

const OUT = `test-results/layout-screenshots${process.env.SCREENSHOT_PACKAGE ? "-" + process.env.SCREENSHOT_PACKAGE : ""}`;

test.beforeAll(() => {
  mkdirSync(OUT, { recursive: true });
});

type Page = import("@playwright/test").Page;

/** 在只读守卫之上，仅额外放行新建报告；生成、导出、资料与账户写入照旧阻断。 */
async function guardWithReportCreation(page: Page): Promise<string[]> {
  const blocked: string[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isCreateReport = request.method() === "POST" && ALLOW_CREATE.test(url.pathname);
    // 建报第二步：写入合同默认值。与 POST 同属一次「新建报告」，分开放行会让流程半途失败。
    const isInitialState = request.method() === "PUT" && ALLOW_INITIAL_STATE.test(url.pathname);
    if (
      isCreateReport
      || isInitialState
      || isReadOnlyRequest(request.method(), request.url())
      || isAuthenticationRequest(request.method(), request.url())
    ) {
      await route.continue();
      return;
    }
    blocked.push(`${request.method()} ${url.pathname}`);
    await route.abort("blockedbyclient");
  });
  return blocked;
}

/** 等待页面主体渲染完毕再截图，避免拍到骨架屏。 */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main").first()).toBeVisible();
}

/**
 * 收资各页需要「当前报告」，否则重定向回报告列表。
 *
 * 既有报告多为旧契约版本，打开只会看到「当前报告基于旧版契约创建」的升级提示页，
 * 拍不到收资界面，故本地验收新建一份当前契约的草稿。只新建、不生成、不导出。
 *
 * 环境变量 SCREENSHOT_PACKAGE 指定准则包（如 hkex_zh_hant），未设时用建报默认（上交所）。
 * 指定时**必须新建**——既有草稿的准则包不可控，复用会拍到错误的准则。
 */
const TARGET_PACKAGE = process.env.SCREENSHOT_PACKAGE ?? "";

/** 建报对话框里各包的选项文案：准则名取自服务端 display_name（各包用自己的语言）。 */
const PACKAGE_OPTION_PATTERNS: Record<string, RegExp> = {
  sse_zh_hans: /上海证券交易所/,
  hkex_zh_hant: /香港聯合交易所/,
  hkex_en: /HKEX/,
};

async function createReport(page: Page) {
  await page.getByRole("button", { name: "新建报告" }).first().click();
  const dialog = page.getByRole("radio").first();
  await expect(dialog).toBeVisible();
  if (TARGET_PACKAGE) {
    const pattern = PACKAGE_OPTION_PATTERNS[TARGET_PACKAGE];
    if (!pattern) throw new Error(`SCREENSHOT_PACKAGE 未知：${TARGET_PACKAGE}`);
    await page.getByRole("radio", { name: pattern }).check();
  }
  await page.getByRole("button", { name: "创建" }).click();
  await settle(page);
}

async function openCurrentContractReport(page: Page) {
  await page.goto("/reports");
  await settle(page);
  // 指定了准则包就必须新建；未指定时优先复用既有草稿（账户报告名额有限）。
  const open = page.getByRole("button", { name: "打开" }).first();
  if (!TARGET_PACKAGE && (await open.count())) {
    await open.click();
    await settle(page);
    return;
  }
  await createReport(page);
}

test("基本信息页：读者反馈联系三个输入框应对齐", async ({ page }) => {
  const blocked = await guardWithReportCreation(page);
  await openCurrentContractReport(page);
  await page.goto("/intake/info");
  await settle(page);
  // 建报链路一旦半途失败，页面会被重定向回报告列表而截图仍旧产出——断言当前路由，
  // 免得「拍到的不是收资界面」这类失败继续以全绿的形式通过。
  await expect(page).toHaveURL(/\/intake\/info$/);
  await page.screenshot({ path: `${OUT}/01-info-full.png`, fullPage: true });
  // 埋点被守卫拦截属预期：它不参与渲染，拦截不影响已经画出来的版面。
  const EXPECTED = [/^POST \/api\/reports\/[^/]+\/telemetry\//];
  expect(blocked.filter((entry) => !EXPECTED.some((pattern) => pattern.test(entry)))).toEqual([]);
});

test("定量信息页：面包屑不应重复分组标题，拖放区应可见", async ({ page }) => {
  const blocked = await guardWithReportCreation(page);
  await openCurrentContractReport(page);
  await page.goto("/intake/metrics");
  await settle(page);
  await expect(page).toHaveURL(/\/intake\/metrics$/);
  await page.screenshot({ path: `${OUT}/02-metrics-full.png`, fullPage: true });
  // 埋点被守卫拦截属预期：它不参与渲染，拦截不影响已经画出来的版面。
  const EXPECTED = [/^POST \/api\/reports\/[^/]+\/telemetry\//];
  expect(blocked.filter((entry) => !EXPECTED.some((pattern) => pattern.test(entry)))).toEqual([]);
});

test("重要性评分页：拖放区应可见", async ({ page }) => {
  const blocked = await guardWithReportCreation(page);
  await openCurrentContractReport(page);
  await page.goto("/intake/scoring");
  await settle(page);
  await expect(page).toHaveURL(/\/intake\/scoring$/);
  await page.screenshot({ path: `${OUT}/03-scoring-full.png`, fullPage: true });

  // 几何断言：矩阵必须整体在评分输入之上，不得与之并排或重叠。
  // 并排布局有两种失败形态——矩阵盖住输入框，或评分表被挤进不足一半的窄栏。
  // 堆叠是定稿形态，用「面板底边 ≤ 首个输入框顶边」守住。
  // 截图只拍不比，结构上发现不了这类问题；一次 boundingBox 比较即可。
  const geometry = await page.evaluate(() => {
    const panel = document.querySelector(".gs-scoring-matrix-panel");
    if (!panel) return null;
    const scoreInputs = [...document.querySelectorAll(".gs-scoring-layout input")].filter(
      (el) => (el.getAttribute("aria-label") ?? "").includes("重要性"),
    );
    if (scoreInputs.length === 0) return null;
    const firstInputTop = Math.min(...scoreInputs.map((el) => el.getBoundingClientRect().top));
    const row = scoreInputs[0].closest("div[style*=\"grid\"]");
    return {
      // >0 表示矩阵底边压过了首个输入框顶边，即回到了并排/重叠形态。
      overhang: Math.round(panel.getBoundingClientRect().bottom - firstInputTop),
      // 评分行应拿到整幅内容宽；并排时它只有一半左右。
      rowWidth: row ? Math.round(row.getBoundingClientRect().width) : 0,
      panelWidth: Math.round(panel.getBoundingClientRect().width),
    };
  });
  if (geometry !== null) {
    expect(geometry.overhang).toBeLessThanOrEqual(0);
    // 堆叠下两者同宽；并排会让评分行明显窄于面板。
    expect(geometry.rowWidth).toBeGreaterThanOrEqual(geometry.panelWidth);
  }
  // 埋点被守卫拦截属预期：它不参与渲染，拦截不影响已经画出来的版面。
  const EXPECTED = [/^POST \/api\/reports\/[^/]+\/telemetry\//];
  expect(blocked.filter((entry) => !EXPECTED.some((pattern) => pattern.test(entry)))).toEqual([]);
});
