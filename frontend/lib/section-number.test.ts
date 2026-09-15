// ABOUTME: 章节编号推导跨端 golden 一致性测试（前端侧）——读后端共享 fixture 跑 numberSections，断言 == expected。
// ABOUTME: 与后端 test_section_numbering_golden.py 消费同一 fixture，两端各自对 golden 成立即防编号双写漂移。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { isVisible } from "./conditions";
import type { Report, Section } from "./schema";
import { numberSections, numberingSchemeFor, type SectionNumberingScheme } from "./section-number";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, "../../backend/tests/fixtures/section_numbering_golden.json"), "utf-8"),
) as {
  cases: {
    name: string;
    report: Report;
    expected: Record<string, string>;
    scheme?: SectionNumberingScheme;
  }[];
};

describe("section numbering golden 一致性（前端 numberSections 镜像后端 number_sections）", () => {
  for (const c of fixture.cases) {
    it(c.name, () => {
      const got = numberSections(
        c.report.sections,
        (s: Section) => isVisible(s, c.report),
        c.scheme ?? "chapter_cn",
      );
      expect(Object.fromEntries(got)).toEqual(c.expected);
    });
  }
});

describe("知识包决定编号方案（防屏幕与 Word 导出所见非所得）", () => {
  it("英文包用 decimal，中文包用 chapter_cn，未绑定包回落简体默认", () => {
    // 取值须与各包 format_profile.yaml 的 numbering.section_scheme 一致：
    // 后端按该值导出 Word，前端不跟随就会出现「英文标题压着第一章」。
    expect(numberingSchemeFor("hkex_en")).toBe("decimal");
    expect(numberingSchemeFor("gri_en")).toBe("decimal");
    expect(numberingSchemeFor("hkex_zh_hant")).toBe("chapter_cn");
    expect(numberingSchemeFor("sse_zh_hans")).toBe("chapter_cn");
    expect(numberingSchemeFor(null)).toBe("chapter_cn");
  });
});
