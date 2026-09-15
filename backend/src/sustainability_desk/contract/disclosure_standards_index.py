# ABOUTME: 附录披露索引表投影——按附录索引表源数据（backend/data/disclosure_standards_index.yaml）投影索引表的固定映射，本模块不调用模型。
# ABOUTME: 前两列与章/节分组来自 data/disclosure_standards_index.yaml 事实源；唯一条件单元格是科技伦理（不适用显示“不涉及”）。
# ABOUTME(en): Appendix index table projection from data/disclosure_standards_index.yaml; this module calls no model.
# ABOUTME(en): First two columns and chapter grouping come from that source; the one conditional cell is tech ethics.
from __future__ import annotations

from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.models import GsTableCell, GsTableRow, Report, Section
from sustainability_desk.contract.visibility import visible

_INDEX_BLOCK_ID = "appendix.standards_index.table"
_TECHNOLOGY_ETHICS_SECTION_ID = "technology_ethics"
_TECHNOLOGY_ETHICS_NOT_APPLICABLE = "不涉及"


class DisclosureIndexClause(BaseModel):
    """索引表中的一条准则条款及其固定对应的报告章节名。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    clause: str
    reportSections: list[str]
    conditionalOnTechnologyEthics: bool = False


class DisclosureIndexSection(BaseModel):
    """准则一节（披露要求列的合并单元）及其全部条款行。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    clauses: list[DisclosureIndexClause]


class DisclosureIndexChapter(BaseModel):
    """准则一章（整行跨列的分组行）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    sections: list[DisclosureIndexSection]


@lru_cache(maxsize=None)
def _load_disclosure_standards_index(package_id: str) -> tuple[DisclosureIndexChapter, ...]:
    package = load_knowledge_package(package_id)
    raw = yaml.safe_load(package.disclosure_standards_index_path.read_text(encoding="utf-8")) or {}
    chapters = tuple(
        DisclosureIndexChapter.model_validate(item)
        for item in raw.get("chapters", []) or []
    )
    if not chapters:
        raise ValueError("披露索引表事实源为空")
    return chapters


def load_disclosure_standards_index(
    package: KnowledgePackage,
) -> tuple[DisclosureIndexChapter, ...]:
    """读取索引表逐字事实源；结构问题必须在装载时暴露。"""

    return _load_disclosure_standards_index(package.id)


def _technology_ethics_included(report: Report) -> bool:
    """科技伦理是否编入本报告：以可见章节树为准，与装配判定同源。"""

    def walk(nodes: list[Section]) -> bool:
        for section in nodes:
            if not visible(section, report):
                continue
            if section.reportSectionId == _TECHNOLOGY_ETHICS_SECTION_ID:
                return True
            if walk(section.children or []):
                return True
        return False

    return walk(report.sections)


def disclosure_standards_index_rows(report: Report) -> list[GsTableRow]:
    """按事实源逐字构造“章分组行 + 每条款一行”的索引表数据行。

    披露要求列按节跨行合并；对应章节列为固定官方议题名，
    仅科技伦理在议题不适用时显示“不涉及”。
    """

    technology_ethics_included = _technology_ethics_included(report)
    rows: list[GsTableRow] = []
    for chapter in load_disclosure_standards_index(knowledge_package_of(report)):
        rows.append(
            GsTableRow(
                children=[
                    GsTableCell(
                        colKey="disclosure_requirement",
                        value=chapter.title,
                        colSpan=3,
                    )
                ]
            )
        )
        for index_section in chapter.sections:
            for position, clause in enumerate(index_section.clauses):
                cells: list[GsTableCell] = []
                if position == 0:
                    cells.append(
                        GsTableCell(
                            colKey="disclosure_requirement",
                            value=index_section.title,
                            rowSpan=len(index_section.clauses),
                        )
                    )
                if (
                    clause.conditionalOnTechnologyEthics
                    and not technology_ethics_included
                ):
                    section_names = [_TECHNOLOGY_ETHICS_NOT_APPLICABLE]
                else:
                    section_names = clause.reportSections
                cells.append(
                    GsTableCell(colKey="clause_reference", value=clause.clause)
                )
                cells.append(
                    GsTableCell(
                        colKey="report_section",
                        value="\n".join(section_names),
                    )
                )
                rows.append(GsTableRow(children=cells))
    return rows


def apply_disclosure_standards_index_projection(report: Report) -> Report:
    """刷新索引表只读投影；条款到章节的映射唯一属于逐字事实源。"""

    rows = disclosure_standards_index_rows(report)

    def project_sections(sections: list[Section]) -> list[Section]:
        projected: list[Section] = []
        for section in sections:
            blocks = []
            for block in section.blocks:
                if block.id == _INDEX_BLOCK_ID and block.table is not None:
                    header_rows = [
                        row for row in block.table.children if row.headerRow
                    ]
                    block = block.model_copy(
                        update={
                            "table": block.table.model_copy(
                                update={"children": header_rows + rows}
                            ),
                            "state": "ready" if rows else "omitted",
                        }
                    )
                blocks.append(block)
            projected.append(
                section.model_copy(
                    update={
                        "blocks": blocks,
                        "children": project_sections(section.children or [])
                        or None,
                    }
                )
            )
        return projected

    return report.model_copy(update={"sections": project_sections(report.sections)})
