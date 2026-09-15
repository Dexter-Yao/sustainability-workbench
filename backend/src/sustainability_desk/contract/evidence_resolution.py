# ABOUTME: 将 Report 中的内容清单与指标值解析为生成证据状态，供导航、旅程和模型上下文共同消费。
# ABOUTME: 本模块只拥有确定性证据解析，不定义模型可见 DTO、Prompt 或生成策略。
# ABOUTME(en): Resolves a Report's material inventory and metric values into generation evidence state.
# ABOUTME(en): Owns deterministic evidence resolution only; defines no model-visible DTO, prompt or generation strategy.
from __future__ import annotations

from dataclasses import dataclass

from sustainability_desk.contract.compiled_definition import CompiledReportDefinition
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.language import Language, non_substantive_answers
from sustainability_desk.contract.loader import quantitative_metrics_vocabulary
from sustainability_desk.contract.models import (
    Block,
    ExplicitGenerationEvidenceSelector,
    IntakeItem,
    MaterialGatedGenerationEvidenceSelector,
    Report,
    ReportSectionGenerationEvidenceSelector,
    Section,
)
from sustainability_desk.contract.topic_section_template import compiled_metric_disclosure_keys
from sustainability_desk.quantitative_metrics import (
    quantitative_metric_draft,
    quantitative_metric_value,
    quantitative_metrics_by_key,
    quantitative_metrics_meta,
)



@dataclass(frozen=True)
class AnswerWording:
    """Words the caller supplies when an intake answer is projected to text (they are model-visible).

    Comes from the package's prompt profile labels; the contract layer never hard-codes them.
    """

    selected_lead: str
    supplement_lead: str
    list_separator: str
    part_separator: str


# Wording used only to decide whether an answer is substantive; the text is never shown.
_PROBE_WORDING = AnswerWording(selected_lead="", supplement_lead="", list_separator="", part_separator="")


def _selection_satisfies_option_groups(item: IntakeItem, selected: list[str]) -> bool:
    """多选题分组最小选择校验；未声明分组时不额外约束。"""

    if not item.optionGroups:
        return True
    selected_set = set(selected)
    for group in item.optionGroups:
        count = sum(1 for option in group.options if option in selected_set)
        if count < group.minSelections:
            return False
    return True


def intake_item_ready(item: IntakeItem) -> bool:
    """判断结构化答案是否合法；资料是否实质由 ``intake_ready_text`` 另行解析。"""

    answer = item.answer
    options = set(item.options or [])
    has_supplement = isinstance(item.supplement, str) and bool(item.supplement.strip())
    if item.kind == "text":
        return (isinstance(answer, str) and bool(answer.strip())) or has_supplement
    if item.kind == "single_select":
        return (isinstance(answer, str) and answer in options) or has_supplement
    if (
        not isinstance(answer, list)
        or not answer
        or not all(isinstance(value, str) and value in options for value in answer)
    ):
        return False if item.optionGroups else has_supplement
    return _selection_satisfies_option_groups(item, answer)


def is_non_substantive_selection(value: str, language: Language) -> bool:
    """判断选择题答案是否只表达无资料、否定或不确定。"""

    return non_substantive_answers(language).is_non_substantive_selection(value)


def is_non_substantive_text_answer(value: str, language: Language) -> bool:
    """判断自由文本是否只是空缺状态标记，而非描述性事实。"""

    return non_substantive_answers(language).is_non_substantive_text(value)


def intake_answer_is_substantive(item: IntakeItem, language: Language) -> bool:
    """Whether the answer body alone (without the supplement) carries a company fact."""

    return intake_answer_text(item, language=language, wording=_PROBE_WORDING) is not None


def intake_answer_text(item: IntakeItem, *, language: Language, wording: AnswerWording) -> str | None:
    """只投影答案本体（不含补充说明）的实质事实文本；非实质选项与空缺标记不产出。"""

    if not intake_item_ready(item):
        return None
    answer = item.answer
    options = set(item.options or [])
    generation_labels = item.generationOptionLabels or {}

    def projected_label(value: str) -> str:
        return generation_labels.get(value, value)

    if item.kind == "text":
        if (
            isinstance(answer, str)
            and answer.strip()
            and not is_non_substantive_text_answer(answer, language)
        ):
            return answer.strip()
        return None
    if item.kind == "single_select":
        if (
            isinstance(answer, str)
            and answer in options
            and not is_non_substantive_selection(answer, language)
        ):
            return f"{wording.selected_lead}{projected_label(answer)}"
        return None
    if isinstance(answer, list) and answer and all(value in options for value in answer):
        substantive = [
            value for value in answer if not is_non_substantive_selection(value, language)
        ]
        if substantive:
            return wording.selected_lead + wording.list_separator.join(projected_label(value) for value in substantive)
    return None


def intake_supplement_text(item: IntakeItem) -> str | None:
    """投影用户补充说明原话；仅在结构化答案合法（item ready）时可用。"""

    if not intake_item_ready(item):
        return None
    if isinstance(item.supplement, str) and item.supplement.strip():
        return item.supplement.strip()
    return None


def intake_ready_text(item: IntakeItem, *, language: Language, wording: AnswerWording) -> str | None:
    """将合法且实质的内容清单答案投影为模型和运行状态共用的事实文本。

    prompt 侧（prompts._intake_items）改用 ``intake_answer_text`` 与
    ``intake_supplement_text`` 分离渲染——补充说明作为用户原话独立呈现，
    使模型能区分「企业事实」与「用户备注」；本函数保持拼接语义，供表格
    生成与运行状态等既有消费方使用。
    """

    parts: list[str] = []
    answer_text = intake_answer_text(item, language=language, wording=wording)
    if answer_text:
        parts.append(answer_text)
    supplement = intake_supplement_text(item)
    if supplement:
        parts.append(f"{wording.supplement_lead}{supplement}")
    return wording.part_separator.join(parts) if parts else None


def _section_with_report_section_id(
    report: Report, report_section_id: str
) -> Section | None:
    def walk(sections: list[Section]) -> Section | None:
        for section in sections:
            if section.reportSectionId == report_section_id:
                return section
            found = walk(section.children or [])
            if found is not None:
                return found
        return None

    return walk(report.sections)


def _section_report_section_of(report: Report, block_id: str) -> str | None:
    def walk(
        sections: list[Section], inherited: str | None
    ) -> tuple[bool, str | None]:
        for section in sections:
            effective = section.reportSectionId or inherited
            if any(block.id == block_id for block in section.blocks) or (
                section.conciseDisclosure is not None
                and section.conciseDisclosure.id == block_id
            ):
                return True, effective
            found, value = walk(section.children or [], effective)
            if found:
                return True, value
        return False, None

    return walk(report.sections, None)[1]


def generation_evidence_keys(
    block: Block,
    template_report: Report,
    instance_report: Report,
    definition: CompiledReportDefinition | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """将生成 selector 解析为唯一的内容清单与指标 key 集合。"""

    if definition is not None:
        generation = definition.generation_for_block(block.id)
        return generation.intake_item_ids, generation.quantitative_metric_ids
    inputs = block.generation.inputs if block.generation else None
    selector = (
        inputs.evidence
        if inputs
        else ExplicitGenerationEvidenceSelector(kind="explicit")
    )
    if isinstance(selector, ExplicitGenerationEvidenceSelector):
        return tuple(selector.intakeItems), tuple(selector.quantitativeMetrics)
    if isinstance(selector, MaterialGatedGenerationEvidenceSelector):
        return tuple(selector.intakeItems), ()
    if not isinstance(selector, ReportSectionGenerationEvidenceSelector):
        raise ValueError(f"块 {block.id} 使用了不支持的证据选择器")
    report_section_id = _section_report_section_of(template_report, block.id)
    if report_section_id is None:
        raise ValueError(f"块 {block.id} 无法解析所属 reportSectionId")
    report_section = _section_with_report_section_id(template_report, report_section_id)
    if report_section is None:
        raise ValueError(f"块 {block.id} 所属报告章节 {report_section_id} 不存在")
    intake_keys = tuple(
        item.key
        for item in instance_report.intakeItems
        if item.contentScopeId == report_section_id
    )
    return intake_keys, compiled_metric_disclosure_keys(report_section)


def greenhouse_gas_accounting_standard(
    metric_key: str, report: Report
) -> str | None:
    """只为声明需要核算标准的温室气体指标返回用户已填标准。"""

    package = knowledge_package_of(report)
    metric = quantitative_metrics_by_key(package).get(metric_key)
    if metric is None or not metric.requiresGreenhouseGasAccountingStandard:
        return None
    meta = quantitative_metrics_meta(report)
    standard = str(meta.get("greenhouseGasAccountingStandard") or "").strip()
    if standard == quantitative_metrics_vocabulary(package).otherStandardLabel:
        standard = str(meta.get("greenhouseGasAccountingStandardOther") or "").strip()
    return standard or None


def quantitative_metric_has_substantive_input(
    metric_key: str, report: Report
) -> bool:
    """指标值、用户备注或适用核算标准任一存在即构成指标事实。"""

    draft = quantitative_metric_draft(report, metric_key)
    return (
        quantitative_metric_value(report, metric_key) is not None
        or bool(str(draft.get("note") or "").strip())
        or greenhouse_gas_accounting_standard(metric_key, report) is not None
    )


def intake_has_gate_opening_evidence(item: IntakeItem, language: Language) -> bool:
    """证据门控 intake 臂的开门判定：答案实质，或补充说明含真实事实。

    与 ``generation_has_substantive_input`` 的差别只有一处：纯状态标记的补充说明
    （「暂无」「暂未填写」等，见 ``is_non_substantive_text_answer``）不开门——
    门控 selector 声明的是「存在实质答案」，零证据不得出具。姿态与 prompt 投影不受影响：否定状态补充说明仍按口径信息进入生成。
    """

    if intake_answer_is_substantive(item, language):
        return True
    supplement = intake_supplement_text(item)
    return supplement is not None and not is_non_substantive_text_answer(supplement, language)


def generation_has_gate_opening_evidence(
    report: Report, *, intake_item_ids: tuple[str, ...]
) -> bool:
    """material_gated 组合门控的 intake 臂判定；材料臂由 Mapping 决定承载。"""

    items_by_key = {item.key: item for item in report.intakeItems}
    language = knowledge_package_of(report).language
    return any(
        intake_has_gate_opening_evidence(item, language)
        for key in intake_item_ids
        if (item := items_by_key.get(key)) is not None
    )


def generation_has_substantive_input(
    report: Report,
    *,
    intake_item_ids: tuple[str, ...],
    quantitative_metric_ids: tuple[str, ...],
) -> bool:
    """只按已解析 selector 判断当前生成节点是否存在实质企业证据。"""

    items_by_key = {item.key: item for item in report.intakeItems}
    language = knowledge_package_of(report).language
    if any(
        intake_answer_is_substantive(item, language) or intake_supplement_text(item) is not None
        for key in intake_item_ids
        if (item := items_by_key.get(key)) is not None
    ):
        return True
    return any(
        quantitative_metric_has_substantive_input(key, report)
        for key in quantitative_metric_ids
    )
