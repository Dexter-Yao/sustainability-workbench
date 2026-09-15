# ABOUTME: 图表编号引擎单测——正文全文连续编号、附录 A.N 独立编号、题注拼装与起编隔离。
from __future__ import annotations

from sustainability_desk.export.figure_projection import FigureNumbering
from sustainability_desk.export.format_profile import load_format_profile
from knowledge_package_fixtures import SSE_PACKAGE


def test_body_figures_and_tables_number_sequentially_and_independently() -> None:
    numbering = FigureNumbering(load_format_profile(SSE_PACKAGE))
    first_figure = numbering.assign(
        "figure",
        block_id="b.img1",
        kind="org_chart",
        caption="治理架构图",
        in_appendix=False,
    )
    first_table = numbering.assign(
        "table",
        block_id="b.tbl1",
        kind="table",
        caption="温室气体排放数据",
        in_appendix=False,
    )
    second_figure = numbering.assign(
        "figure",
        block_id="b.img2",
        kind="evidence_image",
        caption=None,
        in_appendix=False,
    )

    assert first_figure.number_label == "图1"
    assert first_figure.caption_text == "图1　治理架构图"
    assert first_table.number_label == "表1"
    assert first_table.caption_text == "表1　温室气体排放数据"
    # 图与表各自独立计数；无题注图表只输出纯编号。
    assert second_figure.number_label == "图2"
    assert second_figure.caption_text == "图2"


def test_appendix_numbers_use_letter_prefix_and_own_counters() -> None:
    numbering = FigureNumbering(load_format_profile(SSE_PACKAGE))
    numbering.assign(
        "figure",
        block_id="b.img",
        kind="evidence_image",
        caption="正文图",
        in_appendix=False,
    )
    numbering.assign(
        "table", block_id="b.tbl", kind="table", caption="正文表", in_appendix=False
    )
    appendix_figure = numbering.assign(
        "figure",
        block_id="a.img",
        kind="process_flow",
        caption="附录流程图",
        in_appendix=True,
    )
    appendix_table = numbering.assign(
        "table", block_id="a.tbl", kind="table", caption="附录数据表", in_appendix=True
    )
    second_appendix_figure = numbering.assign(
        "figure",
        block_id="a.img2",
        kind="evidence_image",
        caption=None,
        in_appendix=True,
    )

    # 附录子树独立起编，编号带 A 前缀，不延续正文计数。
    assert appendix_figure.number_label == "图A.1"
    assert appendix_figure.caption_text == "图A.1　附录流程图"
    assert appendix_table.number_label == "表A.1"
    assert second_appendix_figure.number_label == "图A.2"
    assert second_appendix_figure.caption_text == "图A.2"


def test_caption_whitespace_is_stripped_before_assembly() -> None:
    numbering = FigureNumbering(load_format_profile(SSE_PACKAGE))
    spec = numbering.assign(
        "figure",
        block_id="b.img",
        kind="evidence_image",
        caption="  两端带空格的题注  ",
        in_appendix=False,
    )
    assert spec.caption_text == "图1　两端带空格的题注"


def test_blank_caption_degrades_to_bare_number() -> None:
    numbering = FigureNumbering(load_format_profile(SSE_PACKAGE))
    spec = numbering.assign(
        "figure",
        block_id="b.img",
        kind="evidence_image",
        caption="   ",
        in_appendix=False,
    )
    assert spec.caption_text == "图1"


def test_fresh_instance_restarts_numbering_per_document() -> None:
    profile = load_format_profile(SSE_PACKAGE)
    first = FigureNumbering(profile)
    first.assign(
        "figure",
        block_id="b.img",
        kind="evidence_image",
        caption="甲",
        in_appendix=False,
    )
    fresh = FigureNumbering(profile)
    spec = fresh.assign(
        "figure",
        block_id="c.img",
        kind="evidence_image",
        caption="乙",
        in_appendix=False,
    )
    # 每份文档（full_report / climate_section）独立起编。
    assert spec.number_label == "图1"
