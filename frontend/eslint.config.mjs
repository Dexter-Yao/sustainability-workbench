import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // 令牌回潮守护（design.md §2）：组件/页面/逻辑里禁止硬编码颜色与超重字重，逼所有视觉走设计令牌。
  {
    files: ["components/**/*.{ts,tsx}", "app/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/#[0-9A-Fa-f]{3,8}/]",
          message: "禁止硬编码 hex 颜色；请用 globals.css 的设计令牌 var(--token)（design.md §2.1）。",
        },
        {
          selector: "Property[key.name='fontWeight'][value.value>600]",
          message: "界面字重上限 600（design.md §2.2，700 界面发硬）；请勿用 700+。",
        },
      ],
      // 破坏性确认一律走 <ConfirmDialog>（design.md §4.0.1 规则③）。
      "no-restricted-properties": [
        "error",
        {
          object: "window",
          property: "confirm",
          message: "禁止 window.confirm；破坏性确认走 components/ui/ConfirmDialog（design.md §4.0.1）。",
        },
        {
          object: "window",
          property: "alert",
          message: "禁止 window.alert；使用页内 role=alert 提示或 InlineAlert（design.md §4.0.1）。",
        },
      ],
      "no-restricted-globals": [
        "error",
        { name: "confirm", message: "禁止 confirm；走 components/ui/ConfirmDialog。" },
        { name: "alert", message: "禁止 alert；使用页内 role=alert 提示或 InlineAlert。" },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright 本机运行产物（HTML 报告含压缩 JS、trace 与视频），不是源码。
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
