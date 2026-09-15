# ABOUTME: 内容清单 IntakeItem 机制测试——模型、答案进 filled_content（结构化→prompt 文本投影）、
# ABOUTME: constrained paragraph 缺少实质证据时进入 context_only，并覆盖 appears_when 路径与 fill 接线。
from pathlib import Path

import pytest
import yaml

from sustainability_desk.contract.models import Block, Condition, ConditionRule, Inline, IntakeItem, Report, Section
from sustainability_desk.contract.evidence_resolution import intake_item_ready
from sustainability_desk.llm.prompts import build_model_context, render_prompt
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_intake_from

BACKEND = Path(__file__).resolve().parents[1]
TOPIC_INTAKE = SSE_PACKAGE.topic_intake_dir
HINT_GENERATION_BOUNDARY_MARKERS = (
    "不得生成",
    "不得编造",
    "系统不得",
    "不得解释",
    "不得坐实",
    "不得把",
)


def _report_with(block, items):
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        intakeItems=items,
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[block])],
    )


def _gen_block(block_id, block_type, intake_keys, *, content=None, appears_when=None):
    return Block(
        id=block_id, type="paragraph", blockType=block_type, source="ai",
        content=content, appears_when=appears_when,
        generation={"task": {"focus": "p"}, "inputs": {"evidence": {"kind": "explicit", "intakeItems": intake_keys}}},
    )


def test_intake_item_and_report_field():
    item = IntakeItem(
        key="climate.q_gov", contentScopeId="climate_change", prompt="谁负责气候事务？",
        kind="single_select", options=["设有专门部门", "暂无"], answer="设有专门部门",
    )
    r = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[], intakeItems=[item])
    assert r.intakeItems[0].key == "climate.q_gov"
    assert r.intakeItems[0].answer == "设有专门部门"


def test_generation_inputs_intake_items():
    blk = _gen_block("b", "constrained", ["climate.q_gov"])
    assert blk.generation.inputs.evidence.intakeItems == ["climate.q_gov"]


def test_intake_answers_become_materials_in_user_prompt():
    """已作答清单项 → 填报内容 DTO（填空=答案文本，多选=所选项规范化）进 user prompt、不进 System；非法选项跳过。"""
    blk = _gen_block("b", "generative", ["k_text", "k_multi", "k_bad"], content=[Inline(kind="text", text="写治理")])
    items = [
        IntakeItem(key="k_text", contentScopeId="t", prompt="谁负责？", kind="text", answer="由ESG办公室负责"),
        IntakeItem(key="k_multi", contentScopeId="t", prompt="做过哪些减排？", kind="multi_select",
                   options=["光伏", "节能改造", "余热回收"], answer=["光伏", "节能改造"]),
        IntakeItem(key="k_bad", contentScopeId="t", prompt="坏选项", kind="single_select",
                   options=["A", "B"], answer="不在选项里"),
    ]
    rep = _report_with(blk, items)
    ctx = build_model_context(blk, rep, rep)
    texts = [m.text for m in ctx.evidence.intake_facts]
    assert any("由ESG办公室负责" in t for t in texts)
    assert any("光伏" in t and "节能改造" in t for t in texts)
    assert all("不在选项里" not in t for t in texts)  # 非法选项被跳过
    system, user = render_prompt(ctx)
    assert "由ESG办公室负责" in user
    assert "由ESG办公室负责" not in system
    assert "由ESG办公室负责" not in "".join(ctx.report_subject)


def test_selection_generation_labels_project_business_answers_for_external_disclosure():
    """选择题保留业务答案，ModelContext 只读取声明的对外披露标签。"""
    block = _gen_block("b", "generative", ["supplier_dimensions"], content=[Inline(kind="text", text="写供应链")])
    item = IntakeItem(
        key="supplier_dimensions",
        contentScopeId="sustainable_supply_chain_management",
        prompt="请选择供应商评价维度。",
        kind="multi_select",
        options=["质量表现", "成本竞争力", "合作稳定性"],
        generationOptionLabels={"成本竞争力": "长期价值与可持续运营效率"},
        answer=["质量表现", "成本竞争力"],
        supplement="重点物料需要兼顾长期合作。",
    )
    report = _report_with(block, [item])

    context = build_model_context(block, report, report)
    # 供给结构分离：答案本体在 text，补充说明作为用户原话备注在 note。
    rendered = "\n".join(material.text for material in context.evidence.intake_facts)
    notes = "\n".join(material.note or "" for material in context.evidence.intake_facts)

    assert item.answer == ["质量表现", "成本竞争力"]
    assert "质量表现" in rendered
    assert "长期价值与可持续运营效率" in rendered
    assert "成本竞争力" not in rendered
    assert "重点物料需要兼顾长期合作" in notes


def test_selection_generation_labels_reject_unknown_options():
    """模型可见标签只能映射同题已声明选项，加载期 fail-loud。"""
    with pytest.raises(ValueError, match="未声明选项"):
        IntakeItem(
            key="k",
            contentScopeId="t",
            prompt="q",
            kind="multi_select",
            options=["A"],
            generationOptionLabels={"B": "对外标签"},
        )


def test_intake_hint_is_user_visible_only_and_generation_boundary_goes_to_system():
    """hint 不进入模型上下文；generationBoundary 进入 System 生成边界，不进入 User 填写内容。"""
    blk = _gen_block("b", "generative", ["k1"], content=[Inline(kind="text", text="写")])
    item = IntakeItem(
        key="k1",
        contentScopeId="t",
        prompt="是否有相关培训？",
        kind="single_select",
        options=["是", "否"],
        hint="如选择是，请补充培训主题。",
        generationBoundary="未填写具体数值时，不得生成培训人次、次数或覆盖率。",
        answer="是",
        supplement="安全培训。",
    )
    rep = _report_with(blk, [item])
    ctx = build_model_context(blk, rep, rep)
    system, user = render_prompt(ctx)

    assert "如选择是，请补充培训主题" not in system + user
    assert "不得生成培训人次" in system
    assert "不得生成培训人次" not in user
    assert "安全培训" in user


def test_topic_intake_hints_do_not_carry_generation_boundaries():
    """topic_intake 的 hint 只面向用户填写；生成约束必须写入 generationBoundary。"""
    violations: list[str] = []
    for path in sorted(TOPIC_INTAKE.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("items", []) or []:
            hint = str(item.get("hint") or "")
            if any(marker in hint for marker in HINT_GENERATION_BOUNDARY_MARKERS):
                violations.append(f"{path.name}:{item.get('key')}")

    assert not violations, "以下内容清单项把生成约束写入了用户可见 hint：" + "、".join(violations)


def test_intake_supplement_fed_with_selection():
    """选项答案 + 补充文字一并进填报内容。"""
    blk = _gen_block("b", "generative", ["k_sel"], content=[Inline(kind="text", text="写")])
    item = IntakeItem(key="k_sel", contentScopeId="t", prompt="谁负责？", kind="single_select",
                      options=["专门部门", "兼管"], answer="专门部门", supplement="由ESG办公室牵头，每季度汇报")
    rep = _report_with(blk, [item])
    ctx = build_model_context(blk, rep, rep)
    text = "\n".join(m.text for m in ctx.evidence.intake_facts)
    notes = "\n".join(m.note or "" for m in ctx.evidence.intake_facts)
    assert "专门部门" in text and "ESG办公室" in notes


def test_intake_supplement_only_is_ready():
    """仅填补充、未选选项 → 视为已就绪（supplement 是重要内容）；appears_when 亦算 exists。"""
    from sustainability_desk.contract.visibility import visible

    cond = Condition(all=[ConditionRule(path="intakeItems.k1", op="exists")])
    blk = _gen_block("b", "generative", ["k1"], appears_when=cond)
    item = IntakeItem(key="k1", contentScopeId="t", prompt="q", kind="single_select", options=["A"], supplement="我们的具体做法")
    rep = _report_with(blk, [item])
    ctx = build_model_context(blk, rep, rep)
    assert any("我们的具体做法" in (m.note or "") for m in ctx.evidence.intake_facts)
    assert visible(blk, rep) is True


def test_multi_select_option_groups_require_each_declared_group():
    """同一道多选题可声明分组选项；补充说明不能替代各组最小选择。"""
    item = IntakeItem(
        key="climate.q_climate_risk_choices",
        contentScopeId="climate_change",
        prompt="哪些风险？",
        kind="multi_select",
        collectionPriority="core",
        options=["台风", "极端高温", "碳定价与排放监管政策变化", "消费者偏好转变风险"],
        optionGroups=[
            {"key": "physical_risk", "label": "物理风险", "minSelections": 1, "options": ["台风", "极端高温"]},
            {
                "key": "transition_risk",
                "label": "转型风险",
                "minSelections": 1,
                "options": ["碳定价与排放监管政策变化", "消费者偏好转变风险"],
            },
        ],
        answer=["台风"],
        supplement="公司补充说明。",
    )
    assert intake_item_ready(item) is False

    ready = item.model_copy(update={"answer": ["台风", "消费者偏好转变风险"]})
    assert intake_item_ready(ready) is True
    block = _gen_block("b", "generative", [ready.key])
    report = _report_with(block, [ready])
    ctx = build_model_context(block, report, report)
    assert any("台风" in material.text and "消费者偏好转变风险" in material.text for material in ctx.evidence.intake_facts)


def test_option_groups_reject_unknown_options():
    """分组选项必须来自同题 options，加载时 fail-loud。"""
    with pytest.raises(ValueError, match="未声明选项"):
        IntakeItem(
            key="k",
            contentScopeId="t",
            prompt="q",
            kind="multi_select",
            options=["A"],
            optionGroups=[{"key": "g", "label": "G", "minSelections": 1, "options": ["B"]}],
        )


def test_option_groups_reject_impossible_minimum():
    """分组最小选择数不得超过该组选项数量。"""
    with pytest.raises(ValueError, match="不得大于该组选项数量"):
        IntakeItem(
            key="k",
            contentScopeId="t",
            prompt="q",
            kind="multi_select",
            options=["A"],
            optionGroups=[{"key": "g", "label": "G", "minSelections": 2, "options": ["A"]}],
        )


def test_unanswered_intake_skipped():
    """未作答清单项不进 filled_content。"""
    blk = _gen_block("b", "generative", ["k1"])
    rep = _report_with(blk, [IntakeItem(key="k1", contentScopeId="t", prompt="q", kind="text")])
    ctx = build_model_context(blk, rep, rep)
    assert ctx.evidence.intake_facts == ()


def test_constrained_without_substantive_evidence_uses_context_only_posture():
    """paragraph 的缺事实分支由 EvidencePosture 表达，不从 constrained 推导省略。"""
    blk = _gen_block("b", "constrained", ["k_req"])
    item = IntakeItem(key="k_req", contentScopeId="t", prompt="减排数据？", kind="text", collectionPriority="core")
    rep = _report_with(blk, [item])
    ctx = build_model_context(blk, rep, rep)

    assert ctx.evidence.substantive_input_present is False
    assert ctx.evidence_posture.level == "context_only"


def test_constrained_with_substantive_evidence_uses_block_facts_posture():
    """采集优先级不参与判断；selector 有实质企业事实时使用 block_facts。"""
    blk = _gen_block("b", "constrained", ["k_req"])
    item = IntakeItem(key="k_req", contentScopeId="t", prompt="减排数据？", kind="text", collectionPriority="optional", answer="范围一 100 tCO2e")
    rep = _report_with(blk, [item])
    ctx = build_model_context(blk, rep, rep)

    assert ctx.evidence.substantive_input_present is True
    assert ctx.evidence_posture.level == "block_facts"


def test_appears_when_intake_exists():
    """appears_when intakeItems.<k> exists：未作答隐藏、作答后显示。"""
    from sustainability_desk.contract.visibility import visible

    cond = Condition(all=[ConditionRule(path="intakeItems.k1", op="exists")])
    blk = _gen_block("b", "generative", ["k1"], appears_when=cond)
    rep_empty = _report_with(blk, [IntakeItem(key="k1", contentScopeId="t", prompt="q", kind="text")])
    assert visible(blk, rep_empty) is False
    rep_ans = _report_with(blk, [IntakeItem(key="k1", contentScopeId="t", prompt="q", kind="text", answer="有")])
    assert visible(blk, rep_ans) is True


def test_load_topic_intake_injects_content_scope_id(tmp_path):
    """load_topic_intake：按文件 contentScopeId 注入每个清单项。"""

    (tmp_path / "climate_change.yaml").write_text(
        "contentScopeId: climate_change\n"
        "items:\n"
        "  - {key: x.q1, prompt: 谁负责？, kind: text}\n"
        "  - {key: x.q2, prompt: 做过哪些？, kind: multi_select, options: [A, B]}\n",
        encoding="utf-8",
    )
    items = load_topic_intake_from(tmp_path, package=SSE_PACKAGE)
    assert [i.key for i in items] == ["x.q1", "x.q2"]
    assert all(i.contentScopeId == "climate_change" for i in items)
    assert items[1].kind == "multi_select" and items[1].options == ["A", "B"]


def test_climate_intake_has_expected_items():
    """气候轻量版清单包含 common 固定题及职责独立的风险、机遇、培训和减排实践题。"""

    from sustainability_desk.planner import load_topic_intake

    items = [i for i in load_topic_intake(SSE_PACKAGE) if i.contentScopeId == "climate_change"]
    expected = {
        "climate.q_governance_roles",
        "climate.q_governance_policies",
        "climate.q_governance_certifications",
        "climate.q_strategy_content",
        "climate.q_climate_risk_choices",
        "climate.q_climate_opportunity_choices",
        "climate.q_climate_target_status",
        "climate.q_training_activities",
        "climate.q_reduction_practices",
    }
    assert {item.key for item in items} == expected
    assert any("应对气候变化" in item.prompt for item in items if item.key == "climate.q_governance_roles")
    kinds = {i.kind for i in items}
    assert kinds <= {"text", "single_select", "multi_select"}


def test_sme_topic_intake_uses_common_and_expert_question_contract():
    """每个有报告章节的议题加载后包含 common 固定题与议题专属题。"""
    from collections import defaultdict

    from sustainability_desk.planner import load_topic_intake
    from topic_intake_assertions import expected_sme_topic_intake_keys

    by_topic: dict[str, list[str]] = defaultdict(list)
    for item in load_topic_intake(SSE_PACKAGE):
        by_topic[item.contentScopeId].append(item.key)

    prefix_by_topic = {
        "climate_change": "climate",
        "risk_management": "risk_management",
    }
    assert by_topic
    for topic_id, keys in by_topic.items():
        prefix = prefix_by_topic.get(topic_id, topic_id)
        expected = expected_sme_topic_intake_keys(prefix)
        assert set(keys) == expected, topic_id
        assert len(set(keys)) == len(keys), topic_id


def test_fill_report_sets_intake_answers():
    """fill_report 据 values.intake 填答案；纯函数不改输入。"""
    from sustainability_desk.contract.fill import fill_report

    blk = Block(id="b", type="paragraph", blockType="generative", source="ai")
    rep = _report_with(blk, [IntakeItem(key="k1", contentScopeId="t", prompt="q", kind="text")])
    filled = fill_report(rep, {"intake": {"k1": "答案A"}})
    assert rep.intakeItems[0].answer is None  # 输入不变
    assert filled.intakeItems[0].answer == "答案A"
