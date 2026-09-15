# ABOUTME: 校验议题内已披露正文的解析边界——只取在先支柱、已落定的正文，不外泄实现细节。
# ABOUTME: 关注"尚未写入的内容会不会被当成既成事实喂给模型"，而非解析函数的内部形状。
from __future__ import annotations

from sustainability_desk.contract.prior_disclosure import (
    PILLAR_ORDER,
    PriorDisclosure,
    pillar_rank_in_report,
    prior_disclosures_for_block,
)
from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.models import Block, Inline, Report
from sustainability_desk.llm.generate import _template
from knowledge_package_fixtures import SSE_PACKAGE


def _paragraph(block_id: str, text: str, state: str | None = "ready") -> Block:
    return Block(
        id=block_id,
        type="paragraph",
        blockType="generative",
        source="ai",
        state=state,
        content=[Inline(kind="text", text=text)] if text else None,
    )


def test_pillar_order_matches_report_structure() -> None:
    """支柱位次取自报告 Section 树，不是本模块自造的排序。"""
    report = _template(SSE_PACKAGE)
    assert pillar_rank_in_report(
        report, "anti_bribery_anti_corruption.gov_structure_responsibilities"
    ) == PILLAR_ORDER.index("governance")
    assert pillar_rank_in_report(
        report, "anti_bribery_anti_corruption.iro_management_framework"
    ) == PILLAR_ORDER.index("iro_management")
    assert pillar_rank_in_report(report, "climate.strategy_direction") == (
        PILLAR_ORDER.index("strategy")
    )


def test_summary_block_has_no_pillar_and_depends_on_nothing() -> None:
    """议题摘要块是 planner 的互斥分支，不属四支柱，排在最前不参照在先正文。"""
    report = _template(SSE_PACKAGE)
    assert pillar_rank_in_report(report, "anti_bribery_anti_corruption.concise_summary") == -1


def _report_with(blocks: list[Block]) -> Report:
    template = _template(SSE_PACKAGE)
    report = template.model_copy(deep=True)
    by_id = {block.id: block for block in blocks}
    for block in report.iter_blocks():
        replacement = by_id.get(block.id)
        if replacement is not None:
            block.content = replacement.content
            block.state = replacement.state
    return report


def test_later_pillar_sees_earlier_pillar_text() -> None:
    """治理支柱已落定的正文，对影响风险与机遇支柱构成已披露事实。"""
    definition = load_compiled_report_definition(SSE_PACKAGE)
    report = _report_with(
        [
            _paragraph(
                "anti_bribery_anti_corruption.gov_structure_responsibilities",
                "公司设立独立的法务合规部门，明确零容忍贿赂政策。",
            )
        ]
    )
    got = prior_disclosures_for_block(
        report, definition, "anti_bribery_anti_corruption.iro_management_framework"
    )
    assert any("零容忍贿赂" in item.text for item in got)
    assert all(item.pillar_title == "治理" for item in got)


def test_same_pillar_blocks_do_not_reference_each_other() -> None:
    """同支柱内的块并发生成，彼此无先后；把对方当已披露会把未落定内容当成事实。"""
    definition = load_compiled_report_definition(SSE_PACKAGE)
    report = _report_with(
        [
            _paragraph(
                "anti_bribery_anti_corruption.iro_management_framework",
                "反贪污管理体系覆盖财务与非财务全流程。",
            )
        ]
    )
    got = prior_disclosures_for_block(
        report, definition, "anti_bribery_anti_corruption.iro_management_measures"
    )
    assert all("财务与非财务全流程" not in item.text for item in got)


def test_unfinished_block_is_not_disclosed() -> None:
    """未落定（非 ready）的块没有正文可参照，不得进入已披露事实。"""
    definition = load_compiled_report_definition(SSE_PACKAGE)
    report = _report_with(
        [
            _paragraph(
                "anti_bribery_anti_corruption.gov_structure_responsibilities",
                "尚未定稿的内容。",
                state="generating",
            )
        ]
    )
    got = prior_disclosures_for_block(
        report, definition, "anti_bribery_anti_corruption.iro_management_framework"
    )
    assert all("尚未定稿" not in item.text for item in got)


def test_other_topic_text_never_leaks_in() -> None:
    """已披露事实按议题隔离；别的议题写了什么与本块无关。"""
    definition = load_compiled_report_definition(SSE_PACKAGE)
    report = _report_with(
        [_paragraph("climate.gov_structure", "气候治理架构涵盖治理层与执行层。")]
    )
    got = prior_disclosures_for_block(
        report, definition, "anti_bribery_anti_corruption.iro_management_framework"
    )
    assert all("气候治理架构" not in item.text for item in got)


def test_disclosure_carries_no_implementation_detail() -> None:
    """投影给模型的对象只有支柱名与正文；blockId、状态与节点结构不得外泄。"""
    assert set(PriorDisclosure.model_fields) == {"pillar_title", "text"}
