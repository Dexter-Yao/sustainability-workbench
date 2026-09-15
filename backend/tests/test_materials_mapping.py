# ABOUTME: 内容清单与定量指标到生成结构的映射测试，确保生成块输入来自声明的 generation.inputs。
# ABOUTME: 旧资料槽合同已移出当前 Report；本文件保留同等边界覆盖但不引用资料上传字段。

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import (
    Block,
    GenerationInputs,
    GenerationSpec,
    Inline,
    IntakeItem,
    Report,
    Section,
)
from sustainability_desk.contract.visibility import visible
from sustainability_desk.llm.prompts import (
    _intake_answer_text,
    _intake_supplement_text,
    build_model_context,
    evidence_materials,
    generation_blocks,
    render_prompt,
)
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.llm.prompt_profiles import answer_wording, prompt_labels
from sustainability_desk.planner import load_topic_templates_from

CONTRACT = SSE_PACKAGE.report_contract_path
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir


def test_generation_blocks_from_contract_inputs() -> None:
    report = load_contract(CONTRACT)
    gen = {item["id"]: item for item in generation_blocks(report)}
    assert gen["company_intro.body"] == {"id": "company_intro.body"}


def test_report_contract_has_front_chapter_intake_items() -> None:
    report = load_contract(CONTRACT)
    keys = {item.key for item in report.intakeItems}
    assert {
        "company_profile",
        "articles",
        "sustainability_governance_duties",
        "sustainability_strategy",
    } <= keys
    company_profile = next(item for item in report.intakeItems if item.key == "company_profile")
    assert company_profile.minChars == 100


def test_company_intro_brief_does_not_require_keyword_coverage() -> None:
    report = load_contract(CONTRACT)
    block = report.find_block("company_intro.body")
    brief = "".join(item.text or "" for item in block.content or [] if item.kind == "text")
    assert "须涵盖" not in brief


def test_user_supplement_flows_into_filled_content() -> None:
    report = load_contract(CONTRACT)
    report.intakeItems = [
        item.model_copy(update={"answer": "公司成立于2000年。", "supplement": "这是2024年最新公司简介"})
        if item.key == "company_profile"
        else item
        for item in report.intakeItems
    ]
    block = report.find_block("company_intro.body")
    ctx = build_model_context(block, report, report)
    # 答案本体与补充说明分离：supplement 作为用户原话备注（note）随 <item> 的「用户说明」行呈现。
    assert ctx.evidence.intake_facts and ctx.evidence.intake_facts[0].text == "公司成立于2000年。"
    assert ctx.evidence.intake_facts[0].note == "这是2024年最新公司简介"


def test_generation_task_keeps_focus_and_uses_no_fact_guidance_only_without_evidence() -> None:
    blk = Block(
        id="climate.gov_structure",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(
            task={
                "focus": "说明气候治理职责。",
                "noFactGuidance": "据行业通行边界形成低承诺方向性正文。",
            },
            inputs=GenerationInputs(evidence={"kind": "explicit", "intakeItems":["climate.q_governance_roles"]}),
        ),
        content=[Inline(kind="text", text="气候治理架构叙述")],
    )
    item = IntakeItem(key="climate.q_governance_roles", contentScopeId="climate_change", prompt="谁负责气候事务？", kind="text")
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        intakeItems=[item],
        sections=[Section(key="env", title="环境", headingLevel=1, children=[
            Section(key="climate.gov", title="一、治理", headingLevel=3, blocks=[blk]),
        ])],
    )
    none_ctx = build_model_context(blk, tmpl, tmpl)
    assert not none_ctx.evidence.intake_facts
    assert "行业通行" in none_ctx.section_task

    inst = tmpl.model_copy(update={"intakeItems": [item.model_copy(update={"answer": "由生产与安环部门负责。"})]})
    have_ctx = build_model_context(blk, tmpl, inst)
    assert have_ctx.evidence.intake_facts and "生产与安环部门" in have_ctx.evidence.intake_facts[0].text
    assert have_ctx.section_task == "说明气候治理职责。"


def test_non_substantive_selection_does_not_enter_materials_or_with_content() -> None:
    blk = Block(
        id="supply.gov",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(
            task={"focus": "说明供应链治理。", "noFactGuidance": "使用低承诺通行口径。"},
            inputs=GenerationInputs(evidence={"kind": "explicit", "intakeItems":["supply.q_role"]}),
        ),
        content=[Inline(kind="text", text="供应链治理")],
    )
    item = IntakeItem(
        key="supply.q_role",
        contentScopeId="sustainable_supply_chain_management",
        prompt="是否设置供应链管理组织或岗位？",
        kind="single_select",
        options=["已设置组织或岗位负责", "暂未设置组织或岗位负责"],
        answer="暂未设置组织或岗位负责",
    )
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        intakeItems=[item],
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[blk])],
    )

    ctx = build_model_context(blk, tmpl, tmpl)

    assert _intake_answer_text(item, language="zh-Hans", wording=answer_wording(prompt_labels(SSE_PACKAGE))) is None
    assert not ctx.evidence.intake_facts
    assert not ctx.evidence.substantive_input_present
    assert "低承诺" in ctx.section_task


def test_non_substantive_selection_with_supplement_is_substantive_content() -> None:
    item = IntakeItem(
        key="supply.q_cert",
        contentScopeId="sustainable_supply_chain_management",
        prompt="是否有供应链相关认证？",
        kind="single_select",
        options=["通过相关认证", "暂无相关认证"],
        answer="暂无相关认证",
        supplement="已建立供应商准入清单，每年更新一次。",
    )

    # 供给结构分离：非实质选择不产出答案事实，补充说明作为用户原话备注（note）供模型区分。
    assert _intake_answer_text(item, language="zh-Hans", wording=answer_wording(prompt_labels(SSE_PACKAGE))) is None
    assert _intake_supplement_text(item) == "已建立供应商准入清单，每年更新一次。"


def test_quantitative_metrics_flow_into_materials_without_internal_fields() -> None:
    blk = Block(
        id="energy_management.metrics_narrative_body",
        type="paragraph",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task={"focus": "energy_management.metrics_narrative_body"},
            inputs=GenerationInputs(evidence={"kind": "explicit", "quantitativeMetrics":["economic_environment_r11"]}),
        ),
        content=[Inline(kind="text", text="能源使用指标")],
    )
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="energy", title="能源管理", headingLevel=2, reportSectionId="energy_management", blocks=[blk])],
    )
    inst = tmpl.model_copy(
        update={
            "meta": {
                "quantitativeMetrics": {
                    "metrics": {
                        "economic_environment_r11": {
                            "value": "123.45",
                            "department": "运营部",
                            "note": "按电费账单统计",
                        },
                        "economic_environment_r12": {"value": "999"},
                    }
                }
            }
        }
    )

    ctx = build_model_context(blk, tmpl, inst)

    assert len(ctx.evidence.metric_evidence) == 1
    text = evidence_materials(ctx.evidence, prompt_labels(SSE_PACKAGE))[0].text
    assert ctx.evidence.metric_evidence[0].metric_name == "电力消耗量"
    assert "来源：ESG 定量数据表" in text
    assert "分类路径：能源管理 / 能源管理 / 传统能源消耗量" in text
    assert "指标名称：电力消耗量" in text
    assert "报告期数值：123.45" in text
    assert "单位：吨标准煤" in text
    assert "用户备注：按电费账单统计" in text
    assert "运营部" not in text
    assert "economic_environment_r11" not in text
    assert "999" not in text
    assert ctx.evidence.substantive_input_present


def test_compiled_metric_narrative_is_hidden_when_any_catalog_value_exists() -> None:
    topic = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)["energy_management"]
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[topic],
        meta={"quantitativeMetrics": {"metrics": {"economic_environment_r11": {"value": "123.45"}}}},
    )
    metrics = next(child for child in topic.children or [] if child.title == "指标与目标")
    narrative = next(
        block for block in metrics.blocks if block.id == "energy_management.metrics_narrative_body"
    )

    assert narrative.appears_when is not None
    assert not visible(narrative, report)


def test_metric_narrative_policy_authorizes_building_language_without_values() -> None:
    topic = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)["energy_management"]
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[topic])
    metrics = next(child for child in topic.children or [] if child.title == "指标与目标")
    block = next(
        item for item in metrics.blocks if item.id == "energy_management.metrics_narrative_body"
    )

    ctx = build_model_context(block, report, report)

    assert visible(block, report)
    assert ctx.metric_narrative_policy is not None
    assert ctx.metric_narrative_policy.indicator_source == "catalog"
    assert "电力消耗量" in ctx.metric_narrative_policy.catalog_metric_labels
    assert all("吨标准煤" not in label for label in ctx.metric_narrative_policy.catalog_metric_labels)
    system, user = render_prompt(ctx, n=1)
    prompt = "\n".join((system, user))
    assert "正着手建立以……等为核心的指标管理体系" in system
    assert "统计、收集、校验与跟踪" in system
    assert "<pillar_purpose>" not in system
    assert "<metric_narrative_policy>" in system
    assert "篇幅约 60–160 字" in system
    assert prompt.count("电力消耗量") == 1
    assert "吨标准煤" not in prompt
    assert "应对气候变化 /" not in prompt
    assert "未填写" not in prompt
    assert "报告期数值：" not in prompt
    assert "本节没有报告期指标数值" in user


def test_quantitative_metrics_flow_into_prompt_even_without_value() -> None:
    blk = Block(
        id="energy_management.metrics_narrative_body",
        type="paragraph",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task={
                "focus": "说明能源使用指标。",
                "noFactGuidance": "缺少实质指标值时不生成具体数据结论。",
            },
            inputs=GenerationInputs(evidence={"kind": "explicit", "quantitativeMetrics":["economic_environment_r11"]}),
        ),
        content=[Inline(kind="text", text="能源使用指标")],
    )
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="energy", title="能源管理", headingLevel=2, reportSectionId="energy_management", blocks=[blk])],
    )

    ctx = build_model_context(blk, tmpl, tmpl)

    assert len(ctx.evidence.metric_evidence) == 1
    text = evidence_materials(ctx.evidence, prompt_labels(SSE_PACKAGE))[0].text
    assert "来源：ESG 定量数据表" in text
    assert "指标名称：电力消耗量" in text
    assert "单位：吨标准煤" in text
    assert "本指标仅作为披露维度参考" in text
    assert "填写值" not in text
    assert "未填写" not in text
    assert "economic_environment_r11" not in text
    assert not ctx.evidence.substantive_input_present
    assert "缺少实质指标值" in ctx.section_task
    assert "形成一个简短自然段" in ctx.content_format


def test_quantitative_metric_note_or_ghg_standard_counts_as_substantive_input() -> None:
    note_block = Block(
        id="energy_management.metrics_narrative_body",
        type="paragraph",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task={"focus": "energy_management.metrics_narrative_body"},
            inputs=GenerationInputs(evidence={"kind": "explicit", "quantitativeMetrics":["economic_environment_r11"]}),
        ),
        content=[Inline(kind="text", text="能源使用指标")],
    )
    ghg_block = note_block.model_copy(
        update={
            "id": "climate_change.metrics_narrative_body",
            "generation": GenerationSpec(
                task={"focus": "climate_change.metrics_narrative_body"},
                inputs=GenerationInputs(evidence={"kind": "explicit", "quantitativeMetrics":["economic_environment_r04"]}),
            ),
        }
    )
    tmpl = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="energy", title="能源管理", headingLevel=2, reportSectionId="energy_management", blocks=[note_block, ghg_block])],
    )
    note_report = tmpl.model_copy(
        update={
            "meta": {
                "quantitativeMetrics": {
                    "metrics": {
                        "economic_environment_r11": {
                            "note": "按全年账单口径统计，暂未录入数值。",
                        },
                    }
                }
            }
        }
    )
    ghg_report = tmpl.model_copy(
        update={
            "meta": {
                "quantitativeMetrics": {
                    "metrics": {},
                    "greenhouseGasAccountingStandard": "GHG Protocol",
                }
            }
        }
    )

    note_ctx = build_model_context(note_block, tmpl, note_report)
    ghg_ctx = build_model_context(ghg_block, tmpl, ghg_report)

    assert note_ctx.evidence.substantive_input_present
    assert ghg_ctx.evidence.substantive_input_present
    assert "最多输出两段" not in note_ctx.content_format
    assert "最多输出两段" not in ghg_ctx.content_format
