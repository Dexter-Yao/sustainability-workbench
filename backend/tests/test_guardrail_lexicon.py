# ABOUTME(en): Guardrail lexicons per language: every language declares a complete lexicon, the Chinese
# ABOUTME(en): typography rules are absent in English, and each lexicon catches its own language's hard lines.
from __future__ import annotations

import re

import pytest

from sustainability_desk.contract.language import LANGUAGES
from sustainability_desk.llm.guardrail_lexicon import EN, ZH_HANS, ZH_HANT, lexicon_for


def test_every_language_has_a_lexicon_whose_patterns_compile() -> None:
    for language in LANGUAGES:
        lexicon = lexicon_for(language)
        assert lexicon.language == language
        assert lexicon.missing_statement_patterns
        for pattern in lexicon.missing_statement_patterns:
            re.compile(pattern)
        for pattern, _message in lexicon.metric_narrative_maturity_patterns:
            re.compile(pattern)
        re.compile(lexicon.sensitive_fact_negation_pattern.format(pattern="x"))
        re.compile(lexicon.sensitive_fact_affirmation_pattern.format(pattern="x"))


@pytest.mark.parametrize(
    ("lexicon", "text"),
    [
        (ZH_HANS, "公司暂未建立相关制度。"),
        (ZH_HANT, "公司暫未建立相關制度。"),
        (EN, "The Company has not yet established a related policy."),
    ],
)
def test_each_lexicon_catches_its_own_missing_statement(lexicon, text) -> None:
    assert any(re.search(pattern, text) for pattern in lexicon.missing_statement_patterns)


def test_chinese_only_typography_rules_are_absent_in_english() -> None:
    assert ZH_HANS.self_numbering_line_pattern is not None
    assert ZH_HANT.approximate_number_comma_pattern is not None
    assert EN.self_numbering_line_pattern is None
    assert EN.approximate_number_comma_pattern is None
    assert EN.formal_document_name_pattern is None
    assert EN.title_trailing_punctuation_pattern.search("Governance structure.")
    assert not EN.title_trailing_punctuation_pattern.search("Governance structure")


def test_numeric_units_follow_the_language() -> None:
    assert ZH_HANS.numeric_with_unit_pattern.match("12.5万元")
    assert ZH_HANT.numeric_with_unit_pattern.match("12.5萬元")
    assert EN.numeric_with_unit_pattern.match("12.5 tonnes")
    assert EN.numeric_pattern.search("about 320 employees").group(0) == "320 employees"


def test_english_social_sensitive_patterns_match_hr_wording() -> None:
    assert any(p.search("Employees who breach labour discipline are penalised.") for p, _ in EN.esg_social_sensitive_patterns)
    assert not any(p.search("The Company supports employee development.") for p, _ in EN.esg_social_sensitive_patterns)


def test_internal_report_text_markers_are_language_specific() -> None:
    """Bare English words such as agent/prompt are report vocabulary in English and must not be markers there."""

    from sustainability_desk.llm.guardrail_lexicon import lexicon_for

    zh_hans = lexicon_for("zh-Hans").internal_report_text_markers
    assert {"agent", "prompt", "AI 不得"} <= set(zh_hans)
    en = lexicon_for("en").internal_report_text_markers
    assert en and all(marker not in {"agent", "Agent", "prompt", "Prompt"} for marker in en)
    assert "File Agent" in en
    assert len(lexicon_for("zh-Hant").internal_report_text_markers) == len(zh_hans)


def test_retry_instruction_keeps_every_issue_seen_so_far() -> None:
    from sustainability_desk.llm.generation_guardrails import GuardrailIssue, build_retry_instruction

    first = GuardrailIssue(key="unsupported_numeric_claim", message="数字问题", evidence="320")
    second = GuardrailIssue(key="missing_or_negative_statement", message="负面表述", evidence="未能")
    instruction = build_retry_instruction([first, second])
    assert "320" in instruction and "未能" in instruction
