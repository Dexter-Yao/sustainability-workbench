# ABOUTME: 利益相关方沟通目录与 Profile 的确定性协调、校验及表格投影单一实现。
# ABOUTME: 本模块不调用模型；议题名称和适用性读取 topic_registry，用户编辑只写 Profile ID 引用。
# ABOUTME(en): The single deterministic reconciliation, validation and table projection for stakeholder engagement.
# ABOUTME(en): Calls no model; topic names and applicability read from topic_registry, and edits write Profile ID refs.
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.models import (
    EngagementMethodKind,
    GsTableCell,
    GsTableRow,
    Report,
    StakeholderEngagementEntry,
    StakeholderEngagementProfile,
    StakeholderType,
)
from sustainability_desk.contract.language import list_separator
from sustainability_desk.contract.topic_registry import (
    load_topic_contract,
    all_assessment_topics,
    applicable_materiality_topics,
)

_BACKEND = Path(__file__).resolve().parents[3]
# The frontend ships one static catalog projection; it follows the package the UI is built for.
PUBLIC_CATALOG_PACKAGE_ID = "sse_zh_hans"
PUBLIC_CATALOG_PATH = _BACKEND.parent / "frontend" / "public" / "stakeholder-engagement.json"
STAKEHOLDER_TABLE_BLOCK_ID = "sm.stakeholder_table"
_EXCLUDED_TOPIC_IDS = frozenset(
    {"due_diligence", "stakeholder_communication", "risk_management"}
)
_METHOD_KIND_ORDER: tuple[EngagementMethodKind, ...] = (
    "communication_channel",
    "participation_mechanism",
    "collaboration_activity",
)


class StakeholderDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StakeholderType
    label: str
    order: int
    defaultMethodIds: list[str]


class EngagementMethodDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: EngagementMethodKind
    allowedStakeholderTypes: list[StakeholderType]


class StakeholderEngagementCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stakeholders: list[StakeholderDefinition]
    methods: list[EngagementMethodDefinition]
    defaultTopicStakeholders: dict[str, list[StakeholderType]]

    @model_validator(mode="after")
    def _validate_catalog(self):
        expected_stakeholders = [
            "government_regulators",
            "shareholders_investors",
            "customers",
            "management",
            "employees",
            "suppliers",
            "partners",
            "community_public",
        ]
        stakeholder_ids = [item.id for item in self.stakeholders]
        if stakeholder_ids != expected_stakeholders:
            raise ValueError("利益相关方目录必须按固定八类声明")
        if [item.order for item in self.stakeholders] != sorted(
            item.order for item in self.stakeholders
        ):
            raise ValueError("利益相关方目录 order 必须递增")

        method_ids = [item.id for item in self.methods]
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("沟通方式目录存在重复 ID")
        method_by_id = {item.id: item for item in self.methods}
        for stakeholder in self.stakeholders:
            for method_id in stakeholder.defaultMethodIds:
                method = method_by_id.get(method_id)
                if method is None:
                    raise ValueError(f"默认沟通方式不存在：{method_id}")
                if stakeholder.id not in method.allowedStakeholderTypes:
                    raise ValueError(
                        f"默认沟通方式 {method_id} 不适用于 {stakeholder.id}"
                    )

        for topic_id, stakeholder_types in self.defaultTopicStakeholders.items():
            if not stakeholder_types:
                raise ValueError(f"默认议题 {topic_id} 未映射利益相关方")
            if len(stakeholder_types) != len(set(stakeholder_types)):
                raise ValueError(f"默认议题 {topic_id} 包含重复利益相关方")
        return self


def _validate_topic_mapping(
    catalog: StakeholderEngagementCatalog, package: KnowledgePackage
) -> None:
    """The default topic mapping must cover exactly the package's stakeholder-relevant topics."""

    expected_topics = {
        topic.id
        for topic in all_assessment_topics(package)
        if topic.id not in _EXCLUDED_TOPIC_IDS
    }
    actual_topics = set(catalog.defaultTopicStakeholders)
    if actual_topics != expected_topics:
        missing = sorted(expected_topics - actual_topics)
        extra = sorted(actual_topics - expected_topics)
        raise ValueError(f"默认议题映射不完整：missing={missing}, extra={extra}")


@lru_cache(maxsize=None)
def _load_stakeholder_engagement_catalog(package_id: str) -> StakeholderEngagementCatalog:
    package = load_knowledge_package(package_id)
    catalog = StakeholderEngagementCatalog.model_validate(
        yaml.safe_load(package.stakeholder_engagement_path.read_text(encoding="utf-8"))
    )
    _validate_topic_mapping(catalog, package)
    return catalog


def load_stakeholder_engagement_catalog(
    package: KnowledgePackage,
) -> StakeholderEngagementCatalog:
    """加载并严格校验确定性利益相关方目录。"""
    return _load_stakeholder_engagement_catalog(package.id)


def validate_stakeholder_engagement_profile(
    profile: StakeholderEngagementProfile,
    *,
    package: KnowledgePackage,
) -> None:
    """校验 Profile 的议题、方式及方式适用对象引用，覆盖完整性留给导出诊断。"""
    catalog = load_stakeholder_engagement_catalog(package)
    allowed_assessment_topic_ids = set(catalog.defaultTopicStakeholders)
    method_by_id = {method.id: method for method in catalog.methods}

    unknown_scope = set(profile.scopeAssessmentTopicIds) - allowed_assessment_topic_ids
    if unknown_scope:
        raise ValueError(f"scopeAssessmentTopicIds 包含未受支持议题：{sorted(unknown_scope)}")
    for entry in profile.entries:
        unknown_topics = set(entry.assessmentTopicIds) - allowed_assessment_topic_ids
        if unknown_topics:
            raise ValueError(
                f"{entry.stakeholderType} 包含未受支持议题：{sorted(unknown_topics)}"
            )
        for method_id in entry.methodIds:
            method = method_by_id.get(method_id)
            if method is None:
                raise ValueError(f"未知沟通方式：{method_id}")
            if entry.stakeholderType not in method.allowedStakeholderTypes:
                raise ValueError(
                    f"沟通方式 {method_id} 不适用于 {entry.stakeholderType}"
                )


def applicable_stakeholder_topic_ids(report: Report) -> tuple[str, ...]:
    """当前轻量版利益相关方表应覆盖的正式评分议题 ID，保持 registry 顺序。"""
    return tuple(
        topic.id
        for topic in applicable_materiality_topics(report)
        if topic.id not in _EXCLUDED_TOPIC_IDS
    )


def _default_profile(
    topic_ids: tuple[str, ...], package: KnowledgePackage
) -> StakeholderEngagementProfile:
    catalog = load_stakeholder_engagement_catalog(package)
    entries = []
    for stakeholder in catalog.stakeholders:
        entries.append(
            StakeholderEngagementEntry(
                stakeholderType=stakeholder.id,
                assessmentTopicIds=[
                    topic_id
                    for topic_id in topic_ids
                    if stakeholder.id
                    in catalog.defaultTopicStakeholders.get(topic_id, [])
                ],
                methodIds=list(stakeholder.defaultMethodIds),
                customMethods=[],
            )
        )
    return StakeholderEngagementProfile(
        scopeAssessmentTopicIds=list(topic_ids),
        entries=entries,
    )


def reconcile_stakeholder_engagement_profile(
    report: Report,
) -> StakeholderEngagementProfile:
    """协调适用范围变化；新增议题套默认映射，移除过期议题，其余用户关系保持不动。"""
    package = knowledge_package_of(report)
    current_topic_ids = applicable_stakeholder_topic_ids(report)
    profile = report.stakeholderEngagement
    if profile is None:
        return _default_profile(current_topic_ids, package)

    catalog = load_stakeholder_engagement_catalog(package)
    current_set = set(current_topic_ids)
    previous_set = set(profile.scopeAssessmentTopicIds)
    added_topic_ids = current_set - previous_set
    entries: list[StakeholderEngagementEntry] = []
    for entry in profile.entries:
        topic_ids = [topic_id for topic_id in entry.assessmentTopicIds if topic_id in current_set]
        for topic_id in current_topic_ids:
            if (
                topic_id in added_topic_ids
                and entry.stakeholderType
                in catalog.defaultTopicStakeholders.get(topic_id, [])
                and topic_id not in topic_ids
            ):
                topic_ids.append(topic_id)
        order = {topic_id: index for index, topic_id in enumerate(current_topic_ids)}
        topic_ids.sort(key=order.__getitem__)
        entries.append(entry.model_copy(update={"assessmentTopicIds": topic_ids}))
    return StakeholderEngagementProfile(
        scopeAssessmentTopicIds=list(current_topic_ids),
        entries=entries,
    )


def missing_stakeholder_topic_ids(report: Report) -> list[str]:
    """返回尚未分配给任何利益相关方的当前适用议题，供统一导出诊断使用。"""
    expected = applicable_stakeholder_topic_ids(report)
    covered = {
        topic_id
        for entry in (report.stakeholderEngagement.entries if report.stakeholderEngagement else [])
        for topic_id in entry.assessmentTopicIds
    }
    return [topic_id for topic_id in expected if topic_id not in covered]


def stakeholder_engagement_rows(report: Report) -> list[GsTableRow]:
    """Profile → 三列表格数据行；中文名称只在此类投影边界解析。"""
    profile = report.stakeholderEngagement
    if profile is None:
        return []
    separator = list_separator(knowledge_package_of(report).language)
    package = knowledge_package_of(report)
    catalog = load_stakeholder_engagement_catalog(package)
    stakeholder_by_id = {item.id: item for item in catalog.stakeholders}
    topics = all_assessment_topics(package)
    topic_by_id = {topic.id: topic for topic in topics}
    topic_order = {topic.id: index for index, topic in enumerate(topics)}
    method_by_id = {method.id: method for method in catalog.methods}
    method_order = {method.id: index for index, method in enumerate(catalog.methods)}
    kind_order = {kind: index for index, kind in enumerate(_METHOD_KIND_ORDER)}

    rows: list[GsTableRow] = []
    for entry in profile.entries:
        topic_labels = [
            topic_by_id[topic_id].name
            for topic_id in sorted(entry.assessmentTopicIds, key=topic_order.__getitem__)
        ]
        controlled_methods = sorted(
            (method_by_id[method_id] for method_id in entry.methodIds),
            key=lambda method: (kind_order[method.kind], method_order[method.id]),
        )
        method_labels: list[str] = []
        for kind in _METHOD_KIND_ORDER:
            for method in controlled_methods:
                if method.kind == kind and method.label not in method_labels:
                    method_labels.append(method.label)
            for method in entry.customMethods:
                if method.kind == kind and method.label not in method_labels:
                    method_labels.append(method.label)
        rows.append(
            GsTableRow(
                children=[
                    GsTableCell(
                        colKey="stk_party",
                        value=stakeholder_by_id[entry.stakeholderType].label,
                    ),
                    GsTableCell(colKey="stk_topics", value=separator.join(topic_labels)),
                    GsTableCell(colKey="stk_methods", value=separator.join(method_labels)),
                ]
            )
        )
    return rows


def apply_stakeholder_engagement_projection(report: Report) -> Report:
    """从目录默认映射或用户确认的 Profile 刷新只读表格投影。

    用户未确认时套用目录默认映射，而不是留一张空表。目录只承载「股东会」「信息披露」
    「客服热线」「员工代表沟通」这类任何在营企业都必然具备的通用沟通渠道，不含事件、
    金额、时间、项目名或成效，因此按默认映射成表不构成编造企业事实——它陈述的是
    企业客观存在的沟通框架，用户随后可在工作台按实际情况调整。

    留空表反而更糟：利益相关方沟通是准则要求的披露项，空表既不满足披露，
    又会让导出闸以「议题未分配沟通对象」阻断交付。
    """

    profile = reconcile_stakeholder_engagement_profile(report)
    report = report.model_copy(update={"stakeholderEngagement": profile})
    rows = stakeholder_engagement_rows(report)

    def project_sections(sections):
        projected = []
        for section in sections:
            blocks = []
            for block in section.blocks:
                if (
                    block.id == STAKEHOLDER_TABLE_BLOCK_ID
                    and block.table is not None
                    and block.table.rowSource == "stakeholder_engagement"
                ):
                    header_rows = [row for row in block.table.children if row.headerRow]
                    block = block.model_copy(
                        update={
                            "table": block.table.model_copy(
                                update={"children": header_rows + rows}
                            )
                        }
                    )
                blocks.append(block)
            projected.append(
                section.model_copy(
                    update={
                        "blocks": blocks,
                        "children": project_sections(section.children)
                        if section.children is not None
                        else None,
                    }
                )
            )
        return projected

    return report.model_copy(update={"sections": project_sections(report.sections)})


def public_stakeholder_engagement_catalog(package: KnowledgePackage) -> dict[str, object]:
    """导出前端标签编辑器所需目录；议题标签从 topic registry 联结，不复制到 YAML。"""
    catalog = load_stakeholder_engagement_catalog(package)
    contract = load_topic_contract(package)
    mapped_topic_ids = set(catalog.defaultTopicStakeholders)
    topics = [
        {
            "id": topic.id,
            "label": topic.name,
            "dimension": contract.dimension_label(topic.dimension),
            "order": topic.order,
        }
        for topic in all_assessment_topics(package)
        if topic.id in mapped_topic_ids
    ]
    return {
        "stakeholders": [item.model_dump() for item in catalog.stakeholders],
        "methods": [item.model_dump() for item in catalog.methods],
        "topics": topics,
    }


def export_public_catalog() -> None:
    package = load_knowledge_package(PUBLIC_CATALOG_PACKAGE_ID)
    PUBLIC_CATALOG_PATH.write_text(
        json.dumps(public_stakeholder_engagement_catalog(package), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    export_public_catalog()
    print(f"已导出利益相关方目录 → {PUBLIC_CATALOG_PATH}")
