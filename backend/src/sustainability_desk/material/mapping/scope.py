# ABOUTME: 从 CompiledReportDefinition 派生 Mapping Agent 的章节级任务地图。
# ABOUTME: 本模块不拥有议题或 Block 语义，也不建立平行 target 目录。
# ABOUTME(en): Derives the Mapping Agent's section-level task map from the CompiledReportDefinition.
# ABOUTME(en): It owns no topic or Block semantics and builds no parallel target catalogue.
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.compiled_definition import (
    CompiledGenerationContract,
    CompiledReportDefinition,
)

type MappingScopeKind = Literal["report_area", "esg_topic"]



class MappingBlockTask(BaseModel):
    """一个 Mapping Scope 内可被资料事实支持的既有生成任务投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    title: str
    semantic_task: str
    information_needs: tuple[str, ...] = ()
    absence_behavior: Literal[
        "render_deterministically",
        "generate_context_only",
        "omit_if_unsupported",
    ]
    intake_item_ids: tuple[str, ...] = ()
    quantitative_metric_ids: tuple[str, ...] = ()
    field_ids: tuple[str, ...] = ()
    standard_requirement_refs: tuple[str, ...] = ()
    evidence_output_facets: tuple[str, ...] = ()

    #: 内部枚举 → Agent 可读的业务口径；投影层不得把实现字面量原样交给模型。
    _ABSENCE_BEHAVIOR_PROJECTION = {
        "render_deterministically": "缺少对应资料时按固定内容确定性渲染",
        "generate_context_only": "缺少对应资料时按行业与业务背景作方向性生成",
        "omit_if_unsupported": "缺少对应资料且无相关答案时整块省略，不进入报告",
    }

    def model_projection(self) -> dict[str, Any]:
        """只向模型提供会改变当前语义判断的任务信息。"""

        return {
            "blockId": self.block_id,
            "title": self.title,
            "mappingObjective": self.semantic_task,
            "informationNeeds": list(self.information_needs),
            "whenInformationMissing": self._ABSENCE_BEHAVIOR_PROJECTION[
                self.absence_behavior
            ],
        }


class MappingScopeDefinition(BaseModel):
    """由报告合同派生的报告区域或 ESG 议题并发单元。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str
    scope_kind: MappingScopeKind
    title: str
    report_section_id: str | None = None
    block_tasks: tuple[MappingBlockTask, ...]

    def model_projection(self) -> dict[str, Any]:
        """生成当前 Mapping Agent 的高信号任务地图。"""

        return {
            "scopeId": self.scope_id,
            "scopeKind": self.scope_kind,
            "title": self.title,
            "reportSectionId": self.report_section_id,
            "blocks": [task.model_projection() for task in self.block_tasks],
        }


class MappingTaskAssembly(BaseModel):
    """从唯一报告合同和当前 Report revision 派生的 Mapping 并发计划。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["sustainability_desk.mapping_task_assembly.v1"] = (
        "sustainability_desk.mapping_task_assembly.v1"
    )
    report_contract_version: str
    scopes: tuple[MappingScopeDefinition, ...]


def material_routes_to_scope(scope: MappingScopeDefinition, applicable_scope_ids: tuple[str, ...]) -> bool:
    """只按 File Agent 已解析的资料 scope 路由；用户标签不再形成第二真相源。"""

    return scope.scope_id in applicable_scope_ids


def _information_needs(
    definition: CompiledReportDefinition,
    contract: CompiledGenerationContract,
) -> tuple[str, ...]:
    """将内部 owner 引用投影成 Agent 可理解、但不复制语义所有权的说明。"""

    needs: list[str] = []
    for item_id in contract.intake_item_ids:
        item = definition.input_definitions_by_id[item_id]
        needs.append(f"用户输入主题：{item.prompt}")
    for metric_id in contract.quantitative_metric_ids:
        metric = definition.metric_definitions_by_id[metric_id]
        needs.append(
            "关联的结构化定量指标："
            f"{metric.metricLabel}（{metric.unit}；数值由定量输入链独立提供）"
        )
    for field_id in contract.field_ids:
        field = definition.fixed_report_definition.fields[field_id]
        needs.append(f"报告基础信息：{field.label}")
    for requirement_id in contract.standard_requirement_refs:
        requirement = definition.standard_requirements_by_id[requirement_id]
        needs.append(f"披露关注：{requirement.title}")
    needs.extend(
        f"结构化输出要点：{facet}"
        for facet in contract.evidence_output_facets
    )
    return tuple(dict.fromkeys(needs))


def _scope_identity(
    definition: CompiledReportDefinition,
    node_id: str,
    report_section_id: str | None,
) -> tuple[str, MappingScopeKind, str]:
    if report_section_id is not None:
        section = next(
            item
            for item in definition.report_sections
            if item.id == report_section_id
        )
        return f"report-section:{report_section_id}", "esg_topic", section.title

    placement = definition.node_placements[node_id]
    if not placement.ancestor_node_ids:
        raise ValueError(f"生成节点没有可映射的报告归属：{node_id}")
    top_ancestor = definition.nodes_by_id[placement.ancestor_node_ids[0]]
    return f"report-area:{top_ancestor.source_id}", "report_area", top_ancestor.title


def assemble_mapping_tasks(
    definition: CompiledReportDefinition,
    *,
    active_block_ids: frozenset[str] | None = None,
) -> MappingTaskAssembly:
    """为当前 Report revision 装配全部适用的动态 Mapping Scope。"""

    grouped: OrderedDict[
        str,
        tuple[MappingScopeKind, str, str | None, list[MappingBlockTask]],
    ] = OrderedDict()
    for contract in definition.generation_contracts.values():
        if (
            active_block_ids is not None
            and contract.block_id not in active_block_ids
        ):
            continue
        scope_id, scope_kind, scope_title = _scope_identity(
            definition,
            contract.node_id,
            contract.report_section_id,
        )
        if scope_id not in grouped:
            grouped[scope_id] = (
                scope_kind,
                scope_title,
                contract.report_section_id,
                [],
            )
        grouped[scope_id][3].append(
            MappingBlockTask(
                block_id=contract.block_id,
                title=definition.nodes_by_id[contract.node_id].title,
                semantic_task=contract.semantic_task,
                information_needs=_information_needs(definition, contract),
                absence_behavior=contract.absence_behavior,
                intake_item_ids=contract.intake_item_ids,
                quantitative_metric_ids=contract.quantitative_metric_ids,
                field_ids=contract.field_ids,
                standard_requirement_refs=contract.standard_requirement_refs,
                evidence_output_facets=contract.evidence_output_facets,
            )
        )

    return MappingTaskAssembly(
        report_contract_version=definition.contract_version,
        scopes=tuple(
            MappingScopeDefinition(
                scope_id=scope_id,
                scope_kind=scope_kind,
                title=title,
                report_section_id=report_section_id,
                block_tasks=tuple(block_tasks),
            )
            for scope_id, (
                scope_kind,
                title,
                report_section_id,
                block_tasks,
            ) in grouped.items()
        )
    )
