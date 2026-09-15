# ABOUTME(en): Report output language as a typed fact (BCP 47); the code-side switch behind prompts,
# ABOUTME(en): guardrail lexicons, length units and Word language tags. Packages declare it, code branches on it.
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Literal, get_args

Language = Literal["zh-Hans", "zh-Hant", "en"]

LANGUAGES: tuple[Language, ...] = get_args(Language)


LengthUnit = Literal["characters", "words"]

# Deterministic <output_language> directive, written in the target language itself. It names the
# language and script only; everything else the model reads comes from the package's prompt profile.
OUTPUT_LANGUAGE_DIRECTIVES: dict[Language, str] = {
    "zh-Hans": "报告输出语言为简体中文（zh-Hans）；全部正文、标题与表格单元格均使用简体中文书写。",
    "zh-Hant": "報告輸出語言為繁體中文（zh-Hant）；全部正文、標題與表格單元格均使用繁體中文書寫。",
    "en": "The report is written in English (en); all body text, headings and table cells must be in English.",
}

# BCP 47 tags Word understands for the languages we render (w:lang / w:eastAsia).
WORD_LANGUAGE_TAGS: dict[Language, str] = {"zh-Hans": "zh-CN", "zh-Hant": "zh-HK", "en": "en-HK"}


def length_unit(language: Language) -> LengthUnit:
    """Chinese prose is measured in characters, English prose in words."""

    return "words" if language == "en" else "characters"


def count_length(text: str, language: Language) -> int:
    """Length of a text in the language's unit: characters (as written) or whitespace-delimited words."""

    if length_unit(language) == "words":
        return len(text.split())
    return len(text)


def word_language_tag(language: Language) -> str:
    return WORD_LANGUAGE_TAGS[language]


# Separator between items of an inline list in report text (stakeholder table cells, list-valued fields).
LIST_SEPARATORS: dict[Language, str] = {"zh-Hans": "、", "zh-Hant": "、", "en": ", "}


def list_separator(language: Language) -> str:
    return LIST_SEPARATORS[language]


def format_month(value: str, language: Language) -> str:
    """Display form of a "YYYY-MM" month value: 2026年3月 in Chinese, March 2026 in English."""

    year, month = value.split("-", 1)
    if language == "en":
        return f"{calendar.month_name[int(month)]} {year}"
    return f"{year}年{int(month)}月"


@dataclass(frozen=True)
class NonSubstantiveAnswers:
    """Answer words that carry no company fact: unknown, negative or "not yet" choices and status-only text.

    Selections match exactly or by prefix; free text matches the whole (trimmed) answer.
    """

    selections: frozenset[str]
    selection_prefixes: tuple[str, ...]
    text_answer_pattern: re.Pattern[str]

    def is_non_substantive_selection(self, value: str) -> bool:
        normalized = value.strip()
        return normalized in self.selections or normalized.startswith(self.selection_prefixes)

    def is_non_substantive_text(self, value: str) -> bool:
        normalized = value.strip().rstrip("。.!！?？").strip()
        return bool(self.text_answer_pattern.fullmatch(normalized))


NON_SUBSTANTIVE_ANSWERS: dict[Language, NonSubstantiveAnswers] = {
    "zh-Hans": NonSubstantiveAnswers(
        selections=frozenset(
            {
                "不确定",
                "否",
                "无",
                "暂无",
                "无相关认证",
                "暂无相关认证",
                "暂未设置组织或岗位负责",
                "暂未设置专门组织或岗位",
                "暂未识别明显气候相关风险",
                "暂未识别明显气候相关机遇",
            }
        ),
        selection_prefixes=("暂无", "暂未"),
        text_answer_pattern=re.compile(
            r"^(?:(?:暂?无)(?:相关)?(?:信息|资料|数据|内容|情况|说明)?|"
            r"暂未(?:填写|提供|掌握|了解|确定)?|没有|否|不确定)$"
        ),
    ),
    "zh-Hant": NonSubstantiveAnswers(
        selections=frozenset(
            {
                "不確定",
                "否",
                "無",
                "沒有",
                "暫無",
                "無相關認證",
                "暫無相關認證",
                "無重大排放源",
                "無重大影響",
                "無有害廢棄物",
                "沒有遇到問題",
                "沒有發現",
                "沒有因工亡故及須呈報工傷",
            }
        ),
        selection_prefixes=("暫無", "暫未"),
        text_answer_pattern=re.compile(
            r"^(?:(?:暫?無)(?:相關)?(?:資料|數據|內容|情況|說明)?|"
            r"暫未(?:填寫|提供|掌握|了解|確定)?|沒有|否|不確定)$"
        ),
    ),
    "en": NonSubstantiveAnswers(
        selections=frozenset(
            {
                "Not sure",
                "No",
                "None",
                "None discovered",
                "No issue",
                "No related certification",
                "No dedicated department or position yet",
                "Not yet systematically identified",
                "No significant emission sources",
                "No significant impact",
                "No hazardous waste",
                "No specific focus area",
                "Not yet",
                "Not yet carried out",
                "No work-related fatality or reportable injury",
            }
        ),
        selection_prefixes=("Not yet", "No ", "None"),
        text_answer_pattern=re.compile(
            r"^(?:n/?a|none|no|not applicable|not available|not sure|unknown|tbd|to be confirmed|"
            r"nothing|not yet(?: provided| known| determined| available)?)$",
            re.IGNORECASE,
        ),
    ),
}


def non_substantive_answers(language: Language) -> NonSubstantiveAnswers:
    return NON_SUBSTANTIVE_ANSWERS[language]
