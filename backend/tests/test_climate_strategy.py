# ABOUTME: 气候战略与风险机遇支柱测试——战略方向、3 张 IRO 表、两路径口径与导出保真。
from pathlib import Path

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import Report
from sustainability_desk.contract.table_ops import resolve_preset_row_seeds
from sustainability_desk.planner import assemble_report, load_topic_intake
from assessment_fixtures import complete_assessment
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir
CONTRACT = SSE_PACKAGE.report_contract_path
TABLE_PREFIX = {
    "climate.strategy_physical_risk": "phys",
    "climate.strategy_transition_risk": "trans",
    "climate.strategy_opportunity": "opp",
}
TABLE_IDS = list(TABLE_PREFIX)
SEVEN_SUFFIXES = ["type", "name", "impact", "value_chain", "time_horizon", "financial", "response"]


def _assess(m="dual"):
    return complete_assessment(
        load_contract(CONTRACT),
        materialities={"climate_change": m},
    )


def _strategy(templates):
    return next(
        child
        for child in templates["climate_change"].children or []
        if child.key == "climate.strategy"
    )


def test_strategy_subsection_present_after_gov():
    """climate.strategy 在 climate.gov 之后挂入 climate_change。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    climate = templates["climate_change"]
    keys = [c.key for c in (climate.children or [])]
    assert keys.index("climate.gov") < keys.index("climate.strategy")


def test_three_tables_are_seven_col_isomorphic():
    """战略节下的 3 表均为 7 列 preset_catalog 表（按模板归入“二、战略”）。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    tables = {block.id: block for block in _strategy(templates).blocks if block.type == "table"}
    assert set(TABLE_IDS) <= set(tables)
    for tid in TABLE_IDS:
        cols = [c.key for c in tables[tid].table.colDefs]
        assert cols == [f"{TABLE_PREFIX[tid]}_{s}" for s in SEVEN_SUFFIXES]
        assert tables[tid].blockType == "generative" and tables[tid].source == "ai"
        assert tables[tid].table.rowSource == "user"
        # preset_catalog：类型/名称为预设锚点，按 fixedRowSeeds 声明目录、category 为并发分组键。
        gen = tables[tid].generation
        assert gen.rowMode == "preset_catalog"
        seeds = gen.fixedRowSeeds or []
        assert seeds and all(s.category and s.theme for s in seeds)


def test_strategy_holds_direction_intro_and_three_tables():
    """按官方拆分指南，风险机遇识别说明与三张表归入战略节；IRO 仅保留条件化 H4。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    strategy = next(c for c in templates["climate_change"].children if c.key == "climate.strategy")
    strategy_blocks = {block.id: block for block in strategy.blocks}
    assert set(strategy_blocks) == {
        "climate.strategy_direction",
        "climate.strategy_identification",
        "climate.strategy_physical_risk",
        "climate.strategy_transition_risk",
        "climate.strategy_opportunity",
    }
    assert [b.id for b in strategy.blocks][0] == "climate.strategy_direction"
    assert strategy_blocks["climate.strategy_direction"].blockType == "generative"
    assert set(
        strategy_blocks["climate.strategy_direction"].generation.inputs.evidence.intakeItems
    ) == {
        "climate.q_climate_target_status",
        "climate.q_strategy_content",
    }
    direction = strategy_blocks["climate.strategy_direction"].generation
    assert direction.standardDisclosureRequirementKeys == [
        "climate.strategy.strategy_decision"
    ]
    iro = next(c for c in templates["climate_change"].children if c.key == "climate.iro")
    assert iro.blocks == []
    assert [c.key for c in iro.children or []] == [
        "climate.iro.management_framework",
        "climate.iro.reduction_practice",
        "climate.iro.training",
    ]


def test_tables_have_gen_hints_and_select_options():
    """关键列 cellType/options/genHint 正确（impact/response=ai_text、value_chain/financial=multi_select 4 维度、type/name 锚点）+ 顶部大标题 + 脚注。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    phys = next(b for b in _strategy(templates).blocks if b.id == "climate.strategy_physical_risk")
    by_key = {c.key: c for c in phys.table.colDefs}
    # 锚点列：type/name 为预设 text，不带生成指引。
    assert by_key["phys_type"].cellType == "text" and by_key["phys_name"].cellType == "text"
    # AI 列：impact/response 为 ai_text；impact 保「统一使用公司」口径以启用主体校验。
    assert by_key["phys_impact"].cellType == "ai_text" and "统一使用“公司”" in by_key["phys_impact"].genHint
    assert "行业和业务类型相关性" in by_key["phys_impact"].genHint
    assert "贴合本公司真实经营场景" not in by_key["phys_impact"].genHint
    assert by_key["phys_response"].cellType == "ai_text" and by_key["phys_response"].genHint
    # 受限选择列：value_chain/time_horizon/financial 为 multi_select（不再强制默认全覆盖）。
    assert by_key["phys_value_chain"].cellType == "multi_select" and by_key["phys_value_chain"].options
    assert "默认覆盖" not in (by_key["phys_value_chain"].genHint or "")
    assert by_key["phys_financial"].cellType == "multi_select" and len(by_key["phys_financial"].options) == 4
    # 顶部跨 7 列大标题 headerRow（物理风险）
    head = phys.table.children[0]
    assert head.headerRow and head.children[0].colSpan == 7 and head.children[0].value == "物理风险"
    # 脚注（财务影响假设 + 影响时限定义）入 table.disclaimer。
    assert phys.table.disclaimer and "影响时限" in phys.table.disclaimer


def test_climate_strategy_table_catalog_matches_intake_groups():
    """气候战略三表目录与用户可选风险/机遇目录保持一致。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    tables = {block.id: block for block in _strategy(templates).blocks if block.type == "table"}
    items = {item.key: item for item in load_topic_intake(SSE_PACKAGE)}

    risk_item = items["climate.q_climate_risk_choices"]
    groups = {group.key: group for group in risk_item.optionGroups or []}
    assert risk_item.collectionPriority == "core"
    assert groups["physical_risk"].minSelections == 1
    assert groups["transition_risk"].minSelections == 1
    assert "暂未识别明显气候相关风险" not in risk_item.options
    assert "不确定" not in risk_item.options
    assert [seed.theme for seed in tables["climate.strategy_physical_risk"].generation.fixedRowSeeds] == groups["physical_risk"].options
    assert [seed.theme for seed in tables["climate.strategy_transition_risk"].generation.fixedRowSeeds] == groups["transition_risk"].options

    opportunity_item = items["climate.q_climate_opportunity_choices"]
    assert opportunity_item.collectionPriority == "core"
    assert "暂未识别明显气候相关机遇" not in opportunity_item.options
    assert "不确定" not in opportunity_item.options
    assert [seed.theme for seed in tables["climate.strategy_opportunity"].generation.fixedRowSeeds] == opportunity_item.options


def test_climate_strategy_tables_project_only_structured_user_selections() -> None:
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    climate = templates["climate_change"]
    intake = load_topic_intake(SSE_PACKAGE)
    answers = {
        "climate.q_climate_risk_choices": ["极端高温", "消费者偏好转变风险"],
        "climate.q_climate_opportunity_choices": ["能源绿色转型"],
    }
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="气候选择投影",
        intakeItems=[
            item.model_copy(update={"answer": answers.get(item.key)})
            for item in intake
            if item.contentScopeId == "climate_change"
        ],
        sections=[climate],
    )

    expected = {
        "climate.strategy_physical_risk": ["极端高温"],
        "climate.strategy_transition_risk": ["消费者偏好转变风险"],
        "climate.strategy_opportunity": ["能源绿色转型"],
    }
    for block_id, themes in expected.items():
        block = report.find_block(block_id)
        assert [seed.theme for seed in resolve_preset_row_seeds(block, report)] == themes


def test_climate_strategy_tables_keep_all_rows_when_user_has_not_selected() -> None:
    """未作答风险/机遇选择时三张表仍完整成行——缺用户输入是正常生成分支。

    气候风险、转型风险与机遇表是准则核心披露，不能因用户没勾选就整表消失
    （回归：战略支柱三表全空）。
    行内容由 noFactGuidance 按行业与业务类型给出方向性表述，不伪造企业事实。
    """
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    intake = load_topic_intake(SSE_PACKAGE)
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="未作答气候选择",
        intakeItems=[
            item.model_copy(update={"answer": None})
            for item in intake
            if item.contentScopeId == "climate_change"
        ],
        sections=[templates["climate_change"]],
    )

    for block_id in (
        "climate.strategy_physical_risk",
        "climate.strategy_transition_risk",
        "climate.strategy_opportunity",
    ):
        block = report.find_block(block_id)
        seeds = resolve_preset_row_seeds(block, report)
        assert seeds, f"{block_id} 未作答时不得整表隐藏"
        assert len(seeds) == len(block.generation.fixedRowSeeds)


def test_strategy_response_columns_use_readable_separator_hint():
    """三张表的应对措施列要求短句和分隔符，避免挤成整段。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    expected_guardrails = {
        "climate.strategy_physical_risk": ("phys_response", ("保险配置", "资产转移规划", "地势评估")),
        "climate.strategy_transition_risk": ("trans_response", ("产品碳足迹管理", "绿色供应链要求")),
        "climate.strategy_opportunity": ("opp_response", ("绿色信贷", "能源管理系统", "绿色供应链准入")),
    }
    for table_id, (response_key, forbidden_terms) in expected_guardrails.items():
        table = next(b for b in _strategy(templates).blocks if b.id == table_id)
        col = next(c for c in table.table.colDefs if c.key == response_key)
        assert "中文分号" in (col.genHint or "")
        assert "不写项目符号" in (col.genHint or "")
        assert "方向性表达" in (col.genHint or "")
        assert any(word in (col.genHint or "") for word in ("不得写预案", "不得写核算体系", "不得写客户标准"))
        for term in forbidden_terms:
            assert term in (col.genHint or "")


def test_strategy_impact_columns_block_low_evidence_specific_objects():
    """潜在影响列不得把低证据资料扩写为场地、客户标准、绿色金融或系统对象。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    checks = {
        "climate.strategy_physical_risk": ("phys_impact", ("低洼", "场地暴露")),
        "climate.strategy_transition_risk": ("trans_impact", ("客户低碳标准", "产品碳足迹表现", "绿色供应链准入")),
        "climate.strategy_opportunity": ("opp_impact", ("绿色信贷", "能源管理系统", "产品碳足迹")),
    }
    for table_id, (impact_key, terms) in checks.items():
        table = next(b for b in _strategy(templates).blocks if b.id == table_id)
        col = next(c for c in table.table.colDefs if c.key == impact_key)
        for term in terms:
            assert term in (col.genHint or "")


def test_opportunity_reference_impacts_avoid_tool_level_examples():
    """机遇表固定目录参考口径只给方向，不默认绿色债券、碳交易或保险工具。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    table = next(b for b in _strategy(templates).blocks if b.id == "climate.strategy_opportunity")
    reference_text = "\n".join(seed.referenceImpact or "" for seed in table.generation.fixedRowSeeds)

    assert "绿色债券" not in reference_text
    assert "碳交易" not in reference_text
    assert "保险风险解决方案" not in reference_text
    assert "表述保持方向性" in reference_text


def test_metrics_methodology_no_data_posture_blocks_mature_process_claims():
    """温室气体指标无数据时只能写声明口径，不得写已推进核算或数据流程。"""
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    climate = templates["climate_change"]
    metrics = next(c for c in climate.children if c.key == "climate_change.metrics")
    block = next(
        b
        for b in metrics.blocks
        if b.id == "climate_change.metrics_narrative_body"
    )
    posture_text = "\n".join(block.generation.simplifiedWritingGuidance or [])

    assert posture_text == ""
    assert block.generation.inputs.evidence.quantitativeMetrics


def test_strategy_assembled_into_environmental_module():
    """climate_change 实质 → climate.strategy 挂入环境可持续模块。"""
    intake = load_topic_intake(SSE_PACKAGE)
    res = assemble_report(
        load_contract(CONTRACT),
        load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE),
        assessment=_assess(),
        intake_items=intake,
    )
    env = next(s for s in res.report.sections if s.key == "environmental_sustainability")
    climate = next(c for c in (env.children or []) if c.key == "climate_change")
    assert any(c.key == "climate.strategy" for c in (climate.children or []))


def test_industry_field_and_strategy_intake_present():
    """industry 字段由行业门类/大类派生；战略输入来自 topic_intake。"""
    report = load_contract(CONTRACT)
    assert "industry" in report.fields and report.fields["industry"].source == "derived"
    intake_keys = {item.key for item in load_topic_intake(SSE_PACKAGE)}
    assert {
        "climate.q_climate_risk_choices",
        "climate.q_climate_opportunity_choices",
        "climate.q_climate_target_status",
        "climate.q_training_activities",
    } <= intake_keys


def test_by_table_two_paths_switch():
    """物理风险表：填了清单 → 有内容口径；未填 → 行业路径 + industry 进报告主体。"""
    from sustainability_desk.contract.fill import fill_report
    from sustainability_desk.export.docx_renderer import load_values_flat
    from sustainability_desk.llm.generate import _template
    from sustainability_desk.llm.prompts import build_model_context
    tmpl = _template(SSE_PACKAGE)
    block = tmpl.find_block("climate.strategy_physical_risk")
    vals = load_values_flat(SSE_PACKAGE.sample_values_path)
    intake = load_topic_intake(SSE_PACKAGE)
    base = assemble_report(load_contract(CONTRACT), load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE), assessment=_assess(), intake_items=intake).report

    inst_have = fill_report(base, vals)
    ctx_have = build_model_context(block, tmpl, inst_have)
    assert ctx_have.evidence.intake_facts and ctx_have.section_task

    inst_none = fill_report(base, {k: vals[k] for k in vals if k != "intake"})
    ctx_none = build_model_context(block, tmpl, inst_none)
    assert not ctx_none.evidence.intake_facts
    assert any(w in ctx_none.section_task for w in ("行业", "标杆", "TCFD"))
    assert any("行业" in g for g in ctx_none.report_subject)  # industry 进报告主体


def test_iro_renders_tables_without_callout_leak(base_template, out_dir):
    """IRO 支柱导出：3 表渲染（多选顿号）；准则 callout 不入正文。"""
    from docx import Document
    from sustainability_desk.contract.fill import fill_report
    from sustainability_desk.export.docx_renderer import load_values_flat, render_docx

    intake = load_topic_intake(SSE_PACKAGE)
    assembled = assemble_report(
        load_contract(CONTRACT),
        load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE),
        assessment=_assess(),
        intake_items=intake,
    ).report
    report = fill_report(assembled, load_values_flat(SSE_PACKAGE.sample_values_path))
    out = render_docx(report, base_template, out_dir / "iro_check.docx")
    doc = Document(str(out))
    heads = {p.text: p.style.name for p in doc.paragraphs if p.style.name.startswith("Heading")}
    assert heads.get("（三）影响、风险与机遇管理") == "Heading 3"
    full = "\n".join(p.text for p in doc.paragraphs)
    assert "ISSB《国际财务报告可持续披露准则第2号" not in full  # 战略准则 callout 不入正文
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert any("成本上升" in c for c in cells)  # 多选财务影响单元格已顿号渲染入表
