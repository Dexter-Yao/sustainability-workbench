# ABOUTME(en): A new report's initial state must carry its own package's fields — never another package's.
# ABOUTME(en): Guards the cross-package leak where an HKEX report inherited Mainland-only fields.
from __future__ import annotations

from datetime import date

import pytest

from sustainability_desk.contract.knowledge_packages import (
    load_knowledge_package,
    all_knowledge_package_ids,
)
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.new_report_state import new_report_state

PACKAGE_IDS = sorted(all_knowledge_package_ids())


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_fields_are_exactly_the_package_contract_fields(package_id: str) -> None:
    """字段集与该包合同全等。

    多出的字段不是无害的空值：`plan_report` 把客户端字段合并到包字段之上，
    一个内地包独有字段（如科技伦理适用范围）混进港交所报告后，会在基本资料页
    显示成一道该包根本没有的必填题，用户永远填不完。
    """

    package = load_knowledge_package(package_id)
    state = new_report_state(package)
    assert set(state.fields) == set(load_package_contract(package).fields)


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_reporting_period_defaults_derive_from_the_previous_calendar_year(package_id: str) -> None:
    """报告年份与报告期起止按包声明的 defaultRule 现算，用户不必手填。

    报告年份是生成必填字段，缺省会让新报告一进来就卡在生成闸上。
    """

    package = load_knowledge_package(package_id)
    contract = load_package_contract(package)
    rules = {
        guidance.defaultRule
        for guidance in (contract.inputGuidance or {}).values()
        if guidance.defaultRule
    }
    state = new_report_state(package, today=date(2026, 9, 7))

    if "previous_calendar_year" in rules:
        assert state.fields["reporting_year"] == "2025"
    if "reporting_year_start" in rules:
        assert state.fields["report_period_start"] == "2025-01-01"
    if "reporting_year_end" in rules:
        assert state.fields["report_period_end"] == "2025-12-31"


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_no_block_skeletons_are_written(package_id: str) -> None:
    """首个状态不含空块骨架。

    范围外章节的空块一旦随首个状态写入即被判为范围外并 403：报告建成却进不去、
    名额被占死，用户连删都删不掉。
    """

    state = new_report_state(load_knowledge_package(package_id))
    assert state.generatedBlocks == {}
    assert state.tableBlocks == {}
    assert state.imageBlocks == {}
    assert state.sectionTitles == {}
    assert state.intakeItems == {}


def test_mainland_only_fields_stay_out_of_hkex_packages() -> None:
    """回归：上交所独有字段曾经出现在港交所报告里。

    根因是建报用客户端静态合同投影（`frontend/public/contract.json`，上交所简体）
    初始化字段集。这条断言直接钉住那 4 个字段。
    """

    mainland_only = {
        "has_technology_ethics_sensitive_activity",
        "board_attendance_rate",
        "board_meeting_count",
        "report_approval_body",
    }
    sse_fields = set(new_report_state(load_knowledge_package("sse_zh_hans")).fields)
    assert mainland_only <= sse_fields

    for package_id in ("hkex_zh_hant", "hkex_en"):
        fields = set(new_report_state(load_knowledge_package(package_id)).fields)
        assert not (mainland_only & fields)
