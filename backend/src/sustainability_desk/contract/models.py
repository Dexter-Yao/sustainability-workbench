# ABOUTME: 报告契约的完整自包含 Pydantic 模型，对齐 SSOT §3——Plate 编辑与导出渲染的唯一真相源。
# ABOUTME: 每块自带内容/类型/样式/表格/图片/备注/条件；递归 Section 树承载文档层级结构。
# ABOUTME(en): Self-contained Pydantic models for the report contract (SSOT §3) — source of truth for Plate and export.
# ABOUTME(en): Each block carries content/type/style/table/image/note/condition; the Section tree holds hierarchy.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
import re
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic import Field as PydanticField  # 业务模型 class Field 遮蔽了 pydantic.Field，故以别名引入字段定义器


# 内容确定性（SSOT §4）：fixed/slot 确定 ｜ constrained/generative 由 LLM 生成。
# 资料语义：constrained=资料是前提（没有资料则保持占位、不生成、不编造公司特定事实）；
# generative=资料是增强（有资料据料贴合、没有资料走行业标杆路径生成参考稿）。
type BlockType = Literal["fixed", "slot", "constrained", "generative"]
# 生成生命周期：有效的模型输出和用户编辑内容均为 ready；omitted 是受控的无内容处置，非失败或“采纳”状态。
type BlockState = Literal[
    "pending", "generating", "ready", "locked", "failed", "omitted"
]
# 值来源（正交于 blockType）
type Source = Literal["template", "user_input", "derived", "user_doc", "assessment", "ai"]
# 结构维度 = Plate 原生节点（标题由 Section.title 承载，不再是块）
type NodeType = Literal["paragraph", "table", "image"]
type FieldType = Literal["string", "number", "year", "month", "date", "email", "percent", "url", "enum"]
type CellType = Literal["text", "single_select", "multi_select", "ai_text"]
type Mark = Literal["bold", "italic", "underline"]
type InputDefaultRule = Literal["previous_calendar_year", "reporting_year_start", "reporting_year_end"]
type CollectionPriority = Literal["core", "recommended", "optional"]
type RequiredBefore = Literal["workbench", "generation", "export"]
# 报告级主输入路径：用户在「上传现成资料由 AI 解析」与「直接回答议题引导问题」之间的二选一。
# 它是报告级事实而非资料工作区状态——生成闸与导出闸都按它裁定议题义务是否阻断，
# 两闸必须读同一侧事实（否则出现"生成得了却导不出"）。
type PrimaryInputMode = Literal["materials", "questions"]
# 议题双重重要性象限（SSOT §3.B）
type Materiality = Literal["dual", "impact", "financial", "non"]
# Topic chapter pillars (the H3 tier). Titles are package display text; code branches on ids only.
type Pillar = Literal["governance", "strategy", "iro_management", "metrics_targets"]
PILLARS: tuple[Pillar, ...] = ("governance", "strategy", "iro_management", "metrics_targets")
SOURCE_PILLARS: tuple[Pillar, ...] = PILLARS[:3]
type StakeholderType = Literal[
    "government_regulators",
    "shareholders_investors",
    "customers",
    "management",
    "employees",
    "suppliers",
    "partners",
    "community_public",
]
type EngagementMethodKind = Literal[
    "communication_channel", "participation_mechanism", "collaboration_activity"
]
type QuantitativeNoValueReason = Literal[
    "not_collected",
    "not_available",
    "not_applicable",
    "will_supplement",
]


class ReportContractModel(BaseModel):
    """Report 及其嵌套 DTO 的严格运行时边界。"""

    model_config = ConfigDict(extra="forbid")


# —— 条件（SSOT §6 可见性门控）——
class ConditionRule(ReportContractModel):
    path: str
    op: Literal["eq", "ne", "exists", "not_exists", "gt", "in", "contains_any"]
    value: object | None = None


class Condition(ReportContractModel):
    all: list[ConditionRule] | None = None
    any: list[ConditionRule] | None = None


# —— 值与行内（SSOT §3.A/B）——
class Field(ReportContractModel):
    key: str
    label: str
    type: FieldType
    source: Source
    value: str | int | float | None = None
    required: bool = False                    # 用户须填（UI 星号与 readiness 引导），不单独决定门禁阶段
    # 门禁阶段：显式声明该字段最晚必须在哪个阶段前完成。留空表示只引导不阻断。
    # 与 IntakeItem.requiredBefore 同一语义，不再由 required 隐式派生阶段。
    requiredBefore: RequiredBefore | None = None
    options: list[str] | None = None          # type=enum
    computed: dict | None = None              # source=derived：{from:[...], rule:...}
    appears_when: Condition | None = None      # 条件展示；可见时 required 才参与导出诊断

    @model_validator(mode="after")
    def _validate_typed_value(self):
        """与前端控件同源约束数值和时间字段，避免绕过 UI 的无效状态进入 Report。"""
        if self.value is None or self.value == "":
            return self
        value = str(self.value)
        if self.type == "number" and not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value):
            raise ValueError("number 字段必须是十进制数")
        if self.type == "percent":
            if not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value) or not 0 <= float(value) <= 100:
                raise ValueError("percent 字段必须是 0 至 100 的十进制数")
        if self.type == "year" and (not re.fullmatch(r"\d{4}", value) or not 1900 <= int(value) <= 9999):
            raise ValueError("year 字段必须是四位年份")
        if self.type == "month" and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("month 字段必须是 YYYY-MM")
        if self.type == "date":
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", value):
                raise ValueError("date 字段必须是 YYYY-MM-DD 日期")
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("date 字段必须是有效 YYYY-MM-DD 日期") from error
        return self


class InputGuidance(ReportContractModel):
    """用户填写体验合同：说明文字与新建报告默认规则，不承载模型或生成约束。

    helpText 与 termExplanation 是同一输入项面向用户的两段受控投影，按 design.md §2.2.1
    的归位判据分工：helpText 承载「填对这一项所必需的」（填什么/怎么填/条件依赖/直接后果），
    常驻页面；termExplanation 承载术语解释与准则背景，折进 ⓘ。两段都直接写给用户看，
    不得使用「用户……」这类第三人称或作者视角措辞。

    三段皆可缺省：标签已自明的输入项不写 helpText——复述标签只是让用户多读一行而得不到
    新信息（design.md §2.2.1）。条目可仅为 defaultRule 或 termExplanation 而存在。
    """

    helpText: str | None = PydanticField(default=None, max_length=60)
    termExplanation: str | None = PydanticField(default=None, max_length=80)
    defaultRule: InputDefaultRule | None = None

    @field_validator("helpText")
    @classmethod
    def _help_text_is_not_blank(cls, value: str | None) -> str | None:
        # 不写（None）是「标签已自明」的决定；写成空串是笔误，仍然拦掉。
        if value is not None and not value.strip():
            raise ValueError("helpText 不得为空字符串；无需说明时整项省略")
        return value


class IntakeOptionGroup(ReportContractModel):
    """内容清单选择题选项分组；用于同一道题内表达分组最小选择要求。"""

    key: str
    label: str
    options: list[str]
    minSelections: int = 0


class IntakeItem(ReportContractModel):
    """内容清单项（SSOT §3.B）：分议题内容清单的一道题 + 用户答案（定义与答案合一，仿 Field）。

    模板态 answer 为空，实例 Report 才带 answer；结构化答案为真相源，文本化仅在 build_model_context。
    """

    key: str
    contentScopeId: str
    prompt: str                               # 题干（书面语问题）
    kind: Literal["text", "single_select", "multi_select"]
    options: list[str] | None = None          # single_select/multi_select 候选项
    generationOptionLabels: dict[str, str] | None = None  # 选择项→模型可见业务标签；原始答案仍为 Report 真相源
    optionGroups: list[IntakeOptionGroup] | None = None  # 多选题分组约束；各组选项必须来自 options
    hint: str | None = PydanticField(default=None, max_length=60)          # 用户可见填写帮助（常驻）
    termExplanation: str | None = PydanticField(default=None, max_length=80)  # 用户可见术语/准则背景（折 ⓘ）
    generationBoundary: str | None = None     # agent-readable 生成边界；不在用户填写界面展示
    minChars: int | None = None               # 填空字数下限（低于则提示补足；用于原样进正文的长文本）
    maxChars: int | None = None               # 填空字数上限
    collectionPriority: CollectionPriority = "recommended"  # 只控制用户采集引导，不拥有生成或导出门禁
    requiredBefore: RequiredBefore | None = None  # 输入门禁阶段；不从 collectionPriority 推断
    answer: str | list[str] | None = None     # 结构化答案：text→str，single_select→str，multi_select→list[str]
    supplement: str | None = None             # 选择题的补充说明文字（重要内容；与 answer 一并喂入生成）

    @model_validator(mode="after")
    def _validate_option_groups(self):
        if self.generationOptionLabels:
            if self.kind not in ("single_select", "multi_select"):
                raise ValueError("generationOptionLabels 仅适用于选择题内容清单项")
            allowed = set(self.options or [])
            unknown = [option for option in self.generationOptionLabels if option not in allowed]
            if unknown:
                raise ValueError(f"generationOptionLabels 包含未声明选项：{unknown}")
            empty_labels = [
                option
                for option, label in self.generationOptionLabels.items()
                if not str(label).strip()
            ]
            if empty_labels:
                raise ValueError(f"generationOptionLabels 包含空模型标签：{empty_labels}")
        if not self.optionGroups:
            return self
        if self.kind != "multi_select":
            raise ValueError("optionGroups 仅适用于 multi_select 内容清单项")
        allowed = set(self.options or [])
        seen: set[str] = set()
        for group in self.optionGroups:
            if group.minSelections < 0:
                raise ValueError(f"选项分组 {group.key} 的 minSelections 不得小于 0")
            if group.minSelections > len(group.options):
                raise ValueError(f"选项分组 {group.key} 的 minSelections 不得大于该组选项数量")
            unknown = [option for option in group.options if option not in allowed]
            if unknown:
                raise ValueError(f"选项分组 {group.key} 包含未声明选项：{unknown}")
            overlap = [option for option in group.options if option in seen]
            if overlap:
                raise ValueError(f"选项分组 {group.key} 与其他分组重复声明选项：{overlap}")
            seen.update(group.options)
        return self


class Inline(ReportContractModel):
    kind: Literal["text", "ref"]
    text: str | None = None                   # kind=text
    ref: str | None = None                    # kind=ref → Field.key 或 assessment 路径
    fallback: str | None = None
    marks: list[Mark] | None = None


# —— 生成规格（SSOT §3.B）——
class ExplicitGenerationEvidenceSelector(ReportContractModel):
    """显式证据选择器：生成块只读取声明的内容清单项和定量指标。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["explicit"]
    intakeItems: list[str] = PydanticField(default_factory=list)
    quantitativeMetrics: list[str] = PydanticField(default_factory=list)


class ReportSectionGenerationEvidenceSelector(ReportContractModel):
    """报告章节证据选择器：摘要块继承所属 H2 的用户输入与指标目录。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["report_section"]


class MaterialGatedGenerationEvidenceSelector(ReportContractModel):
    """证据门控选择器：块的存在性由证据判定，缺证据时整块受控省略而非方向性生成。

    判定为「或」语义：Mapping 判定 supported/partially_supported 的文件资料，或声明的
    intakeItems 中存在实质答案，任一满足块即出具；两者皆无时生成编排直接置
    ``state="omitted"``，随 renderability 从正文与目录消失。纯材料门控是
    intakeItems 为空的退化形态。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["material_gated"]
    intakeItems: list[str] = PydanticField(default_factory=list)


type GenerationEvidenceSelector = Annotated[
    ExplicitGenerationEvidenceSelector
    | ReportSectionGenerationEvidenceSelector
    | MaterialGatedGenerationEvidenceSelector,
    PydanticField(discriminator="kind"),
]


class GenerationInputs(ReportContractModel):
    """生成输入合同：证据选择与额外主体字段分离，不允许未消费的配置静默通过。"""

    model_config = ConfigDict(extra="forbid")

    evidence: GenerationEvidenceSelector
    fields: list[str] = PydanticField(default_factory=list)


class GenerationTask(ReportContractModel):
    """生成块的唯一任务合同；不从正文占位或块类型反向推断。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["standard", "metric_narrative"] = "standard"
    focus: str
    noFactGuidance: str | None = None


class FixedRowSeed(ReportContractModel):
    """固定表格行种子：用于由契约声明表格行主题，生成链只补全文本内容。

    preset_catalog 表：theme=行名称锚点、category=类型（并发分组键）、referenceImpact=该行潜在影响参考口径
    （仅供模型参考改写、不照抄，不作为正文预设）。
    """

    theme: str
    category: str | None = None
    driver_hint: str | None = None
    referenceImpact: str | None = None


class CatalogReference(ReportContractModel):
    """adaptive_catalog 的典型参考条目：仅供前置一步据企业业务取舍/补充生成适用锚点，不强制、不作正文预设。

    category=分组类型（并发分组键，如风险/机遇）、name=条目名称、reference=典型内容/影响参考口径（供参照改写、不照抄）。
    与 FixedRowSeed（preset_catalog 的固定行锚点）是两个不同概念：一为参考、一为固定。
    """

    category: str
    name: str
    reference: str | None = None


class PresetRowSelection(ReportContractModel):
    """preset_catalog 行显隐合同：由结构化内容清单选择确定可生成的固定行。"""

    intakeItemKey: str
    selectionMode: Literal["selected_only"] = "selected_only"
    unansweredBehavior: Literal["hide_all_rows", "show_all_rows"] = "hide_all_rows"


class RowExpansionUnit(ReportContractModel):
    """一个业务行内的一个披露子行：绑定本子行独占填写的列，并可在列级 options 内收窄候选。

    key 进结构化输出 schema 作字段名（不进 prompt）；label 是模型可见的子行名称（如「影响描述」）。
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    columnKeys: list[str]                                  # 本子行独占填写的列；各 unit 之间互斥
    optionsNarrowing: dict[str, list[str]] | None = None   # 列key → 本子行候选（须为该列 options 子集）
    genHintOverride: dict[str, str] | None = None          # 列key → 本子行专属写作要求（覆盖列级 genHint）


class RowExpansion(ReportContractModel):
    """把一个业务行展开成多个披露子行的契约声明（如 IRO 表每议题＝影响行 + 风险机遇行）。

    sharedColumnKeys 每业务行只填一次、跨子行 rowSpan 合并；units 有序，顺序即表内子行顺序。
    与 preset_catalog 的「多业务行归一分组」方向相反，故为独立 rowMode，不复用锚点列序约定。
    """

    model_config = ConfigDict(extra="forbid")

    sharedColumnKeys: list[str]
    units: list[RowExpansionUnit]


# 报告级结论：由某个块产出、供其余块作方向参照的跨块判断。
# 生成编排据此排阶段（产出方先于其余块），不认具体 block id。
# 消费方不需声明——结论按议题归属由 ModelContext 自行解析；
# 结论是方向增强而非前置条件：缺失时其余块照常生成，只是少一层校准。
ConclusionKind = Literal["topic_iro"]


class GenerationSpec(ReportContractModel):
    """模型生成合同；任务、证据与输出约束均须显式声明。"""

    model_config = ConfigDict(extra="forbid")

    task: GenerationTask
    inputs: GenerationInputs = PydanticField(
        default_factory=lambda: GenerationInputs(
            evidence=ExplicitGenerationEvidenceSelector(kind="explicit")
        )
    )
    # 参考模板残留物拦截：模板原型公司的专名、示例数值与编写批注不得出现在任何公司报告里。
    # 只登记「在任何报告中出现都是错的」的字面串——议题词汇、报告年份、通用管理表述不属此列，
    # 那类判断是语义边界，归 evidence_posture 与 judge，不归词面拦截。
    templateResidueBans: list[str] | None = None
    # Evidence-gated facts: surfaces (e.g. a penalty, an exceedance) the output may state only when the
    # block's visible evidence carries them; negated evidence must not be affirmed. Package data, not code.
    evidenceGatedFacts: list[str] | None = None
    targetChars: tuple[int, int] | None = None    # 段落字数软区间 [min,max]（软校验，非硬阻断）
    rowCount: tuple[int, int] | None = None        # 表格行数区间 [min,max]
    fixedRowSeeds: list[FixedRowSeed] | None = None  # 固定行表格的行主题清单；存在时跳过 AI 定行（含 preset_catalog 固定锚点）
    presetRowSelection: PresetRowSelection | None = None  # preset_catalog 固定行的结构化选择来源；不从题干或 block id 推断
    referenceCatalog: list[CatalogReference] | None = None  # adaptive_catalog 的典型参考清单（供前置生成据业务取舍/补充，不强制）
    rowExpansion: RowExpansion | None = None  # 一业务行展开为多披露子行；共享列跨子行合并，子行列各自填写
    rowMode: Literal["preset_catalog", "adaptive_catalog", "expanded_rows"] | None = None  # 目录表生成形态：preset_catalog=固定锚点整表填充；adaptive_catalog=前置生成适用锚点再整表填充；expanded_rows=每业务行按 rowExpansion 展开为多子行
    producesConclusion: ConclusionKind | None = None  # 本块产出可供其余块参照的报告级结论；声明后它先于其余块生成
    standardDisclosureRequirementKeys: list[str] | None = None        # → standard_disclosure_requirements 准则披露要求 key
    # 字段名的 simplified 是公开契约（已流到前端 schema）；内部实现已统一为 lightweight，
    # 待下次契约版本变更时一并收敛（docs/todos.md）。
    simplifiedWritingGuidance: list[str] | None = None                # 轻量版写作颗粒度和距离感；仅 lightweight 生成注入
    disclosureStance: Literal["standard", "risk_disclosure"] = "standard"   # 披露立场：standard=常规叙述（缺失/负面检查全开）；risk_disclosure=风险与不利事项披露块（描述风险本身不算负面，在线 L1 跳过缺失负面一项、离线 judge 据此放宽并仍判公司自身短板）


# —— 评估结果（SSOT §3.B；本期消费上传评分表）——
class IROItem(ReportContractModel):
    kind: Literal["impact", "risk", "opportunity"]
    description: str | None = None
    classes: list[str] | None = None
    valueChain: list[str] | None = None
    timeHorizon: list[str] | None = None
    state: BlockState | None = None


class AssessmentCounts(ReportContractModel):
    dual: int = 0
    impact_only: int = 0
    financial_only: int = 0
    non_material: int = 0
    total: int = 0


class MaterialityThreshold(ReportContractModel):
    financial: float
    impact: float


class MaterialityScoreInput(ReportContractModel):
    """用户为一个 scored 评分议题提供的原始双重重要性输入。"""

    model_config = ConfigDict(extra="forbid")

    assessmentTopicId: str
    financialScore: float
    impactScore: float
    iroItems: list[IROItem] | None = None


class MaterialityAssessmentInput(ReportContractModel):
    """重要性评估的持久化输入；固定分类与计数均不在此重复保存。"""

    model_config = ConfigDict(extra="forbid")

    reportingYear: int
    threshold: MaterialityThreshold
    scores: list[MaterialityScoreInput] = []


class ScoredAssessmentResult(ReportContractModel):
    model_config = ConfigDict(extra="forbid")

    assessmentTopicId: str
    determination: Literal["scored"] = "scored"
    materiality: Materiality
    financialScore: float
    impactScore: float
    iroItems: list[IROItem] | None = None


class FixedAssessmentResult(ReportContractModel):
    model_config = ConfigDict(extra="forbid")

    assessmentTopicId: str
    determination: Literal["fixed"] = "fixed"
    materiality: Materiality


AssessmentTopicResult = Annotated[
    ScoredAssessmentResult | FixedAssessmentResult,
    PydanticField(discriminator="determination"),
]


class MaterialityLabels(ReportContractModel):
    dual: str
    impact: str
    financial: str
    non: str


class MaterialityAxisLabels(ReportContractModel):
    financial: str
    impact: str


class IroKindLabels(ReportContractModel):
    impact: str
    risk: str
    opportunity: str
    risk_opportunity: str


class ImpactClassLabels(ReportContractModel):
    actual_positive: str
    potential_positive: str
    potential_negative: str


class AssessmentVocabulary(ReportContractModel):
    """Display vocabulary of the materiality assessment, owned by the package contract.

    Materiality categories, matrix axis names, IRO kinds and impact classes are rendered into
    tables, charts and model context from here; code branches on the typed slots, never on the words.
    """

    materiality: MaterialityLabels
    materialityAxes: MaterialityAxisLabels
    iroKind: IroKindLabels
    impactClass: ImpactClassLabels


class QuantitativeMetricsVocabulary(ReportContractModel):
    """Package-owned wording of the quantitative metrics table that is validated or printed.

    The greenhouse gas accounting standard is a controlled choice: the option list and the "other"
    sentinel must exist in the package's language, so they are contract data rather than code.
    """

    greenhouseGasAccountingStandards: list[str]
    otherStandardLabel: str
    # Review-only remark naming the standard behind a greenhouse gas value; "{standard}" is substituted.
    accountingStandardRemarkTemplate: str
    # Joins the standard remark with the user's own note inside one remark cell.
    remarkSeparator: str
    # User-facing wording of each QuantitativeNoValueReason, printed on the workbook's instruction sheet.
    # Same reasoning as the accounting standards: it is read by the user, so it must be in the package's
    # language and therefore belongs to contract data rather than a shared code constant.
    noValueReasonLabels: dict[QuantitativeNoValueReason, str]

    @model_validator(mode="after")
    def _validate_choices(self) -> "QuantitativeMetricsVocabulary":
        standards = [item.strip() for item in self.greenhouseGasAccountingStandards]
        if not standards or any(not item for item in standards) or len(set(standards)) != len(standards):
            raise ValueError("greenhouseGasAccountingStandards must be distinct non-empty names")
        if not self.otherStandardLabel.strip() or self.otherStandardLabel in standards:
            raise ValueError("otherStandardLabel must be non-empty and distinct from the named standards")
        if "{standard}" not in self.accountingStandardRemarkTemplate:
            raise ValueError("accountingStandardRemarkTemplate must contain {standard}")
        # Every reason needs wording: a missing key would print a bare enum value into the workbook.
        expected = set(get_args(QuantitativeNoValueReason.__value__))
        if set(self.noValueReasonLabels) != expected:
            raise ValueError(f"noValueReasonLabels must name exactly {sorted(expected)}")
        if any(not label.strip() for label in self.noValueReasonLabels.values()):
            raise ValueError("noValueReasonLabels must not carry empty wording")
        return self


class AssessmentScoreScale(ReportContractModel):
    """双重重要性原始评分尺度：模板声明，导入、录入和 Report 校验共同使用。"""

    minimumExclusive: float
    maximum: float
    multipleOf: float
    # 双重重要性两个维度的用户可见释义，按 design.md §2.2.1 分两段：
    # Definition 常驻（这个维度衡量什么），Explanation 折进 ⓘ（打分后如何影响报告）。
    # 网页与评分表 Excel 共用同一份，避免释义只存在于其中一端。
    financialMaterialityDefinition: str = PydanticField(default="", max_length=60)
    financialMaterialityExplanation: str = PydanticField(default="", max_length=80)
    impactMaterialityDefinition: str = PydanticField(default="", max_length=60)
    impactMaterialityExplanation: str = PydanticField(default="", max_length=80)

    @model_validator(mode="after")
    def _valid_range_and_increment(self):
        if not all(isfinite(value) for value in (self.minimumExclusive, self.maximum, self.multipleOf)):
            raise ValueError("评分尺度必须是有限数值")
        if not self.minimumExclusive < self.maximum:
            raise ValueError("评分尺度的 maximum 必须大于 minimumExclusive")
        if self.multipleOf <= 0:
            raise ValueError("评分尺度的 multipleOf 必须大于 0")
        return self


class AssessmentResult(ReportContractModel):
    reportingYear: int
    topics: list[AssessmentTopicResult] = []
    threshold: MaterialityThreshold | None = None


# —— 利益相关方沟通（SSOT §3.E）——
class CustomEngagementMethod(ReportContractModel):
    """用户补充的沟通、参与或合作方式；类别用于确定性排序，正文只呈现 label。"""

    kind: EngagementMethodKind
    label: str

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str) -> str:
        label = value.strip()
        if not label:
            raise ValueError("自定义沟通方式不得为空")
        return label


class StakeholderEngagementEntry(ReportContractModel):
    """一类稳定利益相关方对应的适用议题与沟通方式引用。"""

    stakeholderType: StakeholderType
    assessmentTopicIds: list[str] = []
    methodIds: list[str] = []
    customMethods: list[CustomEngagementMethod] = []

    @model_validator(mode="after")
    def _deduplicated_references(self):
        if len(self.assessmentTopicIds) != len(set(self.assessmentTopicIds)):
            raise ValueError(f"{self.stakeholderType} 包含重复议题")
        if len(self.methodIds) != len(set(self.methodIds)):
            raise ValueError(f"{self.stakeholderType} 包含重复沟通方式")
        custom_keys = [(method.kind, method.label) for method in self.customMethods]
        if len(custom_keys) != len(set(custom_keys)):
            raise ValueError(f"{self.stakeholderType} 包含重复自定义沟通方式")
        return self


class StakeholderEngagementProfile(ReportContractModel):
    """利益相关方沟通的 parse-first 真相；表格、诊断与 Word 均由此确定性投影。"""

    scopeAssessmentTopicIds: list[str] = []
    entries: list[StakeholderEngagementEntry]

    @model_validator(mode="after")
    def _stable_stakeholder_order(self):
        expected = [
            "government_regulators",
            "shareholders_investors",
            "customers",
            "management",
            "employees",
            "suppliers",
            "partners",
            "community_public",
        ]
        actual = [entry.stakeholderType for entry in self.entries]
        if actual != expected:
            raise ValueError("利益相关方必须按固定八类完整声明")
        if len(self.scopeAssessmentTopicIds) != len(set(self.scopeAssessmentTopicIds)):
            raise ValueError("scopeAssessmentTopicIds 不得重复")
        return self


# —— 表格（SSOT §3.C/§8）——
class GsColDef(ReportContractModel):
    """表格列规格：挂在 GsTable.colDefs（整列共享）；单元格经 colKey 引用其类型/选项/生成指引。"""

    key: str
    header: str
    cellType: CellType = "text"
    options: list[str] | None = None          # single_select/multi_select 候选值
    required: bool = False
    genHint: str | None = None                # 列级生成指引（模型可见）；来源限受控 YAML 契约，防注入（架构 §8）
    presetFullCoverage: bool = False          # multi_select column pre-filled with every option by the system, never by the model
    subjectTerm: Literal["company"] | None = None  # Cells must name the reporting entity by this generic term; guardrails reject its proper names


class RowOrigin(ReportContractModel):
    """AI 定行的 RowSeed 复现快照：单行重生成据此还原 seed（SSOT §3.C/§8）。from 区分 AI 定行 / 用户加行。"""

    model_config = ConfigDict(populate_by_name=True)

    from_: Literal["ai", "user"] = PydanticField("ai", alias="from")  # from 为 Python 关键字，以 alias 承载真实键名
    theme: str | None = None
    category: str | None = None
    driver_hint: str | None = None


class GsTableCell(ReportContractModel):
    """单元格 = Plate td/th 节点 + 业务属性。受控值存 value（保结构化类型）；options 可在单元格级覆盖列级（如 IRO 影响行/风险机遇行选项不同）。"""

    type: Literal["td", "th"] = "td"
    colKey: str | None = None                 # 指向 GsTable.colDefs[].key；表头/被合并占位格可空
    value: str | list[str] | None = None      # 受控值：text/ai_text 为 str，single/multi_select 为 str/list
    options: list[str] | None = None          # 单元格级 options 覆盖列级
    colSpan: int = 1                          # 跨列合并（Plate 原生 colSpan）
    rowSpan: int = 1                          # 跨行合并（Plate 原生 rowSpan）
    cellState: BlockState | None = None        # 单元格级人审/生成态（ai_text 用）
    children: list[dict] = PydanticField(default_factory=lambda: [{"type": "p", "children": [{"text": ""}]}])  # Plate 文本骨架；真相是 value


class GsTableRow(ReportContractModel):
    """行 = Plate tr 节点 + 业务属性。"""

    type: Literal["tr"] = "tr"
    headerRow: bool = False                    # 表头行（含跨列大标题行 / 列名行）
    state: BlockState | None = None            # 逐行人审三态（行即块，E3）
    origin: RowOrigin | None = None            # AI 定行的 RowSeed 快照（单行重生成据此还原 seed）
    generation: GenerationSpec | None = None   # 行内 ai_text 列生成规格（行间无依赖则并发）
    appears_when: Condition | None = None      # 行级显隐（E3）
    children: list[GsTableCell] = []


class GsTable(ReportContractModel):
    """表格 = Plate table 节点形态（table/tr/td/th + 合并 colSpan/rowSpan）+ 业务属性（列规格/受控值/行态）。前后端共用一套：前端渲染受控单元格、Report 直接作真相，后端据此 LLM 生成 / 校验 / 导出。"""

    type: Literal["table"] = "table"
    colDefs: list[GsColDef] = []              # 列规格清单（整列共享，单元格经 colKey 引用）
    caption: str | None = None                # 题注（表题在上）
    disclaimer: str | None = None
    firstColumnNarrow: bool = False           # 首列为标题/序号列时变窄，其余内容列平分
    layoutProfile: Literal["risk_response_matrix"] | None = None  # 多列风险/机遇/应对矩阵导出版式
    iroKind: Literal["risk", "opportunity", "risk_and_opportunity"] | None = None  # Catalog tables: which IRO kinds the rows enumerate (model-facing row label)
    columnWidthWeights: dict[str, int] | None = None  # 按 colDefs[].key 声明 Word 导出列宽权重
    rowSource: Literal[
        "user",
        "assessment_topics",
        "assessment_iro",
        "stakeholder_engagement",
        "certificate_facts",
    ] = "user"
    children: list[GsTableRow] = []


# —— 图片（SSOT §3，含题注）——
class DerivedVisualizationSpec(ReportContractModel):
    """由结构化 Report 数据确定性派生的可视化规格；模型不生成可视化正文。"""

    kind: Literal["quantitative_metric_summary"]
    metricKeys: list[str]
    featuredMetricKeys: list[str] | None = None
    displayMode: Literal["auto", "highlight_cards", "compact_cards", "summary_table"] = "auto"
    groupBy: Literal["category", "groupPath", "none"] = "none"
    emptyBehavior: Literal["hide", "placeholder"] = "hide"


class ImageModel(ReportContractModel):
    caption: str | None = None                # 题注（图题在下）
    placeholder: str | None = None            # 未上传时的占位说明
    derivedVisualization: DerivedVisualizationSpec | None = None  # 由 Report 结构化数据派生的确定性图片
    evidenceAssetId: UUID | None = None       # 预留：正式导出时由 EvidenceAsset 独占图片来源、题注与替代文本
    layoutAssetSlot: bool = False             # 契约声明：本块是排版素材图片承载位
    layoutAssetIds: list[UUID] | None = None  # 运行态：按序插入的素材资产（题注/替代文本归资产 owner）

    @model_validator(mode="after")
    def validate_image_source(self) -> "ImageModel":
        """资产图片不复制元数据；确定性图表与资产图片互斥。"""

        sources = (
            self.evidenceAssetId,
            self.derivedVisualization,
            self.layoutAssetIds,
        )
        if sum(item is not None for item in sources) > 1:
            raise ValueError("图片只能有一种内容来源")
        if self.evidenceAssetId is not None and self.caption is not None:
            raise ValueError("EvidenceAsset 图片的题注必须由资产 owner 提供")
        if self.layoutAssetIds is not None:
            if self.caption is not None:
                raise ValueError("排版素材图片的题注必须由资产 owner 提供")
            if not self.layoutAssetSlot:
                raise ValueError("排版素材只能落在契约声明的承载位")
        return self


# —— 内容块（SSOT §3.A）——
class Block(ReportContractModel):
    id: str
    type: NodeType
    blockType: BlockType
    source: Source
    state: BlockState | None = None           # 生成生命周期；有效模型输出和用户编辑内容统一为 ready
    styleRole: str | None = None              # 格式角色（格式标准 §8），桥接样式母版

    content: list[Inline] | None = None       # type=paragraph
    # 挂在本段末尾的脚注正文。脚注是宿主段落的从属事实，不是独立块——独立成块会让它
    # 参与章节编号、渲染计划与批注锚点，而它在交付物里根本不占正文位置。
    # 编号、上标与分隔线由 Word 母版承载，契约只声明「这段有一条脚注、内容是什么」。
    footnote: list[Inline] | None = None
    table: GsTable | None = None              # type=table（Plate 表格节点形态）
    image: ImageModel | None = None           # type=image
    generation: GenerationSpec | None = None  # constrained/generative 块的生成规格（SSOT §3.B）

    appears_when: Condition | None = None     # 可见性门控（§6）
    # 升级占位标记（仅交付投影设置，不落存储）：非空表示该块是范围外章节的
    # 「正式账户可生成完整内容」占位，渲染侧据此呈现占位版式，评测与生成不消费。
    placeholderNotice: str | None = None
    required: bool = False                     # 必选块（缺失阻断导出）
    recommended: bool = False                  # 强建议（不硬阻，仅 warn）——如组织架构图
    listType: Literal["ordered", "unordered"] | None = None   # 列表项（有序/无序）


class SectionDisplayTitle(ReportContractModel):
    """章节的实例级用户可见标题；稳定导航标题仍由 Section.title 拥有。"""

    model_config = ConfigDict(extra="forbid")

    text: str
    origin: Literal["generated", "user"]
    inputFingerprint: str

    @field_validator("text", "inputFingerprint")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("动态章节标题及其输入指纹不得为空")
        return value


class SectionTitleGeneration(ReportContractModel):
    """H4 标题生产者声明；标题与其直属段落正文由同一次调用返回。"""

    model_config = ConfigDict(extra="forbid")

    sourceBlockId: str
    guidance: str


class Section(ReportContractModel):
    key: str
    title: str                                # 标题纯文本骨架（导航/目录/schema 视图用）
    titleContent: list[Inline] | None = None  # 标题含字段引用时的行内内容；渲染标题时优先于 title
    displayTitle: SectionDisplayTitle | None = None
    titleGeneration: SectionTitleGeneration | None = None
    headingLevel: Literal[1, 2, 3, 4] = 1
    pillar: Pillar | None = None              # Pillar identity of a topic-chapter H3; None outside pillars
    reportModuleId: str | None = None          # 动态 ESG H1 的稳定模块 id
    required: bool = False
    standardRef: str | None = None            # 准则强制结构出处（溯源元数据，导出 QA 校验用）
    appears_when: Condition | None = None
    reportSectionId: str | None = None         # 报告 H2 id；可映射一至多个评分议题
    conciseDisclosure: Block | None = None     # impact/non 分支的 H2 直属摘要；仅议题模板使用
    blocks: list[Block] = []
    children: list[Section] | None = None


class DisclosureProfile(ReportContractModel):
    """报告级披露配置（SSOT §3.D）：大陆准则单选，港交所与其他文件为附加参考。"""

    mainlandStandard: Literal["sse", "szse", "bse"] = "sse"
    includesHongKongExchangeGuide: bool = False
    additionalDisclosureReferences: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _strip_retired_disclosure_detail_level(cls, data: object) -> object:
        # 迁移期兼容层：存量 report_states JSONB 仍可能携带
        # 已废弃的 disclosureDetailLevel 键；读取时剥离，其余未知键仍由 extra="forbid"
        # 拒绝。注意：并非所有写路径都会冲洗旧键——complete_batch 等按原始 dict 打补丁
        # 写回（persistence/section_generations.py），旧键可长期驻留；本校验器只能在
        # 对库只读扫描确认无该键后删除，不得以「写回自然冲洗」推定提前退场。
        if isinstance(data, dict) and "disclosureDetailLevel" in data:
            data = {k: v for k, v in data.items() if k != "disclosureDetailLevel"}
        return data


@dataclass(frozen=True)
class ReportInputMetadata:
    """与值字段共址的输入义务元数据；compiler 只读派生，不复制当前值。"""

    target_handle: str
    label: str
    value_type: FieldType
    required_before: RequiredBefore | None = None


class ExternalAssuranceReport(ReportContractModel):
    """外部鉴证报告附件事实：只记录是否纳入及对外展示标签。"""

    isIncluded: bool = False
    fileLabel: str | None = None


class ReaderFeedbackContactInformation(ReportContractModel):
    """读者反馈固定文本所需联系方式。"""

    address: Annotated[
        str | None,
        ReportInputMetadata(
            target_handle="appendix.reader_feedback.address",
            label="读者反馈地址",
            value_type="string",
        ),
    ] = None
    email: Annotated[
        str | None,
        ReportInputMetadata(
            target_handle="appendix.reader_feedback.email",
            label="读者反馈邮箱",
            value_type="email",
        ),
    ] = None
    phone: Annotated[
        str | None,
        ReportInputMetadata(
            target_handle="appendix.reader_feedback.phone",
            label="读者反馈电话",
            value_type="string",
        ),
    ] = None


class AppendixPackage(ReportContractModel):
    """附录事实包：独立于议题与前四章正文，供附录章节、诊断与导出使用。"""

    externalAssuranceReport: ExternalAssuranceReport = ExternalAssuranceReport()
    readerFeedbackContactInformation: ReaderFeedbackContactInformation = ReaderFeedbackContactInformation()


class QuantitativeMetricDraft(ReportContractModel):
    """单个 ESG 定量指标的用户填写值（report.meta.quantitativeMetrics.metrics 的元素）；形状受控。"""

    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    noValueReason: QuantitativeNoValueReason | None = None
    department: str | None = None
    note: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def normalize_unfilled_value(cls, value: object) -> object | None:
        """在 Report 边界将用户未填写状态归一为空值，禁止其进入图片、正文或 Judge 事实。"""
        if value is None:
            return None
        text = str(value).strip()
        if not text or text == "未填写":
            return None
        if not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", text):
            raise ValueError("定量指标值必须是十进制数，不得包含单位、千分位或说明文字")
        return text

    @model_validator(mode="after")
    def value_and_no_value_reason_are_mutually_exclusive(
        self,
    ) -> QuantitativeMetricDraft:
        """已填数值和无值原因表达不同事实，禁止同一草稿同时声明。"""
        if self.value is not None and self.noValueReason is not None:
            raise ValueError("定量指标值与无值原因不得同时填写")
        return self


class QuantitativeMetricsMeta(ReportContractModel):
    """ESG 定量数据表的受控形状：指标草稿字典 + 温室气体核算标准。"""

    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, QuantitativeMetricDraft] = {}
    greenhouseGasAccountingStandard: str | None = None
    greenhouseGasAccountingStandardOther: str | None = None


class ReportMeta(ReportContractModel):
    """Report.meta 的 typed 契约，承载定量数据与重要性组织策略。"""

    quantitativeMetrics: QuantitativeMetricsMeta = QuantitativeMetricsMeta()
    materialityStrategy: Literal["complete_coverage"] | None = None


class Report(ReportContractModel):
    title: str
    fields: dict[str, Field] = {}
    inputGuidance: dict[str, InputGuidance] | None = None  # 用户可见填写说明与默认规则；模板态配置，不是报告事实
    intakeItems: list[IntakeItem] = []         # 分议题内容清单（题目+结构化答案）；本期用户内容输入主路径（SSOT §3.A）
    assessmentScoreScale: AssessmentScoreScale | None = None  # 模板态评分尺度；不是评分事实或模型上下文
    assessmentVocabulary: AssessmentVocabulary | None = None  # Template-state display vocabulary of the assessment; not a report fact
    quantitativeMetricsVocabulary: QuantitativeMetricsVocabulary | None = None  # Template-state wording of the metrics table; not a report fact
    assessmentInput: MaterialityAssessmentInput | None = None  # 用户评分输入；固定分类和注册表元数据均由 resolver 现算
    assessment: AssessmentResult | None = None  # 双重重要性评估快照（E1）
    disclosureProfile: DisclosureProfile | None = None  # 报告级披露配置（SSOT §3.D）；None 视作默认大陆准则与简化披露
    appendixPackage: AppendixPackage = AppendixPackage()  # 附录事实包；独立于议题与前四章字段
    stakeholderEngagement: StakeholderEngagementProfile | None = None  # 利益相关方表的可编辑结构化真相
    sections: list[Section]
    meta: ReportMeta | None = None             # ESG 定量数据表等报告级 meta（typed，取代裸 dict）
    # Stamped by the package loader from the directory a template was read from; never authored in
    # YAML. Derived from reports.report_profile_id → ReportProfile.knowledge_package, so topic and
    # metric resolution never fall back to a global default package.
    knowledgePackageId: str | None = None

    @model_validator(mode="after")
    def _validate_input_guidance(self):
        """说明路径必须对应可渲染的非议题输入位置；默认规则只允许三个报告期字段。"""
        default_rule_targets = {
            "previous_calendar_year": "fields.reporting_year.value",
            "reporting_year_start": "fields.report_period_start.value",
            "reporting_year_end": "fields.report_period_end.value",
        }
        static_paths = {
            "assessment.threshold.financial",
            "assessment.threshold.impact",
            "appendixPackage.readerFeedbackContactInformation.email",
            "appendixPackage.readerFeedbackContactInformation.address",
            "appendixPackage.readerFeedbackContactInformation.phone",
            "meta.quantitativeMetrics.greenhouseGasAccountingStandard",
        }
        metric_path_prefix = "meta.quantitativeMetrics.metrics."
        metric_path_suffixes = (".value", ".department", ".note")

        for path, guidance in (self.inputGuidance or {}).items():
            if path.startswith("fields.") and path.endswith(".value"):
                field_key = path.removeprefix("fields.").removesuffix(".value")
                if not field_key or "." in field_key or field_key not in self.fields:
                    raise ValueError(f"inputGuidance 路径指向未声明字段：{path}")
            elif path in static_paths:
                pass
            elif not (
                path.startswith(metric_path_prefix)
                and any(path.endswith(suffix) for suffix in metric_path_suffixes)
                and path[len(metric_path_prefix) :].split(".", 1)[0]
            ):
                raise ValueError(f"inputGuidance 路径不支持：{path}")

            if guidance.defaultRule and default_rule_targets[guidance.defaultRule] != path:
                raise ValueError(
                    f"默认规则 {guidance.defaultRule} 只能用于 {default_rule_targets[guidance.defaultRule]}"
                )
        return self

    @model_validator(mode="after")
    def _validate_assessment_scores(self):
        """实例有评分尺度时，所有已装配的原始得分必须满足模板尺度。"""
        if self.assessmentScoreScale is None or self.assessment is None:
            return self
        from sustainability_desk.contract.materiality_scoring import validate_materiality_score

        for topic in self.assessment.topics:
            if topic.determination != "scored":
                continue
            validate_materiality_score(topic.financialScore, self.assessmentScoreScale)
            validate_materiality_score(topic.impactScore, self.assessmentScoreScale)
        return self

    @model_validator(mode="after")
    def _validate_stakeholder_engagement(self):
        """Profile 引用必须来自正式议题与受控方式目录；覆盖完整性由导出诊断负责。"""
        if self.stakeholderEngagement is not None:
            from sustainability_desk.contract.knowledge_packages import knowledge_package_of
            from sustainability_desk.contract.stakeholder_engagement import validate_stakeholder_engagement_profile

            validate_stakeholder_engagement_profile(
                self.stakeholderEngagement, package=knowledge_package_of(self)
            )
        return self

    def iter_blocks(self):
        """深度遍历所有块（含子节）。"""
        def walk(sections):
            for sec in sections:
                yield from sec.blocks
                if sec.conciseDisclosure is not None:
                    yield sec.conciseDisclosure
                if sec.children:
                    yield from walk(sec.children)
        yield from walk(self.sections)

    def find_block(self, block_id: str) -> Block:
        for blk in self.iter_blocks():
            if blk.id == block_id:
                return blk
        raise KeyError(block_id)
