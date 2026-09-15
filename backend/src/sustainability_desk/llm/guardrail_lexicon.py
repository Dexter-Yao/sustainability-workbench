# ABOUTME(en): Guardrail lexicons — the language-specific word surfaces the deterministic guardrails match
# ABOUTME(en): (missing-statement phrases, sensitive HR wording, numeric units, typographic rules). One lexicon per
# ABOUTME(en): report language; the checks in generation_guardrails.py stay language-neutral and pick the lexicon
# ABOUTME(en): of the report's package. Rules that only exist in Chinese typography are None in the English lexicon.
from __future__ import annotations

import re
from dataclasses import dataclass

from sustainability_desk.contract.language import Language


@dataclass(frozen=True)
class GuardrailLexicon:
    """Word surfaces of one language consumed by the online guardrails.

    Every pattern here is a high-certainty hard line (leaks, fabricated numbers or names, missing or
    negative statements, sensitive HR wording, typography). Semantic quality stays with the judges.
    """

    language: Language
    # Generic word for the reporting entity; table cells with subjectTerm=company must use it.
    company_subject_term: str
    # (surface, message): phrases that never belong in report prose (model self-reference,
    # delivery-flow talk, echoed empty-input placeholders).
    forbidden_output_patterns: tuple[tuple[str, str], ...]
    missing_statement_patterns: tuple[str, ...]
    metric_narrative_maturity_patterns: tuple[tuple[str, str], ...]
    formal_document_name_pattern: re.Pattern[str] | None
    formal_principle_pattern: re.Pattern[str] | None
    esg_social_sensitive_patterns: tuple[tuple[re.Pattern[str], str], ...]
    # Regex templates with a {pattern} slot for evidence-gated facts (negation / affirmation cues).
    sensitive_fact_negation_pattern: str
    sensitive_fact_affirmation_pattern: str
    numeric_pattern: re.Pattern[str]
    numeric_with_unit_pattern: re.Pattern[str]
    self_numbering_line_pattern: re.Pattern[str] | None
    numeric_range_missing_percent_pattern: re.Pattern[str] | None
    approximate_number_comma_pattern: re.Pattern[str] | None
    title_trailing_punctuation_pattern: re.Pattern[str]
    version_placeholder_only_pattern: re.Pattern[str] | None
    # Export-gate markers of internal notes or agent instructions that must never appear in report text.
    # Phrase-level in English: bare words such as "agent" or "prompt" are ordinary report vocabulary there.
    internal_report_text_markers: tuple[str, ...] = ()


_ZH_QUOTE_OPEN = "“\"「『"
_ZH_QUOTE_CLOSE = "”\"」』"
_ZH_QUOTED_PHRASE = rf"[{_ZH_QUOTE_OPEN}][^{_ZH_QUOTE_CLOSE}]{{2,40}}[{_ZH_QUOTE_CLOSE}]"

_ZH_HANS_SOCIAL_MESSAGE_HR = "输出包含不适合 ESG 报告的人力资本管理表述。"
_ZH_HANS_SOCIAL_MESSAGE_FLOOR = "输出包含不宜写入报告正文的合规底线表述。"


def _delivery_confirmation(verbs: tuple[str, ...], subjects: tuple[str, ...], suffix: str, message: str):
    # Delivery-flow talk ("please confirm with the client") is internal collaboration wording;
    # every verb × subject combination is banned so a rewording never slips through.
    return tuple((f"{verb}{subject}{suffix}", message) for verb in verbs for subject in subjects)


ZH_HANS = GuardrailLexicon(
    language="zh-Hans",
    company_subject_term="公司",
    forbidden_output_patterns=(
        ("本节用户未填写内容", "输出复述了内部空内容占位。"),
        ("作为AI", "输出包含模型身份说明。"),
        ("作为 AI", "输出包含模型身份说明。"),
        ("交付前请", "输出包含面向交付流程的内部说明。"),
    )
    + _delivery_confirmation(("请", "待"), ("客户", "贵司", "用户"), "确认", "输出包含面向交付流程的内部说明。"),
    missing_statement_patterns=(
        r"未填写",
        r"暂未",
        r"尚未",
        r"暂无",
        r"未能",
        r"未披露",
        r"未对外披露",
        r"未统计",
        r"未量化",
        r"未通过",
        r"未提交",
        r"未设置",
        r"未建立",
        r"未形成",
        r"未作量化",
        r"不作进一步量化",
    ),
    metric_narrative_maturity_patterns=(
        (
            r"已(?:经)?(?:建立|构建|形成).{0,12}(?:指标|数据|统计).{0,8}(?:体系|机制)",
            "指标正文不得把建设中口径写成已建立的成熟事实。",
        ),
        (
            r"(?:监督(?:、|和|与)?(?:改善|改进)|对比分析)",
            "指标正文不得写入未获授权的成熟管理过程。",
        ),
        (
            r"(?:取得|实现|形成).{0,12}(?:成效|成果|提升|改善)",
            "指标正文不得写入未获授权的实际成效。",
        ),
    ),
    formal_document_name_pattern=re.compile(r"《[^》]{2,40}》"),
    formal_principle_pattern=re.compile(
        rf"(?:秉持|坚持|遵循|倡导|提出|形成).{{0,6}}({_ZH_QUOTED_PHRASE})(?:的)?(?:原则|理念|口号|方针)?"
        rf"|({_ZH_QUOTED_PHRASE})(?:原则|理念|口号|方针)"
    ),
    esg_social_sensitive_patterns=(
        (re.compile(r"劳动纪律"), _ZH_HANS_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:惩罚|处罚|惩戒).{0,6}员工|员工.{0,6}(?:惩罚|处罚|惩戒)"), _ZH_HANS_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:要求)?员工.{0,4}服从|服从性"), _ZH_HANS_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:轻视|忽视|不顾及).{0,8}员工隐私"), _ZH_HANS_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:轻视|忽视|不顾及).{0,8}员工多样性"), _ZH_HANS_SOCIAL_MESSAGE_HR),
        (re.compile(r"五险一金"), "输出包含过度具体的员工法定保障表述。"),
        (re.compile(r"依法与员工签订劳动合同"), _ZH_HANS_SOCIAL_MESSAGE_FLOOR),
        (re.compile(r"按时足额.{0,8}(?:缴纳)?(?:社会保险|社保)"), _ZH_HANS_SOCIAL_MESSAGE_FLOOR),
        (re.compile(r"各项待遇按时足额落实|待遇按时足额落实|按时足额落实"), _ZH_HANS_SOCIAL_MESSAGE_FLOOR),
        (
            re.compile(r"(?:薪酬福利|薪酬|工资|薪资).{0,8}按时足额.{0,4}(?:发放|支付|落实)"),
            _ZH_HANS_SOCIAL_MESSAGE_FLOOR,
        ),
    ),
    sensitive_fact_negation_pattern=r"(?:未发生|无|没有|不存在|未出现|未受到|未涉及|未发现).{{0,18}}{pattern}",
    sensitive_fact_affirmation_pattern=(
        r"(?:存在|(?<!未)发生|(?<!未)出现|(?<!未)受到|(?<!未)被|已完成|(?<!未)完成|(?<!未)涉及|持有).{{0,18}}{pattern}"
    ),
    numeric_pattern=re.compile(
        r"(?<![A-Za-z0-9_.])"
        r"(?:\d{4}年|\d+(?:,\d{3})*(?:\.\d+)?(?:%|％|人次|人|万元|亿元|吨|tCO2e|tCO2|kgCO2e|kWh|MWh|GWh|次|项|个)?)"
    ),
    numeric_with_unit_pattern=re.compile(
        r"^(\d+(?:,\d{3})*(?:\.\d+)?)(%|％|人次|人|万元|亿元|吨|tCO2e|tCO2|kgCO2e|kWh|MWh|GWh|次|项|个|年)$"
    ),
    # 自编号：段落以中文序号起行即与标题编号重复（格式标准 §8）。
    self_numbering_line_pattern=re.compile(
        r"^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\))",
        re.MULTILINE,
    ),
    # 数值范围两端必须同带百分号（GB/T 15835-2011）。
    numeric_range_missing_percent_pattern=re.compile(
        r"(?<![%％0-9.])(\d+(?:\.\d+)?)\s*[～~—－-]\s*(\d+(?:\.\d+)?[%％])"
    ),
    # 概数连用不加顿号（GB/T 15835-2011）；量词后缀避免误伤「一、总体目标」式结构。
    approximate_number_comma_pattern=re.compile(
        r"[一二三四五六七八九十两]、[一二三四五六七八九十两](?=[天日个月年人次名条件项位周分秒元])"
    ),
    # 标题末尾不用标点（GB/T 15834-2011）。
    title_trailing_punctuation_pattern=re.compile(r"[。．.！!？?；;，,、：:]\s*$"),
    version_placeholder_only_pattern=re.compile(
        r"^(?:版本|方案)\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:文本|内容)$"
    ),
    internal_report_text_markers=(
        "AI 不得",
        "不得改写",
        "监管强制表述",
        "按所选准则",
        "agent",
        "Agent",
        "prompt",
        "Prompt",
        "建模同步完善",
        "将随各章节准则建模",
    )
)

_ZH_HANT_SOCIAL_MESSAGE_HR = "輸出包含不適合 ESG 報告的人力資本管理表述。"
_ZH_HANT_SOCIAL_MESSAGE_FLOOR = "輸出包含不宜寫入報告正文的合規底線表述。"

# Traditional Chinese: the same hard lines transcribed to Hong Kong usage (僱員, 匱乏 wording kept close
# to the HKEX ESG Reporting Code vocabulary). Typographic rules are shared with Simplified Chinese.
ZH_HANT = GuardrailLexicon(
    language="zh-Hant",
    company_subject_term="公司",
    forbidden_output_patterns=(
        ("本節用戶未填寫內容", "輸出複述了內部空內容佔位。"),
        ("作為AI", "輸出包含模型身份說明。"),
        ("作為 AI", "輸出包含模型身份說明。"),
        ("交付前請", "輸出包含面向交付流程的內部說明。"),
    )
    + _delivery_confirmation(("請", "待"), ("客戶", "貴司", "用戶"), "確認", "輸出包含面向交付流程的內部說明。"),
    missing_statement_patterns=(
        r"未填寫",
        r"暫未",
        r"尚未",
        r"暫無",
        r"未能",
        r"未披露",
        r"未對外披露",
        r"未統計",
        r"未量化",
        r"未通過",
        r"未提交",
        r"未設置",
        r"未建立",
        r"未形成",
        r"未作量化",
        r"不作進一步量化",
    ),
    metric_narrative_maturity_patterns=(
        (
            r"已(?:經)?(?:建立|構建|形成).{0,12}(?:指標|數據|統計).{0,8}(?:體系|機制)",
            "指標正文不得把建設中口徑寫成已建立的成熟事實。",
        ),
        (
            r"(?:監督(?:、|和|與)?(?:改善|改進)|對比分析)",
            "指標正文不得寫入未獲授權的成熟管理過程。",
        ),
        (
            r"(?:取得|實現|形成).{0,12}(?:成效|成果|提升|改善)",
            "指標正文不得寫入未獲授權的實際成效。",
        ),
    ),
    formal_document_name_pattern=re.compile(r"《[^》]{2,40}》"),
    formal_principle_pattern=re.compile(
        rf"(?:秉持|堅持|遵循|倡導|提出|形成).{{0,6}}({_ZH_QUOTED_PHRASE})(?:的)?(?:原則|理念|口號|方針)?"
        rf"|({_ZH_QUOTED_PHRASE})(?:原則|理念|口號|方針)"
    ),
    esg_social_sensitive_patterns=(
        (re.compile(r"勞動紀律"), _ZH_HANT_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:懲罰|處罰|懲戒).{0,6}僱員|僱員.{0,6}(?:懲罰|處罰|懲戒)"), _ZH_HANT_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:要求)?僱員.{0,4}服從|服從性"), _ZH_HANT_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:輕視|忽視|不顧及).{0,8}僱員私隱"), _ZH_HANT_SOCIAL_MESSAGE_HR),
        (re.compile(r"(?:輕視|忽視|不顧及).{0,8}僱員多樣性"), _ZH_HANT_SOCIAL_MESSAGE_HR),
        (re.compile(r"依法與僱員簽訂僱傭合約"), _ZH_HANT_SOCIAL_MESSAGE_FLOOR),
        (re.compile(r"按時足額.{0,8}(?:供款|繳付)?(?:強積金|社會保險)"), _ZH_HANT_SOCIAL_MESSAGE_FLOOR),
        (
            re.compile(r"(?:薪酬福利|薪酬|工資|薪金).{0,8}按時足額.{0,4}(?:發放|支付|落實)"),
            _ZH_HANT_SOCIAL_MESSAGE_FLOOR,
        ),
    ),
    sensitive_fact_negation_pattern=r"(?:未發生|無|沒有|不存在|未出現|未受到|未涉及|未發現).{{0,18}}{pattern}",
    sensitive_fact_affirmation_pattern=(
        r"(?:存在|(?<!未)發生|(?<!未)出現|(?<!未)受到|(?<!未)被|已完成|(?<!未)完成|(?<!未)涉及|持有).{{0,18}}{pattern}"
    ),
    numeric_pattern=re.compile(
        r"(?<![A-Za-z0-9_.])"
        r"(?:\d{4}年|\d+(?:,\d{3})*(?:\.\d+)?(?:%|％|人次|人|萬元|億元|港元|噸|tCO2e|tCO2|kgCO2e|kWh|MWh|GWh|次|項|個)?)"
    ),
    numeric_with_unit_pattern=re.compile(
        r"^(\d+(?:,\d{3})*(?:\.\d+)?)(%|％|人次|人|萬元|億元|港元|噸|tCO2e|tCO2|kgCO2e|kWh|MWh|GWh|次|項|個|年)$"
    ),
    self_numbering_line_pattern=ZH_HANS.self_numbering_line_pattern,
    numeric_range_missing_percent_pattern=ZH_HANS.numeric_range_missing_percent_pattern,
    approximate_number_comma_pattern=re.compile(
        r"[一二三四五六七八九十兩]、[一二三四五六七八九十兩](?=[天日個月年人次名條件項位週分秒元])"
    ),
    title_trailing_punctuation_pattern=ZH_HANS.title_trailing_punctuation_pattern,
    version_placeholder_only_pattern=re.compile(
        r"^(?:版本|方案)\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:文本|內容)$"
    ),
    internal_report_text_markers=(
        "AI 不得",
        "不得改寫",
        "監管強制表述",
        "按所選準則",
        "agent",
        "Agent",
        "prompt",
        "Prompt",
        "建模同步完善",
        "將隨各章節準則建模",
    )
)

_EN_SOCIAL_MESSAGE_HR = "Output contains human-capital wording unsuitable for an ESG report."
_EN_SOCIAL_MESSAGE_FLOOR = "Output states a legal compliance floor as if it were a disclosure."
_EN_UNITS = (
    r"%|％|tCO2e|tCO2|kgCO2e|kWh|MWh|GWh|tonnes?|tons?|m3|m³|litres?|liters?|employees|people|persons|"
    r"hours|cases|items|times|incidents|HK\$|HKD|USD|RMB|million|billion"
)

# English: the same hard lines. Chinese-only typography (self-numbering with 一、, approximate-number
# commas, full-width digits) has no English counterpart and is None; word boundaries replace the
# character-adjacency the Chinese patterns rely on.
EN = GuardrailLexicon(
    language="en",
    company_subject_term="the Company",
    forbidden_output_patterns=(
        ("No content was provided for this section", "Output echoes the internal empty-input placeholder."),
        ("As an AI", "Output contains a model self-description."),
        ("as an AI", "Output contains a model self-description."),
        ("before delivery, please", "Output contains delivery-flow instructions."),
        ("Before delivery, please", "Output contains delivery-flow instructions."),
        ("please confirm with the client", "Output contains delivery-flow instructions."),
        ("to be confirmed by the client", "Output contains delivery-flow instructions."),
        ("subject to client confirmation", "Output contains delivery-flow instructions."),
        ("please confirm with the user", "Output contains delivery-flow instructions."),
    ),
    missing_statement_patterns=(
        r"\b(?:has|have|had) not (?:yet )?(?:been )?(?:established|disclosed|quantified|collected|set up|formed|adopted|submitted|conducted|implemented)\b",
        r"\bnot (?:yet )?(?:established|disclosed|quantified|collected|available|in place|formed|adopted|submitted|conducted|implemented)\b",
        r"\bno (?:formal |written )?(?:data|information|policy|system|mechanism|target)s? (?:is|are|was|were) (?:available|in place|disclosed)\b",
        r"\b(?:was|were|is|are) unable to\b",
        r"\bfailed to (?:disclose|quantify|collect|establish)\b",
        r"\bnot (?:been )?(?:further )?quantified\b",
        r"\bleft blank\b",
    ),
    metric_narrative_maturity_patterns=(
        (
            r"\b(?:has|have|had) (?:already )?(?:established|built|put in place|formed)\b.{0,40}\b(?:indicator|metric|data|statistical)\b.{0,20}\b(?:system|framework|mechanism)\b",
            "Metric prose must not present a system under construction as an established fact.",
        ),
        (
            r"\b(?:monitor(?:s|ed|ing)? and (?:improv|enhanc)\w*|comparative analysis|benchmark(?:ed|ing) against)\b",
            "Metric prose must not claim mature management processes that were not authorised.",
        ),
        (
            r"\b(?:achieved|delivered|realised|realized|recorded)\b.{0,40}\b(?:results|improvements?|gains|reductions?|savings)\b",
            "Metric prose must not claim actual results that were not authorised.",
        ),
    ),
    formal_document_name_pattern=None,
    formal_principle_pattern=re.compile(
        r"(?:uphold|adhere to|follow|advocate|propose|embrace|form)\w*\s.{0,12}\"([^\"]{2,40})\""
        r"|\"([^\"]{2,40})\"\s(?:principle|philosophy|slogan|policy|motto)"
    ),
    esg_social_sensitive_patterns=(
        (re.compile(r"\blabou?r discipline\b", re.IGNORECASE), _EN_SOCIAL_MESSAGE_HR),
        (
            re.compile(r"\b(?:punish|penali[sz]e|disciplin)\w*\b.{0,12}\bemployees\b|\bemployees\b.{0,12}\b(?:punish|penali[sz]e|disciplin)\w*", re.IGNORECASE),
            _EN_SOCIAL_MESSAGE_HR,
        ),
        (re.compile(r"\b(?:employee|staff) obedience\b|\bobedient (?:employees|staff|workforce)\b", re.IGNORECASE), _EN_SOCIAL_MESSAGE_HR),
        (re.compile(r"\b(?:disregard|ignore|neglect)\w*\b.{0,12}\bemployee privacy\b", re.IGNORECASE), _EN_SOCIAL_MESSAGE_HR),
        (re.compile(r"\b(?:disregard|ignore|neglect)\w*\b.{0,12}\b(?:employee )?diversity\b", re.IGNORECASE), _EN_SOCIAL_MESSAGE_HR),
        (
            re.compile(r"\bsign(?:s|ed|ing)? (?:employment|labou?r) contracts?\b.{0,30}\b(?:as required by|in accordance with) (?:the )?law\b", re.IGNORECASE),
            _EN_SOCIAL_MESSAGE_FLOOR,
        ),
        (
            re.compile(r"\b(?:pays?|paid|paying|makes?|made|making)\b.{0,20}\b(?:MPF|mandatory provident fund|social insurance|statutory) (?:contributions?|payments?)\b.{0,20}\b(?:on time|in full)\b", re.IGNORECASE),
            _EN_SOCIAL_MESSAGE_FLOOR,
        ),
        (
            re.compile(r"\b(?:wages|salaries|remuneration|benefits)\b.{0,20}\b(?:paid|settled|delivered)\b.{0,10}\b(?:on time and in full|in full and on time)\b", re.IGNORECASE),
            _EN_SOCIAL_MESSAGE_FLOOR,
        ),
    ),
    sensitive_fact_negation_pattern=r"(?:no|not|never|without|freeof|didnot|hasnot|havenot|noneof)\W{{0,3}}\w{{0,12}}\W{{0,18}}{pattern}",
    sensitive_fact_affirmation_pattern=r"(?:was|were|is|are|has|have|had|received|incurred|completed|holds?|subjectto|recordedin).{{0,18}}{pattern}",
    numeric_pattern=re.compile(
        r"(?<![A-Za-z0-9_.])"
        rf"(?:\d{{4}}\b|\d+(?:,\d{{3}})*(?:\.\d+)?(?:\s?(?:{_EN_UNITS}))?)"
    ),
    numeric_with_unit_pattern=re.compile(rf"^(\d+(?:,\d{{3}})*(?:\.\d+)?)\s?({_EN_UNITS})$"),
    self_numbering_line_pattern=None,
    numeric_range_missing_percent_pattern=re.compile(
        r"(?<![%％0-9.])(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?%)"
    ),
    approximate_number_comma_pattern=None,
    title_trailing_punctuation_pattern=re.compile(r"[.!?;:,]\s*$"),
    version_placeholder_only_pattern=re.compile(
        r"^(?:version|option|variant)\s*\d+\s*(?:text|content)?$", re.IGNORECASE
    ),
    internal_report_text_markers=(
        "As an AI",
        "as an AI",
        "File Agent",
        "Mapping Agent",
        "Image Agent",
        "system prompt",
        "System prompt",
        "the user prompt",
        "AI must not",
        "must not be rewritten by AI",
    )
)

LEXICONS: dict[Language, GuardrailLexicon] = {"zh-Hans": ZH_HANS, "zh-Hant": ZH_HANT, "en": EN}


def lexicon_for(language: Language) -> GuardrailLexicon:
    """The guardrail lexicon of a report language."""

    return LEXICONS[language]
