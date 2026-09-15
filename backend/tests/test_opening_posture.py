# ABOUTME: 开篇与议题口径区分测试——报告开篇为固定正文，不再把开篇式口径外溢到议题 generative 块。
# ABOUTME: by_type[generative] 保持中性基线；利益相关方/可持续发展开篇由 about.opening 固定文案承载。
from pathlib import Path

from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.export.docx_renderer import load_values_flat
from sustainability_desk.llm.generate import _template
from sustainability_desk.llm.prompts import build_model_context, render_prompt
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
VALUES = SSE_PACKAGE.sample_values_path


def _inst():
    return fill_report(load_contract(CONTRACT), load_values_flat(VALUES))


def test_opening_block_is_fixed_report_opening_text():
    """about.opening 是固定报告开篇，不进入 LLM 生成。"""
    tmpl = _template(SSE_PACKAGE)
    block = tmpl.find_block("about.opening")
    text = "".join(inline.text or "" for inline in block.content or [] if inline.kind == "text")

    assert block.blockType == "fixed"
    assert block.generation is None
    assert "可持续发展理念" in text
    assert "利益相关方" in text


def test_topic_generative_block_has_no_opening_posture():
    """议题 generative 块（climate.gov_structure）不含开篇式口径——开篇口径不外溢。"""
    tmpl = _template(SSE_PACKAGE)
    inst = _inst()
    system, _ = render_prompt(build_model_context(tmpl.find_block("climate.gov_structure"), tmpl, inst), n=1)
    assert "开篇式" not in system and "双碳" not in system
