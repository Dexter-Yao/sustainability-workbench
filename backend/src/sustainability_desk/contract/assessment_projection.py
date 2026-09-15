# ABOUTME: 评估→values 投影（纯函数）：AssessmentResult → fill_report 可消费的 values 片段（fields/tables）。
# ABOUTME: 名称、维度与章节关系只从 Registry 解析；固定分类进入结果表但不制造评分坐标。
# ABOUTME(en): Assessment-to-values projection (pure): AssessmentResult becomes a values fragment for fill_report.
# ABOUTME(en): Names, dimensions and sections resolve from the Registry; fixed topics invent no score coordinates.
from __future__ import annotations

from sustainability_desk.contract.models import (
    AssessmentResult,
    AssessmentVocabulary,
    GsTableRow,
    Report,
    ScoredAssessmentResult,
)
from sustainability_desk.contract.table_ops import harvest_table_rows
from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.contract.topic_registry import ResolvedTopicContract, load_topic_contract

# 投影目标地址：契约既定 block id（投影消费契约结构，不改契约）。
TOPIC_TABLE_BLOCK_ID = "sm.topic_table"
IRO_TABLE_BLOCK_ID = "sm.iro_table"


def _has_resolved_table_rows(rows: list[GsTableRow]) -> bool:
    """判断 Report revision 是否已持有表格数据，避免导出投影覆盖已冻结结果。"""

    return any(
        cell.value not in (None, "", [])
        for row in rows
        if not row.headerRow
        for cell in row.children
    )


def _topic_row(
    topic, contract: ResolvedTopicContract, vocabulary: AssessmentVocabulary
) -> dict[str, str]:
    ref = contract.assessmentTopicsById[topic.assessmentTopicId]
    return {
        "topic_dimension": contract.dimension_label(ref.dimension),
        "topic_name": ref.name,
        "topic_materiality": getattr(vocabulary.materiality, topic.materiality),
    }


def _iro_row(
    topic: ScoredAssessmentResult,
    contract: ResolvedTopicContract,
    vocabulary: AssessmentVocabulary,
) -> dict[str, object]:
    ref = contract.assessmentTopicsById[topic.assessmentTopicId]
    impacts = [i for i in topic.iroItems or [] if i.kind == "impact"]
    risks_opps = [i for i in topic.iroItems or [] if i.kind in ("risk", "opportunity")]
    value_chain = next((i.valueChain for i in topic.iroItems or [] if i.valueChain), None)
    time_horizon = next((i.timeHorizon for i in topic.iroItems or [] if i.timeHorizon), None)
    impact_classes = sorted({c for i in impacts for c in (i.classes or [])})
    riskopp_classes = sorted(
        {c for i in risks_opps for c in (i.classes or [])}
        or {
            vocabulary.iroKind.risk if i.kind == "risk" else vocabulary.iroKind.opportunity
            for i in risks_opps
            if i.description
        }
    )
    # 形态与契约 rowExpansion（sm.iro_table）一致：共享列在外层、每个子行一个嵌套对象。
    return {
        "iro_topic": ref.name,
        "iro_value_chain": value_chain or [],
        "iro_time_horizon": time_horizon or [],
        "impact": {
            "iro_desc": "；".join(i.description for i in impacts if i.description),
            "iro_class": impact_classes,
        },
        "risk_opportunity": {
            "iro_desc": "；".join(i.description for i in risks_opps if i.description),
            "iro_class": riskopp_classes,
        },
    }


def project_assessment(assessment: AssessmentResult, *, package: KnowledgePackage) -> dict:
    """把评估结果投影为 fill_report/渲染可消费的 values 片段（tables）。

    纯函数、不触契约：议题逐条铺 sm.topic_table 行；财务/双重重要性议题铺 sm.iro_table 行。
    assessment 本身仍是唯一事实源，表格行只是导出/显示投影。
    """
    contract = load_topic_contract(package)
    vocabulary = assessment_vocabulary(package)
    iro_topics = [
        topic
        for topic in assessment.topics
        if topic.determination == "scored" and topic.materiality in ("dual", "financial")
    ]
    return {
        "tables": {
            TOPIC_TABLE_BLOCK_ID: [_topic_row(t, contract, vocabulary) for t in assessment.topics],
            IRO_TABLE_BLOCK_ID: [_iro_row(t, contract, vocabulary) for t in iro_topics],
        },
    }


def apply_assessment_projection(report: Report) -> Report:
    """把后端 resolved assessment 确定性投影到工作台与导出共用表格。"""
    if report.assessment is None:
        return report
    tables = project_assessment(report.assessment, package=knowledge_package_of(report))["tables"]

    def project_sections(sections):
        projected = []
        for section in sections:
            blocks = []
            for block in section.blocks:
                table = block.table
                if table is None or table.rowSource not in {"assessment_topics", "assessment_iro"}:
                    blocks.append(block)
                    continue
                headers = [row for row in table.children if row.headerRow]
                existing_rows = [row for row in table.children if not row.headerRow]
                if _has_resolved_table_rows(existing_rows):
                    blocks.append(block)
                    continue
                rows = harvest_table_rows(block, tables.get(block.id, []))
                blocks.append(
                    block.model_copy(update={"table": table.model_copy(update={"children": [*headers, *rows]})})
                )
            projected.append(
                section.model_copy(
                    update={
                        "blocks": blocks,
                        "children": project_sections(section.children or [])
                        if section.children is not None
                        else None,
                    }
                )
            )
        return projected

    return report.model_copy(update={"sections": project_sections(report.sections)})
