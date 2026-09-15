// ABOUTME: 披露依据与内容语言按包投影的守护测试，直接读各包 package.yaml 比对。
// ABOUTME: 准则全名是对外合规陈述，漂移一个字即错误陈述；新增包时不守护会静默漂移。
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { disclosureBasisFor, fixedStandardName, selectedStandardNames } from "./disclosure-basis";
import { listSeparatorFor, reportLanguageFor } from "./package-language";
import type { Report } from "./schema";

const here = dirname(fileURLToPath(import.meta.url));
const PACKAGES_DIR = join(here, "../../backend/data/knowledge_packages");

/** package.yaml 的极简读取：只取本测试关心的标量与字符串数组，不引 YAML 依赖。 */
function readPackageManifest(packageId: string): {
  language: string;
  mainlandSelectable: boolean;
  primaryStandardNames: string[];
} {
  const text = readFileSync(join(PACKAGES_DIR, packageId, "package.yaml"), "utf-8");
  const language = /^language:\s*(\S+)/m.exec(text)?.[1] ?? "";
  const mainlandSelectable = /mainland_standard_selectable:\s*true/.test(text);
  const primaryStandardNames: string[] = [];
  const block = /primary_standard_names:\s*\n((?:\s+-\s+.*\n?)+)/.exec(text);
  if (block) {
    for (const line of block[1].split("\n")) {
      const item = /^\s+-\s+(.*\S)\s*$/.exec(line);
      if (!item) continue;
      let value = item[1];
      if (/^".*"$/.test(value)) value = JSON.parse(value);
      primaryStandardNames.push(value);
    }
  }
  return { language, mainlandSelectable, primaryStandardNames };
}

const packageIds = readdirSync(PACKAGES_DIR, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name);

function reportForPackage(knowledgePackageId: string): Report {
  return { title: "t", fields: {}, intakeItems: [], sections: [], knowledgePackageId };
}

describe("披露依据与内容语言按包投影", () => {
  it("枚举到了全部知识包", () => {
    expect(packageIds).toContain("sse_zh_hans");
    expect(packageIds).toContain("hkex_en");
  });

  for (const packageId of packageIds) {
    const manifest = readPackageManifest(packageId);

    it(`${packageId}：内容语言与 package.yaml 一致`, () => {
      expect(reportLanguageFor(packageId)).toBe(manifest.language);
    });

    it(`${packageId}：披露依据形态与 package.yaml 一致`, () => {
      // 封存包（gri_en）不绑定 report profile、建报不可选，前端无需登记其披露依据。
      if (!(packageId in { sse_zh_hans: 1, hkex_zh_hant: 1, hkex_en: 1 })) return;
      const basis = disclosureBasisFor(packageId);
      expect(basis.selectableMainland).toBe(manifest.mainlandSelectable);
      if (!manifest.mainlandSelectable) {
        expect(basis.primaryStandardNames).toEqual(manifest.primaryStandardNames);
        // 固定准则的包：基本信息页只陈述依据，正文引用与该陈述同一文本。
        expect(fixedStandardName(reportForPackage(packageId))).toBe(manifest.primaryStandardNames[0]);
        expect(selectedStandardNames(reportForPackage(packageId))).toEqual(manifest.primaryStandardNames);
      }
    });
  }

  it("港交所报告不派生出上交所准则名", () => {
    const names = selectedStandardNames(reportForPackage("hkex_en")).join(" ");
    expect(names).not.toContain("上海证券交易所");
    expect(names).toContain("Appendix C2");
  });

  it("列表分隔符随内容语言：英文用半角逗号", () => {
    expect(listSeparatorFor("hkex_en")).toBe(", ");
    expect(listSeparatorFor("sse_zh_hans")).toBe("、");
    expect(listSeparatorFor("hkex_zh_hant")).toBe("、");
  });
});
