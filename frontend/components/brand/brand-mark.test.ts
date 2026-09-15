// ABOUTME: 文字字标的静态合同测试：只链接站内首页，不引用任何外部站点地址或品牌图形资产。
// ABOUTME: 认证页与报告列表共用同一组件，产品名只从 lib/product-name 读取。
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

describe("品牌字标", () => {
  it("只从产品名常量取字，链接站内首页", () => {
    const component = source("components/brand/brand-mark.tsx");
    // 字标只能从产品名的单一出口取字，组件内不写字面量。产品名是**用户可见名**
    // （当前为中性功能名，品牌未定），随界面语言，故出口是界面字典的 product 组。
    expect(component).toContain("t.product.name");
    expect(component).toContain("t.product.markCompact");
    // 紧凑标是独立文案，不得由全称截断得来。
    expect(component).not.toMatch(/t\.product\.name\.slice/);
    expect(component).toContain('href="/"');
    expect(component).not.toMatch(/https?:\/\//);
    expect(component).not.toContain("wordmark");
  });

  it("顶栏、认证页与报告列表都使用同一字标", () => {
    for (const file of [
      "components/shell/AppTopBar.tsx",
      "components/auth/account-access-frame.tsx",
      "app/login/page.tsx",
      "components/shell/ReportDirectory.tsx",
    ]) {
      const content = source(file);
      expect(content, file).toContain("BrandMark");
      expect(content, file).not.toContain("wordmark");
      expect(content, file).not.toContain("websiteUrl");
    }
  });
});
