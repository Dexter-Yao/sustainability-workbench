// ABOUTME: 整节生成 API 类型——由后端 SectionGenerationResponse 严格输出合同自动生成，请勿手改。
// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。

export type BlockState = "pending" | "generating" | "ready" | "locked" | "failed" | "omitted";
export type GenerationEvidenceSelector =
  | ExplicitGenerationEvidenceSelector
  | ReportSectionGenerationEvidenceSelector
  | MaterialGatedGenerationEvidenceSelector;

/**
 * 整节生成或幂等重放的完整公共响应。
 */
export interface SectionGenerationResponse {
  batch_id: string;
  mode: "initial" | "regeneration";
  replayed: boolean;
  state_seq: number;
  results: (ParagraphGenerationResult | TableGenerationResult)[];
  section_titles: {
    [k: string]: SectionDisplayTitle;
  };
  input_fingerprint: string;
  freshness: "fresh";
  company_business_summary: string | null;
  allowance: SectionRewriteAllowance;
}
/**
 * 从 Report 正文状态投影的一项段落结果。
 */
export interface ParagraphGenerationResult {
  block_id: string;
  text: string;
}
/**
 * 从 Report 表格状态投影的一项表格结果。
 */
export interface TableGenerationResult {
  block_id: string;
  rows: GsTableRow[];
}
/**
 * 行 = Plate tr 节点 + 业务属性。
 */
export interface GsTableRow {
  type?: "tr";
  headerRow?: boolean;
  state?: BlockState | null;
  origin?: RowOrigin | null;
  generation?: GenerationSpec | null;
  appears_when?: Condition | null;
  children: GsTableCell[];
}
/**
 * AI 定行的 RowSeed 复现快照：单行重生成据此还原 seed（SSOT §3.C/§8）。from 区分 AI 定行 / 用户加行。
 */
export interface RowOrigin {
  from?: "ai" | "user";
  theme?: string | null;
  category?: string | null;
  driver_hint?: string | null;
}
/**
 * 模型生成合同；任务、证据与输出约束均须显式声明。
 */
export interface GenerationSpec {
  task: GenerationTask;
  inputs?: GenerationInputs;
  templateResidueBans?: string[] | null;
  evidenceGatedFacts?: string[] | null;
  targetChars?: [unknown, unknown] | null;
  rowCount?: [unknown, unknown] | null;
  fixedRowSeeds?: FixedRowSeed[] | null;
  presetRowSelection?: PresetRowSelection | null;
  referenceCatalog?: CatalogReference[] | null;
  rowExpansion?: RowExpansion | null;
  rowMode?: ("preset_catalog" | "adaptive_catalog" | "expanded_rows") | null;
  producesConclusion?: "topic_iro" | null;
  standardDisclosureRequirementKeys?: string[] | null;
  simplifiedWritingGuidance?: string[] | null;
  disclosureStance?: "standard" | "risk_disclosure";
}
/**
 * 生成块的唯一任务合同；不从正文占位或块类型反向推断。
 */
export interface GenerationTask {
  mode?: "standard" | "metric_narrative";
  focus: string;
  noFactGuidance?: string | null;
}
/**
 * 生成输入合同：证据选择与额外主体字段分离，不允许未消费的配置静默通过。
 */
export interface GenerationInputs {
  evidence: GenerationEvidenceSelector;
  fields?: string[];
}
/**
 * 显式证据选择器：生成块只读取声明的内容清单项和定量指标。
 */
export interface ExplicitGenerationEvidenceSelector {
  kind: "explicit";
  intakeItems?: string[];
  quantitativeMetrics?: string[];
}
/**
 * 报告章节证据选择器：摘要块继承所属 H2 的用户输入与指标目录。
 */
export interface ReportSectionGenerationEvidenceSelector {
  kind: "report_section";
}
/**
 * 证据门控选择器：块的存在性由证据判定，缺证据时整块受控省略而非方向性生成。
 *
 * 判定为「或」语义：Mapping 判定 supported/partially_supported 的文件资料，或声明的
 * intakeItems 中存在实质答案，任一满足块即出具；两者皆无时生成编排直接置
 * ``state="omitted"``，随 renderability 从正文与目录消失。纯材料门控是
 * intakeItems 为空的退化形态。
 */
export interface MaterialGatedGenerationEvidenceSelector {
  kind: "material_gated";
  intakeItems?: string[];
}
/**
 * 固定表格行种子：用于由契约声明表格行主题，生成链只补全文本内容。
 *
 * preset_catalog 表：theme=行名称锚点、category=类型（并发分组键）、referenceImpact=该行潜在影响参考口径
 * （仅供模型参考改写、不照抄，不作为正文预设）。
 */
export interface FixedRowSeed {
  theme: string;
  category?: string | null;
  driver_hint?: string | null;
  referenceImpact?: string | null;
}
/**
 * preset_catalog 行显隐合同：由结构化内容清单选择确定可生成的固定行。
 */
export interface PresetRowSelection {
  intakeItemKey: string;
  selectionMode?: "selected_only";
  unansweredBehavior?: "hide_all_rows" | "show_all_rows";
}
/**
 * adaptive_catalog 的典型参考条目：仅供前置一步据企业业务取舍/补充生成适用锚点，不强制、不作正文预设。
 *
 * category=分组类型（并发分组键，如风险/机遇）、name=条目名称、reference=典型内容/影响参考口径（供参照改写、不照抄）。
 * 与 FixedRowSeed（preset_catalog 的固定行锚点）是两个不同概念：一为参考、一为固定。
 */
export interface CatalogReference {
  category: string;
  name: string;
  reference?: string | null;
}
/**
 * 把一个业务行展开成多个披露子行的契约声明（如 IRO 表每议题＝影响行 + 风险机遇行）。
 *
 * sharedColumnKeys 每业务行只填一次、跨子行 rowSpan 合并；units 有序，顺序即表内子行顺序。
 * 与 preset_catalog 的「多业务行归一分组」方向相反，故为独立 rowMode，不复用锚点列序约定。
 */
export interface RowExpansion {
  sharedColumnKeys: string[];
  units: RowExpansionUnit[];
}
/**
 * 一个业务行内的一个披露子行：绑定本子行独占填写的列，并可在列级 options 内收窄候选。
 *
 * key 进结构化输出 schema 作字段名（不进 prompt）；label 是模型可见的子行名称（如「影响描述」）。
 */
export interface RowExpansionUnit {
  key: string;
  label: string;
  columnKeys: string[];
  optionsNarrowing?: {
    [k: string]: string[];
  } | null;
  genHintOverride?: {
    [k: string]: string;
  } | null;
}
export interface Condition {
  all?: ConditionRule[] | null;
  any?: ConditionRule[] | null;
}
export interface ConditionRule {
  path: string;
  op: "eq" | "ne" | "exists" | "not_exists" | "gt" | "in" | "contains_any";
  value?: unknown;
}
/**
 * 单元格 = Plate td/th 节点 + 业务属性。受控值存 value（保结构化类型）；options 可在单元格级覆盖列级（如 IRO 影响行/风险机遇行选项不同）。
 */
export interface GsTableCell {
  type?: "td" | "th";
  colKey?: string | null;
  value?: string | string[] | null;
  options?: string[] | null;
  colSpan?: number;
  rowSpan?: number;
  cellState?: BlockState | null;
  children?: {
    [k: string]: unknown;
  }[];
}
/**
 * 章节的实例级用户可见标题；稳定导航标题仍由 Section.title 拥有。
 */
export interface SectionDisplayTitle {
  text: string;
  origin: "generated" | "user";
  inputFingerprint: string;
}
/**
 * 整节生成完成后的服务端权威重写额度。
 */
export interface SectionRewriteAllowance {
  quota: number;
  used: number;
  reserved: number;
  remaining: number;
}
