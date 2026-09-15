// ABOUTME: 章节编号推导——按可见章节树位置算每节序号，产出 Map<sectionKey, 编号前缀>；编号渲染期推导、不进数据。
// ABOUTME: 镜像后端 contract/section_number.py，同一 golden fixture 守护两端一致；可见性作注入谓词，不依赖具体实现。

import type { Section } from "./schema";

// 不参与「第N章」编号的 H1：前置说明章与附录，其子节照常编号。
const UNNUMBERED_CHAPTER_KEYS = new Set(["about_report", "company_intro", "report_appendix"]);

const CN_DIGITS = "零一二三四五六七八九";

/** 正整数转中文数字（报告章节量级，支持 1–99）。 */
function cn(n: number): string {
  if (n < 10) return CN_DIGITS.charAt(n);
  if (n === 10) return "十";
  if (n < 20) return "十" + CN_DIGITS.charAt(n - 10);
  if (n < 100) {
    const tens = Math.floor(n / 10);
    const ones = n % 10;
    return CN_DIGITS.charAt(tens) + "十" + (ones ? CN_DIGITS.charAt(ones) : "");
  }
  return String(n);
}

// chapter_cn: 第N章 / 一、 / （一） / 1.   decimal: 1 / 1.1 / 1.1.1（前置大章的整棵子树不编号，
// 故前置小节永不与章号冲突）。取值来自报告所属知识包的 format_profile.numbering.section_scheme。
export type SectionNumberingScheme = "chapter_cn" | "decimal";

// 镜像各知识包 format_profile.yaml 的 numbering.section_scheme。后端导出 Word 按同一取值
// 编号（export/docx_renderer.py 取 format_profile），前端若不跟随就会所见非所得——
// 英文包屏幕上出现「第一章」而导出是「1」。未知包按简体默认，与建报默认 profile 一致。
const PACKAGE_NUMBERING_SCHEMES: Record<string, SectionNumberingScheme> = {
  sse_zh_hans: "chapter_cn",
  hkex_zh_hant: "chapter_cn",
  hkex_en: "decimal",
  gri_en: "decimal",
};

/** 报告所属知识包的章节编号方案；未绑定包时按简体默认。 */
export function numberingSchemeFor(
  knowledgePackageId: string | null | undefined,
): SectionNumberingScheme {
  return (knowledgePackageId && PACKAGE_NUMBERING_SCHEMES[knowledgePackageId]) || "chapter_cn";
}

/** 按 headingLevel 决定编号格式（方案 A）：H1「第N章 」/ H2「N、」/ H3「（N）」。 */
function label(level: number, ordinal: number): string {
  if (level === 1) return `第${cn(ordinal)}章 `;
  if (level === 2) return `${cn(ordinal)}、`;
  if (level === 3) return `（${cn(ordinal)}）`;
  return `${ordinal}. `;
}

function hasTitle(sec: Section): boolean {
  if (sec.titleContent && sec.titleContent.length) return true;
  return !!(sec.title && sec.title.trim());
}

/**
 * 按可见章节树位置推导每节编号前缀。
 * - 序号按「同一父节点下同 headingLevel 的可见有标题兄弟」计数；格式按 headingLevel 与 scheme。
 * - 前置大章（白名单）label 为空；chapter_cn 下其子节照常从「一、」起编号，decimal 下整棵子树不编号。
 * - 空标题分组节透明：不占号，其子节并入父级同层编号。
 * - 不可见节（appears_when 不满足）不占号、不产 label。
 */
export function numberSections(
  sections: Section[],
  isVisibleFn: (sec: Section) => boolean,
  scheme: SectionNumberingScheme = "chapter_cn",
): Map<string, string> {
  const out = new Map<string, string>();

  const walk = (
    secs: Section[],
    counters: Record<number, number>,
    path: number[],
    numbered: boolean,
  ) => {
    for (const sec of secs) {
      if (!isVisibleFn(sec)) continue;
      const kids = sec.children ?? [];
      if (!hasTitle(sec)) {
        walk(kids, counters, path, numbered); // 透明分组节：子节并入父级同层编号
        continue;
      }
      const level = sec.headingLevel ?? 1;
      if (level === 1 && UNNUMBERED_CHAPTER_KEYS.has(sec.key)) {
        out.set(sec.key, "");
        walk(kids, {}, [], scheme === "chapter_cn");
        continue;
      }
      if (!numbered) {
        out.set(sec.key, "");
        walk(kids, {}, [], false);
        continue;
      }
      counters[level] = (counters[level] ?? 0) + 1;
      const currentPath = [...path, counters[level]];
      out.set(
        sec.key,
        scheme === "chapter_cn"
          ? label(level, counters[level])
          : currentPath.join(".") + " ",
      );
      walk(kids, {}, currentPath, true); // 有标题节点：子节新起一组计数
    }
  };

  walk(sections, {}, [], true);
  return out;
}
