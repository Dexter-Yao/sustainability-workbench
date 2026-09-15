// ABOUTME: 恒生行业分类系统（HSIC）的前端受控选项，仅暴露行业与行业组两级，供港交所知识包使用。
// ABOUTME: 与国标目录同构（code/name/majorCode），同样只进报告主体语境，不驱动准则差异或议题适用性。

import {
  INDUSTRY_DIVISIONS,
  INDUSTRY_MAJOR_CATEGORIES,
  type IndustryDivision,
  type IndustryMajorCategory,
} from "./industry-catalog";

/** HSIC 第一级「行业」。繁體用語，供 hkex_zh_hant 包。 */
export const HSIC_MAJOR_CATEGORIES_ZH_HANT: IndustryMajorCategory[] = [
  { code: "10", name: "能源" },
  { code: "11", name: "原材料業" },
  { code: "12", name: "工業" },
  { code: "20", name: "非必需性消費" },
  { code: "25", name: "必需性消費" },
  { code: "30", name: "醫療保健業" },
  { code: "35", name: "金融業" },
  { code: "40", name: "資訊科技業" },
  { code: "45", name: "電訊業" },
  { code: "50", name: "公用事業" },
  { code: "60", name: "地產建築業" },
  { code: "70", name: "綜合企業" },
];

/** HSIC 第二级「行業組」。繁體用語，供 hkex_zh_hant 包。 */
export const HSIC_DIVISIONS_ZH_HANT: IndustryDivision[] = [
  { code: "1010", name: "能源設備及服務", majorCode: "10" },
  { code: "1020", name: "石油及天然氣", majorCode: "10" },
  { code: "1030", name: "煤炭", majorCode: "10" },
  { code: "1040", name: "替代能源", majorCode: "10" },
  { code: "1110", name: "化工", majorCode: "11" },
  { code: "1120", name: "建築材料", majorCode: "11" },
  { code: "1130", name: "容器及包裝", majorCode: "11" },
  { code: "1140", name: "金屬及礦物", majorCode: "11" },
  { code: "1150", name: "紙及林業產品", majorCode: "11" },
  { code: "1210", name: "航空航天及國防", majorCode: "12" },
  { code: "1220", name: "建築及工程", majorCode: "12" },
  { code: "1230", name: "電力設備", majorCode: "12" },
  { code: "1240", name: "工業工程", majorCode: "12" },
  { code: "1250", name: "工業支援服務", majorCode: "12" },
  { code: "1260", name: "機械製造", majorCode: "12" },
  { code: "1270", name: "運輸", majorCode: "12" },
  { code: "2010", name: "汽車", majorCode: "20" },
  { code: "2020", name: "耐用消費品", majorCode: "20" },
  { code: "2030", name: "紡織及服飾", majorCode: "20" },
  { code: "2040", name: "消費者服務", majorCode: "20" },
  { code: "2050", name: "媒體及娛樂", majorCode: "20" },
  { code: "2060", name: "零售業", majorCode: "20" },
  { code: "2510", name: "食物及必需消費品零售", majorCode: "25" },
  { code: "2520", name: "食品飲料", majorCode: "25" },
  { code: "2530", name: "家庭及個人用品", majorCode: "25" },
  { code: "2540", name: "農業產品", majorCode: "25" },
  { code: "3010", name: "醫療保健設備", majorCode: "30" },
  { code: "3020", name: "醫療保健服務", majorCode: "30" },
  { code: "3030", name: "製藥", majorCode: "30" },
  { code: "3040", name: "生物技術", majorCode: "30" },
  { code: "3510", name: "銀行", majorCode: "35" },
  { code: "3520", name: "保險", majorCode: "35" },
  { code: "3530", name: "證券及經紀", majorCode: "35" },
  { code: "3540", name: "其他金融", majorCode: "35" },
  { code: "4010", name: "半導體", majorCode: "40" },
  { code: "4020", name: "軟件服務", majorCode: "40" },
  { code: "4030", name: "資訊科技器材", majorCode: "40" },
  { code: "4510", name: "電訊服務", majorCode: "45" },
  { code: "5010", name: "電力", majorCode: "50" },
  { code: "5020", name: "燃氣供應", majorCode: "50" },
  { code: "5030", name: "自來水供應", majorCode: "50" },
  { code: "6010", name: "地產發展", majorCode: "60" },
  { code: "6020", name: "地產投資", majorCode: "60" },
  { code: "6030", name: "地產服務", majorCode: "60" },
  { code: "6040", name: "建築", majorCode: "60" },
  { code: "7010", name: "綜合企業", majorCode: "70" },
];

/** HSIC 第一级「行业」。英文，供 hkex_en 包。 */
export const HSIC_MAJOR_CATEGORIES_EN: IndustryMajorCategory[] = [
  { code: "10", name: "Energy" },
  { code: "11", name: "Materials" },
  { code: "12", name: "Industrials" },
  { code: "20", name: "Consumer Discretionary" },
  { code: "25", name: "Consumer Staples" },
  { code: "30", name: "Healthcare" },
  { code: "35", name: "Financials" },
  { code: "40", name: "Information Technology" },
  { code: "45", name: "Telecommunications" },
  { code: "50", name: "Utilities" },
  { code: "60", name: "Properties & Construction" },
  { code: "70", name: "Conglomerates" },
];

/** HSIC 第二级「行业组」。英文，供 hkex_en 包。 */
export const HSIC_DIVISIONS_EN: IndustryDivision[] = [
  { code: "1010", name: "Energy Equipment & Services", majorCode: "10" },
  { code: "1020", name: "Oil & Gas", majorCode: "10" },
  { code: "1030", name: "Coal", majorCode: "10" },
  { code: "1040", name: "Alternative Energy", majorCode: "10" },
  { code: "1110", name: "Chemicals", majorCode: "11" },
  { code: "1120", name: "Construction Materials", majorCode: "11" },
  { code: "1130", name: "Containers & Packaging", majorCode: "11" },
  { code: "1140", name: "Metals & Mining", majorCode: "11" },
  { code: "1150", name: "Paper & Forest Products", majorCode: "11" },
  { code: "1210", name: "Aerospace & Defense", majorCode: "12" },
  { code: "1220", name: "Construction & Engineering", majorCode: "12" },
  { code: "1230", name: "Electrical Equipment", majorCode: "12" },
  { code: "1240", name: "Industrial Engineering", majorCode: "12" },
  { code: "1250", name: "Support Services", majorCode: "12" },
  { code: "1260", name: "Machinery", majorCode: "12" },
  { code: "1270", name: "Transportation", majorCode: "12" },
  { code: "2010", name: "Automobiles", majorCode: "20" },
  { code: "2020", name: "Consumer Durables", majorCode: "20" },
  { code: "2030", name: "Textiles & Apparel", majorCode: "20" },
  { code: "2040", name: "Consumer Services", majorCode: "20" },
  { code: "2050", name: "Media & Entertainment", majorCode: "20" },
  { code: "2060", name: "Retailing", majorCode: "20" },
  { code: "2510", name: "Food & Staples Retailing", majorCode: "25" },
  { code: "2520", name: "Food & Beverages", majorCode: "25" },
  { code: "2530", name: "Household & Personal Products", majorCode: "25" },
  { code: "2540", name: "Agricultural Products", majorCode: "25" },
  { code: "3010", name: "Healthcare Equipment", majorCode: "30" },
  { code: "3020", name: "Healthcare Services", majorCode: "30" },
  { code: "3030", name: "Pharmaceuticals", majorCode: "30" },
  { code: "3040", name: "Biotechnology", majorCode: "30" },
  { code: "3510", name: "Banks", majorCode: "35" },
  { code: "3520", name: "Insurance", majorCode: "35" },
  { code: "3530", name: "Securities & Brokerage", majorCode: "35" },
  { code: "3540", name: "Other Financials", majorCode: "35" },
  { code: "4010", name: "Semiconductors", majorCode: "40" },
  { code: "4020", name: "Software & Services", majorCode: "40" },
  { code: "4030", name: "IT Hardware", majorCode: "40" },
  { code: "4510", name: "Telecommunications Services", majorCode: "45" },
  { code: "5010", name: "Electricity", majorCode: "50" },
  { code: "5020", name: "Gas Supply", majorCode: "50" },
  { code: "5030", name: "Water Supply", majorCode: "50" },
  { code: "6010", name: "Property Development", majorCode: "60" },
  { code: "6020", name: "Property Investment", majorCode: "60" },
  { code: "6030", name: "Property Services", majorCode: "60" },
  { code: "6040", name: "Construction", majorCode: "60" },
  { code: "7010", name: "Conglomerates", majorCode: "70" },
];

/** 知识包 → 行业目录。
 *
 * 内地包用国标 GB/T 4754；港交所两包用 HSIC——C2 守则本身不规定行业分类体系，
 * 但让香港发行人从国标目录里挑一项是错的口径。行业只进报告主体语境，
 * 不驱动准则差异与议题适用性，故切换目录不影响任何生成分支。
 *
 * 未知或缺失包 id 回落国标：新报告在 /api/plan 绑定包之前会短暂无值，
 * 此时按内地默认渲染与建报默认 profile 一致，不会闪现空目录。 */
export function industryCatalogFor(knowledgePackageId: string | null | undefined): {
  majorCategories: IndustryMajorCategory[];
  divisions: IndustryDivision[];
} {
  if (knowledgePackageId === "hkex_zh_hant") {
    return { majorCategories: HSIC_MAJOR_CATEGORIES_ZH_HANT, divisions: HSIC_DIVISIONS_ZH_HANT };
  }
  if (knowledgePackageId === "hkex_en") {
    return { majorCategories: HSIC_MAJOR_CATEGORIES_EN, divisions: HSIC_DIVISIONS_EN };
  }
  return { majorCategories: INDUSTRY_MAJOR_CATEGORIES, divisions: INDUSTRY_DIVISIONS };
}
