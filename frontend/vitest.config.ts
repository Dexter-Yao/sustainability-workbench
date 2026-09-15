// ABOUTME: 前端单元测试发现边界，避免 Vitest 把独立 Playwright E2E spec 当作自身测试加载。
// ABOUTME: 除 e2e/ 外沿用 Vitest 默认排除规则，现有测试发现范围保持不变。
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": new URL(".", import.meta.url).pathname,
    },
  },
  test: {
    exclude: [...configDefaults.exclude, "e2e/**"],
    // 界面语言在测试里钉死简体：既有断言验证组件行为而非文案，不应随语言切换红掉。
    setupFiles: ["./vitest.setup.ts"],
  },
});
