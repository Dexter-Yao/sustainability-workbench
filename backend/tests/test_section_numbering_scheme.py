# ABOUTME(en): Section numbering schemes: chapter_cn keeps the Chinese 第N章/一、/（一） labels; decimal
# ABOUTME(en): produces 1 / 1.1 / 1.1.1 and leaves the subtree of an unnumbered front chapter unnumbered.
from __future__ import annotations

from types import SimpleNamespace

from sustainability_desk.contract.section_number import number_sections


def _section(key, title, level, children=()):
    return SimpleNamespace(key=key, title=title, headingLevel=level, children=list(children), titleContent=None)


TREE = [
    _section("about_report", "關於本報告", 1, [_section("about_report.scope", "匯報範圍", 2)]),
    _section(
        "environment",
        "環境",
        1,
        [
            _section("environment.emissions", "排放物", 2, [_section("environment.emissions.gov", "管治", 3)]),
            _section("environment.energy", "能源", 2),
        ],
    ),
    _section("report_appendix", "附錄", 1, [_section("report_appendix.kpi", "關鍵績效指標", 2)]),
]


def test_chapter_cn_scheme_numbers_front_matter_children() -> None:
    labels = number_sections(TREE, lambda _: True, scheme="chapter_cn")
    assert labels["about_report"] == ""
    assert labels["about_report.scope"] == "一、"
    assert labels["environment"] == "第一章 "
    assert labels["environment.emissions.gov"] == "（一）"


def test_decimal_scheme_numbers_hierarchically_and_skips_unnumbered_subtrees() -> None:
    labels = number_sections(TREE, lambda _: True, scheme="decimal")
    assert labels["about_report"] == "" and labels["about_report.scope"] == ""
    assert labels["environment"] == "1 "
    assert labels["environment.emissions"] == "1.1 "
    assert labels["environment.emissions.gov"] == "1.1.1 "
    assert labels["environment.energy"] == "1.2 "
    assert labels["report_appendix"] == "" and labels["report_appendix.kpi"] == ""


def test_default_scheme_is_chapter_cn() -> None:
    assert number_sections(TREE, lambda _: True)["environment"] == "第一章 "
