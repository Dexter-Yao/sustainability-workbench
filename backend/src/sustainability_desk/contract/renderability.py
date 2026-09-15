# ABOUTME: 报告正文与 Word 投影共用的可渲染性判定，确保空表、空章节和完整覆盖策略只由同一 Report 事实决定。
# ABOUTME: 本模块不生成内容或改变 Report；它只将条件、受控省略和派生表格行投影为可见性结论。
# ABOUTME(en): Renderability verdicts shared by report prose and the Word projection, decided by the same Report facts.
# ABOUTME(en): Generates no content and mutates no Report; projects conditions, omission and derived rows to visibility.
from __future__ import annotations

from sustainability_desk.contract.models import Block, GsTableRow, Report, Section
from sustainability_desk.contract.visibility import visible

def uses_complete_coverage(report: Report) -> bool:
    """返回该 revision 是否采用无评分的完整议题覆盖投影。"""

    return getattr(report.meta, "materialityStrategy", None) == "complete_coverage"


def renderable_table_rows(
    table,
    report: Report,
    block_id: str | None = None,
) -> list[GsTableRow]:
    """返回实际会写入报告的表格行，表头不是单独可导出的数据内容。"""

    if table.rowSource == "certificate_facts":
        # 证书行由生成期从排版素材资产投影写入 children；此处只按既有规则读已写入的行。
        # 无证书素材时数据行为空，block_is_renderable 据此让整章不出现。
        return [row for row in table.children if row.headerRow or visible(row, report)]
    if block_id and table.rowSource == "stakeholder_engagement":
        from sustainability_desk.contract.stakeholder_engagement import stakeholder_engagement_rows

        header_rows = [row for row in table.children if row.headerRow]
        return header_rows + stakeholder_engagement_rows(report)
    return [row for row in table.children if row.headerRow or visible(row, report)]


def block_is_renderable(block: Block, report: Report) -> bool:
    """判断 Block 是否会形成公开报告正文，避免导出器临时猜测空内容。"""

    if not visible(block, report) or block.state == "omitted":
        return False
    if uses_complete_coverage(report) and block.source == "assessment":
        return False
    if block.type == "table" and block.table is not None:
        return any(
            not row.headerRow
            for row in renderable_table_rows(block.table, report, block.id)
        )
    if block.type == "image" and block.image is not None:
        if block.image.layoutAssetIds:
            return True
        if block.image.evidenceAssetId is not None:
            return True
        if block.image.derivedVisualization is not None:
            if block.image.derivedVisualization.emptyBehavior != "hide":
                return True
            from sustainability_desk.quantitative_metrics import quantitative_metric_value

            return any(
                quantitative_metric_value(report, metric_key) is not None
                for metric_key in block.image.derivedVisualization.metricKeys
            )
        if block.id == "sm.matrix_image":
            return bool(report.assessment and report.assessment.topics)
        # 没有受控资产或确定性图表规格的模板 slot 不是公开交付内容。
        # placeholder 只可作为建模/输入提示，不得进入正文、目录或 Word。
        return False
    return True


def section_is_renderable(section: Section, report: Report) -> bool:
    """章节仅在自身或子树拥有实际输出时进入正文、目录和导航。"""

    return visible(section, report) and (
        any(block_is_renderable(block, report) for block in section.blocks)
        or any(
            section_is_renderable(child, report)
            for child in section.children or []
        )
    )
