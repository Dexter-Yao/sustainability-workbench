# ABOUTME: 根据已解析议题合同和重要性结果，装配五个报告模块及其报告章节。
# ABOUTME: Planner 只消费 AssessmentTopic → ReportSection → ReportModule 单向关系，不猜测实体类型或补造内容骨架。
# ABOUTME(en): Assembles the five report modules and their report sections from parsed topic contracts and materiality.
# ABOUTME(en): Consumes only the one-way AssessmentTopic to ReportSection to ReportModule relation; invents no content.
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Generator

import yaml

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.loader import validate_column_keys_in_blocks
from sustainability_desk.contract.assessment_projection import apply_assessment_projection
from sustainability_desk.contract.models import AssessmentResult, Block, IntakeItem, Materiality, Report, Section
from sustainability_desk.contract.stakeholder_engagement import apply_stakeholder_engagement_projection
from sustainability_desk.contract.topic_section_template import (
    TopicSectionTemplate,
    compile_topic_section_template,
)
from sustainability_desk.contract.topic_registry import (
    applicability_facts_from_report,
    applies,
    load_topic_contract,
)
from sustainability_desk.contract.compiled_definition import (
    CompiledReportDefinition,
    load_compiled_report_definition,
)


class TopicGuardError(Exception):
    """报告装配失败：重要性结果、当前适用范围或议题模板不一致。"""


@dataclass(frozen=True)
class PlanDiagnostic:
    reportSectionId: str
    status: str


@dataclass
class PlanResult:
    report: Report
    diagnostics: list[PlanDiagnostic] = field(default_factory=list)


def _has_financial_materiality(materialities: list[Materiality]) -> bool:
    return any(value in {"financial", "dual"} for value in materialities)


def _assessment_by_id(assessment: AssessmentResult) -> dict[str, object]:
    return {topic.assessmentTopicId: topic for topic in assessment.topics}


def _validate_assessment_scope(
    fixed: Report,
    assessment: AssessmentResult,
    definition: CompiledReportDefinition,
) -> dict[str, object]:
    facts = applicability_facts_from_report(fixed)
    expected = tuple(
        topic for topic in definition.assessment_topics if applies(topic.applicability, facts)
    )
    expected_ids = {topic.id for topic in expected}
    by_id = _assessment_by_id(assessment)
    actual_ids = set(by_id)
    if actual_ids == expected_ids:
        return by_id

    missing = [topic.name for topic in expected if topic.id not in actual_ids]
    topics_by_id = {topic.id: topic for topic in definition.assessment_topics}
    excluded = [
        topics_by_id[topic_id].name
        if topic_id in topics_by_id
        else topic_id
        for topic_id in sorted(actual_ids - expected_ids)
    ]
    messages: list[str] = []
    if missing:
        messages.append(f"重要性结果缺少适用议题：{'、'.join(missing)}")
    if excluded:
        messages.append(f"重要性结果包含当前配置不适用议题：{'、'.join(excluded)}")
    raise TopicGuardError("；".join(messages))


def _assemble_report_section(
    template: Section,
    *,
    member_materialities: list[Materiality],
) -> Section:
    """按合并 H2 的重要性聚合结果选择四要素或直属摘要分支。"""
    if _has_financial_materiality(member_materialities):
        return template.model_copy(update={"blocks": [], "conciseDisclosure": None})
    if template.conciseDisclosure is None:
        raise TopicGuardError(f"报告章节 {template.title} 缺少 conciseDisclosure 分支。")
    return template.model_copy(
        update={
            "blocks": [template.conciseDisclosure],
            "children": None,
            "conciseDisclosure": None,
        }
    )


def _insert_modules_before_appendix(fixed_sections: list[Section], modules: list[Section]) -> list[Section]:
    appendix_index = next(
        (index for index, section in enumerate(fixed_sections) if section.key == "report_appendix"),
        len(fixed_sections),
    )
    return [*fixed_sections[:appendix_index], *modules, *fixed_sections[appendix_index:]]


def assemble_report(
    fixed: Report,
    topic_templates: dict[str, Section],
    *,
    assessment: AssessmentResult | None,
    intake_items: list[IntakeItem] | None = None,
    definition: CompiledReportDefinition | None = None,
    complete_coverage: bool = False,
) -> PlanResult:
    """固定前章 + 严格议题合同 + 完整重要性结果 → Report。"""
    definition = definition or load_compiled_report_definition(knowledge_package_of(fixed))
    diagnostics: list[PlanDiagnostic] = []
    relationships = {
        relationship.report_section_id: relationship
        for relationship in definition.topic_relationships
        if applies(relationship.applicability, applicability_facts_from_report(fixed))
    }
    report_sections_by_id = {section.id: section for section in definition.report_sections}
    topics_by_id = {topic.id: topic for topic in definition.assessment_topics}
    applicable_sections = [
        (
            report_sections_by_id[section.id],
            tuple(topics_by_id[topic_id] for topic_id in relationships[section.id].assessment_topic_ids),
        )
        for section in definition.report_sections
        if section.id in relationships
    ]
    applicable_section_ids = {section.id for section, _topics in applicable_sections}

    if complete_coverage and assessment is not None:
        raise TopicGuardError("完整议题覆盖策略不得携带重要性评分结果")
    if (assessment is None or not assessment.topics) and not complete_coverage:
        modules: list[Section] = []
    else:
        assessment_by_id = (
            _validate_assessment_scope(fixed, assessment, definition)
            if not complete_coverage
            else {}
        )
        sections_by_module: dict[str, list[Section]] = {}
        for report_section, assessment_topics in applicable_sections:
            template = topic_templates.get(report_section.id)
            if template is None:
                diagnostics.append(PlanDiagnostic(report_section.id, "template_missing"))
                raise TopicGuardError(f"适用报告章节 {report_section.title} 缺少章节模板。")
            section_template = (
                template
                if complete_coverage
                else _assemble_report_section(
                    template,
                    member_materialities=[
                        assessment_by_id[topic.id].materiality
                        for topic in assessment_topics
                    ],
                )
            )
            section = section_template.model_copy(
                update={
                    "title": report_section.title,
                    "reportSectionId": report_section.id,
                }
            )
            sections_by_module.setdefault(report_section.reportModuleId, []).append(section)
            diagnostics.append(PlanDiagnostic(report_section.id, "report_section_included"))

        modules = []
        for module in sorted(definition.report_modules, key=lambda item: item.order):
            children = sections_by_module.get(module.id, [])
            if not children:
                continue
            modules.append(
                Section(
                    key=module.id,
                    title=module.navigationTitle,
                    headingLevel=1,
                    reportModuleId=module.id,
                    children=children,
                )
            )

    for section in definition.report_sections:
        if section.id not in applicable_section_ids:
            diagnostics.append(PlanDiagnostic(section.id, "omitted_by_config"))

    base_intake = list(fixed.intakeItems or [])
    topic_intake = [
        item for item in (intake_items or []) if item.contentScopeId in applicable_section_ids
    ]
    report = fixed.model_copy(
        update={
            "assessment": assessment,
            "sections": _insert_modules_before_appendix(list(fixed.sections), modules),
            "intakeItems": [*base_intake, *topic_intake],
        }
    )
    report = apply_stakeholder_engagement_projection(report)
    report = apply_assessment_projection(report)
    return PlanResult(report=report, diagnostics=diagnostics)


def merge_prose(assembled: Report, current: Report) -> tuple[Report, list[str], list[str]]:
    """以新装配结构为准，按稳定 block/section id 保留当前正文和动态标题。"""
    cur_blocks = {block.id: block for block in current.iter_blocks()}
    cur_intake = {item.key: item for item in current.intakeItems or []}

    def merge_block(block: Block) -> Block:
        existing = cur_blocks.get(block.id)
        if existing is None:
            return block
        return block.model_copy(
            update={
                "content": existing.content,
                "state": existing.state,
                "table": existing.table,
            }
        )

    def merge_section(section: Section) -> Section:
        return section.model_copy(
            update={
                "displayTitle": next(
                    (
                        existing.displayTitle
                        for existing in _iter_sections(current.sections)
                        if existing.key == section.key
                    ),
                    None,
                ),
                "blocks": [merge_block(block) for block in section.blocks],
                "children": [merge_section(child) for child in section.children]
                if section.children
                else section.children,
            }
        )

    def report_sections(report: Report) -> dict[str, str]:
        return {
            section.reportSectionId: section.title
            for section in _iter_sections(report.sections)
            if section.reportSectionId is not None
        }

    assembled_sections = report_sections(assembled)
    current_sections = report_sections(current)
    added = [assembled_sections[key] for key in assembled_sections.keys() - current_sections.keys()]
    dropped = [current_sections[key] for key in current_sections.keys() - assembled_sections.keys()]
    intake = [
        item.model_copy(
            update={
                "answer": cur_intake[item.key].answer,
                "supplement": cur_intake[item.key].supplement,
            }
        )
        if item.key in cur_intake
        else item
        for item in assembled.intakeItems
    ]
    merged = current.model_copy(
        update={
            "sections": [merge_section(section) for section in assembled.sections],
            "intakeItems": intake,
            "assessment": assembled.assessment,
            # 以下都是**包资产**，一律以装配结果为准。
            #
            # 基底是 `current`（客户端送来的 Report），不显式覆盖就会原样保留客户端的值，
            # 而客户端只有一份静态合同投影（frontend/public/contract.json，上交所简体）。
            # 于是港交所报告会长出内地包独有的必填题（fields），并显示简体的填写说明与
            # 评分尺度定义（inputGuidance / assessmentScoreScale）——用户看到的是另一个
            # 包的产品资产。值仍取自 current：planning_contract 已把用户填的值合进包字段。
            "fields": assembled.fields,
            "title": assembled.title,
            "inputGuidance": assembled.inputGuidance,
            "assessmentScoreScale": assembled.assessmentScoreScale,
            "assessmentVocabulary": assembled.assessmentVocabulary,
            "quantitativeMetricsVocabulary": assembled.quantitativeMetricsVocabulary,
        }
    )
    return merged, sorted(added), sorted(dropped)


def _iter_sections(sections: list[Section]) -> Generator[Section, None, None]:
    for section in sections:
        yield section
        if section.children:
            yield from _iter_sections(section.children)


def _iter_section_blocks(section: Section) -> Generator[Block, None, None]:
    yield from section.blocks or []
    if section.conciseDisclosure is not None:
        yield section.conciseDisclosure
    for child in section.children or []:
        yield from _iter_section_blocks(child)


def _validate_title_generation(section: Section, *, where: str) -> None:
    if section.titleGeneration is not None:
        if section.headingLevel != 4:
            raise ValueError(f"{where}：titleGeneration 仅允许声明在 H4。")
        producers = [
            block for block in section.blocks if block.id == section.titleGeneration.sourceBlockId
        ]
        if len(producers) != 1:
            raise ValueError(f"{where}：标题生产者必须是 H4 的唯一直属块。")
        producer = producers[0]
        if producer.type != "paragraph" or producer.generation is None or producer.source != "ai":
            raise ValueError(f"{where}：标题生产者必须是直属 AI 段落生成块。")
    for child in section.children or []:
        _validate_title_generation(child, where=where)


@lru_cache(maxsize=8)
def _load_topic_templates_cached(resolved_dir: str, package_id: str) -> dict[str, Section]:
    out: dict[str, Section] = {}
    directory = Path(resolved_dir)
    if not directory.exists():
        return out
    package = load_knowledge_package(package_id)
    known_sections = load_topic_contract(package).reportSectionsById
    for path in sorted(directory.glob("*.yaml")):
        source = TopicSectionTemplate.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")),
            context={"package": package},
        )
        section = compile_topic_section_template(source, package=package)
        if section.reportSectionId is None:
            raise ValueError(f"议题模板 {path.name} 缺少 reportSectionId。")
        if section.reportSectionId not in known_sections:
            raise ValueError(f"议题模板 {path.name} 引用未知 reportSectionId。")
        if path.stem != section.reportSectionId:
            raise ValueError(f"议题模板 {path.name} 与 reportSectionId 不匹配。")
        if section.reportSectionId in out:
            raise ValueError(f"重复议题模板：{section.reportSectionId}")
        validate_column_keys_in_blocks(
            _iter_section_blocks(section), where=f"议题模板 {path.name}"
        )
        _validate_title_generation(section, where=f"议题模板 {path.name}")
        out[section.reportSectionId] = section
    return out


def load_topic_templates_from(
    dir_path: Path | str, *, package: KnowledgePackage
) -> dict[str, Section]:
    """Strictly load topic section templates from a directory, validated against the package registry.

    Cached per directory and package; every call returns deep copies callers may mutate.
    """
    return {
        key: section.model_copy(deep=True)
        for key, section in _load_topic_templates_cached(
            str(Path(dir_path).resolve()), package.id
        ).items()
    }


def load_topic_templates(package: KnowledgePackage) -> dict[str, Section]:
    """严格加载知识包的 Topic Section 模板并校验 Registry、表格列和标题生产者。"""
    return load_topic_templates_from(package.topic_sections_dir, package=package)


def _format_common_intake_value(value: object, *, topic_title: str) -> object:
    if isinstance(value, str):
        return value.replace("{topic_title}", topic_title)
    if isinstance(value, list):
        return [_format_common_intake_value(item, topic_title=topic_title) for item in value]
    return value


def _load_common_topic_intake_templates(
    dir_path: Path, package: KnowledgePackage
) -> list[IntakeItem]:
    common_path = dir_path.parent / "topic_intake_common.yaml"
    if not common_path.exists():
        return []
    raw = yaml.safe_load(common_path.read_text(encoding="utf-8")) or {}
    templates = raw.get("fixedPillarQuestionTemplates") or []
    out: list[IntakeItem] = []
    for section in load_topic_contract(package).source.reportSections:
        prefix = section.sectionPrefix or section.id
        for template in templates:
            item = {
                key: _format_common_intake_value(value, topic_title=section.title)
                for key, value in template.items()
                if key not in {"keySuffix", "pillar"}
            }
            item["key"] = f"{prefix}.{template['keySuffix']}"
            item["contentScopeId"] = section.id
            out.append(IntakeItem.model_validate(item))
    return out


@lru_cache(maxsize=8)
def _load_topic_intake_cached(resolved_dir: str, package_id: str) -> tuple[IntakeItem, ...]:
    directory = Path(resolved_dir)
    package = load_knowledge_package(package_id)
    out = _load_common_topic_intake_templates(directory, package)
    if not directory.exists():
        return tuple(out)
    known_sections = load_topic_contract(package).reportSectionsById
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        content_scope_id = raw["contentScopeId"]
        if content_scope_id not in known_sections:
            raise ValueError(f"内容清单 {path.name} 引用未知 contentScopeId。")
        if path.stem != content_scope_id:
            raise ValueError(f"内容清单 {path.name} 与 contentScopeId 不匹配。")
        for item in raw.get("items", []) or []:
            out.append(IntakeItem.model_validate({**item, "contentScopeId": content_scope_id}))
    return tuple(out)


def load_topic_intake_from(
    dir_path: Path | str, *, package: KnowledgePackage
) -> list[IntakeItem]:
    """Load intake items from a directory (plus its sibling common templates), validated against the package.

    Cached per directory and package; every call returns deep copies callers may mutate.
    """
    return [
        item.model_copy(deep=True)
        for item in _load_topic_intake_cached(str(Path(dir_path).resolve()), package.id)
    ]


def load_topic_intake(package: KnowledgePackage) -> list[IntakeItem]:
    """加载知识包的内容清单，并把文件级 contentScopeId 注入每个结构化问题。"""
    return load_topic_intake_from(package.topic_intake_dir, package=package)


def with_topic_sections(report: Report, templates: dict[str, Section]) -> Report:
    """将模板并入 prompt 配置态；运行时报告仍由 assemble_report 选择单一内容分支。"""
    return report.model_copy(update={"sections": [*report.sections, *templates.values()]})
