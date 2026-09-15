# ABOUTME(en): The report language is a typed fact of the knowledge package: every prompt opens with the
# ABOUTME(en): <output_language> directive of that language, and lengths are counted in its unit.
from __future__ import annotations

from knowledge_package_fixtures import SSE_PACKAGE, sse_model_context
from sustainability_desk.contract.language import (
    LANGUAGES,
    OUTPUT_LANGUAGE_DIRECTIVES,
    count_length,
    length_unit,
    word_language_tag,
)
from sustainability_desk.llm.generate import _template
from sustainability_desk.llm.prompts import build_model_context, render_prompt, render_propose_prompt


def test_every_language_has_a_directive_unit_and_word_tag() -> None:
    for language in LANGUAGES:
        assert OUTPUT_LANGUAGE_DIRECTIVES[language]
        assert length_unit(language) in {"characters", "words"}
        assert word_language_tag(language)
    assert length_unit("en") == "words" and length_unit("zh-Hant") == "characters"
    assert count_length("公司 高度重视", "zh-Hans") == 7
    assert count_length("The company cares deeply.", "en") == 4


def test_model_context_carries_the_package_language_and_prompts_open_with_it() -> None:
    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.gov_structure")
    ctx = build_model_context(block, template, template)
    assert ctx.knowledge_package_id == SSE_PACKAGE.id
    assert ctx.output_language == SSE_PACKAGE.language == "zh-Hans"

    system, _user = render_prompt(ctx, n=1)
    directive = OUTPUT_LANGUAGE_DIRECTIVES["zh-Hans"]
    assert system.startswith(f"<output_language>\n{directive}\n</output_language>")
    assert system.count("<output_language>") == 1


def test_table_prompts_open_with_the_directive_too() -> None:
    ctx = sse_model_context(section_task="识别风险", output_language="zh-Hant")
    system, _user = render_propose_prompt(ctx, [], count_min=1, count_max=3)
    assert system.startswith("<output_language>\n" + OUTPUT_LANGUAGE_DIRECTIVES["zh-Hant"])
