# ABOUTME: 校验 IRO 表结论的解析边界——按结构证据归并业务行，编辑破坏的组不得错位注入下游。
# ABOUTME: 关注"错误结论会不会被当作某议题的事实"，而非解析函数的内部形状。
from __future__ import annotations

from sustainability_desk.contract.iro_conclusions import (
    iro_conclusions_by_topic,
    parse_iro_conclusions,
)
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.contract.models import (
    AssessmentResult,
    Block,
    GenerationSpec,
    GenerationTask,
    GsColDef,
    GsTable,
    GsTableCell,
    GsTableRow,
    Report,
    RowExpansion,
    RowExpansionUnit,
    ScoredAssessmentResult,
    Section,
)
from knowledge_package_fixtures import SSE_PACKAGE

COL_DEFS = [
    GsColDef(key="iro_topic", header="议题", cellType="text"),
    GsColDef(key="iro_desc", header="描述", cellType="ai_text"),
    GsColDef(
        key="iro_class",
        header="分类",
        cellType="multi_select",
        options=["潜在负面影响", "机遇", "风险"],
    ),
    GsColDef(
        key="iro_value_chain",
        header="影响范围",
        cellType="multi_select",
        options=["公司运营"],
    ),
    GsColDef(
        key="iro_time_horizon", header="影响周期", cellType="multi_select", options=["中期"]
    ),
]

EXPANSION = RowExpansion(
    sharedColumnKeys=["iro_topic", "iro_value_chain", "iro_time_horizon"],
    units=[
        RowExpansionUnit(key="impact", label="影响描述", columnKeys=["iro_desc", "iro_class"]),
        RowExpansionUnit(
            key="risk_opportunity",
            label="风险与/或机遇影响描述",
            columnKeys=["iro_desc", "iro_class"],
        ),
    ],
)


def _shared_row(topic: str, desc: str, klass: str) -> GsTableRow:
    """首子行：带共享列（rowSpan 合并）+ 本子行列。"""
    return GsTableRow(
        children=[
            GsTableCell(type="td", colKey="iro_topic", value=topic, rowSpan=2),
            GsTableCell(type="td", colKey="iro_desc", value=desc),
            GsTableCell(type="td", colKey="iro_class", value=[klass]),
            GsTableCell(type="td", colKey="iro_value_chain", value=["公司运营"], rowSpan=2),
            GsTableCell(type="td", colKey="iro_time_horizon", value=["中期"], rowSpan=2),
        ]
    )


def _continuation_row(desc: str, klass: str) -> GsTableRow:
    """续子行：省略被合并的共享列占位格。"""
    return GsTableRow(
        children=[
            GsTableCell(type="td", colKey="iro_desc", value=desc),
            GsTableCell(type="td", colKey="iro_class", value=[klass]),
        ]
    )


def _block(rows: list[GsTableRow]) -> Block:
    return Block(
        id="sm.iro_table",
        type="table",
        blockType="constrained",
        source="ai",
        table=GsTable(colDefs=COL_DEFS, children=rows),
        generation=GenerationSpec(
            task=GenerationTask(focus="IRO"),
            rowMode="expanded_rows",
            rowExpansion=EXPANSION,
        ),
    )


def test_parses_well_formed_groups() -> None:
    block = _block(
        [
            _shared_row("气候变化", "对外部环境的影响", "潜在负面影响"),
            _continuation_row("对公司自身的风险", "风险"),
            _shared_row("水资源", "取水影响流域", "潜在负面影响"),
            _continuation_row("节水带来成本机遇", "机遇"),
        ]
    )

    conclusions = parse_iro_conclusions(block)

    assert [c.topic_name for c in conclusions] == ["气候变化", "水资源"]
    assert conclusions[0].impact_summary == "对外部环境的影响"
    assert conclusions[0].risk_opportunity_summary == "对公司自身的风险"
    assert conclusions[1].risk_opportunity_classes == ("机遇",)


def test_deleted_continuation_row_does_not_shift_next_topic() -> None:
    """用户删掉一个续子行后，后续议题不得整体错位。

    回归：原按固定 span 位置分组，删一行会让「水资源」的影响描述被读成
    「气候变化」的风险机遇结论，并静默注入下游议题章节的方向参照。
    """
    block = _block(
        [
            _shared_row("气候变化", "对外部环境的影响", "潜在负面影响"),
            # 用户在工作台删掉了气候变化的风险机遇子行
            _shared_row("水资源", "取水影响流域", "潜在负面影响"),
            _continuation_row("节水带来成本机遇", "机遇"),
        ]
    )

    conclusions = parse_iro_conclusions(block)

    # 残缺的「气候变化」组被丢弃，而不是吞掉下一个议题的行。
    assert [c.topic_name for c in conclusions] == ["水资源"]
    assert conclusions[0].impact_summary == "取水影响流域"
    assert conclusions[0].risk_opportunity_summary == "节水带来成本机遇"


def test_extra_continuation_row_drops_that_group_only() -> None:
    """多出一个子行的组被丢弃，但不影响其余议题。"""
    block = _block(
        [
            _shared_row("气候变化", "影响", "潜在负面影响"),
            _continuation_row("风险", "风险"),
            _continuation_row("用户多加的一行", "机遇"),
            _shared_row("水资源", "取水影响", "潜在负面影响"),
            _continuation_row("机遇", "机遇"),
        ]
    )

    conclusions = parse_iro_conclusions(block)

    assert [c.topic_name for c in conclusions] == ["水资源"]


def test_orphan_continuation_rows_before_any_topic_are_ignored() -> None:
    """首个共享行之前的孤立续行无从归属，直接丢弃而非误配。"""
    block = _block(
        [
            _continuation_row("无主的描述", "风险"),
            _shared_row("气候变化", "影响", "潜在负面影响"),
            _continuation_row("风险", "风险"),
        ]
    )

    conclusions = parse_iro_conclusions(block)

    assert [c.topic_name for c in conclusions] == ["气候变化"]
    assert conclusions[0].impact_summary == "影响"


def test_block_without_expansion_yields_nothing() -> None:
    block = Block(
        id="sm.iro_table",
        type="table",
        blockType="constrained",
        source="ai",
        table=GsTable(colDefs=COL_DEFS, children=[]),
        generation=GenerationSpec(task=GenerationTask(focus="IRO")),
    )
    assert parse_iro_conclusions(block) == ()


def _report_with_topics(rows: list[GsTableRow], topic_ids: list[str]) -> Report:
    """构造带评分结果的 Report：IRO 表 + 评分事实，用于校验名称对齐。"""
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="测试报告",
        sections=[
            Section(
                key="sm",
                title="可持续发展治理",
                blocks=[_block(rows)],
            )
        ],
        assessment=AssessmentResult(
            reportingYear=2025,
            topics=[
                ScoredAssessmentResult(
                    assessmentTopicId=tid,
                    materiality="dual",
                    financialScore=4.0,
                    impactScore=4.0,
                )
                for tid in topic_ids
            ],
        ),
    )


def test_conclusion_must_match_a_scored_topic_name() -> None:
    """议题名称与评分结果对齐：名称不在当前 IRO 范围内的结论一律丢弃。

    表格结构可被用户编辑破坏，而议题名称有独立真相源——IRO 表行由评分结果确定
    (rowSource: assessment_iro)，iro_topic 由系统按 topic_registry 官方名称写入，
    模型不可增删改名。据此过滤可确保下游拿到的结论必定归属真实议题。
    """
    contract = load_topic_contract(SSE_PACKAGE)
    topic = contract.source.assessmentTopics[0]

    report = _report_with_topics(
        [
            _shared_row(topic.name, "真实议题的影响", "潜在负面影响"),
            _continuation_row("真实议题的风险", "风险"),
            # 表里残留一个已不在评分范围内的议题（如用户改了评分后表未重算）
            _shared_row("某个不在评分范围的议题", "残留影响", "潜在负面影响"),
            _continuation_row("残留风险", "风险"),
        ],
        [topic.id],
    )

    by_topic = iro_conclusions_by_topic(report)

    assert set(by_topic) == {topic.name}
    assert by_topic[topic.name].impact_summary == "真实议题的影响"


def test_no_assessment_facts_yields_nothing() -> None:
    """无评分事实可对齐时不臆测：全部丢弃，而非按表格结构放行。"""
    contract = load_topic_contract(SSE_PACKAGE)
    topic = contract.source.assessmentTopics[0]
    report = _report_with_topics(
        [
            _shared_row(topic.name, "影响", "潜在负面影响"),
            _continuation_row("风险", "风险"),
        ],
        [],
    )

    assert iro_conclusions_by_topic(report) == {}
