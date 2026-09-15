// ABOUTME: 披露依据按知识包的前端投影，镜像各包 package.yaml 的 disclosure_basis。
// ABOUTME(en): Per-package disclosure basis projection, mirroring each package's `disclosure_basis`.
// ABOUTME: 基本信息页的依据陈述与报告正文的准则名引用同源于此，两处不得各写一份。
import type { Report } from "./schema";

/**
 * 一个知识包的披露依据形态。
 *
 * `selectableMainland` 为真时准则由用户在沪深北之间选择（内地包）；为假时准则由包固定
 * （港交所两包），界面只陈述依据、不渲染选择器——给港交所发行人一份沪深北单选是错的口径。
 */
interface DisclosureBasis {
  selectableMainland: boolean;
  /** 可选内地准则的全名；仅 selectableMainland 为真时有值。 */
  mainlandStandardNames?: Record<string, string>;
  /** 可加选的港交所守则名；仅内地包有值。 */
  hongKongGuideName?: string;
  /** 包固定的准则全名；仅 selectableMainland 为假时有值。 */
  primaryStandardNames?: readonly string[];
}

const SSE_MAINLAND_STANDARD_NAMES: Record<string, string> = {
  sse: "《上海证券交易所上市公司自律监管指引第14号——可持续发展报告（试行）》",
  szse: "《深圳证券交易所上市公司自律监管指引第17号——可持续发展报告（试行）》",
  bse: "《北京证券交易所上市公司持续监管指引第11号——可持续发展报告（试行）》",
};

/**
 * 各包的披露依据。文本与 `backend/data/knowledge_packages/<id>/package.yaml` 的
 * `disclosure_basis` 逐字一致，由 `disclosure-basis.test.ts` 读 YAML 守护——
 * 准则全名是合规主张的一部分，漂移一个字都是错误的对外陈述。
 */
const DISCLOSURE_BASIS_BY_PACKAGE: Record<string, DisclosureBasis> = {
  sse_zh_hans: {
    selectableMainland: true,
    mainlandStandardNames: SSE_MAINLAND_STANDARD_NAMES,
    hongKongGuideName: "《香港联合交易所有限公司环境、社会及管治报告守则》",
  },
  hkex_zh_hant: {
    selectableMainland: false,
    primaryStandardNames: ["香港聯合交易所有限公司《證券上市規則》附錄C2《環境、社會及管治報告守則》"],
  },
  hkex_en: {
    selectableMainland: false,
    primaryStandardNames: [
      'Appendix C2 "Environmental, Social and Governance Reporting Code" to the Rules Governing the Listing of Securities on The Stock Exchange of Hong Kong Limited',
    ],
  },
};

/** 未知或缺失包 id 回落内地包：新报告在 /api/plan 绑定包之前会短暂无值。 */
export function disclosureBasisFor(knowledgePackageId: string | null | undefined): DisclosureBasis {
  return (knowledgePackageId && DISCLOSURE_BASIS_BY_PACKAGE[knowledgePackageId]) || DISCLOSURE_BASIS_BY_PACKAGE.sse_zh_hans;
}

/**
 * 该报告的准则由知识包固定时给出依据陈述，可选时返回 null。
 *
 * 基本信息页据此决定渲染选择器还是只陈述依据。
 */
export function fixedStandardName(report: Report): string | null {
  const basis = disclosureBasisFor(report.knowledgePackageId);
  if (basis.selectableMainland) return null;
  return basis.primaryStandardNames?.[0] ?? null;
}

/**
 * 内地准则单选项的全名；仅内地包渲染该选择器。
 *
 * 固定准则的包不调用本函数——`fixedStandardName` 非空即表示不渲染选择器。
 */
export function mainlandStandardNames(report: Report): Record<string, string> {
  return disclosureBasisFor(report.knowledgePackageId).mainlandStandardNames ?? SSE_MAINLAND_STANDARD_NAMES;
}

/** 对外展示的准则名称列表，镜像后端 contract/report_values.py 的 selected_standard_names。 */
export function selectedStandardNames(report: Report): string[] {
  const basis = disclosureBasisFor(report.knowledgePackageId);
  const profile = report.disclosureProfile;
  const names: string[] = [];
  if (basis.selectableMainland) {
    const mainland = profile?.mainlandStandard ?? "sse";
    const mainlandNames = basis.mainlandStandardNames ?? SSE_MAINLAND_STANDARD_NAMES;
    names.push(mainlandNames[mainland] ?? mainlandNames.sse);
    if (profile?.includesHongKongExchangeGuide && basis.hongKongGuideName) {
      names.push(basis.hongKongGuideName);
    }
  } else {
    names.push(...(basis.primaryStandardNames ?? []));
  }
  for (const item of profile?.additionalDisclosureReferences ?? []) {
    const clean = String(item).trim();
    if (clean) names.push(clean);
  }
  return names;
}
