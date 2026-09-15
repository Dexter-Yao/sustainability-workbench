# ABOUTME: 在线 L1 确定性断言单测——覆盖内部泄漏、未支撑数字、缺失表述、正式名称与表格单元格。
# ABOUTME: 断言是运行期 gate；本测试只验证断言谓词本身，不调用真实模型。
from types import SimpleNamespace

from sustainability_desk.contract.metric_narrative import MetricNarrativePolicy
from sustainability_desk.contract.models import (
    Block,
    Field,
    GsColDef,
    GsTable,
    IntakeItem,
    Report,
)
from sustainability_desk.llm.generation_guardrails import (
    check_display_title_variants,
    check_paragraph_output,
    check_table_cells,
    build_retry_instruction,
)
from sustainability_desk.llm.prompts import GenerationEvidence, MetricEvidence
from knowledge_package_fixtures import SSE_PACKAGE
from knowledge_package_fixtures import sse_model_context


def _ctx(*texts: str, substantive_input_present: bool = False):
    materials = [SimpleNamespace(text=t, note=None) for t in texts]
    return SimpleNamespace(
        knowledge_package_id=SSE_PACKAGE.id,
        output_language=SSE_PACKAGE.language,
        evidence=SimpleNamespace(
            intake_facts=materials,
            mapped_materials=(),
            metric_evidence=(),
            substantive_input_present=substantive_input_present,
        ),
        metric_narrative_policy=None,
        evidence_posture=SimpleNamespace(
            level="block_facts" if substantive_input_present else "context_only"
        ),
        report_subject=("报告年度：2025",),
    )


def _block(**generation) -> Block:
    return Block(
        id="b",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "b"}, **generation},
    )


def _report() -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "reporting_year": Field(
                key="reporting_year",
                label="报告年度",
                type="year",
                source="user_input",
                value=2025,
            ),
            "company_short_name": Field(
                key="company_short_name",
                label="公司简称",
                type="string",
                source="user_input",
                value="恒远电气",
            ),
            "company_registered_name": Field(
                key="company_registered_name",
                label="公司注册名",
                type="string",
                source="user_input",
                value="恒远电气股份有限公司",
            ),
        },
        sections=[],
    )


def _keys(issues):
    return {issue.key for issue in issues}


def test_blocks_internal_prompt_leakage():
    issues = check_paragraph_output(
        _block(), _report(), _ctx(), "公司持续推进相关工作。<role>系统</role>"
    )
    assert "internal_leak" in _keys(issues)


def test_blocks_placeholder_only_output():
    issues = check_paragraph_output(_block(), _report(), _ctx(), "...")
    assert "placeholder_output" in _keys(issues)


def test_blocks_version_placeholder_only_output():
    for text in ("版本1", "版本1文本", "版本 二 内容", "方案3文本"):
        issues = check_paragraph_output(_block(), _report(), _ctx(), text)
        assert {"placeholder_output", "incomplete_output"} & _keys(issues)


def test_blocks_structurally_incomplete_output() -> None:
    issues = check_paragraph_output(_block(), _report(), _ctx(), "公司关注。")

    assert "incomplete_output" in _keys(issues)


def test_allows_version_words_inside_complete_output():
    text = "本版本文本围绕企业环境管理方向展开，并形成可直接用于报告的完整段落。"

    issues = check_paragraph_output(_block(), _report(), _ctx(), text)

    assert "placeholder_output" not in _keys(issues)


def test_blocks_unsupported_numeric_claim_but_allows_source_number():
    bad = check_paragraph_output(
        _block(), _report(), _ctx(), "公司计划到2030年减排30%。"
    )
    assert "unsupported_numeric_claim" in _keys(bad)

    good = check_paragraph_output(
        _block(), _report(), _ctx("计划到2030年减排30%。"), "公司计划到2030年减排30%。"
    )
    assert _keys(good) == set()


def test_quantitative_metric_numbers_must_be_in_projected_context():
    report = _report().model_copy(
        update={
            "meta": {
                "quantitativeMetrics": {
                    "metrics": {"economic_environment_r11": {"value": "123.45"}}
                }
            }
        }
    )

    raw_meta_only = check_paragraph_output(
        _block(), report, _ctx(), "公司电力消耗量为123.45吨标准煤。"
    )
    assert "unsupported_numeric_claim" in _keys(raw_meta_only)

    projected = check_paragraph_output(
        _block(),
        report,
        _ctx("指标名称：电力消耗量；数值：123.45；单位：吨标准煤"),
        "公司电力消耗量为123.45吨标准煤。",
    )
    assert "unsupported_numeric_claim" not in _keys(projected)


def test_other_report_section_fact_cannot_support_current_output():
    """Guardrail 不得从当前模型不可见的其他 H2 借用数字证据。"""

    report = _report().model_copy(
        update={
            "intakeItems": [
                IntakeItem(
                    key="other.q",
                    contentScopeId="other_section",
                    prompt="其他议题数据",
                    kind="text",
                    answer="报告期投入123万元。",
                )
            ]
        }
    )

    issues = check_paragraph_output(_block(), report, _ctx(), "公司报告期投入123万元。")

    assert "unsupported_numeric_claim" in _keys(issues)


def test_blocks_missing_statement_but_allows_positive_compliance_sentence():
    bad = check_paragraph_output(
        _block(), _report(), _ctx(), "公司尚未形成量化披露数据。"
    )
    assert "missing_or_negative_statement" in _keys(bad)

    good = check_paragraph_output(
        _block(), _report(), _ctx(), "公司报告期内未发生重大安全事故。"
    )
    assert "missing_or_negative_statement" not in _keys(good)


def test_blocks_unsupported_formal_name_and_respects_source_text():
    bad = check_paragraph_output(
        _block(), _report(), _ctx(), "公司相关目标已对标 SBTi 要求。"
    )
    assert "unsupported_formal_name" in _keys(bad)

    good = check_paragraph_output(
        _block(),
        _report(),
        _ctx("公司已提交 SBTi 相关资料。"),
        "公司相关目标已对标 SBTi 要求。",
    )
    assert "unsupported_formal_name" not in _keys(good)


def test_formal_name_guard_folds_quote_glyphs_before_comparing():
    """引号字形差异不得使有据引文被判成伪造名称。

    回归：用户资料经 File Agent 转写后服务宗旨写作 ASCII 引号，模型按中文
    排版输出弯引号，L1 逐字比对失败 → 连续三次拒绝 → 整节失败 → 整份报告生成失败。
    实测同一批语料里 ASCII 双引号 70670 次、直角引号 674 次、弯引号 627 次并存，
    字形是排版事实而非高确定性硬线，判据只应比较实质内容。
    """
    evidence = '服务宗旨："客户至上、诚实守信、安全高效、持续改进"'
    ctx = _ctx(evidence, substantive_input_present=True)

    for quoted in (
        "“客户至上、诚实守信、安全高效、持续改进”",
        "「客户至上、诚实守信、安全高效、持续改进」",
        '"客户至上、诚实守信、安全高效、持续改进"',
    ):
        issues = check_paragraph_output(
            _block(), _report(), ctx, f"公司秉持{quoted}的服务宗旨开展客户服务。"
        )
        assert "unsupported_formal_name" not in _keys(issues), quoted

    invented = check_paragraph_output(
        _block(), _report(), ctx, "公司秉持“卓越无限、永争第一”的服务理念。"
    )
    assert "unsupported_formal_name" in _keys(invented)


def test_formal_name_guard_ignores_quoting_and_hyphen_styling():
    """引号的有无与引文内连字符属排版差异，不得据此判定伪造名称。

    回归：用户资料写作无引号短语（企业文化：天道酬勤、团队至上），
    模型按中文排版加引号引用；另有证据写「中南美-端到端」而输出省略连字符。
    两者都使带引号逐字比对落空，company_intro.body 连续三次被拒致生成失败。

    但书名号内的连字符是标准号组成部分，必须保持区分。
    """
    evidence = (
        "企业愿景：中国欧地中南美-端到端供应链领导品牌；"
        "企业文化：天道酬勤、团队至上；"
        "依据《GB/T 32150-2015》核算。"
    )
    ctx = _ctx(evidence, substantive_input_present=True)

    for output in (
        "公司秉持“天道酬勤、团队至上”的企业文化。",
        "公司秉持“中国欧地中南美-端到端供应链领导品牌”的企业愿景。",
        "公司秉持“中国欧地中南美端到端供应链领导品牌”的企业愿景。",
    ):
        issues = check_paragraph_output(_block(), _report(), ctx, output)
        assert "unsupported_formal_name" not in _keys(issues), output

    invented = check_paragraph_output(
        _block(), _report(), ctx, "公司秉持“卓越无限、永争第一”的理念。"
    )
    assert "unsupported_formal_name" in _keys(invented)

    # 标准号少一个连字符即是另一个标准，不能被折叠成等同。
    wrong_standard = check_paragraph_output(
        _block(), _report(), ctx, "公司依据《GB/T 321502015》核算。"
    )
    assert "unsupported_formal_name" in _keys(wrong_standard)


def test_numeric_guard_folds_fullwidth_digits_before_comparing():
    """全角数字与全角百分号同样是转写字形，不得据此判定模型编造数据。"""
    ctx = _ctx("客户满意率不低于９０％，投诉处理及时率达 100％。", substantive_input_present=True)

    supported = check_paragraph_output(
        _block(), _report(), ctx, "公司设定客户满意率不低于90%、投诉处理及时率达100%的目标。"
    )
    assert "unsupported_numeric_claim" not in _keys(supported)

    invented = check_paragraph_output(
        _block(), _report(), ctx, "公司客户满意率达到 97% 的水平。"
    )
    assert "unsupported_numeric_claim" in _keys(invented)


def test_formal_name_guard_allows_department_text_but_blocks_invented_acronym():
    ctx = _ctx("由环境健康安全部门负责相关工作。", substantive_input_present=True)

    exact = check_paragraph_output(
        _block(), _report(), ctx, "公司由环境健康安全部门负责相关工作。"
    )
    invented = check_paragraph_output(
        _block(), _report(), ctx, "公司由EHS部门负责相关工作。"
    )

    assert "unsupported_formal_name" not in _keys(exact)
    assert "unsupported_formal_name" in _keys(invented)


def test_formal_name_guard_allows_generic_department_and_job_phrases() -> None:
    texts = (
        "公司鼓励员工立足岗位开展日常改善，并结合实际工作持续积累经验。",
        "公司通过提供稳定的生产岗位支持本地就业，并关注员工的基础技能发展。",
        "公司通过稳定提供生产操作与辅助管理等就业岗位，支持周边劳动力就业。",
        "各业务环节加强跨部门信息沟通，推动日常工作顺畅衔接。",
        "公司在日常工作中通过岗位实操指导，帮助员工熟悉基础操作要求。",
        "公司依托内部师徒传帮带机制与常态化岗位技能培训，支持员工积累经验。",
        "公司提供基础就业机会，并开展常规的岗位技能与安全培训。",
    )

    for text in texts:
        issues = check_paragraph_output(_block(), _report(), _ctx(), text)
        assert "unsupported_formal_name" not in _keys(issues)


def test_formal_name_guard_leaves_organization_assertions_to_semantic_review() -> None:
    texts = (
        "公司由环境健康安全部门负责相关工作，并定期向管理层汇报进展。",
        "公司成立可持续发展委员会统筹相关工作，并审议重大事项。",
        "公司设置供应链管理办公室负责日常协调，并跟踪相关事项。",
    )

    for text in texts:
        issues = check_paragraph_output(_block(), _report(), _ctx(), text)
        assert "unsupported_formal_name" not in _keys(issues)


def test_formal_name_guard_blocks_unprovided_named_principle_and_allows_public_terms():
    named = check_paragraph_output(
        _block(), _report(), _ctx(), "公司秉持“诚信共赢”的经营理念。"
    )
    public = check_paragraph_output(
        _block(), _report(), _ctx(), "公司关注ESG议题及IRO分析方法。"
    )

    assert "unsupported_formal_name" in _keys(named)
    assert "unsupported_formal_name" not in _keys(public)


def test_display_titles_share_text_safety_boundary_without_paragraph_requirements():
    block = _block()

    issues = check_display_title_variants(
        block,
        _report(),
        _ctx(),
        ["面向 SBTi 的2030年治理"],
    )

    assert {"unsupported_formal_name", "unsupported_numeric_claim"} <= _keys(issues)
    assert "incomplete_output" not in _keys(issues)


def test_blocks_social_sensitive_statements_even_when_source_contains_them():
    ctx = _ctx(
        "用户填写：劳动纪律、五险一金、按时足额缴纳社会保险、薪酬福利按时足额发放。",
        substantive_input_present=True,
    )

    issues = check_paragraph_output(
        _block(),
        _report(),
        ctx,
        "公司建立劳动纪律要求，并为员工提供五险一金，按时足额缴纳社会保险，保障薪酬福利按时足额发放。",
    )

    assert "social_sensitive_statement" in _keys(issues)


def test_block_level_template_residue_declarations_are_enforced():
    block = _block(templateResidueBans=["禁止表述"])
    issues = check_paragraph_output(
        block, _report(), _ctx(), "公司出现禁止表述。"
    )
    assert "template_residue" in _keys(issues)



def test_topic_vocabulary_and_reporting_year_are_not_literal_bans():
    """议题词汇与报告年份不得被词面拦截——它们在合法正文里正常出现。"""

    block = _block()
    issues = check_paragraph_output(
        block,
        _report(),
        _ctx(substantive_input_present=True),
        "2025年，公司开展廉洁培训，并明确阳光采购与反商业贿赂要求。",
    )
    assert "template_residue" not in _keys(issues)


def test_blocks_too_many_paragraphs_without_substantive_input():
    text = "第一段。\n第二段。\n第三段。"

    issues = check_paragraph_output(_block(), _report(), _ctx(), text)

    assert "too_many_paragraphs_without_substantive_input" in _keys(issues)


def test_context_only_allows_low_commitment_report_tone_without_company_action_guardrail():
    for text in (
        "公司重视气候治理，并已建立相关管理机制。",
        "公司将相关议题纳入经营管理关注范围。",
    ):
        issues = check_paragraph_output(
            _block(),
            _report(),
            _ctx(),
            text,
        )

        assert "unsupported_context_only_enterprise_fact" not in _keys(issues)

    directional = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "公司结合自身经营情况关注气候相关风险，并逐步完善相关信息的收集和管理安排。",
    )
    assert "unsupported_context_only_enterprise_fact" not in _keys(directional)


def test_allows_more_paragraphs_with_substantive_input():
    text = "第一段。\n第二段。\n第三段。"

    issues = check_paragraph_output(
        _block(),
        _report(),
        _ctx("用户提供了实质说明。", substantive_input_present=True),
        text,
    )

    assert "too_many_paragraphs_without_substantive_input" not in _keys(issues)


def test_table_cells_check_required_ai_text_and_text_issues():
    block = Block(
        id="t",
        type="table",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "t"}},
        table=GsTable(
            colDefs=[
                GsColDef(key="name", header="名称", cellType="text", required=True),
                GsColDef(key="response", header="措施", cellType="ai_text"),
            ]
        ),
    )
    issues = check_table_cells(
        block, _report(), _ctx(), {"name": "", "response": "暂未披露具体措施。"}
    )
    assert {"required_cell_empty", "missing_or_negative_statement"} <= _keys(issues)


def test_table_cells_do_not_apply_no_substantive_input_paragraph_limit():
    block = Block(
        id="t",
        type="table",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "t"}},
        table=GsTable(
            colDefs=[GsColDef(key="response", header="措施", cellType="ai_text")]
        ),
    )

    issues = check_table_cells(
        block, _report(), _ctx(), {"response": "第一段。\n第二段。\n第三段。"}
    )

    assert "too_many_paragraphs_without_substantive_input" not in _keys(issues)


def test_table_cells_block_internal_unfilled_state_as_output():
    block = Block(
        id="t",
        type="table",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "t"}},
        table=GsTable(colDefs=[GsColDef(key="metric", header="指标", cellType="text")]),
    )

    issues = check_table_cells(block, _report(), _ctx(), {"metric": "未填写"})

    assert "missing_or_negative_statement" in _keys(issues)


def test_table_cells_block_company_name_when_column_requires_company_subject():
    block = Block(
        id="t",
        type="table",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "t"}},
        table=GsTable(
            colDefs=[
                GsColDef(
                    key="impact",
                    header="潜在影响",
                    cellType="text",
                    subjectTerm="company",
                ),
            ]
        ),
    )
    bad = check_table_cells(
        block, _report(), _ctx(), {"impact": "恒远电气可能面临客户交付压力。"}
    )
    assert "table_company_subject" in _keys(bad)

    good = check_table_cells(
        block, _report(), _ctx(), {"impact": "公司可能面临客户交付压力。"}
    )
    assert "table_company_subject" not in _keys(good)


def test_pollutant_table_blocks_sensitive_facts_not_in_declared_context():
    """污染物风险表不得引用未进入本块上下文的超标、处罚或整改事实。"""
    block = Block(
        id="pollutant_emissions_management.strategy_risk_opportunity_table",
        type="table",
        blockType="generative",
        source="ai",
        generation={
            "task": {"focus": "t"},
            "evidenceGatedFacts": ["超标排放", "处罚", "整改完成", "整改"],
        },
        table=GsTable(
            colDefs=[
                GsColDef(key="risk_description", header="具体内容", cellType="ai_text"),
                GsColDef(
                    key="response_measures", header="应对措施", cellType="ai_text"
                ),
            ]
        ),
    )

    issues = check_table_cells(
        block,
        _report(),
        _ctx("污染物排放风险与机遇：关注法规政策风险和声誉风险。"),
        {
            "risk_description": "公司报告期内存在超标排放并受到处罚。",
            "response_measures": "公司已完成整改。",
        },
    )

    assert "unsupported_evidence_gated_fact" in _keys(issues)


def test_pollutant_table_allows_sensitive_facts_when_declared_context_supports_them():
    """污染物敏感事实可由本块声明读取的用户填写内容支撑。"""
    block = Block(
        id="pollutant_emissions_management.strategy_risk_opportunity_table",
        type="table",
        blockType="generative",
        source="ai",
        generation={
            "task": {"focus": "t"},
            "evidenceGatedFacts": ["超标排放", "处罚", "整改完成", "整改"],
        },
        table=GsTable(
            colDefs=[
                GsColDef(key="risk_description", header="具体内容", cellType="ai_text"),
            ]
        ),
    )

    issues = check_table_cells(
        block,
        _report(),
        _ctx("用户填写：报告期内未发生超标排放、处罚或整改事项。"),
        {"risk_description": "公司报告期内未发生超标排放、处罚或整改事项。"},
    )

    assert "unsupported_evidence_gated_fact" not in _keys(issues)


def test_pollutant_table_blocks_affirming_sensitive_facts_when_user_negates_them():
    """用户填写未发生时，模型不得反向坐实为已发生或已整改事实。"""
    block = Block(
        id="pollutant_emissions_management.strategy_risk_opportunity_table",
        type="table",
        blockType="generative",
        source="ai",
        generation={
            "task": {"focus": "t"},
            "evidenceGatedFacts": ["超标排放", "处罚", "整改完成", "整改"],
        },
        table=GsTable(
            colDefs=[
                GsColDef(key="risk_description", header="具体内容", cellType="ai_text"),
            ]
        ),
    )

    issues = check_table_cells(
        block,
        _report(),
        _ctx("用户填写：报告期内未发生超标排放、处罚或整改事项。"),
        {"risk_description": "公司报告期内存在超标排放并受到处罚。"},
    )

    assert "unsupported_evidence_gated_fact" in _keys(issues)


def test_retry_instruction_is_deduplicated_and_actionable():
    issues = check_paragraph_output(_block(), _report(), _ctx(), "公司暂未披露数据。")
    instruction = build_retry_instruction(issues)
    assert "重新生成" in instruction
    assert "暂未" in instruction


def test_metric_narrative_allows_building_stage_and_blocks_mature_claims() -> None:
    context = _ctx()
    context.metric_narrative_policy = MetricNarrativePolicy(
        indicator_source="generated_general",
    )

    allowed = check_paragraph_output(
        _block(),
        _report(),
        context,
        "公司正在着手建立指标管理体系，推进相关信息的统计、收集、校验与跟踪，并为后续披露做好准备。",
    )
    blocked = check_paragraph_output(
        _block(),
        _report(),
        context,
        "公司已建立指标管理体系，持续开展对比分析并取得显著成效。",
    )
    supervision_blocked = check_paragraph_output(
        _block(),
        _report(),
        context,
        "公司持续开展相关指标的监督和改善。",
    )

    assert "metric_narrative_maturity" not in _keys(allowed)
    assert "metric_narrative_maturity" in _keys(blocked)
    assert "metric_narrative_maturity" in _keys(supervision_blocked)


def test_metric_narrative_guardrail_does_not_use_hidden_metric_metadata() -> None:
    context = sse_model_context(
        evidence=GenerationEvidence(
            metric_evidence=(
                MetricEvidence(
                    metric_name="电力消耗量",
                    category_path=("EHS内部分类",),
                    unit="兆瓦时",
                ),
            ),
        ),
        metric_narrative_policy=MetricNarrativePolicy(
            indicator_source="catalog",
            catalog_metric_labels=("电力消耗量",),
        ),
    )

    issues = check_paragraph_output(
        _block(),
        _report(),
        context,
        "公司正着手建立EHS指标管理体系，并推进相关数据统计与跟踪。",
    )

    assert "unsupported_formal_name" in _keys(issues)


def test_expanded_row_guardrail_locates_issue_to_its_unit():
    """契约声明 rowExpansion 时，子行内的空 AI 文本定位到该子行，而非整表一个笼统位置。"""
    from sustainability_desk.contract.models import (
        GenerationSpec,
        GenerationTask,
        RowExpansion,
        RowExpansionUnit,
    )

    block = Block(
        id="t.expand",
        type="table",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task=GenerationTask(focus="补全两段披露。"),
            rowMode="expanded_rows",
            rowExpansion=RowExpansion(
                sharedColumnKeys=["topic"],
                units=[
                    RowExpansionUnit(
                        key="impact", label="影响描述", columnKeys=["desc"]
                    ),
                    RowExpansionUnit(
                        key="risk_opportunity",
                        label="风险与机遇描述",
                        columnKeys=["desc"],
                    ),
                ],
            ),
        ),
        table=GsTable(
            colDefs=[
                GsColDef(key="topic", header="议题", cellType="text"),
                GsColDef(key="desc", header="描述", cellType="ai_text"),
            ]
        ),
    )
    issues = check_table_cells(
        block,
        _report(),
        _ctx(),
        {
            "topic": "应对气候变化",
            "impact": {"desc": ""},
            "risk_opportunity": {"desc": "低碳转型可能带来市场机遇。"},
        },
    )

    empties = [i for i in issues if i.key == "ai_text_cell_empty"]
    assert [i.location for i in empties] == ["影响描述·描述"]


def test_blocks_chinese_self_numbering_lines_but_allows_continuous_body():
    bad = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "一、总体目标\n公司围绕可持续发展开展管理工作。",
    )
    assert "output_self_numbering" in _keys(bad)

    paren = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "（一）治理架构\n公司设立可持续发展治理架构。",
    )
    assert "output_self_numbering" in _keys(paren)

    good = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "公司围绕可持续发展开展管理工作，总体目标明确。",
    )
    assert "output_self_numbering" not in _keys(good)


def test_blocks_numeric_range_missing_percent_but_allows_complete_range():
    bad = check_paragraph_output(
        _block(),
        _report(),
        _ctx("可再生能源占比15～30%。"),
        "公司可再生能源占比为15～30%。",
    )
    assert "numeric_range_missing_percent" in _keys(bad)

    good = check_paragraph_output(
        _block(),
        _report(),
        _ctx("可再生能源占比15%～30%。"),
        "公司可再生能源占比为15%～30%。",
    )
    assert "numeric_range_missing_percent" not in _keys(good)
    assert _keys(good) == set()


def test_range_check_ignores_year_ranges_and_percentage_point_ranges():
    years = check_paragraph_output(
        _block(),
        _report(),
        _ctx("规划期为2024-2025年。"),
        "公司规划期为2024-2025年。",
    )
    assert "numeric_range_missing_percent" not in _keys(years)


def test_blocks_approximate_number_comma_but_allows_plain_approximation():
    bad = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "项目整改历时三、四天，公司完成相关安排。",
    )
    assert "approximate_number_comma" in _keys(bad)

    good = check_paragraph_output(
        _block(),
        _report(),
        _ctx(),
        "项目整改历时三四天，公司完成相关安排。",
    )
    assert "approximate_number_comma" not in _keys(good)


def test_blocks_title_trailing_punctuation_but_allows_clean_title():
    bad = check_display_title_variants(
        _block(), _report(), _ctx(), ["治理架构与职责。"]
    )
    assert "title_trailing_punctuation" in _keys(bad)

    good = check_display_title_variants(_block(), _report(), _ctx(), ["治理架构与职责"])
    assert "title_trailing_punctuation" not in _keys(good)


def test_year_token_is_supported_when_bare_year_appears_in_evidence() -> None:
    """报告主体常以「报告年份：2025」承载年份；正文写「2025年」不得判为未支撑数字。

    NUMERIC_PATTERN 捕获 \\d{4}年，单位集合若缺「年」，带年份
    的合法表述在证据仅含裸年号时会被误拦。
    """
    from sustainability_desk.llm.generation_guardrails import _norm, _numeric_token_supported
    from sustainability_desk.llm.guardrail_lexicon import ZH_HANS

    source = _norm("报告年份：2025\n公司简称：晟原精密")
    assert _numeric_token_supported("2025年", source, ZH_HANS)
    assert not _numeric_token_supported("2030年", source, ZH_HANS)

