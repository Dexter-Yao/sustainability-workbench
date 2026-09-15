# ABOUTME: 分工 map（topic_scope）实例/模板来源测试——块集按实例，does 取模板稳定 brief。
# ABOUTME: 防取到已生成正文当 does；正文不再按 materiality 裁支柱。
from pathlib import Path

from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import Inline
from sustainability_desk.export.docx_renderer import load_values_flat
from sustainability_desk.llm.generate import _template
from sustainability_desk.llm.prompts import build_model_context
from sustainability_desk.planner import assemble_report, load_topic_intake
from assessment_fixtures import complete_assessment
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir
VALUES = SSE_PACKAGE.sample_values_path


def _assess(materiality):
    return complete_assessment(
        load_contract(CONTRACT),
        materialities={"climate_change": materiality},
    )


def _instance(materiality):
    base = assemble_report(load_contract(CONTRACT), load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE),
                           assessment=_assess(materiality),
                           intake_items=load_topic_intake(SSE_PACKAGE)).report
    return fill_report(base, load_values_flat(VALUES))


def test_impact_branch_has_only_direct_concise_disclosure():
    """impact 议题只装配 H2 直属摘要，不把四要素职责注入分工 map。"""
    inst = _instance("impact")
    block = inst.find_block("climate_change.concise_summary")
    ctx = build_model_context(block, _template(SSE_PACKAGE), inst)
    assert ctx.topic_scope == ""
    block_ids = {item.id for item in inst.iter_blocks()}
    assert all(
        candidate not in block_ids
        for candidate in (
            "climate.gov_structure",
            "climate.strategy_physical_risk",
            "climate.iro_reduction_practice",
            "climate_change.metrics_narrative_body",
        )
    )


def test_concise_disclosure_parses_own_section_facts_and_metric_catalog():
    """report_section 同时继承本 H2 用户事实与目录指标，不读取其他 H2 证据。"""

    inst = _instance("impact")
    climate = next(item for item in inst.intakeItems if item.contentScopeId == "climate_change")
    other = next(
        item
        for item in inst.intakeItems
        if item.contentScopeId == "circular_economy_promotion"
    )
    climate.supplement = "CLIMATE_SCOPE_SENTINEL"
    other.supplement = "OTHER_SCOPE_SENTINEL"

    block = inst.find_block("climate_change.concise_summary")
    ctx = build_model_context(block, _template(SSE_PACKAGE), inst)

    # 补充说明分离到 note；范围隔离断言覆盖 text 与 note 两个承载面。
    fact_text = "\n".join(f"{item.text} {item.note or ''}" for item in ctx.evidence.intake_facts)
    assert "CLIMATE_SCOPE_SENTINEL" in fact_text
    assert "OTHER_SCOPE_SENTINEL" not in fact_text
    assert ctx.evidence.substantive_input_present is True
    assert [metric.metric_name for metric in ctx.evidence.metric_evidence] == [
        "范围一：温室气体排放总量",
        "范围二：温室气体排放总量",
        "温室气体排放总量（范围一+范围二）",
    ]
    assert all(metric.value is None for metric in ctx.evidence.metric_evidence)


def test_topic_scope_does_from_template_not_instance_content():
    """共享证据的相邻任务取模板声明；即便实例正文被覆盖也不读取实例内容。"""
    inst = _instance("dual")
    # 模拟兄弟块已生成：覆盖 iro_reduction_practice 的 content 为一段"伪正文"
    sentinel = "这是一段已经生成并写回的伪正文不应出现在分工map"

    def _walk(secs):
        for s in secs:
            for b in s.blocks:
                if b.id == "climate.strategy_transition_risk":
                    b.content = [Inline(kind="text", text=sentinel)]
            if s.children:
                _walk(s.children)
    _walk(inst.sections)

    block = _template(SSE_PACKAGE).find_block("climate.strategy_physical_risk")
    ctx = build_model_context(block, _template(SSE_PACKAGE), inst)
    assert sentinel not in ctx.topic_scope, "分工 map 取到了实例已生成正文（应取模板 brief）"
    assert "气候相关转型风险及应对措施" in ctx.topic_scope
    assert block.generation.task.focus not in ctx.topic_scope
