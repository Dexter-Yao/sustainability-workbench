# ABOUTME(en): Deterministic language conventions the code branches on: month display, inline list separators
# ABOUTME(en): and the non-substantive answer vocabularies of each language; the mainland wording is pinned.
from __future__ import annotations

import pytest

from sustainability_desk.contract.evidence_resolution import (
    AnswerWording,
    intake_answer_text,
    is_non_substantive_selection,
    is_non_substantive_text_answer,
)
from sustainability_desk.contract.language import LANGUAGES, format_month, list_separator, non_substantive_answers
from sustainability_desk.contract.models import IntakeItem


def test_month_display_follows_the_language() -> None:
    assert format_month("2026-03", "zh-Hans") == "2026年3月"
    assert format_month("2026-03", "zh-Hant") == "2026年3月"
    assert format_month("2026-03", "en") == "March 2026"


def test_list_separator_follows_the_language() -> None:
    assert list_separator("zh-Hans") == "、"
    assert list_separator("zh-Hant") == "、"
    assert list_separator("en") == ", "


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_declares_non_substantive_answers(language) -> None:
    assert non_substantive_answers(language).selections


@pytest.mark.parametrize(
    ("value", "language", "expected"),
    [
        ("暂无相关认证", "zh-Hans", True),
        ("暂无制度，但有日常管理做法", "zh-Hans", True),
        ("设有专职部门或岗位负责", "zh-Hans", False),
        ("不確定", "zh-Hant", True),
        ("暫無成文政策，但有日常管理做法", "zh-Hant", True),
        ("設有相關政策、程序或管理要求", "zh-Hant", False),
        ("Not sure", "en", True),
        ("No written policy, but day-to-day management practices", "en", True),
        ("Policies, procedures or management requirements in place", "en", False),
        ("Certifications held", "en", False),
    ],
)
def test_non_substantive_selection_detection(value, language, expected) -> None:
    assert is_non_substantive_selection(value, language) is expected


@pytest.mark.parametrize(
    ("value", "language", "expected"),
    [("暂未填写", "zh-Hans", True), ("公司设有节能小组。", "zh-Hans", False), ("暫無資料", "zh-Hant", True), ("N/A", "en", True), ("Not yet.", "en", True), ("The company runs an energy team.", "en", False)],
)
def test_non_substantive_text_detection(value, language, expected) -> None:
    assert is_non_substantive_text_answer(value, language) is expected


def test_intake_answer_projection_uses_the_supplied_wording() -> None:
    item = IntakeItem(
        key="climate.q_climate_risks",
        contentScopeId="climate_change",
        prompt="Which climate-related risks has the company identified?",
        kind="multi_select",
        options=["Prolonged heat", "Energy price volatility", "Not yet systematically identified"],
        answer=["Prolonged heat", "Not yet systematically identified", "Energy price volatility"],
    )
    wording = AnswerWording(selected_lead="Selected: ", supplement_lead="Supplement: ", list_separator=", ", part_separator="; ")
    assert intake_answer_text(item, language="en", wording=wording) == "Selected: Prolonged heat, Energy price volatility"
    assert intake_answer_text(item.model_copy(update={"answer": ["Not yet systematically identified"]}), language="en", wording=wording) is None
