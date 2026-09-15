// ABOUTME: 浏览器 E2E 配置，默认运行匿名只读烟测，并按环境变量启用登录态合成报告链路。
// ABOUTME: 远程登录需显式授权；测试本身通过请求守卫禁止模型调用、导出与业务写入。
import { defineConfig, devices, type Project } from "@playwright/test";
import { loadEnvConfig } from "@next/env";

loadEnvConfig(process.cwd());

const LOCAL_BASE_URL = "http://127.0.0.1:3000";
const baseURL = process.env.SUSTAINABILITY_DESK_E2E_BASE_URL ?? LOCAL_BASE_URL;
const hasCredentials = Boolean(
  process.env.SUSTAINABILITY_DESK_E2E_EMAIL && process.env.SUSTAINABILITY_DESK_E2E_PASSWORD,
);
const remoteAuthOrigin = process.env.SUSTAINABILITY_DESK_E2E_AUTH_ORIGIN;
const target = new URL(baseURL);
const isLoopback = ["127.0.0.1", "localhost", "::1"].includes(target.hostname);

if (
  hasCredentials
  && !isLoopback
  && process.env.SUSTAINABILITY_DESK_E2E_ALLOW_REMOTE_LOGIN !== "1"
) {
  throw new Error(
    "远程 E2E 登录默认关闭；确认目标为非生产测试环境后设置 SUSTAINABILITY_DESK_E2E_ALLOW_REMOTE_LOGIN=1",
  );
}
if (hasCredentials && !isLoopback && !remoteAuthOrigin) {
  throw new Error(
    "远程 E2E 登录必须通过 SUSTAINABILITY_DESK_E2E_AUTH_ORIGIN 声明页面实际使用的认证服务 origin",
  );
}
if (remoteAuthOrigin) {
  new URL(remoteAuthOrigin);
}

const projects: Project[] = [
  {
    name: "anonymous-chromium",
    testMatch: /(anonymous|request-safety)\.spec\.ts/,
    use: { ...devices["Desktop Chrome"] },
  },
];

if (hasCredentials) {
  projects.push(
    {
      name: "auth-setup",
      testMatch: /auth\.setup\.ts/,
      use: {
        trace: "off",
        screenshot: "off",
        video: "off",
      },
    },
    {
      name: "authenticated-synthetic-chromium",
      testMatch: /(authenticated-(synthetic|gate)|layout-screenshots|report-document-screenshots)\.spec\.ts/,
      dependencies: ["auth-setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "test-results/.auth/user.json",
      },
    },
  );
}

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results/artifacts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects,
  webServer: baseURL === LOCAL_BASE_URL
    ? {
        command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
        url: LOCAL_BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
});
