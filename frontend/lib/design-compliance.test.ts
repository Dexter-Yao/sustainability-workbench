// ABOUTME: design.md 遵从性静态合同测试，覆盖报告正文、三线表、目录缺料点、品牌边界与设计系统稿。
// ABOUTME: §7 注册表与 screen id 双向覆盖/单页唯一、§9 调色板禁令已纳入可执行控制。
// ABOUTME: 这些断言守住用户可见设计语义与 logo 专用资产边界，不引入组件渲染依赖，也不触碰业务 schema。
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { zhHans } from "./i18n/zh-Hans";

function readProjectFile(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

function readUiSources(relativeDirectory: string): string {
  const directory = path.join(process.cwd(), relativeDirectory);

  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const relativePath = path.join(relativeDirectory, entry.name);
      if (entry.isDirectory()) return readUiSources(relativePath);
      if (!/\.(css|ts|tsx)$/.test(entry.name)) return [];
      return [readProjectFile(relativePath)];
    })
    .join("\n");
}

describe("design.md 静态视觉合同", () => {
  it("报告正文段落使用正式文档排版，H2 为 20px", () => {
    const source = readProjectFile("components/report-document/document-nodes.tsx");

    expect(source).toContain('fontFamily: "var(--font-serif)"');
    expect(source).toContain("lineHeight: 1.95");
    expect(source).toContain('textAlign: "justify"');
    expect(source).toContain('fontFamily: "var(--font-sans)"');
    expect(source).toContain("2: { size: 20");
  });

  it("报告表格使用三线表语义，不使用主色实心表头", () => {
    const source = readProjectFile("components/editor/gs-table.tsx");

    expect(source).toContain('background: "var(--surface)"');
    expect(source).toContain('borderTop: "1.5px solid var(--border-strong)"');
    expect(source).toContain('borderBottom: "1.5px solid var(--border-strong)"');
    expect(source).not.toContain('background: "var(--accent)"');
    expect(source).not.toContain("background: THEME");
  });

  it("报告目录红点只表达诊断明确缺料，不表达普通未开始", () => {
    const source = readProjectFile("components/shell/ReportDirectory.tsx");

    expect(source).toContain("sectionHasIssue(section, issues)");
    expect(source).toContain('issue.level === "block"');
    expect(source).not.toContain("state === \"pending\"");
  });

  it("三类结构化输入共用轻量外壳并返回准备概览", () => {
    const source = readProjectFile("app/intake/layout.tsx");

    expect(source).toContain("components/intake/intake-step-navigation");
    expect(source).not.toContain("previewSectionKeys");
    expect(source).not.toContain("三栏");
  });

  it("步骤位置唯一来源是左栏步骤导航（IntakeStepRail），footer 直连只有唯一共享实现", () => {
    const shared = readProjectFile("components/intake/intake-step-navigation.tsx");
    const layout = readProjectFile("app/intake/layout.tsx");
    const processing = readProjectFile("components/materials/material-processing-page.tsx");
    const directory = readProjectFile("components/shell/ReportDirectory.tsx");
    const topBar = readProjectFile("components/shell/AppTopBar.tsx");
    const stepRail = readProjectFile("components/shell/IntakeStepRail.tsx");

    expect(shared).toContain("IntakeStepFooter");
    expect(shared).not.toContain("IntakeStepNav");
    // 末步（资料处理/议题信息）自带页尾生成区，不再经由共享 footer 折返任何概览页或生成区组件。
    expect(shared).not.toContain("GenerationLaunchSection");
    // 「下一步」措辞已进界面字典（源码里不再有该字面量）：此处断言两侧同时成立——
    // 共享 footer 确实渲染该文案，且字典里的中文措辞未被改掉。
    expect(shared).toContain("t.shell.nextStep");
    expect(zhHans.shell.nextStep).toContain("下一步：");
    expect(layout).toContain("components/intake/intake-step-navigation");
    expect(layout).not.toContain('aria-label="准备步骤"');
    // 步骤数量只能来自 getIntakeSteps(scope)（design.md §3.0），承载面是左栏 IntakeStepRail；
    // 顶栏与工作台章节树都不得再渲染步骤组。
    expect(stepRail).toContain("getIntakeSteps");
    expect(topBar).not.toContain("getIntakeSteps");
    expect(directory).not.toContain("getIntakeSteps");
    expect(directory).not.toContain("报告准备");
    // 分组名已进界面字典（源码里不再有该字面量）：断言两侧同时成立——目录确实渲染
    // 该 key，且字典里的中文措辞未被改成「报告准备」一类旧口径。
    expect(directory).toContain("t.reportDirectory.sections");
    expect(zhHans.reportDirectory.sections).toBe("报告章节");
    // 页尾生成区只有唯一共享实现（materials 路径挂资料处理页尾、questions 路径挂议题信息页尾），
    // 点击成功后进入生成与交付页。
    const generationSection = readProjectFile("components/intake/generation-section.tsx");
    const questionsPage = readProjectFile("app/intake/questions/page.tsx");
    expect(generationSection).toContain('router.push("/reports/generation")');
    expect(processing).toContain("components/intake/generation-section");
    expect(questionsPage).toContain("components/intake/generation-section");
  });

  it("品牌字标字体与苔石色不进入产品 UI", () => {
    const uiSources = `${readUiSources("app")}\n${readUiSources("components")}`;

    expect(uiSources).not.toMatch(/Newsreader/i);
    expect(uiSources).not.toMatch(/#(?:A8C0B2|66826F|4E6857|374B3E)/i);
  });


  it("报告准备与资料入口遵守说明字号、最高字重与显式生成边界", () => {
    const styles = readProjectFile("app/globals.css");
    const intake = readProjectFile("components/materials/report-file-intake-page.tsx");
    // 准备概览页已废除:显式生成边界由资料处理页（末步）页尾生成区承载。
    const processing = readProjectFile("components/materials/material-processing-page.tsx");

    expect(styles).toContain("--text-overline-size: 11px");
    expect(styles).toContain("--font-weight-semibold: 600");
    // .gs-material-* 平行样式体系已按 design.md §4.0 迁入 components/ui 并删除，不得回潮。
    expect(styles).not.toContain(".gs-material");
    expect(intake).not.toContain("material-automation/lightweight");
    // 显式生成边界由末步页尾生成区（唯一共享实现）承载。
    expect(processing).toContain("GenerationSection");
  });

  it("前端禁用 Tailwind 调色板色阶与黑白字面类（§9）", () => {
    const scan = (dir: string): string => {
      let combined = "";
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { combined += scan(relativePath); continue; }
        if (!/\.tsx?$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        combined += readProjectFile(relativePath) + "\n";
      }
      return combined;
    };
    const sources = `${scan("app")}${scan("components")}`;
    expect(sources).not.toMatch(
      /(text|bg|border)-(neutral|gray|slate|zinc|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d+/,
    );
    expect(sources).not.toMatch(/(text|bg|border)-(white|black)\b/);
  });

  it("置灰 Button 必须提供 disabledReason（§4.0.1，静态检查）", () => {
    // Button 组件的 dev 断言只在运行时报 console.error；此静态检查让违规在测试层即失败，
    // 不再流到浏览器。豁免：disabledReason 条件表达式恒有值由组件自身语义保证，这里只查缺失。
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        const source = readProjectFile(relativePath);
        for (const match of source.matchAll(/<Button\b([^>]*?)>/g)) {
          const attrs = match[1];
          if (/\bdisabled[=\s]/.test(attrs) && !attrs.includes("disabledReason")) {
            violations.push(`${relativePath}:${source.slice(0, match.index).split("\n").length}`);
          }
        }
      }
    };
    scan("app");
    scan("components");
    expect(violations, "disabled 按钮必须同行给出不可用原因（disabledReason）").toEqual([]);
  });

  it("app/components 禁止十六进制色值（§9.2 规则①）", () => {
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx?$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        const source = readProjectFile(relativePath);
        if (/#[0-9a-fA-F]{3,8}\b/.test(source)) violations.push(relativePath);
      }
    };
    scan("app");
    scan("components");
    expect(violations, "十六进制色值只允许出现在 globals.css 令牌层").toEqual([]);
  });

  it("所有 var(--x) 引用都能在 globals.css 中找到声明（§9.2 规则②）", () => {
    const styles = readProjectFile("app/globals.css");
    const declared = new Set([...styles.matchAll(/(--[a-z][a-z0-9-]*)\s*:/g)].map((m) => m[1]));
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.(tsx?|css)$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        const source = readProjectFile(relativePath);
        for (const m of source.matchAll(/var\((--[a-z][a-z0-9-]*)[),]/g)) {
          if (!declared.has(m[1])) violations.push(`${relativePath}: var(${m[1]})`);
        }
      }
    };
    scan("app");
    scan("components");
    expect(violations, "引用了未在 :root 声明的令牌（--shadow-float 类缺陷）").toEqual([]);
  });

  it("标题层级使用 --text-title/section/subsection-size，不用 15px 及以上字面量（§9.2 规则③，无豁免）", () => {
    // 标题三阶令牌已齐备，页面 h1(20)/区块小标题(16)/次级(15) 都有对应令牌可用；
    // 检查③ 的 1[1-4] 覆盖不到这一带，故在此单独检查，且**不设豁免清单**：新增即红。
    // 唯一例外是报告正文（serif / 15px / 1.95），它是独立排版面，在下方 allowlist 显式登记。
    const reportBodyTypography = new Set(["components/report-document/document-nodes.tsx"]);
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        if (reportBodyTypography.has(relativePath)) continue;
        const source = readProjectFile(relativePath);
        if (/fontSize:\s*(1[5-9]|2[0-9])\b/.test(source)) violations.push(relativePath);
      }
    };
    scan("app");
    scan("components");
    expect(violations, "标题字号必须引用 --text-title/section/subsection-size 令牌").toEqual([]);
  });

  it("说明式文字使用 --text-*-size 四阶，不用 11–14px 字面量（§9.2 规则③，豁免清单只许收缩）", () => {
    // 尚未迁移到 ui 原语层的文件（工作台/editor 面）；
    // 批次重做时逐个移出，不得新增。
    const pendingMigration = new Set([
      "components/editor/checks-drawer.tsx",
      "components/editor/gs-table.tsx",
      "components/editor/keyboard-flow-bar.tsx",
      "components/editor/layout-asset-figure.tsx",
      "components/editor/matrix-image.tsx",
      "components/editor/metric-summary-image.tsx",
      "components/editor/stakeholder-engagement-table.tsx",
      "components/editor/standards-clause-annotation.tsx",
      "components/editor/topic-intake-field.tsx",
    ]);
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        if (pendingMigration.has(relativePath)) continue;
        const source = readProjectFile(relativePath);
        if (/fontSize:\s*1[1-4]\b/.test(source)) violations.push(relativePath);
      }
    };
    scan("app");
    scan("components");
    expect(violations, "说明式文字字号必须引用 --text-*-size 令牌").toEqual([]);
  });

  it("全库禁止 window.confirm / window.alert（§9.2 规则④）", () => {
    const violations: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx?$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        const source = readProjectFile(relativePath);
        if (/window\.(confirm|alert)\(/.test(source)) violations.push(relativePath);
      }
    };
    scan("app");
    scan("components");
    expect(violations, "破坏性确认必须走 components/ui/ConfirmDialog").toEqual([]);
  });

  it("页面注册表与前端 screen id 双向覆盖且单页唯一（§7）", () => {
    const design = readProjectFile("../design.md");
    const section = design.slice(design.indexOf("## 7."), design.indexOf("## 8."));
    const registryKeys = [...section.matchAll(/^\|[^|]+\| `([a-z-]+)` \|/gm)].map((m) => m[1]);
    expect(registryKeys.length).toBeGreaterThan(10);

    const idFiles = new Map<string, Set<string>>();
    const add = (id: string, file: string) => {
      const files = idFiles.get(id) ?? new Set<string>();
      files.add(file);
      idFiles.set(id, files);
    };
    const scan = (dir: string) => {
      for (const entry of readdirSync(path.join(process.cwd(), dir), { withFileTypes: true })) {
        const relativePath = path.join(dir, entry.name);
        if (entry.isDirectory()) { scan(relativePath); continue; }
        if (!/\.tsx?$/.test(entry.name) || /\.test\./.test(entry.name)) continue;
        const source = readProjectFile(relativePath);
        for (const m of source.matchAll(/(?:data-screen-id|screenId)="([^"]+)"/g)) add(m[1], relativePath);
      }
    };
    scan("app");
    scan("components");
    // intake 各步的屏 id 在布局的 SCREEN_IDS 映射里声明（屏标签派生自步骤声明，见 layout ABOUTME）。
    const layout = readProjectFile("app/intake/layout.tsx");
    for (const m of layout.matchAll(/": "([a-z-]+)"/g)) add(m[1], "app/intake/layout.tsx");

    const frontendIds = [...idFiles.keys()];
    const subStateAllowlist = new Set<string>();
    for (const key of registryKeys) {
      expect(frontendIds, `注册表 ${key} 缺少前端 screen id`).toContain(key);
    }
    for (const id of frontendIds) {
      expect(
        registryKeys.includes(id) || subStateAllowlist.has(id),
        `前端 screen id ${id} 未登记于 design.md 注册表`,
      ).toBe(true);
    }
    for (const [id, files] of idFiles) {
      expect(files.size, `screen id ${id} 应由单一页面文件声明`).toBe(1);
    }
  });
});
