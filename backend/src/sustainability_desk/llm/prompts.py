# ABOUTME: 报告生成提示词组装器——从 typed Prompt Profile 与 ModelContext 构造任务专用 System/User 消息。
# ABOUTME: Profile 只承载跨议题稳定片段；Block.generation 拥有议题任务配置，用户资料只经白名单投影进入模型。
# ABOUTME(en): Prompt assembler: builds task System/User messages from a typed Profile and a ModelContext.
# ABOUTME(en): The Profile holds cross-topic segments; Block.generation owns task config; user data enters allowlisted.
from __future__ import annotations


import hashlib

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.evidence_resolution import (
    generation_evidence_keys as _evidence_keys,
    generation_has_substantive_input,
    greenhouse_gas_accounting_standard as _ghg_accounting_standard,
    intake_answer_is_substantive,
    intake_answer_text as _intake_answer_text,
    intake_supplement_text as _intake_supplement_text,
)
from sustainability_desk.contract.evidence_semantics import (
    EvidencePosture,
    resolve_evidence_posture,
)
from sustainability_desk.contract.compiled_definition import CompiledReportDefinition
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.language import OUTPUT_LANGUAGE_DIRECTIVES, Language
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.contract.models import (
    Block,
    GsColDef,
    IroKindLabels,
    Report,
    RowExpansion,
    Section,
)
from sustainability_desk.contract.metric_narrative import (
    MetricNarrativePolicy,
    metric_narrative_policy_rules,
)
from sustainability_desk.contract.iro_conclusions import iro_conclusions_by_topic
from sustainability_desk.contract.prior_disclosure import (
    PriorDisclosure,
    prior_disclosures_for_block,
)
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.contract.pillar_semantics import (
    PillarPurpose,
    context_only_calibration_lines,
    resolve_pillar_purpose,
    resolve_public_disclosure_guidance,
)
from sustainability_desk.llm.prompt_profiles import (
    PromptLabels,
    ReportGenerationPromptProfile,
    load_prompt_profile,
    prompt_labels,
    answer_wording,
)
from sustainability_desk.llm.table_schema import RowSeed
from sustainability_desk.material.intake.file_agent_contract import FileMaterial
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.quantitative_metrics import (
    quantitative_metric_draft,
    quantitative_metric_display_label,
    quantitative_metric_value,
    quantitative_metrics_by_key,
)

CATALOG_ROW_SUPPORT_STATUS_KEY = "_catalog_row_support_status"
CATALOG_ROW_SUPPORT_EVIDENCE_KEY = "_catalog_row_support_evidence"
CATALOG_ROW_WRITING_RULE_KEY = "_catalog_row_writing_rule"
CATALOG_INTERNAL_ROW_KEYS = {
    "referenceImpact",
    CATALOG_ROW_SUPPORT_STATUS_KEY,
    CATALOG_ROW_SUPPORT_EVIDENCE_KEY,
    CATALOG_ROW_WRITING_RULE_KEY,
}
def generation_blocks(report: Report) -> list[dict]:
    """可生成块清单；前端仅需运行身份，证据选择始终由 Report 合同拥有。"""
    out: list[dict] = []
    for blk in report.iter_blocks():
        g = blk.generation
        if blk.blockType in ("constrained", "generative") and g:
            out.append({"id": blk.id})
    return out


def _report_subject_lines(
    block: Block,
    report: Report,
    context_fields: tuple[str, ...],
    generation_field_ids: tuple[str, ...] | None = None,
    *,
    labels: PromptLabels,
) -> list[str]:
    """报告主体「标签：值」——全局上下文字段（公司/年份/行业）∪ 本块声明字段，去重、缺值跳过。"""
    keys: list[str] = list(context_fields)
    generation_fields = generation_field_ids
    if generation_fields is None:
        generation = block.generation
        generation_fields = tuple(
            generation.inputs.fields
            if generation and generation.inputs and generation.inputs.fields
            else ()
        )
    for key in generation_fields:
        if key not in keys:
            keys.append(key)
    lines: list[str] = []
    for key in keys:
        fld = report.fields.get(key)
        if fld and fld.value not in (None, ""):
            lines.append(f"{fld.label}{labels.key_value_separator}{fld.value}")
    return lines


def generation_task_focus(block: Block) -> str:
    """返回块显式声明的唯一生成任务；不从占位正文、题注或 block 类型推断。"""

    return block.generation.task.focus.strip() if block.generation else ""


def _topic_section_of(report: Report, block_id: str) -> Section | None:
    """找块所属 ReportSection H2，供分工 map 遍历同一内容分支。"""

    def contains(sec: Section) -> bool:
        if any(b.id == block_id for b in sec.blocks) or (
            sec.conciseDisclosure is not None and sec.conciseDisclosure.id == block_id
        ):
            return True
        return any(contains(c) for c in (sec.children or []))

    def walk(sections) -> Section | None:
        for sec in sections:
            if sec.reportSectionId and contains(sec):
                return sec
            got = walk(sec.children) if sec.children else None
            if got:
                return got
        return None

    return walk(report.sections)


def _topic_scope_text(
    instance_report: Report, template_report: Report, block: Block, *, labels: PromptLabels
) -> str:
    """仅投影与当前块共享 Evidence 的相邻任务；当前任务由 section_task 单独拥有。"""
    from sustainability_desk.contract.visibility import visible

    topic = _topic_section_of(instance_report, block.id)
    if topic is None:
        return ""
    current_intake_keys, current_metric_keys = _evidence_keys(
        block,
        template_report,
        instance_report,
    )
    current_evidence_keys = {
        ("intake", key) for key in current_intake_keys
    } | {
        ("metric", key) for key in current_metric_keys
    }
    if not current_evidence_keys:
        return ""

    def iter_visible_blocks(section: Section):
        if not visible(section, instance_report):
            return
        for candidate in section.blocks:
            if visible(candidate, instance_report):
                yield candidate
        for child in section.children or []:
            yield from iter_visible_blocks(child)

    lines: list[str] = []
    for pillar in topic.children or []:
        for blk in iter_visible_blocks(pillar):
            if blk.blockType not in ("generative", "constrained"):
                continue
            if blk.id == block.id:
                continue
            try:
                template_block = template_report.find_block(blk.id)
            except KeyError:
                continue
            intake_keys, metric_keys = _evidence_keys(
                template_block,
                template_report,
                instance_report,
            )
            sibling_evidence_keys = {
                ("intake", key) for key in intake_keys
            } | {
                ("metric", key) for key in metric_keys
            }
            if current_evidence_keys.isdisjoint(sibling_evidence_keys):
                continue
            does = generation_task_focus(template_block)
            if not does:
                continue
            lines.append(f"- {does}")
    if not lines:
        return ""
    return labels.structure.topic_scope_heading + "\n" + "\n".join(lines)


def _compiled_topic_scope_text(
    definition: CompiledReportDefinition,
    instance_report: Report,
    block: Block,
    *,
    labels: PromptLabels,
) -> str:
    """从编译关系索引选择共享 Evidence 的相邻任务，不反向遍历 Section 树。"""

    from sustainability_desk.contract.visibility import visible_block_in_report

    current = definition.generation_for_block(block.id)
    current_placement = definition.placement_for_block(block.id)
    evidence = {
        *(f"intake:{key}" for key in current.intake_item_ids),
        *(f"metric:{key}" for key in current.quantitative_metric_ids),
    }
    if not evidence:
        return ""
    lines: list[str] = []
    for candidate in definition.generation_contracts.values():
        if candidate.block_id == block.id or candidate.report_section_id != current.report_section_id:
            continue
        candidate_placement = definition.placement_for_block(candidate.block_id)
        if (
            current_placement.pillar_title is not None
            and candidate_placement.pillar_title is None
        ):
            # H2 concise summary 是 planner 的互斥分支，不是四支柱块的相邻职责。
            continue
        candidate_evidence = {
            *(f"intake:{key}" for key in candidate.intake_item_ids),
            *(f"metric:{key}" for key in candidate.quantitative_metric_ids),
        }
        if evidence.isdisjoint(candidate_evidence):
            continue
        try:
            if not visible_block_in_report(instance_report, candidate.block_id):
                continue
        except (KeyError, ValueError):
            continue
        if candidate.semantic_task:
            lines.append(f"- {candidate.semantic_task}")
    if not lines:
        return ""
    return labels.structure.topic_scope_heading + "\n" + "\n".join(dict.fromkeys(lines))


def _intake_items(keys: tuple[str, ...], report: Report) -> tuple[Material, ...]:
    """已解析的内容清单 key → 已就绪用户事实；未填和非实质选项不进入模型证据。

    答案本体与补充说明分离渲染：补充说明是用户原话备注（Material.note →
    <item> 内的「用户说明」行），模型据此区分「企业事实」与「用户备注」；
    其中的『暂无制度』类状态说明由 evidence posture 约束为口径信息，不得转述进正文。
    """

    by_key = {i.key: i for i in report.intakeItems}
    package = knowledge_package_of(report)
    wording = answer_wording(prompt_labels(package))
    items: list[Material] = []
    for key in contributing_intake_item_ids(keys, report):
        item = by_key[key]
        answer_text = _intake_answer_text(item, language=package.language, wording=wording)
        supplement = _intake_supplement_text(item)
        items.append(
            Material(label=item.prompt, text=answer_text or "", note=supplement)
        )
    return tuple(items)


def contributing_intake_item_ids(keys: tuple[str, ...], report: Report) -> tuple[str, ...]:
    """已解析清单 key 中实际进入模型证据的项（有答案或补充说明）；与 ``_intake_items`` 同一过滤。

    生成期来源记录据此落库：批注列出的问题必须恰是模型当次看到的问题，不多不少。
    """

    by_key = {i.key: i for i in report.intakeItems}
    language = knowledge_package_of(report).language
    contributing: list[str] = []
    for key in keys:
        item = by_key.get(key)
        if item is None:
            continue
        if intake_answer_is_substantive(item, language) or _intake_supplement_text(item):
            contributing.append(key)
    return tuple(contributing)


def _intake_generation_boundaries(
    keys: tuple[str, ...], report: Report, *, labels: PromptLabels
) -> tuple[str, ...]:
    """已解析清单项的生成边界；只投影题干和边界文本，不投影内部 key。"""

    by_key = {item.key: item for item in report.intakeItems}
    boundaries: list[str] = []
    for key in keys:
        item = by_key.get(key)
        boundary = item.generationBoundary.strip() if item and item.generationBoundary else ""
        if boundary:
            boundaries.append(f"{item.prompt}{labels.key_value_separator}{boundary}")
    return tuple(boundaries)


def _quantitative_metric_evidence(
    keys: tuple[str, ...],
    report: Report,
) -> tuple[MetricEvidence, ...]:
    """将已解析指标目录投影为 typed evidence，不暴露内部 key 或填报状态。"""

    metrics_by_key = quantitative_metrics_by_key(knowledge_package_of(report))
    evidence: list[MetricEvidence] = []
    for key in keys:
        metric = metrics_by_key.get(key)
        if metric is None:
            continue
        draft = quantitative_metric_draft(report, key)
        value = quantitative_metric_value(report, key)
        note = str(draft.get("note") or "").strip()
        standard = _ghg_accounting_standard(key, report)
        evidence.append(
            MetricEvidence(
                metric_name=quantitative_metric_display_label(metric),
                category_path=tuple([metric.category, *metric.groupPath]),
                unit=metric.unit,
                value=value,
                note=note or None,
                accounting_standard=standard,
            )
        )
    return tuple(evidence)


def _metric_narrative_policy(
    block: Block,
    report: Report,
    metric_keys: tuple[str, ...],
) -> MetricNarrativePolicy | None:
    """只为指标正文任务投影产品授权；指标值与分支可见性仍由 Report 合同决定。"""

    generation = block.generation
    if generation is None or generation.task.mode != "metric_narrative":
        return None
    if any(quantitative_metric_value(report, key) is not None for key in metric_keys):
        return None
    catalog = quantitative_metrics_by_key(knowledge_package_of(report))
    labels = tuple(
        dict.fromkeys(
            quantitative_metric_display_label(catalog[key])
            for key in metric_keys
        )
    )
    return MetricNarrativePolicy(
        indicator_source="catalog" if metric_keys else "generated_general",
        catalog_metric_labels=labels,
    )


def _section_report_section_of(report: Report, block_id: str) -> str | None:
    """找块所属 reportSectionId；H2 以下的块继承最近祖先关系。"""

    def walk(sections, inherited: str | None) -> tuple[bool, str | None]:
        for sec in sections:
            effective = sec.reportSectionId or inherited
            if any(b.id == block_id for b in sec.blocks) or (
                sec.conciseDisclosure is not None and sec.conciseDisclosure.id == block_id
            ):
                return True, effective
            if sec.children:
                found, value = walk(sec.children, effective)
                if found:
                    return True, value
        return False, None

    return walk(report.sections, None)[1]


def _assessment_whitelist(
    block: Block,
    template_report: Report,
    instance_report: Report,
    definition: CompiledReportDefinition | None = None,
) -> list[dict]:
    """把所属合并 H2 的全部成员议题投影为白名单结论，不注入原始得分。"""
    if block.table is not None and block.table.rowSource == "assessment_iro":
        if instance_report.assessment is None:
            return []
        registry = load_topic_contract(knowledge_package_of(instance_report)).assessmentTopicsById
        topics = {
            result.assessmentTopicId: registry[result.assessmentTopicId]
            for result in instance_report.assessment.topics
            if result.determination == "scored"
            and result.materiality in ("dual", "financial")
            and result.assessmentTopicId in registry
        }
    else:
        report_section_id = (
            definition.generation_for_block(block.id).report_section_id
            if definition is not None
            else _section_report_section_of(template_report, block.id)
        )
        if not report_section_id or instance_report.assessment is None:
            return []
        topics = (
            {
                topic.id: topic
                for topic in definition.assessment_topics
                if topic.reportSectionId == report_section_id
            }
            if definition is not None
            else {
                topic.id: topic
                for topic in load_topic_contract(
                    knowledge_package_of(instance_report)
                ).assessmentTopicsByReportSectionId[report_section_id]
            }
        )
    results = {
        result.assessmentTopicId: result for result in instance_report.assessment.topics
    }
    # IRO 表已确定的结论是本报告对该议题的定调；用户在评分表确认的条目优先，
    # 未确认时用 IRO 表结论作方向参照。缺结论只是少一层校准，不阻断本章生成。
    conclusions = iro_conclusions_by_topic(instance_report)
    briefs: list[AssessmentBrief] = []
    for topic in topics.values():
        result = results.get(topic.id)
        if result is None:
            continue
        iro = [
            IroBrief(kind=item.kind, description=item.description)
            for item in (getattr(result, "iroItems", None) or [])
            if item.description
        ]
        if not iro:
            iro = _iro_briefs_from_conclusion(conclusions.get(topic.name))
        briefs.append(AssessmentBrief(name=topic.name, iro=iro))
    return briefs


def _iro_briefs_from_conclusion(conclusion) -> list[IroBrief]:
    """把 IRO 表结论投影为模型可见的 IRO 条目；只出方向性判断，不带表格结构或分类枚举。"""
    if conclusion is None:
        return []
    briefs: list[IroBrief] = []
    if conclusion.impact_summary:
        briefs.append(IroBrief(kind="impact", description=conclusion.impact_summary))
    if conclusion.risk_opportunity_summary:
        briefs.append(
            IroBrief(kind="risk_opportunity", description=conclusion.risk_opportunity_summary)
        )
    return briefs


def _has_assessment_iro_evidence(
    block: Block,
    assessment: tuple[AssessmentBrief, ...],
) -> bool:
    """IRO 表仅把用户已填写的 IRO 描述视为企业事实；评分分类本身不是事实。"""
    return (
        block.table is not None
        and block.table.rowSource == "assessment_iro"
        and any(item.iro for item in assessment)
    )


class ModelContextDTO(BaseModel):
    """模型可见上下文及其嵌套 DTO 的严格不可变边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Material(ModelContextDTO):
    """命名资料抽取文本——可进 prompt 的用户资料内容（label 来源标签 / text 抽取正文 / note 用户对资料的说明）。"""

    label: str
    text: str
    note: str | None = None


class MetricEvidence(ModelContextDTO):
    """模型可见的单项指标证据；指标定义始终进入，值与备注仅在用户提供时存在。"""

    metric_name: str
    category_path: tuple[str, ...]
    unit: str
    value: str | None = None
    note: str | None = None
    accounting_standard: str | None = None


class GenerationEvidence(ModelContextDTO):
    """当前生成调用的唯一证据投影；Prompt、Guardrail、Judge 和 artifact 共同消费。"""

    intake_facts: tuple[Material, ...] = ()
    mapped_materials: tuple[Material, ...] = ()
    metric_evidence: tuple[MetricEvidence, ...] = ()
    substantive_input_present: bool = False


def _metric_materials(
    evidence: tuple[MetricEvidence, ...], labels: PromptLabels
) -> tuple[Material, ...]:
    """将 typed 指标证据渲染为模型用户资料；不添加内部填报状态。"""

    sep = labels.key_value_separator
    words = labels.evidence
    materials: list[Material] = []
    for metric in evidence:
        parts = [
            words.metric_source_line,
            f"{words.metric_category_path}{sep}{' / '.join(metric.category_path)}",
            f"{words.metric_name}{sep}{metric.metric_name}",
            f"{words.metric_unit}{sep}{metric.unit}",
        ]
        if metric.value is not None:
            parts.append(f"{words.metric_value}{sep}{metric.value}")
        else:
            parts.append(words.metric_no_value_boundary)
        if metric.note:
            parts.append(f"{words.metric_note}{sep}{metric.note}")
        if metric.accounting_standard:
            parts.append(f"{words.metric_accounting_standard}{sep}{metric.accounting_standard}")
        materials.append(
            Material(
                label=words.metric_material_label.format(metric_name=metric.metric_name),
                text=words.part_separator.join(parts),
            )
        )
    return tuple(materials)


def evidence_materials(evidence: GenerationEvidence, labels: PromptLabels) -> tuple[Material, ...]:
    """统一渲染当前 Evidence 的全部用户可见资料。"""

    return (
        *evidence.intake_facts,
        *evidence.mapped_materials,
        *_metric_materials(evidence.metric_evidence, labels),
    )


def metric_narrative_fact_materials(
    evidence: GenerationEvidence, labels: PromptLabels
) -> tuple[Material, ...]:
    """投影无值指标正文仍需看到的用户事实，不重复目录、单位或分类路径。"""

    sep = labels.key_value_separator
    words = labels.evidence
    materials = [*evidence.intake_facts, *evidence.mapped_materials]
    accounting_standards: set[str] = set()
    for metric in evidence.metric_evidence:
        parts: list[str] = []
        if metric.note:
            parts.append(f"{words.metric_name}{sep}{metric.metric_name}")
            parts.append(f"{words.metric_note}{sep}{metric.note}")
        if metric.accounting_standard and metric.accounting_standard not in accounting_standards:
            accounting_standards.add(metric.accounting_standard)
            parts.append(f"{words.metric_accounting_standard}{sep}{metric.accounting_standard}")
        if parts:
            materials.append(
                Material(
                    label=words.metric_material_label.format(metric_name=metric.metric_name),
                    text=words.part_separator.join(parts),
                )
            )
    return tuple(materials)


class IroBrief(ModelContextDTO):
    """议题 IRO 白名单条目——仅性质与描述，绝无内部结构。"""

    kind: str
    description: str


class AssessmentBrief(ModelContextDTO):
    """已判定为重要的议题及其 IRO 结论；绝不含原始得分 financial/impactScore 或阈值。

    重要性本身不进模型上下文：Planner 已据它把议题解析成四要素或摘要分支，模型收到的是
    装配好的块。曾有 financial_important / impact_important 两个布尔随上下文序列化却无人
    读取，它们还把「必然有两个轴」写进了模型可见边界——单轴准则只能伪造另一个轴。
    """

    name: str
    iro: tuple[IroBrief, ...] = ()


class DisplayTitleTask(ModelContextDTO):
    """同一次段落生成调用需要完成的实例标题任务。"""

    guidance: str


class SectionPlacement(ModelContextDTO):
    """生成块在正式报告 H2-H4 结构中的运行时位置；标题所有权仍在 Section。"""

    reportSectionTitle: str
    pillarTitle: str | None = None
    contentUnitTitle: str | None = None


class ModelContext(ModelContextDTO):
    """唯一交给 LLM 层的上下文 DTO——Report / Material / AssessmentResult / 原始得分 / provenance / 内部结构绝不进此对象。"""

    knowledge_package_id: str            # Package whose prompt profile and vocabulary word this context
    output_language: Language            # Report language (BCP 47) → <output_language>; projection of the package
    task_kind: str = "generate"          # generate | edit | review
    role: str = ""                       # Profile 声明的角色与披露语境 → <role>
    report_body_contract: str = ""       # Profile 声明的公开报告正文体裁 → <report_body_contract>
    expression_guidance: str = ""        # 段落组织与语言表达指导 → <expression_guidance>；表格分支为空
    report_subject: tuple[str, ...] = ()  # 报告主体「标签：值」（公司/行业/年份）→ <report_subject>
    topic_scope: str = ""                # 与当前块共享 Evidence 的相邻任务边界（无 block id）→ <topic_scope>
    prior_disclosures: tuple[PriorDisclosure, ...] = ()  # 本议题在先支柱已写入报告的正文 → <prior_disclosure>
    pillar_purpose: PillarPurpose | None = None  # 正式标题合同解析出的 typed 支柱职责；只供合同与评估分类
    section_placement: SectionPlacement | None = None  # Section 树解析出的 H2-H4 稳定结构位置
    section_task: str = ""               # GenerationTask.focus 与必要 noFactGuidance → <section_task>
    disclosure_stance: str = "standard"  # 披露立场（standard | risk_disclosure），供 trace/eval 与守卫同源读取
    public_disclosure_guidance: str = ""  # 风险披露的公开报告距离；由 disclosure_stance 确定性投影
    standard_disclosure_requirements: tuple[str, ...] = ()  # 准则披露要求正文；当前恒空，接通属待办
    intake_generation_boundaries: tuple[str, ...] = ()  # 内容清单生成边界，不进入用户填写内容
    writing_granularity: tuple[str, ...] = ()  # 写作颗粒度与距离感 → <writing_granularity>；档位名不进模型上下文
    evidence: GenerationEvidence = GenerationEvidence()  # 当前调用唯一事实投影
    evidence_posture: EvidencePosture    # 输入证据使用边界；措辞来自包 profile，由构造器按事实状态解析
    metric_narrative_policy: MetricNarrativePolicy | None = None  # 无值指标正文的产品授权边界
    length: tuple[int, int] | None = None  # 字数软区间（targetChars）→ <length>
    content_format: str = ""             # 只约束结构化输出中的 content 字段 → <content_format>
    assessment: tuple[AssessmentBrief, ...] = ()  # 白名单议题结论（无 scores）
    display_title_task: DisplayTitleTask | None = None
    row_context: dict[str, str] = {}     # 表格行级受控输入（末端只读，RowSeed 白名单）


def context_package(ctx: ModelContext) -> KnowledgePackage:
    """The knowledge package a context was built for; prompt wording and vocabulary come from it."""

    return load_knowledge_package(ctx.knowledge_package_id)


def context_profile(ctx: ModelContext) -> ReportGenerationPromptProfile:
    return load_prompt_profile(context_package(ctx))


def filled_content_materials(ctx: ModelContext) -> tuple[Material, ...]:
    """返回实际进入 User `<filled_content>` 的资料，是 Prompt 与守卫的共同事实边界。"""

    labels = context_profile(ctx).labels
    if ctx.metric_narrative_policy is not None:
        return metric_narrative_fact_materials(ctx.evidence, labels)
    return evidence_materials(ctx.evidence, labels)


def model_context_observation_metadata(block: Block, ctx: ModelContext) -> dict[str, object]:
    """生成不含正文的 Evidence 观测元数据；指纹用于识别上下文漂移。"""

    inputs = block.generation.inputs if block.generation else None
    selector_kind = inputs.evidence.kind if inputs else "explicit"
    fingerprint = hashlib.sha256(ctx.model_dump_json().encode("utf-8")).hexdigest()
    return {
        "evidence_selector_kind": selector_kind,
        "intake_fact_count": len(ctx.evidence.intake_facts),
        "metric_evidence_count": len(ctx.evidence.metric_evidence),
        "evidence_level": ctx.evidence_posture.level,
        # 本块生成时看见的在先支柱正文条数：排查「A 块是不是复述了 B 块」时，
        # 轨迹要能直接回答该块当次有没有已披露事实可参照，而不必解析整个 taskContext。
        "prior_disclosure_count": len(ctx.prior_disclosures),
        "context_fingerprint": f"sha256:{fingerprint}",
    }


def _display_title_task(report: Report, block_id: str) -> DisplayTitleTask | None:
    def walk(sections: list[Section]) -> DisplayTitleTask | None:
        for section in sections:
            declaration = section.titleGeneration
            if declaration is not None and declaration.sourceBlockId == block_id:
                return DisplayTitleTask(guidance=declaration.guidance)
            found = walk(section.children or [])
            if found is not None:
                return found
        return None

    return walk(report.sections)


def _section_trail(report: Report, block_id: str) -> list[Section]:
    """返回包含目标块的完整 Section 路径；未知块不得静默退化为空定位。"""

    def walk(
        sections: list[Section],
        trail: list[Section],
    ) -> list[Section] | None:
        for section in sections:
            current = [*trail, section]
            if any(block.id == block_id for block in section.blocks) or (
                section.conciseDisclosure is not None
                and section.conciseDisclosure.id == block_id
            ):
                return current
            found = walk(section.children or [], current)
            if found is not None:
                return found
        return None

    found = walk(report.sections, [])
    if found is None:
        raise ValueError(f"无法定位生成块 {block_id} 的 Section 路径")
    return found


def resolve_section_placement(
    report: Report,
    block_id: str,
) -> SectionPlacement | None:
    """从 Section 树确定性投影 H2-H4；H1-only 前章段落不伪装成报告 H2。"""

    trail = _section_trail(report, block_id)
    by_level = {section.headingLevel: section for section in trail}
    report_section = by_level.get(2)
    if report_section is None:
        return None
    pillar = by_level.get(3)
    content_unit = by_level.get(4)
    return SectionPlacement(
        reportSectionTitle=report_section.title,
        pillarTitle=pillar.title if pillar is not None else None,
        contentUnitTitle=(
            content_unit.title if content_unit is not None else None
        ),
    )


def resolve_generation_evidence(
    block: Block,
    template_report: Report,
    instance_report: Report,
    definition: CompiledReportDefinition | None = None,
    *,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> GenerationEvidence:
    """Report → 当前生成调用证据的唯一 parse 边界。"""

    intake_keys, metric_keys = _evidence_keys(
        block, template_report, instance_report, definition
    )
    intake_facts = _intake_items(intake_keys, instance_report)
    metric_evidence = _quantitative_metric_evidence(metric_keys, instance_report)
    mapped_materials = _mapped_file_materials(
        block_id=block.id,
        file_materials=mapped_file_materials,
        decision=block_material_decision,
        label=prompt_labels(
            _package_for(template_report, instance_report, definition)
        ).evidence.mapped_material,
    )
    substantive_input_present = generation_has_substantive_input(
        instance_report,
        intake_item_ids=intake_keys,
        quantitative_metric_ids=metric_keys,
    ) or bool(mapped_materials)
    return GenerationEvidence(
        intake_facts=intake_facts,
        mapped_materials=mapped_materials,
        metric_evidence=metric_evidence,
        substantive_input_present=substantive_input_present,
    )


def _package_for(
    template_report: Report,
    instance_report: Report,
    definition: CompiledReportDefinition | None,
) -> KnowledgePackage:
    """The package of a generation call: the compiled definition's, else the template's, else the instance's."""

    if definition is not None:
        return load_knowledge_package(definition.package_id)
    return knowledge_package_of(
        template_report if template_report.knowledgePackageId is not None else instance_report
    )


def _mapped_file_materials(
    *,
    block_id: str,
    file_materials: tuple[FileMaterial, ...],
    decision: BlockMaterialDecision | None,
    label: str,
) -> tuple[Material, ...]:
    """将当前 Block 明确采用的 FileMaterial 投影为不含 lineage 的模型资料。"""

    if decision is None:
        if file_materials:
            raise ValueError("传入文件资料时必须同时提供当前 Block 的采用决定")
        return ()
    if decision.block_id != block_id:
        raise ValueError(
            f"BlockMaterialDecision 属于 {decision.block_id}，不能用于 {block_id}"
        )
    if decision.disposition not in {"supported", "partially_supported"}:
        if decision.material_ids:
            raise ValueError(
                f"{decision.disposition} 决定不得把文件资料送入生成上下文"
            )
        return ()

    materials_by_id = {material.material_id: material for material in file_materials}
    if len(materials_by_id) != len(file_materials):
        raise ValueError("文件资料内容身份不得重复")
    projected: list[Material] = []
    for material_id in decision.material_ids:
        material = materials_by_id.get(material_id)
        if material is None:
            raise ValueError(f"Block 采用决定引用了未知文件资料：{material_id}")
        projected.append(Material(label=label, text=material.content_markdown))
    return tuple(projected)


def _resolve_block_section_placement(
    definition: CompiledReportDefinition | None,
    template_report: Report,
    instance_report: Report,
    block_id: str,
) -> SectionPlacement | None:
    """块的 H2–H4 位置：编译定义优先，缺位时回落 Section 树。

    两条来源不是冗余：编译定义的 `report_section_title` 只对议题章节有值（由
    topic_registry 的 `reportSectionId` 填充），前四章块结构性为空；而 Section 树
    对两者都能解析。缺位即置 None 会让前四章块不知道自己在写哪一节。
    """

    if definition is not None:
        try:
            placement = definition.placement_for_block(block_id)
        except KeyError:
            placement = None
        if placement is not None and placement.report_section_title:
            return SectionPlacement(
                reportSectionTitle=placement.report_section_title,
                pillarTitle=placement.pillar_title,
                contentUnitTitle=placement.content_unit_title,
            )
    # 实例 Report 携带本次可见的章节结构；块不在实例树中（如按模板直建上下文的
    # 合同预览与测试路径）时回落模板态。_section_trail 对未知块 fail-loud，
    # 故两条都要收窄异常——位置缺失只应少一段提示词，不应中断生成。
    for source in (instance_report, template_report):
        try:
            placement = resolve_section_placement(source, block_id)
        except ValueError:
            continue
        if placement is not None:
            return placement
    return None


def build_model_context(
    block: Block,
    template_report: Report,
    instance_report: Report,
    *,
    definition: CompiledReportDefinition | None = None,
    task_kind: str = "generate",
    row_seed: RowSeed | None = None,
    mapped_file_materials: tuple[FileMaterial, ...] = (),
    block_material_decision: BlockMaterialDecision | None = None,
) -> ModelContext:
    """从配置 + 白名单 Report 字段/资料装配 ModelContext。这是**唯一**为构造模型上下文而访问 Report 的地方。

    生成元数据（GenerationTask / 轻量版写作口径 / 字数 targetChars / 准则披露要求 standardDisclosureRequirementKeys）以 block.generation 为唯一源；
    Prompt Profile 只提供跨议题稳定片段。准则披露要求仅按块声明解析，仅取模型可见字段。
    """
    package = _package_for(template_report, instance_report, definition)
    prompt_profile = load_prompt_profile(package)
    shared_system_segments = prompt_profile.shared_system_segments
    labels = prompt_profile.labels
    compiled_generation = (
        definition.generation_for_block(block.id) if definition is not None else None
    )
    intake_keys, metric_keys = _evidence_keys(
        block, template_report, instance_report, definition
    )
    evidence = resolve_generation_evidence(
        block,
        template_report,
        instance_report,
        definition,
        mapped_file_materials=mapped_file_materials,
        block_material_decision=block_material_decision,
    )
    metric_policy = _metric_narrative_policy(
        block,
        instance_report,
        metric_keys,
    )
    assessment = tuple(
        _assessment_whitelist(block, template_report, instance_report, definition)
    )
    has_substantive_inputs = (
        evidence.substantive_input_present
        or _has_assessment_iro_evidence(block, assessment)
    )
    if has_substantive_inputs and not evidence.substantive_input_present:
        evidence = evidence.model_copy(update={"substantive_input_present": True})
    has_generation_basis = has_substantive_inputs or metric_policy is not None
    g_spec = block.generation
    section_task = (
        compiled_generation.semantic_task
        if compiled_generation is not None
        else generation_task_focus(block)
    )
    if not has_substantive_inputs and g_spec and g_spec.task.noFactGuidance:
        section_task = "\n".join((section_task, g_spec.task.noFactGuidance.strip()))
    # 准则披露要求（standardDisclosureRequirementKeys → standard_disclosure_requirements）
    # 仍是数据资产，但不注入生成上下文：2026-09-07 A/B 已裁决（sse 无收益、gri 有害，
    # 模型会把无事实支撑的要求写成「本报告未包含…」触发在线守卫）。证据见 docs/todos.md §3.3。
    standard_disclosure_requirements: tuple[str, ...] = ()
    writing_granularity = (
        tuple(
            text
            for line in ((g_spec.simplifiedWritingGuidance if g_spec else None) or [])
            if (text := str(line).strip())
        )
        if has_substantive_inputs
        else ()
    )
    content_format = shared_system_segments.content_format.strip()
    if block.type == "paragraph" and not has_substantive_inputs:
        content_format = "\n".join(
            part
            for part in (
                content_format,
                labels.output.short_paragraph_per_variant,
            )
            if part
        )
    return ModelContext(
        knowledge_package_id=package.id,
        output_language=package.language,
        task_kind=task_kind,
        role=shared_system_segments.role.strip(),
        report_body_contract=shared_system_segments.report_body_contract.strip(),
        expression_guidance=(
            shared_system_segments.expression_guidance.strip()
            if block.type == "paragraph" and metric_policy is None
            else ""
        ),
        report_subject=tuple(
            _report_subject_lines(
                block,
                instance_report,
                shared_system_segments.context_fields,
                (
                    compiled_generation.field_ids
                    if compiled_generation is not None
                    else None
                ),
                labels=labels,
            )
        ),
        topic_scope=(
            _compiled_topic_scope_text(definition, instance_report, block, labels=labels)
            if definition is not None
            else _topic_scope_text(instance_report, template_report, block, labels=labels)
        ),
        # 已披露正文按支柱先后解析；无编译定义时（历史/测试路径）不臆测先后，留空。
        prior_disclosures=(
            prior_disclosures_for_block(instance_report, definition, block.id)
            if definition is not None
            else ()
        ),
        pillar_purpose=(
            definition.placement_for_block(block.id).pillar_purpose
            if definition is not None
            else resolve_pillar_purpose(template_report, block.id)
        ),
        # 章节位置优先取编译定义；前四章块在编译侧恒为空——`report_section_title` 只由
        # topic_registry 的 `reportSectionId` 填充（compiled_definition.py:739-741），
        # 而 report_contract.yaml 全文无该字段，故前四章结构性拿不到编译位置。
        # 此时回落 Section 树解析：块必须知道自己在写哪一节，否则跨章节复述只剩提示词
        # 一层防线，而消费该提示词的块连自己在哪一节都不知道（如 report_contract.yaml
        # 的「法人治理结构属公司治理章节，不得在此复述」）。
        section_placement=_resolve_block_section_placement(
            definition, template_report, instance_report, block.id
        ),
        section_task=section_task,
        disclosure_stance=(g_spec.disclosureStance if g_spec else "standard"),
        public_disclosure_guidance=resolve_public_disclosure_guidance(
            g_spec.disclosureStance if g_spec else "standard", prompt_profile
        ),
        standard_disclosure_requirements=standard_disclosure_requirements,
        intake_generation_boundaries=_intake_generation_boundaries(
            intake_keys, instance_report, labels=labels
        ),
        writing_granularity=writing_granularity,
        evidence=evidence,
        evidence_posture=resolve_evidence_posture(
            prompt_profile.evidence_postures,
            substantive_input_present=has_substantive_inputs,
            metric_narrative=metric_policy is not None,
        ),
        metric_narrative_policy=metric_policy,
        length=(g_spec.targetChars if g_spec and g_spec.targetChars and has_generation_basis else None),
        content_format=content_format,
        assessment=assessment,
        display_title_task=(
            DisplayTitleTask(guidance=compiled_generation.display_title_guidance)
            if compiled_generation is not None
            and compiled_generation.display_title_guidance is not None
            else (
                None
                if definition is not None
                else _display_title_task(template_report, block.id)
            )
        ),
        row_context=(
            {k: v for k, v in row_seed.model_dump().items() if v} if row_seed else {}
        ),
    )


def _xml_escape(s: str) -> str:
    """转义用户内容里的 XML 特殊字符，杜绝伪造结构标签（如 </filled_content>、<role>）越权——防提示词注入。"""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _filled_items_xml(materials: tuple[Material, ...], labels: PromptLabels) -> str:
    """用户填写/资料渲染为转义后的 <item> 列表——label/text/note 全部转义，结构标签由系统侧控制。"""
    sep = labels.key_value_separator
    items: list[str] = []
    for m in materials:
        lines = ["<item>", f"{labels.evidence.intake_item}{sep}{_xml_escape(m.label)}"]
        if m.text.strip():
            lines.append(_xml_escape(m.text))
        if m.note:
            lines.append(f"{labels.evidence.intake_note}{sep}{_xml_escape(m.note)}")
        lines.append("</item>")
        items.append("\n".join(lines))
    return "\n".join(items)


def _xml(tag: str, body: str) -> str:
    """结构化分隔：把片段包进 XML 标签（取代 ## 拼接）。"""
    return f"<{tag}>\n{body.strip()}\n</{tag}>"


def model_visible_assessment_lines(
    assessment: tuple[AssessmentBrief, ...],
    *,
    iro_kind_labels: IroKindLabels,
    key_value_separator: str,
) -> tuple[str, ...]:
    """仅投影模型需要消费的 IRO 结论；重要性已由 Planner 解析为内容树。

    ``kind`` is an internal enum; the package's assessment vocabulary names it for the model.
    """

    lines: list[str] = []
    for t in assessment:
        if not t.iro:
            continue
        lines.append(f"- {t.name}")
        for iro in t.iro or []:
            label = getattr(iro_kind_labels, iro.kind, iro.kind)
            lines.append(f"  · {label}{key_value_separator}{iro.description}")
    return tuple(lines)


def _metric_narrative_policy_body(ctx: ModelContext, profile: ReportGenerationPromptProfile) -> str:
    """将 typed 无值指标正文授权投影为独立 Prompt 片段。"""

    policy = ctx.metric_narrative_policy
    if policy is None:
        return ""
    return "\n".join(
        metric_narrative_policy_rules(
            policy, profile.metric_narrative, list_separator=profile.labels.list_separator
        )
    )


def section_placement_lines(
    placement: SectionPlacement, labels: PromptLabels
) -> tuple[str, ...]:
    """以稳定业务名称投影当前正文位置，供生成与 Judge 复用。"""

    sep = labels.key_value_separator
    words = labels.structure
    lines = [f"{words.report_section}{sep}{placement.reportSectionTitle}"]
    if placement.pillarTitle:
        lines.append(f"{words.pillar}{sep}{placement.pillarTitle}")
    if placement.contentUnitTitle:
        lines.append(f"{words.content_unit}{sep}{placement.contentUnitTitle}")
    lines.append(words.placement_anchor_note)
    lines.append(words.placement_output_note)
    return tuple(lines)


def _prior_disclosure_text(
    disclosures: tuple[PriorDisclosure, ...], labels: PromptLabels
) -> str:
    """把已披露正文投影为模型可读的既成事实；只出支柱名与正文，不出 blockId 与状态。

    与 <topic_scope> 分段表达：topic_scope 说「相邻任务负责什么」（事前边界），
    本段说「报告里已经写了什么」（既成事实）。合并会让模型分不清哪些是计划、
    哪些已发生，进而把尚未落定的内容当成已披露。

    实测（真实轨迹上下文，n=5）：反商业贿赂议题
    iro_management_measures 块的重复表述 25/25 → 0/25，本块自有表述 15/15 全保。
    同议题 iro_management_framework 块自有表述同时下降（15/15 → 6/15），
    原因是该块收到的 intake_facts 与治理块完全相同——它本就没有属于自己的事实，
    属内容清单的题目归属问题，不是本段的副作用。
    """

    words = labels.structure
    lines = [
        words.prior_disclosure_item.format(pillar_title=item.pillar_title, text=item.text)
        for item in disclosures
    ]
    return (
        words.prior_disclosure_heading
        + "\n"
        + "\n".join(lines)
        + "\n"
        + words.prior_disclosure_footer
    )


def _system_segments(
    ctx: ModelContext,
    *,
    task: str,
    include_context_only_calibration: bool = False,
) -> list[str]:
    """System 提示词 XML 分段（越靠前越静态，利于缓存）；段落/表格生成共用，task 由调用方给定。"""
    profile = context_profile(ctx)
    labels = profile.labels
    sep = labels.key_value_separator
    segs: list[str] = [
        _xml("output_language", OUTPUT_LANGUAGE_DIRECTIVES[ctx.output_language])
    ]
    if ctx.role:
        segs.append(_xml("role", ctx.role))
    if ctx.report_body_contract:
        segs.append(_xml("report_body_contract", ctx.report_body_contract))
    if ctx.expression_guidance:
        segs.append(_xml("expression_guidance", ctx.expression_guidance))
    if ctx.report_subject:
        segs.append(_xml("report_subject", "\n".join(ctx.report_subject)))
    if ctx.section_placement is not None:
        segs.append(
            _xml(
                "section_placement",
                "\n".join(section_placement_lines(ctx.section_placement, labels)),
            )
        )
    evidence = ctx.evidence_posture
    words = labels.structure
    segs.append(
        _xml(
            "evidence_posture",
            f"{words.evidence_level}{sep}{evidence.level}\n"
            f"{words.source_use}{sep}{evidence.sourceUse}\n"
            f"{words.assertion_style}{sep}{evidence.assertionStyle}",
        )
    )
    segs.append(_xml("section_task", task))
    if ctx.topic_scope:
        segs.append(_xml("topic_scope", ctx.topic_scope))
    if ctx.prior_disclosures:
        segs.append(
            _xml("prior_disclosure", _prior_disclosure_text(ctx.prior_disclosures, labels))
        )
    if (
        include_context_only_calibration
        and evidence.level == "context_only"
    ):
        calibration_lines = context_only_calibration_lines(ctx.pillar_purpose, profile)
        if calibration_lines:
            segs.append(
                _xml(
                    "context_only_calibration",
                    "\n".join(calibration_lines),
                )
            )
    if ctx.display_title_task is not None:
        segs.append(
            _xml(
                "display_title_task",
                ctx.display_title_task.guidance + "\n" + labels.output.display_title_sync,
            )
        )
    if ctx.public_disclosure_guidance:
        segs.append(_xml("public_disclosure_guidance", ctx.public_disclosure_guidance))
    if ctx.standard_disclosure_requirements:
        segs.append(
            _xml(
                "standard_disclosure_requirements",
                "\n".join(f"- {item}" for item in ctx.standard_disclosure_requirements),
            )
        )
    metric_policy = _metric_narrative_policy_body(ctx, profile)
    if metric_policy:
        segs.append(_xml("metric_narrative_policy", metric_policy))
    if ctx.intake_generation_boundaries:
        segs.append(
            _xml(
                "intake_generation_boundaries",
                "\n".join(f"- {item}" for item in ctx.intake_generation_boundaries),
            )
        )
    if ctx.writing_granularity:
        segs.append(_xml("writing_granularity", "\n".join(f"- {line}" for line in ctx.writing_granularity)))
    iro_context = model_visible_assessment_lines(
        ctx.assessment,
        iro_kind_labels=assessment_vocabulary(context_package(ctx)).iroKind,
        key_value_separator=sep,
    )
    if iro_context:
        segs.append(
            _xml("iro_context", "\n".join([words.iro_context_directive, *iro_context]))
        )
    if ctx.length:
        length_guidance = (
            labels.output.length_metric_narrative.format(min=ctx.length[0], max=ctx.length[1])
            if ctx.metric_narrative_policy is not None
            else labels.output.length_default.format(max=ctx.length[1])
        )
        segs.append(_xml("length", length_guidance))
    return segs


def _filled_content(ctx: ModelContext) -> str:
    """User 提示词：仅承载用户填写，转义后包进 <filled_content>/<item>；未填写写纯事实。无走标杆/据料等指令（指令在 System）。"""
    labels = context_profile(ctx).labels
    materials = filled_content_materials(ctx)
    if ctx.metric_narrative_policy is not None and not materials:
        return f"<filled_content>{labels.evidence.no_metric_values}</filled_content>"
    if materials:
        return "<filled_content>\n" + _filled_items_xml(materials, labels) + "\n</filled_content>"
    return "<filled_content />"


def render_prompt(ctx: ModelContext, *, n: int = 3) -> tuple[str, str]:
    """ModelContext → (系统提示词, 用户提示词)。System 全 XML、静态在前；User 仅 filled_content。只读 ctx。"""
    segs = _system_segments(
        ctx,
        task=ctx.section_task,
        include_context_only_calibration=(
            ctx.metric_narrative_policy is None
        ),
    )
    output_words = context_profile(ctx).labels.output
    if n == 1:
        variant_requirement = output_words.single_variant
    elif ctx.metric_narrative_policy is not None:
        variant_requirement = output_words.variants_same_level.format(n=n)
    else:
        variant_requirement = output_words.variants_diverse.format(n=n)
    output_contract = (
        output_words.structured_output_lead + variant_requirement + output_words.content_complete
    )
    if ctx.display_title_task is not None:
        output_contract += "\n" + output_words.display_title_pairing
    segs.append(_xml("output_contract", output_contract))
    if ctx.content_format:
        segs.append(_xml("content_format", ctx.content_format))
    system = "\n\n".join(s for s in segs if s and s.strip())
    return system, _filled_content(ctx)


def _col_spec_lines(columns: list[GsColDef], labels: PromptLabels) -> list[str]:
    """列规格（仅露 header + 选项 + genHint，绝不露列 key/内部结构）。"""
    words = labels.table
    out: list[str] = []
    for col in columns:
        desc = col.header
        if col.options:
            template = (
                words.options_multi_template
                if col.cellType == "multi_select"
                else words.options_single_template
            )
            desc += template.format(options=labels.list_separator.join(col.options))
        if col.genHint:
            desc += words.hint_template.format(hint=col.genHint)
        out.append(f"- {desc}")
    return out


def render_propose_prompt(ctx: ModelContext, columns: list[GsColDef], *, count_min: int, count_max: int) -> tuple[str, str]:
    """定行：让模型据表主题 + 路径口径输出 RowSeed 条目清单（结构化）。System 与段落生成同源 XML 装配。"""
    words = context_profile(ctx).labels.table
    task = (
        f"{ctx.section_task}\n"
        + words.propose_task.format(count_min=count_min, count_max=count_max)
    )
    segs = _system_segments(ctx, task=task)
    system = "\n\n".join(s for s in segs if s and s.strip())
    return system, _filled_content(ctx)


def render_catalog_table_fill_prompt(
    ctx: ModelContext,
    catalog_rows: list[dict[str, str | None]],
    columns: list[GsColDef],
    *,
    kind_label: str,
) -> tuple[str, str]:
    """目录表整表填充：锚点行由契约或前置定行给定，用户资料作为全表参考，不逐行照搬。"""
    labels = context_profile(ctx).labels
    words = labels.table
    support_words = labels.table_support
    header_by_key = {col.key: col.header for col in columns}
    row_xml_blocks: list[str] = []
    for row in catalog_rows:
        anchor_parts = [
            f'<column label="{_xml_escape(header_by_key.get(key, key))}">{_xml_escape(str(value))}</column>'
            for key, value in row.items()
            if key not in CATALOG_INTERNAL_ROW_KEYS and value
        ]
        ref = row.get("referenceImpact")
        support_status = str(row.get(CATALOG_ROW_SUPPORT_STATUS_KEY) or "framework_anchor")
        support_evidence = str(
            row.get(CATALOG_ROW_SUPPORT_EVIDENCE_KEY) or support_words.default_evidence
        )
        writing_rule = str(
            row.get(CATALOG_ROW_WRITING_RULE_KEY) or support_words.default_writing_rule
        )
        row_parts = [
            "<catalog_row>",
            "<anchor_columns>",
            "\n".join(anchor_parts),
            "</anchor_columns>",
            '<row_input_support status="' + _xml_escape(support_status) + '">',
            f"<business_meaning>{_xml_escape(support_evidence)}</business_meaning>",
            f"<writing_rule>{_xml_escape(writing_rule)}</writing_rule>",
            "</row_input_support>",
        ]
        if ref:
            row_parts.append(f"<reference_scope>{_xml_escape(str(ref))}</reference_scope>")
        row_parts.append("</catalog_row>")
        row_xml_blocks.append("\n".join(row_parts))
    row_input_context = (
        "<catalog_row_input_context>\n"
        "<support_status_guide>\n"
        '<support_status code="user_supported_anchor">\n'
        + words.user_supported_guide
        + "\n"
        "</support_status>\n"
        '<support_status code="framework_anchor">\n'
        + words.framework_guide
        + "\n"
        "</support_status>\n"
        "</support_status_guide>\n"
        "<catalog_rows>\n"
        + "\n".join(row_xml_blocks)
        + "\n</catalog_rows>\n"
        "</catalog_row_input_context>"
    )
    task = "\n".join(
        (
            ctx.section_task,
            words.catalog_task.format(kind_label=kind_label),
            words.column_requirements,
            "\n".join(_col_spec_lines(columns, labels)),
            words.catalog_user_material_rules,
            words.row_input_context_heading,
            row_input_context,
        )
    )
    segs = _system_segments(ctx, task=task)
    system = "\n\n".join(s for s in segs if s and s.strip())
    return system, _filled_content(ctx)


def render_adaptive_propose_prompt(
    ctx: ModelContext,
    anchor_cols: list[GsColDef],
    references: list,
    *,
    count_min: int,
    count_max: int,
    kind_label: str,
) -> tuple[str, str]:
    """adaptive_catalog 前置：据报告主体业务/行业识别本企业**适用**的锚点条目（类别/类型），有界行数。

    典型参考清单（referenceCatalog）仅供参照取舍、不得照抄、不得套用不适用项；只有本表绑定用户输入直接支持时才补充清单外条目。
    锚点列的选项/genHint 经 _col_spec_lines 进 System；User 仅 filled_content。
    """
    labels = context_profile(ctx).labels
    words = labels.table
    ref_lines = "\n".join(
        f"- {(r.category + '·') if r.category else ''}{r.name}"
        + (words.reference_note.format(reference=r.reference) if r.reference else "")
        for r in references
    )
    # 清单含机遇类条目的表，所选条目至少覆盖一条机遇：表题承诺「风险与机遇」，只给风险
    # 是准则缺口。清单本身无机遇类（如反商业贿赂，本就只有风险）的表不加该约束——
    # 覆盖要求由清单构成派生；「机遇」一词取自包的评估词表，不硬编码。
    opportunity_word = assessment_vocabulary(context_package(ctx)).iroKind.opportunity
    opportunity_categories = sorted(
        {r.category for r in references if r.category and opportunity_word in r.category}
    )
    coverage_line = (
        "\n"
        + words.opportunity_coverage.format(
            categories=labels.list_separator.join(opportunity_categories)
        )
        if opportunity_categories
        else ""
    )
    task = (
        words.adaptive_task.format(kind_label=kind_label, count_min=count_min, count_max=count_max)
        + "\n"
        + "\n".join(_col_spec_lines(anchor_cols, labels))
        + "\n"
        + words.adaptive_field_rule
        + "\n"
        + words.adaptive_reference_intro
        + "\n"
        + (ref_lines or words.none)
        + coverage_line
    )
    segs = _system_segments(ctx, task=task)
    system = "\n\n".join(s for s in segs if s and s.strip())
    return system, _filled_content(ctx)


def render_complete_prompt(
    ctx: ModelContext,
    columns: list[GsColDef],
    *,
    expansion: RowExpansion | None = None,
) -> tuple[str, str]:
    """补全：让模型据 row_seed + 列规格生成完整一行（结构化输出，schema 由调用方按 columns 推导）。

    契约声明 rowExpansion 时，按披露子行分组呈现要求：共享项每个条目只写一次，
    各子行各自有独立的写作口径与候选。合并、行序与占位格属实现细节，不进入模型视野。
    """
    labels = context_profile(ctx).labels
    words = labels.table
    sep = labels.key_value_separator
    if expansion is not None:
        by_key = {col.key: col for col in columns}
        shared_lines = _col_spec_lines([by_key[key] for key in expansion.sharedColumnKeys], labels)
        unit_blocks = []
        for unit in expansion.units:
            unit_cols = [
                by_key[key].model_copy(
                    update={
                        "options": (unit.optionsNarrowing or {}).get(key, by_key[key].options),
                        "genHint": (unit.genHintOverride or {}).get(key, by_key[key].genHint),
                    }
                )
                for key in unit.columnKeys
            ]
            unit_blocks.append(
                words.unit_heading.format(label=unit.label)
                + "\n"
                + "\n".join(_col_spec_lines(unit_cols, labels))
            )
        unit_labels = labels.list_separator.join(
            words.unit_name.format(label=u.label) for u in expansion.units
        )
        task = (
            f"{ctx.section_task}\n"
            + words.expansion_task
            + "\n"
            + words.expansion_units_intro.format(
                count=len(expansion.units), unit_labels=unit_labels
            )
            + "\n"
            + words.expansion_shared_intro
            + "\n"
            + "\n".join(shared_lines)
            + "\n\n"
            + words.expansion_units_lead
            + "\n"
            + "\n\n".join(unit_blocks)
        )
    else:
        task = (
            f"{ctx.section_task}\n"
            + words.complete_row_task
            + "\n"
            + "\n".join(_col_spec_lines(columns, labels))
        )
    segs = _system_segments(ctx, task=task)
    system = "\n\n".join(s for s in segs if s and s.strip())
    user_bits: list[str] = []
    if ctx.row_context:
        seed_lines = [f"{words.row_theme}{sep}{_xml_escape(str(ctx.row_context.get('theme', '')))}"]
        if ctx.row_context.get("category"):
            seed_lines.append(f"{words.row_category}{sep}{_xml_escape(str(ctx.row_context['category']))}")
        if ctx.row_context.get("driver_hint"):
            seed_lines.append(
                f"{words.row_driver_hint}{sep}{_xml_escape(str(ctx.row_context['driver_hint']))}"
            )
        user_bits.append(_xml("row_seed", "\n".join(seed_lines)))
    user_bits.append(_filled_content(ctx))
    user = "\n\n".join(user_bits)
    return system, user
