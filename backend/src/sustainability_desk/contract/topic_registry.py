# ABOUTME: 解析评分议题、报告章节与报告模块的单向权威合同，并提供经校验的只读索引。
# ABOUTME: 下游只能消费 ResolvedTopicContract；不得反转裸 YAML 或通过字符串相等猜测实体类型。
# ABOUTME(en): The one-way authoritative contract resolving scoring topics, report sections and report modules.
# ABOUTME(en): Downstream consumes ResolvedTopicContract only; never inverts raw YAML nor guesses types by string match.
from __future__ import annotations

from functools import lru_cache
from types import MappingProxyType
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.models import Materiality, Report

TECHNOLOGY_ETHICS_FIELD = "has_technology_ethics_sensitive_activity"

# Assessment dimensions (E/S/G) are identified by id; the package registry owns their display labels.
DimensionId = Literal["environment", "social", "governance"]


class DimensionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DimensionId
    label: str
    order: int

class MaterialityDetermination(BaseModel):
    """评分策略：用户评分或由产品合同固定分类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["scored", "fixed"]
    materiality: Materiality | None = None

    @model_validator(mode="after")
    def _fixed_requires_materiality(self) -> MaterialityDetermination:
        if self.kind == "fixed" and self.materiality is None:
            raise ValueError("fixed materiality determination 必须声明 materiality")
        if self.kind == "scored" and self.materiality is not None:
            raise ValueError("scored materiality determination 不得预设 materiality")
        return self


class AssessmentTopicRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    dimension: DimensionId
    order: int
    reportSectionId: str | None = None
    applicability: str | None = None
    materialityDetermination: MaterialityDetermination


class ReportSectionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    reportModuleId: str
    order: int
    sectionPrefix: str | None = None


class ReportModuleRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    navigationTitle: str
    order: int
    # None: the module title is fixed to navigationTitle and no title generation is invoked.
    titleGenerationGuidance: str | None = None


class TopicRegistrySource(BaseModel):
    """topic_registry.yaml 的严格输入边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: tuple[DimensionRef, ...]
    reportModules: tuple[ReportModuleRef, ...]
    reportSections: tuple[ReportSectionRef, ...]
    assessmentTopics: tuple[AssessmentTopicRef, ...]


class ResolvedReportSection(BaseModel):
    """报告 H2 及由成员评分议题派生的业务属性。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: ReportSectionRef
    assessmentTopics: tuple[AssessmentTopicRef, ...]
    dimension: DimensionId
    applicability: str | None = None


class ResolvedTopicContract(BaseModel):
    """Registry 的唯一运行时表示；反向索引全部由单向源关系派生。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    source: TopicRegistrySource
    dimensionsById: Mapping[str, DimensionRef]
    assessmentTopicsById: Mapping[str, AssessmentTopicRef]
    reportSectionsById: Mapping[str, ReportSectionRef]
    reportModulesById: Mapping[str, ReportModuleRef]
    assessmentTopicsByReportSectionId: Mapping[str, tuple[AssessmentTopicRef, ...]]
    reportSectionsByReportModuleId: Mapping[str, tuple[ReportSectionRef, ...]]
    resolvedReportSectionsById: Mapping[str, ResolvedReportSection]

    def dimension_label(self, dimension: DimensionId) -> str:
        """Display label of an assessment dimension in the package language."""

        return self.dimensionsById[dimension].label


def _unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"议题合同存在重复 {label}。")


def _resolve(source: TopicRegistrySource) -> ResolvedTopicContract:
    _unique([item.id for item in source.assessmentTopics], "assessment topic id")
    _unique([item.name for item in source.assessmentTopics], "assessment topic name")
    _unique([item.id for item in source.reportSections], "report section id")
    _unique([item.title for item in source.reportSections], "report section title")
    _unique([item.id for item in source.reportModules], "report module id")
    _unique([item.navigationTitle for item in source.reportModules], "report module navigation title")
    _unique([item.order for item in source.reportModules], "report module order")
    _unique([item.id for item in source.dimensions], "dimension id")
    _unique([item.label for item in source.dimensions], "dimension label")
    _unique([item.order for item in source.dimensions], "dimension order")
    dimensions_by_id = {item.id: item for item in source.dimensions}
    for topic in source.assessmentTopics:
        if topic.dimension not in dimensions_by_id:
            raise ValueError(f"评分议题 {topic.id} 指向未声明的维度 {topic.dimension}。")
    for dimension in dimensions_by_id:
        _unique(
            [item.order for item in source.assessmentTopics if item.dimension == dimension],
            f"assessment topic order（dimension={dimension}）",
        )

    topics_by_id = {item.id: item for item in source.assessmentTopics}
    sections_by_id = {item.id: item for item in source.reportSections}
    modules_by_id = {item.id: item for item in source.reportModules}
    by_section: dict[str, list[AssessmentTopicRef]] = {item.id: [] for item in source.reportSections}
    by_module: dict[str, list[ReportSectionRef]] = {item.id: [] for item in source.reportModules}

    for topic in source.assessmentTopics:
        if topic.reportSectionId is None:
            continue
        if topic.reportSectionId not in sections_by_id:
            raise ValueError(f"评分议题 {topic.id} 指向不存在的报告章节 {topic.reportSectionId}。")
        by_section[topic.reportSectionId].append(topic)

    resolved_sections: dict[str, ResolvedReportSection] = {}
    for section in source.reportSections:
        if section.reportModuleId not in modules_by_id:
            raise ValueError(f"报告章节 {section.id} 指向不存在的报告模块 {section.reportModuleId}。")
        members = tuple(by_section[section.id])
        if not members:
            raise ValueError(f"报告章节 {section.id} 没有任何评分议题引用。")
        dimensions = {item.dimension for item in members}
        if len(dimensions) != 1:
            raise ValueError(f"合并报告章节 {section.id} 的评分议题维度不一致。")
        applicability = {item.applicability for item in members}
        if len(applicability) != 1:
            raise ValueError(f"合并报告章节 {section.id} 的评分议题适用性规则不一致。")
        resolved_sections[section.id] = ResolvedReportSection(
            definition=section,
            assessmentTopics=members,
            dimension=next(iter(dimensions)),
            applicability=next(iter(applicability)),
        )
        by_module[section.reportModuleId].append(section)

    for module_id, sections in by_module.items():
        _unique([item.order for item in sections], f"report section order（module={module_id}）")
        sections.sort(key=lambda item: item.order)

    return ResolvedTopicContract(
        source=source,
        dimensionsById=MappingProxyType(dimensions_by_id),
        assessmentTopicsById=MappingProxyType(topics_by_id),
        reportSectionsById=MappingProxyType(sections_by_id),
        reportModulesById=MappingProxyType(modules_by_id),
        assessmentTopicsByReportSectionId=MappingProxyType(
            {key: tuple(value) for key, value in by_section.items()}
        ),
        reportSectionsByReportModuleId=MappingProxyType(
            {key: tuple(value) for key, value in by_module.items()}
        ),
        resolvedReportSectionsById=MappingProxyType(resolved_sections),
    )


@lru_cache(maxsize=None)
def _load_topic_contract(package_id: str) -> ResolvedTopicContract:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.topic_registry_path.read_text(encoding="utf-8"))
    return _resolve(TopicRegistrySource.model_validate(raw))


def load_topic_contract(package: KnowledgePackage) -> ResolvedTopicContract:
    return _load_topic_contract(package.id)


class TopicApplicabilityFacts(BaseModel):
    """决定议题适用性的全部事实；适用性规则只读本对象，不各自翻找载体结构。

    Report 与编辑期 StoredReportState 是同一批事实的两种载体：前者字段为 Field 对象，
    后者为扁平值。二者各自解析为本对象后共用同一套规则，避免两处判定漂移。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    technologyEthicsSensitiveActivity: str | None = None


def applicability_facts_from_report(report: Report | None) -> TopicApplicabilityFacts:
    if report is None:
        return TopicApplicabilityFacts()
    field = report.fields.get(TECHNOLOGY_ETHICS_FIELD)
    return TopicApplicabilityFacts(
        technologyEthicsSensitiveActivity=(
            None if field is None else _as_optional_text(field.value)
        ),
    )


def applicability_facts_from_values(
    *,
    field_values: Mapping[str, object],
) -> TopicApplicabilityFacts:
    """从编辑期扁平字段值解析适用性事实，供写入边界在构造 Report 之前判定范围。"""

    return TopicApplicabilityFacts(
        technologyEthicsSensitiveActivity=_as_optional_text(
            field_values.get(TECHNOLOGY_ETHICS_FIELD)
        ),
    )


def _as_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def applies(rule: str | None, facts: TopicApplicabilityFacts) -> bool:
    if rule is None:
        return True
    if rule == "technology_ethics_sensitive_activity":
        # 未作答时议题保持适用；只有明确选「否」才移出范围。
        return facts.technologyEthicsSensitiveActivity != "否"
    raise ValueError(f"未知议题适用性规则：{rule}")


def all_assessment_topics(package: KnowledgePackage) -> tuple[AssessmentTopicRef, ...]:
    return load_topic_contract(package).source.assessmentTopics


def all_report_sections(package: KnowledgePackage) -> tuple[ReportSectionRef, ...]:
    return load_topic_contract(package).source.reportSections


def all_report_modules(package: KnowledgePackage) -> tuple[ReportModuleRef, ...]:
    return tuple(
        sorted(load_topic_contract(package).source.reportModules, key=lambda item: item.order)
    )


def resolve_topic(package: KnowledgePackage, name: str) -> AssessmentTopicRef | None:
    label = str(name).strip()
    return next(
        (topic for topic in all_assessment_topics(package) if topic.name == label), None
    )


TopicScopeBasis = Report | TopicApplicabilityFacts | None


def _facts(basis: TopicScopeBasis) -> TopicApplicabilityFacts:
    """统一入参：调用方可传 Report，也可传编辑期已解析的事实。"""

    if isinstance(basis, TopicApplicabilityFacts):
        return basis
    return applicability_facts_from_report(basis)


def _package_for(basis: TopicScopeBasis, package: KnowledgePackage | None) -> KnowledgePackage:
    """A Report carries its package; bare applicability facts must name one explicitly."""

    if package is not None:
        return package
    if isinstance(basis, Report):
        return knowledge_package_of(basis)
    raise ValueError("topic scope without a Report requires an explicit knowledge package")


def applicable_materiality_topics(
    basis: TopicScopeBasis, *, package: KnowledgePackage | None = None
) -> tuple[AssessmentTopicRef, ...]:
    """当前配置下进入重要性结果的完整议题范围（含 fixed）。"""
    facts = _facts(basis)
    return tuple(
        topic
        for topic in all_assessment_topics(_package_for(basis, package))
        if applies(topic.applicability, facts)
    )


def applicable_scoring_topics(
    basis: TopicScopeBasis, *, package: KnowledgePackage | None = None
) -> tuple[AssessmentTopicRef, ...]:
    """当前配置下必须由用户评分的议题范围。"""
    return tuple(
        topic
        for topic in applicable_materiality_topics(basis, package=package)
        if topic.materialityDetermination.kind == "scored"
    )


def applicable_report_sections(
    basis: TopicScopeBasis, *, package: KnowledgePackage | None = None
) -> tuple[ResolvedReportSection, ...]:
    contract = load_topic_contract(_package_for(basis, package))
    facts = _facts(basis)
    return tuple(
        contract.resolvedReportSectionsById[section.id]
        for section in contract.source.reportSections
        if applies(contract.resolvedReportSectionsById[section.id].applicability, facts)
    )


def applicable_report_modules(
    report: Report | None, *, package: KnowledgePackage | None = None
) -> tuple[ReportModuleRef, ...]:
    resolved = _package_for(report, package)
    visible_module_ids = {
        section.definition.reportModuleId
        for section in applicable_report_sections(report, package=resolved)
    }
    return tuple(
        module for module in all_report_modules(resolved) if module.id in visible_module_ids
    )


def section_prefix_of(package: KnowledgePackage, report_section_id: str) -> str:
    section = load_topic_contract(package).reportSectionsById[report_section_id]
    return section.sectionPrefix or section.id
