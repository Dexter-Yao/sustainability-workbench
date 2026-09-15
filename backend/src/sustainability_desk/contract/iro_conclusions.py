# ABOUTME: IRO 表结论的领域对象与解析边界——把已生成/已填写的 sm.iro_table 解析为按议题索引的 typed 结论。
# ABOUTME: 下游议题章节只消费本结论（方向性判断），不回头解析表格节点，也不据此坐实企业具体做法。
# ABOUTME(en): Domain objects and parse boundary for IRO table conclusions, indexed by topic from sm.iro_table.
# ABOUTME(en): Downstream sections consume only these directional conclusions, never re-parsing table nodes.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.models import Block, Report, RowExpansion
from sustainability_desk.contract.table_ops import row_values
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.topic_registry import load_topic_contract

IRO_TABLE_BLOCK_ID = "sm.iro_table"


class TopicIroConclusion(BaseModel):
    """一个议题在 IRO 表中已确定的影响 / 风险机遇结论。

    仅承载下游需要的方向性判断；不含行号、单元格坐标、评分或表格节点结构。
    origin 区分用户在评分表中确认的条目与本次生成的方向性结论，供下游标注证据强度。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic_name: str
    impact_summary: str = ""
    impact_classes: tuple[str, ...] = ()
    risk_opportunity_summary: str = ""
    risk_opportunity_classes: tuple[str, ...] = ()
    value_chain: tuple[str, ...] = ()
    time_horizon: tuple[str, ...] = ()
    origin: Literal["user_provided", "generated"] = "generated"

    def has_content(self) -> bool:
        """是否含可供下游参照的方向性内容（两段描述至少有一段非空）。"""
        return bool(self.impact_summary.strip() or self.risk_opportunity_summary.strip())


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value if str(item).strip())
    return ""


def _group_by_shared_columns(
    data_rows: list, shared_keys: frozenset[str], span: int
) -> list[list]:
    """按「共享列出现在首子行」这一结构事实切分业务行组，不按固定位置切。

    build_expanded_rows 保证共享列只在首子行出格（其余子行省略被合并的占位格），
    因此「带共享列的行」就是一个业务行的开始。用户在工作台增删子行后位置分组会
    整体错位——把 A 议题的风险描述读成 B 议题的影响——而结构分组不会。

    只接受恰好 span 行的完整组：多于或少于都说明该组已被编辑破坏，宁可丢弃该组，
    也不把错位内容当作某个议题的结论注入下游。
    """
    groups: list[list] = []
    current: list = []
    for row in data_rows:
        starts_group = bool(shared_keys & set(row_values(row)))
        if starts_group and current:
            groups.append(current)
            current = []
        if starts_group or current:
            current.append(row)
        # 首行之前的孤立续行（共享列被删）无从归属，直接丢弃。
    if current:
        groups.append(current)
    return [group for group in groups if len(group) == span]


def parse_iro_conclusions(block: Block) -> tuple[TopicIroConclusion, ...]:
    """把 IRO 表的数据行解析为按议题索引的 typed 结论（parse-first 边界）。

    表按契约 rowExpansion 每议题展开为多个子行：共享列只出现在首个子行（rowSpan 合并），
    其余子行只带本子行的列。据此按结构证据归并回业务行，不依赖行号奇偶或位置假设。
    """
    table = block.table
    expansion: RowExpansion | None = (
        block.generation.rowExpansion if block.generation else None
    )
    if table is None or expansion is None:
        return ()

    span = len(expansion.units)
    shared_keys = frozenset(expansion.sharedColumnKeys)
    data_rows = [row for row in table.children if not row.headerRow]
    conclusions: list[TopicIroConclusion] = []

    for group in _group_by_shared_columns(data_rows, shared_keys, span):
        shared = row_values(group[0])
        by_unit = {
            unit.key: row_values(row)
            for unit, row in zip(expansion.units, group)
        }
        topic_name = _as_text(shared.get("iro_topic"))
        if not topic_name:
            continue
        impact = by_unit.get("impact", {})
        risk_opportunity = by_unit.get("risk_opportunity", {})
        conclusions.append(
            TopicIroConclusion(
                topic_name=topic_name,
                impact_summary=_as_text(impact.get("iro_desc")),
                impact_classes=_as_tuple(impact.get("iro_class")),
                risk_opportunity_summary=_as_text(risk_opportunity.get("iro_desc")),
                risk_opportunity_classes=_as_tuple(risk_opportunity.get("iro_class")),
                value_chain=_as_tuple(shared.get("iro_value_chain")),
                time_horizon=_as_tuple(shared.get("iro_time_horizon")),
            )
        )
    return tuple(conclusions)


def _scored_iro_topic_names(report: Report) -> frozenset[str]:
    """当前评分结果中进入 IRO 表的官方议题名称集合。

    IRO 表的行由评分结果确定（rowSource: assessment_iro），`iro_topic` 单元格
    由系统按 topic_registry 的官方名称写入，模型不可增删改名
    （table_gen.py:_assessment_iro_row_seeds 与 _apply_fixed_seed_cells）。
    因此议题名称是权威键，可用来校验解析结果是否仍对应真实议题。
    """
    if report.assessment is None:
        return frozenset()
    registry = load_topic_contract(knowledge_package_of(report)).assessmentTopicsById
    names: set[str] = set()
    for result in report.assessment.topics:
        if result.determination != "scored" or result.materiality not in {"dual", "financial"}:
            continue
        topic = registry.get(result.assessmentTopicId)
        if topic is not None:
            names.add(topic.name)
    return frozenset(names)


def iro_conclusions_by_topic(report: Report) -> dict[str, TopicIroConclusion]:
    """解析当前 Report 的 IRO 表结论，按议题名索引；表不存在或不可见时返回空。

    最终以议题名称与评分结果对齐：只保留名称确实属于当前 IRO 议题范围的结论。
    表格结构可被用户编辑破坏，而议题名称有独立真相源（评分结果 + topic_registry），
    据此过滤可确保下游拿到的结论必定归属真实议题，而非错位或残留内容。
    """
    block = next(
        (blk for blk in report.iter_blocks() if blk.id == IRO_TABLE_BLOCK_ID), None
    )
    if block is None:
        return {}
    scored_names = _scored_iro_topic_names(report)
    conclusions = [
        conclusion
        for conclusion in parse_iro_conclusions(block)
        if conclusion.has_content()
    ]
    if not scored_names:
        # 无评分事实可对齐（如评分未完成）：不臆测，全部丢弃而非按表格结构放行。
        return {}
    return {
        conclusion.topic_name: conclusion
        for conclusion in conclusions
        if conclusion.topic_name in scored_names
    }
