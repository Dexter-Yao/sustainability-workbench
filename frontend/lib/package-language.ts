// ABOUTME: 知识包语言的前端投影，镜像各包 package.yaml 的 language 字段。
// ABOUTME(en): Per-package content language projection, mirroring each package's `language`.
// ABOUTME: 报告内容语言（这里）与界面语言是两条正交的轴：前者是报告属性、随包固定，
// ABOUTME: 后者是用户属性；本模块只回答「这份报告的正文是什么语言」。

/** 报告内容语言，与后端 contract/language.py 的 Language 同集。 */
export type ReportLanguage = "zh-Hans" | "zh-Hant" | "en";

/**
 * 各包的内容语言，与 `backend/data/knowledge_packages/<id>/package.yaml` 的 `language`
 * 逐包一致，由 `package-language.test.ts` 读 YAML 守护——新增包时不守护会静默漂移。
 */
const LANGUAGE_BY_PACKAGE: Record<string, ReportLanguage> = {
  sse_zh_hans: "zh-Hans",
  hkex_zh_hant: "zh-Hant",
  hkex_en: "en",
  gri_en: "en",
};

/** 未知或缺失包 id 回落简体：新报告在 /api/plan 绑定包之前会短暂无值。 */
export function reportLanguageFor(knowledgePackageId: string | null | undefined): ReportLanguage {
  return (knowledgePackageId && LANGUAGE_BY_PACKAGE[knowledgePackageId]) || "zh-Hans";
}

/**
 * 行内列表的分隔符，镜像后端 contract/language.py 的 LIST_SEPARATORS。
 *
 * 报告正文里的多值字段（准则名、议题名、沟通方式）按此拼接：中文用顿号、英文用逗号加空格。
 * 写死顿号会让英文正文出现「A、B」这种中文标点。
 */
export function listSeparatorFor(knowledgePackageId: string | null | undefined): string {
  return reportLanguageFor(knowledgePackageId) === "en" ? ", " : "、";
}
