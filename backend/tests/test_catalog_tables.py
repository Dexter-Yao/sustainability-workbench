# ABOUTME: 目录表契约测试——preset_catalog（固定锚点）与 adaptive_catalog（前置据业务+referenceCatalog 生成适用锚点）两形态的结构合同。
# ABOUTME: 守护锚点/AI 列拆分（首个 ai_text 分界）、adaptive 三表用 referenceCatalog 且类型列为 AI 生成（非固定 single_select）。

from sustainability_desk.llm.table_gen import _anchor_ai_split
from knowledge_package_fixtures import SSE_PACKAGE
from knowledge_package_fixtures import sse_model_context
from sustainability_desk.planner import load_topic_templates_from

TOPIC_DIR = SSE_PACKAGE.topic_sections_dir

ADAPTIVE_TABLES = {
    "energy_management": "energy_management.strategy_risk_opportunity_table",
    "pollutant_emissions_management": "pollutant_emissions_management.strategy_risk_opportunity_table",
    "anti_bribery_anti_corruption": "anti_bribery_anti_corruption.strategy_risk_response_table",
}


def _find(section, block_id):
    for blk in section.blocks:
        if blk.id == block_id:
            return blk
    for child in section.children or []:
        got = _find(child, block_id)
        if got:
            return got
    return None


def test_climate_three_tables_are_preset_catalog():
    """气候三表为 preset_catalog：固定 fixedRowSeeds、无 referenceCatalog。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    strategy = next(c for c in templates["climate_change"].children if c.key == "climate.strategy")
    tables = [b for b in strategy.blocks if b.type == "table"]
    assert len(tables) == 3
    for blk in tables:
        assert blk.generation.rowMode == "preset_catalog"
        assert blk.generation.fixedRowSeeds and not blk.generation.referenceCatalog
        assert blk.generation.presetRowSelection is not None
        assert blk.generation.presetRowSelection.selectionMode == "selected_only"
        # 用户勾选后按所选过滤；未作答时仍完整成行——准则核心披露不因缺用户输入而消失。
        assert blk.generation.presetRowSelection.unansweredBehavior == "show_all_rows"


def test_adaptive_tables_use_reference_catalog_and_ai_type():
    """能源/污染物/反腐三表为 adaptive_catalog：用 referenceCatalog、有 rowCount 上下限、类型列为 AI 生成（text 非固定 single_select）。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    for topic_id, block_id in ADAPTIVE_TABLES.items():
        blk = _find(templates[topic_id], block_id)
        assert blk is not None, block_id
        gen = blk.generation
        assert gen.rowMode == "adaptive_catalog"
        assert not gen.fixedRowSeeds
        assert gen.referenceCatalog and all(r.category and r.name for r in gen.referenceCatalog)
        assert gen.rowCount and gen.rowCount[1] >= gen.rowCount[0] >= 1
        anchors, ai_cols = _anchor_ai_split(blk.table.colDefs)
        # 锚点非空、AI 列非空、末列为 ai_text；类型/名称锚点由前置生成，故不得为固定 single_select 选项列。
        assert anchors and ai_cols
        assert ai_cols[-1].cellType == "ai_text"
        identity = anchors[-1]  # 条目标识锚点（类型/名称）
        assert identity.cellType == "text", f"{block_id} 标识锚点应为 AI 生成 text，实为 {identity.cellType}"


def test_opportunity_coverage_is_required_only_where_catalog_offers_opportunities():
    """清单含机遇类条目的表须能放下「至少一条机遇」；只有风险的表不受该约束。

    否则会出现污染物表题承诺「风险与机遇」、实际两行全是风险的情况。
    覆盖要求由清单构成派生（见 prompts.render_adaptive_propose_prompt），不硬编码类别名；
    行数下限须容得下「风险 + 至少一条机遇」，否则下限与覆盖要求互相打架。
    """

    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    checked = 0
    for topic_key, block_id in ADAPTIVE_TABLES.items():
        block = _find(templates[topic_key], block_id)
        assert block is not None, block_id
        catalog = block.generation.referenceCatalog or []
        assert catalog, block_id
        has_opportunity = any("机遇" in (ref.category or "") for ref in catalog)
        row_min = block.generation.rowCount[0]
        if has_opportunity:
            # 至少 2 风险 + 1 机遇：下限低于 3 时模型可以只出风险而不违反行数约束。
            assert row_min >= 3, f"{block_id} 含机遇条目但行数下限为 {row_min}"
            checked += 1
        else:
            assert not any("机遇" in (ref.name or "") for ref in catalog), block_id
    assert checked >= 2, "应至少有两张风险机遇表参与该断言"


def test_adaptive_prompt_states_opportunity_coverage_from_catalog():
    """提示词的机遇覆盖句由清单派生：有机遇条目才出现，没有则整句不出现。"""

    from sustainability_desk.llm.prompts import render_adaptive_propose_prompt

    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)

    def propose_system(topic_key: str) -> str:
        block = _find(templates[topic_key], ADAPTIVE_TABLES[topic_key])
        anchors, _ = _anchor_ai_split(block.table.colDefs)
        system, _ = render_adaptive_propose_prompt(
            sse_model_context(),
            anchors,
            block.generation.referenceCatalog or [],
            count_min=block.generation.rowCount[0],
            count_max=block.generation.rowCount[1],
            kind_label="风险与机遇",
        )
        return system

    with_opportunity = propose_system("pollutant_emissions_management")
    assert "所选条目须至少包含其中一条" in with_opportunity

    risk_only = propose_system("anti_bribery_anti_corruption")
    assert "所选条目须至少包含其中一条" not in risk_only
