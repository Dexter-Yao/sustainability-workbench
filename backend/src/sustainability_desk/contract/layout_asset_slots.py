# ABOUTME: 从编译契约派生"报告范围 → 素材图片承载块"的唯一映射,供图片识别任务目录与生成期放置共用。
# ABOUTME: scope 身份与 Mapping 的 _scope_identity 同构派生(esg_topic 用 report-section、report_area 用顶层章 source_id),零硬编码。
# ABOUTME(en): Derives the sole report-scope-to-image-carrier-block mapping from the compiled contract.
# ABOUTME(en): Scope identity is derived isomorphically with the Mapping's _scope_identity; zero hardcoding.
from __future__ import annotations

from types import MappingProxyType
from typing import Callable, TypeVar

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.compiled_definition import CompiledReportDefinition
from sustainability_desk.contract.models import Block, Section


class LayoutScope(BaseModel):
    """一个块所属的报告范围身份；素材承载位据此对齐。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str
    scope_kind: str  # "report_area" | "esg_topic",与 FileMaterialScope.kind 对齐
    scope_title: str


class LayoutAssetSlot(BaseModel):
    """一个契约声明的素材图片承载位及其报告范围身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str
    scope_kind: str  # "report_area" | "esg_topic",与 FileMaterialScope.kind 对齐
    scope_title: str
    block_id: str


def layout_scope_for_block(
    definition: CompiledReportDefinition,
    block_id: str,
    *,
    section_title: str = "",
) -> LayoutScope:
    """按编译定义中的节点位置派生块所属报告范围：议题块归 report-section，前章块归顶层章。"""

    placement = definition.placement_for_block(block_id)
    if placement.report_section_id is not None:
        return LayoutScope(
            scope_id=f"report-section:{placement.report_section_id}",
            scope_kind="esg_topic",
            scope_title=placement.report_section_title or section_title,
        )
    if not placement.ancestor_node_ids:
        raise ValueError(f"块没有可映射的报告归属：{block_id}")
    top_ancestor = definition.nodes_by_id[placement.ancestor_node_ids[0]]
    return LayoutScope(
        scope_id=f"report-area:{top_ancestor.source_id}",
        scope_kind="report_area",
        scope_title=top_ancestor.title,
    )


_Derived = TypeVar("_Derived")

# 值为 (definition, 派生结果) 二元组：同时持有 definition 引用防止其被回收后
# id() 被复用给另一个对象，导致缓存命中错误的编译定义。
_derived_cache: dict[
    tuple[str, int], tuple[CompiledReportDefinition, object]
] = {}


def _cached_by_definition(
    key: str,
    definition: CompiledReportDefinition,
    compute: Callable[[CompiledReportDefinition], _Derived],
) -> _Derived:
    """按 id(definition) 缓存派生结果。

    CompiledReportDefinition 含不可哈希的 MappingProxyType 字段,不能作
    functools.lru_cache 的参数,因此改用显式 id() 键的进程内缓存；
    load_compiled_report_definition 本身已 lru_cache 为进程内单例,同一编译定义
    在同一进程内 id 稳定，maxsize 上限为 8（与其 lru_cache(maxsize=8) 对齐）。
    """

    cache_key = (key, id(definition))
    cached_entry = _derived_cache.get(cache_key)
    if cached_entry is not None and cached_entry[0] is definition:
        return cached_entry[1]  # type: ignore[return-value]
    if len(_derived_cache) >= 16:
        _derived_cache.clear()
    computed = compute(definition)
    _derived_cache[cache_key] = (definition, computed)
    return computed


def _walk_contract_blocks(
    definition: CompiledReportDefinition,
    visit: Callable[[Section, Block], None],
) -> None:
    # 议题章节的 Section 对象由模板加载器持有,编译定义只保存其节点;两处共同构成全部来源。
    from sustainability_desk.contract.knowledge_packages import load_knowledge_package
    from sustainability_desk.planner import load_topic_templates

    def walk(section: Section) -> None:
        for block in section.blocks:
            visit(section, block)
        for child in section.children or []:
            walk(child)

    for section in definition.fixed_report_definition.sections:
        walk(section)
    for section in load_topic_templates(
        load_knowledge_package(definition.package_id)
    ).values():
        walk(section)


def layout_asset_slots(
    definition: CompiledReportDefinition,
) -> tuple[LayoutAssetSlot, ...]:
    """扫描编译定义中 layoutAssetSlot=True 的 image block,派生按契约声明序的承载位目录。

    每个报告范围至多一个承载位;重复声明是契约错误,编译期即失败。
    """

    return _cached_by_definition("layout_asset_slots", definition, _compute_layout_asset_slots)


def _compute_layout_asset_slots(
    definition: CompiledReportDefinition,
) -> tuple[LayoutAssetSlot, ...]:
    slots: list[LayoutAssetSlot] = []
    seen_scopes: set[str] = set()

    def visit(section: Section, block: Block) -> None:
        image = block.image
        if image is None or not image.layoutAssetSlot:
            return
        scope = layout_scope_for_block(definition, block.id, section_title=section.title)
        if scope.scope_id in seen_scopes:
            raise ValueError(f"报告范围 {scope.scope_id} 声明了多个素材承载位")
        seen_scopes.add(scope.scope_id)
        slots.append(
            LayoutAssetSlot(
                scope_id=scope.scope_id,
                scope_kind=scope.scope_kind,
                scope_title=scope.scope_title,
                block_id=block.id,
            )
        )

    _walk_contract_blocks(definition, visit)
    return tuple(slots)


def layout_asset_block_by_scope(
    definition: CompiledReportDefinition,
) -> MappingProxyType[str, str]:
    """返回 scope_id → 承载块 block_id 的放置映射（只读，供消费方共享缓存结果）。"""

    return MappingProxyType(
        {slot.scope_id: slot.block_id for slot in layout_asset_slots(definition)}
    )
