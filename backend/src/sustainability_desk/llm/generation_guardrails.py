# ABOUTME: 在线生成确定性守卫（Guardrail）——生成后立即阻断高确定性错误并驱动有界重试；属在线关键路径拦截，区别于离线 evaluator。
# ABOUTME: 只做跨议题通用检查；议题/块级规则经 GenerationSpec.templateResidueBans/disclosureStance 等配置进入。
# ABOUTME(en): Deterministic online guardrails: block high-certainty errors after generation and drive bounded retries.
# ABOUTME(en): Cross-topic generic checks only; topic and block rules arrive via GenerationSpec config, not this module.
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.llm.guardrail_lexicon import GuardrailLexicon, lexicon_for
from sustainability_desk.contract.models import Block, GsColDef, Report
from sustainability_desk.contract.metric_narrative import metric_narrative_policy_rules
from sustainability_desk.llm.prompts import context_profile, filled_content_materials

MAX_GENERATION_ATTEMPTS = 3
MIN_PARAGRAPH_CONTENT_CHARS = 8


@dataclass(frozen=True)
class GuardrailIssue:
    """单条在线断言问题；message 可进入重试提示，evidence 仅保留短片段。"""

    key: str
    message: str
    evidence: str | None = None
    location: str | None = None


class GuardrailViolation(ValueError):
    """生成结果未通过在线 L1 断言。"""

    def __init__(self, issues: list[GuardrailIssue]):
        self.issues = issues
        summary = "；".join(issue.message for issue in issues[:3])
        if len(issues) > 3:
            summary += f"；另有 {len(issues) - 3} 项问题"
        super().__init__(f"生成结果未通过确定性检查：{summary}")


# Language-neutral surfaces only. Every language-specific word surface (missing statements, sensitive
# HR wording, numeric units, typography) lives in llm/guardrail_lexicon.py and is picked per report.
INTERNAL_LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("blockId", "输出包含内部块字段。"),
    ("standardDisclosureRequirementKey", "输出包含准则披露要求字段。"),
    ("sourceClauseReferenceLabels", "输出包含内部条款来源字段。"),
    ("provenance", "输出包含内部溯源字段。"),
    ("<filled_content>", "输出包含提示词上下文标签。"),
    ("</filled_content>", "输出包含提示词上下文标签。"),
    ("<role>", "输出包含提示词系统标签。"),
    ("</role>", "输出包含提示词系统标签。"),
    ("<report_subject>", "输出包含提示词系统标签。"),
)

FORMAL_ACRONYM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9-]{1,15}|SBTi)(?![A-Za-z0-9-])"
)
PUBLIC_ACRONYMS: frozenset[str] = frozenset({"ESG", "IRO", "ISO"})

COMPANY_NAME_FIELD_KEYS: tuple[str, ...] = (
    "company_registered_name",
    "company_short_name",
)

MARKDOWN_LINE_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)、]\s+)", re.MULTILINE
)
LOCAL_PATH_PATTERN = re.compile(r"/Users/|/tmp/|\.json\b|\.yaml\b|\.yml\b")
PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n+")
PLACEHOLDER_ONLY_PATTERN = re.compile(r"^[.\s。…·・,，、;；:：_—-]+$")


# 词面比对的字形归一化表。用户资料经 File Agent 转写后引号字形随原文件格式漂移
# （实测同一批语料里 ASCII 双引号、弯引号与直角引号三种混用），而中文正文按排版规范
# 输出弯引号。若不归一化，L1 会把"证据里明明有、只是引号不同"的引文判成伪造名称，
# 模型改写多次仍被拒直至整份报告生成失败。
# 判据只应看实质内容：字形差异是排版事实，不是高确定性硬线。
_GLYPH_EQUIVALENTS = str.maketrans(
    {
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "「": '"', "」": '"', "『": '"', "』": '"',
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "＜": "<", "＞": ">",
        "（": "(", "）": ")",
        "：": ":", "；": ";",
        "－": "-", "—": "-", "–": "-",
        "％": "%",
        # 全角数字与字母：转写自 PDF/扫描件的资料常保留全角，量化判据若不折叠，
        # 会把"证据里写作 ９０％"的数字判成模型编造。
        **{chr(0xFF10 + i): chr(0x30 + i) for i in range(10)},
        **{chr(0xFF21 + i): chr(0x41 + i) for i in range(26)},
        **{chr(0xFF41 + i): chr(0x61 + i) for i in range(26)},
    }
)


def _norm(text: str) -> str:
    """归一化到可比对的词面：去空白与千分位，并把等价字形折叠为同一形态。"""

    folded = text.translate(_GLYPH_EQUIVALENTS)
    return re.sub(r"\s+", "", folded).replace(",", "")


def _formal_name_core(token: str) -> str:
    """取正式名称用于比对的实质内容。

    加不加引号是模型的排版选择，不是名称本身。用户资料常写作无引号短语
    （如「企业文化：天道酬勤、团队至上」），模型按中文排版加引号引用后，
    带引号比对必然落空并被判成伪造，连续拒绝会导致整次生成失败。

    引号型 token 内的连字符同属排版差异（证据「中南美-端到端」对输出「中南美端到端」），
    一并折叠；书名号与缩写 token 不做该处理——`《GB/T 32150-2015》`、`ISO 14064-1`
    里的连字符是标准号的组成部分，删除会让不同标准彼此等同。
    """

    normalized = _norm(token)
    stripped = normalized.strip("\"'")
    if stripped == normalized:
        return normalized
    return stripped.replace("-", "")


def _lexicon(report: Report) -> GuardrailLexicon:
    """The guardrail lexicon of the report's package language."""

    return lexicon_for(knowledge_package_of(report).language)


def _formal_name_tokens(text: str, lexicon: GuardrailLexicon) -> tuple[str, ...]:
    """提取高确定性的正式名称表面；普通治理词和公共 ESG 术语不进入拦截。"""

    tokens: list[str] = []
    if lexicon.formal_document_name_pattern is not None:
        tokens.extend(
            match.group(0) for match in lexicon.formal_document_name_pattern.finditer(text)
        )
    for match in FORMAL_ACRONYM_PATTERN.finditer(text):
        token = match.group(0)
        if token.upper() not in PUBLIC_ACRONYMS:
            tokens.append(token)
    if lexicon.formal_principle_pattern is not None:
        for match in lexicon.formal_principle_pattern.finditer(text):
            token = match.group(1) or match.group(2)
            if token:
                tokens.append(token)
    return tuple(dict.fromkeys(tokens))


def model_visible_evidence_text(ctx: Any) -> str:
    """当前模型实际可见的事实文本；正文与表格守卫共用同一边界。"""
    return _model_visible_evidence_text(ctx)


def _model_visible_evidence_text(ctx: Any) -> str:
    """复用实际 Prompt 投影，避免隐藏 Evidence 为输出提供旁路支持。"""
    parts: list[str] = []
    for material in filled_content_materials(ctx):
        parts.append(str(getattr(material, "text", "") or ""))
        parts.append(str(getattr(material, "note", "") or ""))
    policy = getattr(ctx, "metric_narrative_policy", None)
    if policy is not None:
        profile = context_profile(ctx)
        parts.extend(
            metric_narrative_policy_rules(
                policy, profile.metric_narrative, list_separator=profile.labels.list_separator
            )
        )
    for topic in getattr(ctx, "assessment", ()) or ():
        for iro in getattr(topic, "iro", ()) or ():
            description = str(getattr(iro, "description", "") or "")
            if description:
                parts.append(description)
    return "\n".join(parts)


def _all_source_text(ctx: Any, report: Report) -> str:
    """在线守卫只读取当前模型可见 Evidence 与报告主体，不跨议题扫描 Report。"""

    parts = [_model_visible_evidence_text(ctx)]
    for line in getattr(ctx, "report_subject", ()) or ():
        parts.append(str(line))
    return "\n".join(parts)


def _declared_context_text(ctx: Any) -> str:
    return _model_visible_evidence_text(ctx)


def _numeric_token_supported(token: str, source_norm: str, lexicon: GuardrailLexicon) -> bool:
    normalized = _norm(token)
    if normalized in source_norm:
        return True
    match = lexicon.numeric_with_unit_pattern.match(token)
    if not match:
        return False
    number, unit = match.groups()
    return _norm(number) in source_norm and _norm(unit) in source_norm


def _evidence_gated_fact_issues(
    block: Block, ctx: Any, text: str, lexicon: GuardrailLexicon, *, location: str | None
) -> list[GuardrailIssue]:
    """Facts a block declares as evidence-gated may appear only when the visible evidence carries them.

    A gated surface (e.g. a penalty or an exceedance) is rejected when the evidence never mentions it,
    or when the evidence negates it while the output affirms it. The surfaces are block contract data
    (GenerationSpec.evidenceGatedFacts); the negation and affirmation cues are language lexicon.
    """

    gated = block.generation.evidenceGatedFacts if block.generation else None
    if not gated:
        return []
    source_norm = _norm(_declared_context_text(ctx))
    text_norm = _norm(text)
    issues: list[GuardrailIssue] = []
    for pattern in gated:
        pattern_norm = _norm(pattern)
        if pattern not in text:
            continue
        source_has_pattern = pattern_norm in source_norm
        negation = lexicon.sensitive_fact_negation_pattern.format(pattern=re.escape(pattern_norm))
        affirmation = lexicon.sensitive_fact_affirmation_pattern.format(
            pattern=re.escape(pattern_norm)
        )
        source_negates = bool(re.search(negation, source_norm))
        source_affirms = bool(re.search(affirmation, source_norm))
        output_affirms = bool(re.search(affirmation, text_norm))
        if (not source_has_pattern) or (
            output_affirms and source_negates and not source_affirms
        ):
            issues.append(
                GuardrailIssue(
                    "unsupported_evidence_gated_fact",
                    "输出包含用户填写内容中未提供的敏感事实。",
                    pattern,
                    location,
                )
            )
    return issues


def _template_residue_issues(
    block: Block, text: str, *, location: str | None
) -> list[GuardrailIssue]:
    """拦截参考模板残留物：本块登记的模板示例事实与编写批注。"""

    issues: list[GuardrailIssue] = []
    generation = block.generation
    if generation is None:
        return issues
    for banned in generation.templateResidueBans or []:
        if banned and banned in text:
            issues.append(
                GuardrailIssue(
                    "template_residue",
                    "输出包含参考模板残留内容（原型公司专名、示例数值或编写批注）。",
                    banned,
                    location,
                )
            )
    return issues


def _paragraph_count(text: str) -> int:
    """按模型输出中的非空换行段落计数。"""
    return len(
        [part for part in PARAGRAPH_SPLIT_PATTERN.split(text.strip()) if part.strip()]
    )


def _company_name_surfaces(report: Report, lexicon: GuardrailLexicon) -> set[str]:
    names: set[str] = set()
    for key in COMPANY_NAME_FIELD_KEYS:
        value = report.fields.get(key).value if key in report.fields else None
        if isinstance(value, str):
            name = value.strip()
            if name and name != lexicon.company_subject_term:
                names.add(name)
    return names


def _company_subject_issues(
    report: Report, text: str, lexicon: GuardrailLexicon, *, location: str | None
) -> list[GuardrailIssue]:
    issues: list[GuardrailIssue] = []
    for name in _company_name_surfaces(report, lexicon):
        if name in text:
            issues.append(
                GuardrailIssue(
                    "table_company_subject",
                    f"表格单元格应统一使用“{lexicon.company_subject_term}”，不要写公司简称或注册名。",
                    name,
                    location,
                )
            )
    return issues


def _text_issues(
    block: Block,
    report: Report,
    ctx: Any,
    text: str,
    *,
    location: str | None = None,
    require_contract_points: bool = True,
) -> list[GuardrailIssue]:
    lexicon = _lexicon(report)
    issues: list[GuardrailIssue] = []
    stripped = text.strip()
    if not stripped:
        issues.append(GuardrailIssue("empty_output", "输出为空。", location=location))
        return issues
    if PLACEHOLDER_ONLY_PATTERN.fullmatch(stripped):
        issues.append(
            GuardrailIssue(
                "placeholder_output",
                "输出仅包含占位符或省略号，必须生成可直接采用的完整正文。",
                stripped[:20],
                location,
            )
        )
        return issues
    if (
        lexicon.version_placeholder_only_pattern is not None
        and lexicon.version_placeholder_only_pattern.fullmatch(stripped)
    ):
        issues.append(
            GuardrailIssue(
                "placeholder_output",
                "当前输出仅为版本占位标记，必须生成可直接采用的完整正文。",
                stripped[:20],
                location,
            )
        )
        return issues
    for surface, message in (*INTERNAL_LEAK_PATTERNS, *lexicon.forbidden_output_patterns):
        if surface in text:
            issues.append(GuardrailIssue("internal_leak", message, surface, location))
    if LOCAL_PATH_PATTERN.search(text):
        issues.append(
            GuardrailIssue(
                "internal_path_leak",
                "输出包含本地路径或内部文件名。",
                location=location,
            )
        )
    if MARKDOWN_LINE_PATTERN.search(text):
        issues.append(
            GuardrailIssue(
                "output_format",
                "输出包含标题、列表或 Markdown 格式。",
                location=location,
            )
        )
    self_numbering = (
        lexicon.self_numbering_line_pattern.search(text)
        if lexicon.self_numbering_line_pattern is not None
        else None
    )
    if self_numbering:
        issues.append(
            GuardrailIssue(
                "output_self_numbering",
                "段落不得自造与标题编号重复的中文序号（一、/（一）等），直接输出连续正文。",
                self_numbering.group(0).strip(),
                location,
            )
        )
    missing_percent = (
        lexicon.numeric_range_missing_percent_pattern.search(text)
        if lexicon.numeric_range_missing_percent_pattern is not None
        else None
    )
    if missing_percent:
        issues.append(
            GuardrailIssue(
                "numeric_range_missing_percent",
                "数值范围的百分号不得省略，应写作 15%～30% 的形式。",
                missing_percent.group(0),
                location,
            )
        )
    approximate_comma = (
        lexicon.approximate_number_comma_pattern.search(text)
        if lexicon.approximate_number_comma_pattern is not None
        else None
    )
    if approximate_comma:
        issues.append(
            GuardrailIssue(
                "approximate_number_comma",
                "概数连用不加顿号，应写作「三四天」的形式。",
                approximate_comma.group(0),
                location,
            )
        )

    # 风险与不利事项披露块描述风险本身即带负面措辞，正则无法区分"外部风险描述"与"公司自身短板"，
    # 故按声明的披露立场跳过此项确定性检查；块内真负面（公司自身缺失）的召回交由离线 judge。
    stance = block.generation.disclosureStance if block.generation else "standard"
    if stance != "risk_disclosure":
        for pattern in lexicon.missing_statement_patterns:
            match = re.search(pattern, text)
            if match:
                issues.append(
                    GuardrailIssue(
                        "missing_or_negative_statement",
                        "输出包含缺失、未做或未披露类负面表述。"
                        "若该表述转述自填写内容或用户说明中的状态描述，请将其删除："
                        "正文不披露「暂未建立」「尚未出台」类状态，"
                        "对应内容改按已有做法与审慎、低承诺的方向性安排表达。",
                        match.group(0),
                        location,
                    )
                )

    if getattr(ctx, "metric_narrative_policy", None) is not None:
        for pattern, message in lexicon.metric_narrative_maturity_patterns:
            match = re.search(pattern, text)
            if match:
                issues.append(
                    GuardrailIssue(
                        "metric_narrative_maturity",
                        message,
                        match.group(0),
                        location,
                    )
                )

    source_norm = _norm(_all_source_text(ctx, report))
    for match in lexicon.numeric_pattern.finditer(text):
        token = match.group(0)
        if not _numeric_token_supported(token, source_norm, lexicon):
            issues.append(
                GuardrailIssue(
                    "unsupported_numeric_claim",
                    "输出包含用户事实中未提供的具体数字或量化信息；数字与单位须按用户事实原样书写，不得换算单位或改写数量级。",
                    token,
                    location,
                )
            )
    # 引号型 token 已折叠连字符，证据侧需按同一形态比对，否则单边处理仍然落空。
    source_dehyphenated = source_norm.replace("-", "")
    for token in _formal_name_tokens(text, lexicon):
        core = _formal_name_core(token)
        haystack = source_norm if core == _norm(token) else source_dehyphenated
        if core not in haystack:
            issues.append(
                GuardrailIssue(
                    "unsupported_formal_name",
                    "输出包含当前证据中未提供的组织、制度、认证、项目、缩写或命名理念。",
                    token,
                    location,
                )
            )
    for pattern, message in lexicon.esg_social_sensitive_patterns:
        match = pattern.search(text)
        if match:
            issues.append(
                GuardrailIssue(
                    "social_sensitive_statement",
                    message,
                    match.group(0),
                    location,
                )
            )

    issues.extend(_evidence_gated_fact_issues(block, ctx, text, lexicon, location=location))

    issues.extend(_template_residue_issues(block, text, location=location))
    return issues


def check_paragraph_output(
    block: Block, report: Report, ctx: Any, text: str
) -> list[GuardrailIssue]:
    """检查单个段落候选。返回空列表表示通过。"""
    issues = _text_issues(block, report, ctx, text)
    stripped = text.strip()
    if stripped and len(_norm(stripped)) < MIN_PARAGRAPH_CONTENT_CHARS:
        issues.append(
            GuardrailIssue(
                "incomplete_output",
                "当前输出缺少可直接用于报告的实质正文。",
                stripped[:20],
            )
        )
    evidence = getattr(ctx, "evidence", None)
    if (
        not getattr(evidence, "substantive_input_present", False)
        and _paragraph_count(text) > 2
    ):
        issues.append(
            GuardrailIssue(
                "too_many_paragraphs_without_substantive_input",
                "本节不存在实质用户事实时，段落正文最多输出两段。",
            )
        )
    return issues


def check_paragraph_variants(
    block: Block, report: Report, ctx: Any, variants: list[str]
) -> list[GuardrailIssue]:
    """检查一组段落候选；任一候选不通过即返回问题。"""
    issues: list[GuardrailIssue] = []
    if not variants:
        return [GuardrailIssue("empty_variants", "未返回任何候选正文。")]
    for idx, variant in enumerate(variants):
        for issue in check_paragraph_output(block, report, ctx, variant):
            issues.append(
                issue
                if issue.location
                else GuardrailIssue(
                    issue.key, issue.message, issue.evidence, f"variant[{idx}]"
                )
            )
    return issues


def check_display_title_variants(
    block: Block,
    report: Report,
    ctx: Any,
    variants: list[str],
) -> list[GuardrailIssue]:
    """动态标题复用正文的高确定性文本边界，但不承担正文必含点或篇幅合同。"""
    lexicon = _lexicon(report)
    issues: list[GuardrailIssue] = []
    for idx, title in enumerate(variants):
        stripped_title = title.strip()
        if stripped_title and lexicon.title_trailing_punctuation_pattern.search(stripped_title):
            issues.append(
                GuardrailIssue(
                    "title_trailing_punctuation",
                    "标题末尾不用标点。",
                    stripped_title[-8:],
                    f"displayTitle[{idx}]",
                )
            )
        issues.extend(
            _text_issues(
                block,
                report,
                ctx,
                title,
                location=f"displayTitle[{idx}]",
                require_contract_points=False,
            )
        )
    return issues


def check_table_cells(
    block: Block, report: Report, ctx: Any, cells: dict[str, object]
) -> list[GuardrailIssue]:
    """检查表格单行补全结果；契约声明 rowExpansion 时逐子行检查并把问题定位到该子行。"""
    lexicon = _lexicon(report)
    issues: list[GuardrailIssue] = []
    col_defs = block.table.colDefs if block.table else []
    by_key = {col.key: col for col in col_defs}
    expansion = block.generation.rowExpansion if block.generation else None

    def check_group(
        columns: list[GsColDef], values: dict[str, object], *, prefix: str = ""
    ) -> None:
        for col in columns:
            value = values.get(col.key)
            location = f"{prefix}{col.header}"
            if col.required and _is_empty(value):
                issues.append(
                    GuardrailIssue(
                        "required_cell_empty", "表格必填单元格为空。", location=location
                    )
                )
            if col.cellType == "ai_text" and _is_empty(value):
                issues.append(
                    GuardrailIssue(
                        "ai_text_cell_empty",
                        "表格 AI 文本单元格为空。",
                        location=location,
                    )
                )
            for piece in _cell_text_values(value):
                issues.extend(
                    _text_issues(block, report, ctx, piece, location=location)
                )
                if col.subjectTerm == "company":
                    issues.extend(
                        _company_subject_issues(report, piece, lexicon, location=location)
                    )

    if expansion is None:
        check_group(col_defs, cells)
        actual_classification_values = [cells.get("iro_class") or []]
    else:
        check_group([by_key[key] for key in expansion.sharedColumnKeys], cells)
        actual_classification_values = []
        for unit in expansion.units:
            unit_values = cells.get(unit.key) or {}
            if not isinstance(unit_values, dict):
                issues.append(
                    GuardrailIssue(
                        "expanded_unit_missing",
                        f"缺少「{unit.label}」这一段披露。",
                        location=unit.label,
                    )
                )
                continue
            unit_cols = [
                by_key[key].model_copy(
                    update={
                        "genHint": (unit.genHintOverride or {}).get(
                            key, by_key[key].genHint
                        )
                    }
                )
                for key in unit.columnKeys
            ]
            check_group(unit_cols, unit_values, prefix=f"{unit.label}·")
            actual_classification_values.append(unit_values.get("iro_class") or [])

    if (
        block.table is not None
        and block.table.rowSource == "assessment_iro"
        and getattr(getattr(ctx, "evidence_posture", None), "level", None)
        == "context_only"
    ):
        # An "actual" impact asserts something happened; without company IRO facts the
        # contract only permits potential classes. The word itself is package vocabulary.
        actual_positive = assessment_vocabulary(
            knowledge_package_of(report)
        ).impactClass.actual_positive
        if any(actual_positive in values for values in actual_classification_values):
            issues.append(
                GuardrailIssue(
                    "unsupported_actual_iro_classification",
                    f"缺少企业 IRO 事实时不得将议题分类为“{actual_positive}”。",
                    actual_positive,
                    "分类",
                )
            )
    return issues


def build_retry_instruction(issues: list[GuardrailIssue]) -> str:
    """将断言问题转为模型可执行的修复指令。"""
    if not issues:
        return ""
    lines = ["上一次输出未通过确定性检查。请重新生成，并严格修复以下问题："]
    seen: set[tuple[str, str | None]] = set()
    for issue in issues:
        key = (issue.key, issue.evidence)
        if key in seen:
            continue
        seen.add(key)
        evidence = f"（问题片段：{issue.evidence}）" if issue.evidence else ""
        location = f"{issue.location}：" if issue.location else ""
        lines.append(f"- {location}{issue.message}{evidence}")
        if len(lines) >= 8:
            break
    return "\n".join(lines)


def _cell_text_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    text = str(value)
    return [text] if text.strip() else []


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    return not str(value).strip()
