# ABOUTME: XML 提示词装配测试——typed 片段独立渲染，User 仅承载 filled_content。
# ABOUTME: 守护分工、支柱、证据、准则、指标和任务的单一职责，不恢复混合 domain_rules。
import re
from pathlib import Path

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import KNOWLEDGE_PACKAGES_ROOT
from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import AssessmentResult
from sustainability_desk.contract.user_visible_disclosure_clause_annotations import load_user_visible_disclosure_clause_annotations
from sustainability_desk.export.docx_renderer import load_values_flat
from sustainability_desk.llm.generate import _template
from sustainability_desk.llm.prompts import (
    build_model_context,
    render_complete_prompt,
    render_catalog_table_fill_prompt,
    render_prompt,
)
from sustainability_desk.llm.table_gen import _anchor_ai_split, _table_kind_label
from sustainability_desk.llm.table_schema import RowSeed
from sustainability_desk.planner import assemble_report, load_topic_intake
from assessment_fixtures import complete_assessment
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir
VALUES = SSE_PACKAGE.sample_values_path


def _assess(materiality: str = "dual") -> AssessmentResult:
    return complete_assessment(
        load_contract(CONTRACT),
        materialities={"climate_change": materiality},
    )


def _instance(*, with_intake: bool):
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    intake = load_topic_intake(SSE_PACKAGE)
    base = assemble_report(
        load_contract(CONTRACT), templates,
        assessment=_assess(), intake_items=intake,
    ).report
    vals = load_values_flat(VALUES)
    if not with_intake:
        vals = {k: vals[k] for k in vals if k != "intake"}
    return fill_report(base, vals)


def test_system_is_xml_segmented():
    """System 提示词按 typed 职责分段，不包含已删除的混合规则容器。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)
    for tag in (
        "<role>",
        "<report_body_contract>",
        "<expression_guidance>",
        "<report_subject>",
        "<section_placement>",
        "<evidence_posture>",
        "<output_contract>",
        "<content_format>",
    ):
        assert tag in system, f"System 缺 XML 段 {tag}"
    assert "<pillar_purpose>" not in system
    assert "<output_format>" not in system
    # climate.gov_structure 与 IRO 管理框架块共享治理题证据 → 共享分工段合法出现。
    assert "<topic_scope>" in system
    assert "<domain_rules>" not in system
    assert "<report_subject_usage>" not in system


def test_paragraph_expression_guidance_is_separate_from_role_and_user_content() -> None:
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, user = render_prompt(ctx, n=1)

    assert system.count("<expression_guidance>") == 1
    assert system.index("<role>") < system.index("<report_body_contract>") < system.index("<expression_guidance>") < system.index("<report_subject>")
    assert "术语准确、一致" in system
    assert "最有信息量" not in system
    assert "段落先明确中心" in system
    assert "中国中小企业" in system
    assert "符合上市公司公开披露的口径" not in system
    assert "咨询建议、行动方案、待办清单或操作指引" in system
    assert "expression_guidance" not in user


def test_paragraph_placement_and_task_have_distinct_ownership() -> None:
    """Section 树负责位置，GenerationTask.focus 只负责当前块写什么。"""

    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)

    assert ctx.section_placement is not None
    assert ctx.section_placement.reportSectionTitle == "应对气候变化"
    assert ctx.section_placement.pillarTitle == "治理"
    assert ctx.section_task == block.generation.task.focus
    assert system.count(block.generation.task.focus) == 1
    assert "<section_placement>" in system
    assert "报告二级章节：应对气候变化" in system
    assert "三级支柱：治理" in system
    assert "标题已承担当前正文的结构定位" in system
    assert "当前输出是上述标题下的局部报告正文" in system
    assert "当前任务和证据直接展开" in system


def test_materiality_flags_are_not_repeated_in_paragraph_prompt_without_iro() -> None:
    """Planner 已据重要性选择内容树，正文调用不再重复同一结构结论。"""

    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)

    assert ctx.assessment
    assert "<related_topics>" not in system
    assert "<iro_context>" not in system
    assert "财务重要性（Financial Materiality）" not in system
    assert "影响重要性（Impact Materiality）" not in system


def test_materiality_iro_table_uses_compiled_context_and_deterministic_topic_row() -> None:
    template = _template(SSE_PACKAGE)
    block = template.find_block("sm.iro_table")
    instance = _instance(with_intake=False)

    assert block.blockType == "constrained"
    assert block.generation is not None
    assert block.table is not None and block.table.rowSource == "assessment_iro"
    ctx = build_model_context(
        block,
        template,
        instance,
        definition=load_compiled_report_definition(SSE_PACKAGE),
        row_seed=RowSeed(theme="应对气候变化", category="双重重要性"),
    )
    expansion = block.generation.rowExpansion
    system, user = render_complete_prompt(ctx, block.table.colDefs, expansion=expansion)

    assert ctx.evidence_posture.level == "context_only"
    assert "财务重要性或双重重要性范围" in system
    assert "不得声称公司已发生、已识别或已建立" in system
    assert "financialScore" not in system and "impactScore" not in system
    assert "主题：应对气候变化" in user

    # 两段披露各自独立呈现，候选按子行收窄；合并/占位格等实现细节不进模型视野。
    assert "「影响描述」" in system and "「风险与/或机遇影响描述」" in system
    assert "只写该议题对外部环境与社会造成的影响" in system
    assert "只写该议题对公司自身构成的风险或带来的机遇" in system
    assert "可多选：实际正面影响、潜在正面影响、潜在负面影响）" in system
    assert "可多选：机遇、风险）" in system
    assert "rowSpan" not in system and "iro_desc" not in system and "iro_class" not in system


def test_paragraph_expression_guidance_does_not_enter_table_prompt() -> None:
    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.strategy_physical_risk")
    ctx = build_model_context(block, template, _instance(with_intake=True))
    system, _user = render_catalog_table_fill_prompt(
        ctx,
        [
            {
                "phys_type": "急性风险",
                "phys_name": "台风",
                "referenceImpact": "台风可能影响生产运营",
            }
        ],
        block.table.colDefs,
        kind_label="风险",
    )

    assert ctx.expression_guidance == ""
    assert "<expression_guidance>" not in system


def test_report_subject_in_system_carries_company():
    """报告主体（公司简称/行业/年份）进 System 的 <report_subject>，不进 User。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    inst = _instance(with_intake=True)
    ctx = build_model_context(block, _template(SSE_PACKAGE), inst)
    system, user = render_prompt(ctx, n=1)
    company = inst.fields["company_short_name"].value
    assert str(company) in system
    assert "<report_subject>" in system
    assert str(company) not in user, "报告主体不应进 User"
    assert "报告主体只用于称谓、术语和背景定位" in system
    assert "不是本段需要复述的内容" in system


def test_topic_scope_lists_only_shared_evidence_siblings_without_block_ids():
    """分工 map 只列共享 Evidence 的相邻任务，不重复当前任务或泄漏 block id。"""
    block = _template(SSE_PACKAGE).find_block("climate.strategy_physical_risk")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)
    assert "气候相关转型风险及应对措施" in ctx.topic_scope
    assert block.generation.task.focus not in ctx.topic_scope
    assert "你负责撰写本节" not in ctx.topic_scope
    # 绝不露 block id
    for bid in ("climate.strategy_physical_risk", "strategy_physical_risk", "gov_structure", "climate.gov_structure"):
        assert bid not in system, f"分工 map 泄漏 block id：{bid}"


def test_typed_pillar_purpose_stays_internal_while_risk_guidance_enters_system() -> None:
    block = _template(SSE_PACKAGE).find_block("climate.strategy_physical_risk")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)

    assert ctx.pillar_purpose is not None
    assert ctx.pillar_purpose.name == "战略"
    assert "<pillar_purpose>" not in system
    assert "聚焦高层目标、风险与机遇判断" not in system
    assert "<public_disclosure_guidance>" in system
    assert "方向性、可能性因果表达" in system


def test_context_only_evidence_posture_keeps_report_subject_as_background() -> None:
    block = _template(SSE_PACKAGE).find_block("product_quality_safety.iro_lifecycle_quality_safety_controls")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False))
    system, _user = render_prompt(ctx, n=1)

    assert ctx.evidence.substantive_input_present is False
    assert ctx.evidence_posture.level == "context_only"
    assert ctx.pillar_purpose is not None
    assert ctx.pillar_purpose.name == "影响、风险与机遇管理"
    assert "<pillar_purpose>" not in system
    assert "所属行业：" in system
    assert "当前模块没有直接企业事实" in system
    assert "判断当前任务的相关性" in system
    assert "行业普遍、基础且正常经营所需的管理关注" in system
    assert "低承诺的企业报告语态" in system
    assert "不得把行业相关性、主营业务背景或指标目录改写为可核验的企业事实" in system
    assert "本议题与企业经营的关系" not in system
    assert "识别评估流程、管理实践、行动及实施措施" not in system
    assert "<context_only_writing_example>" not in system
    assert "结合自身业务特点和发展阶段持续关注相关要求" not in system
    assert "结合报告主体与本议题的关系" not in system
    assert "可直接纳入企业可持续发展（ESG）报告的正式正文" in system
    assert "轻量版写作" not in system
    assert "<length>" not in system
    assert "形成一个简短自然段" in system


def test_no_input_context_does_not_inject_block_specific_prohibition_lists() -> None:
    block = _template(SSE_PACKAGE).find_block("waste_management.iro_classification_and_disposal")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False))
    system, _user = render_prompt(ctx, n=1)

    assert "说明废弃物分类、处置、减量和资源化利用的相关实践" in system
    assert "当前模块没有直接企业事实" in system
    assert "分类收集、规范暂存、源头减量和资源化利用" not in system
    assert "不枚举推测的废弃物种类" not in system
    assert "不写第三方委托关系或特定工艺措施" not in system


def test_topic_scope_excludes_hidden_sibling_blocks():
    """议题分工 map 只列当前实例可见块，不把隐藏条件块写入 Prompt 上下文。"""
    report = _instance(with_intake=True)
    report.intakeItems = [
        item.model_copy(update={"answer": "否"}) if item.key == "climate.q_training_activities" else item
        for item in report.intakeItems
    ]
    block = _template(SSE_PACKAGE).find_block("climate.iro_reduction_practice")
    system, _user = render_prompt(build_model_context(block, _template(SSE_PACKAGE), report), n=1)
    assert "应对气候变化培训或活动叙述" not in system


def test_topic_scope_is_omitted_when_visible_siblings_use_independent_evidence() -> None:
    """即使同一 H2 有多个可见块，证据不重叠时也不向当前调用倒入相邻任务。"""

    template = _template(SSE_PACKAGE)
    block = template.find_block("innovation_driven.gov_rd_governance")
    context = build_model_context(block, template, _instance(with_intake=True))

    assert context.topic_scope == ""


# 档位名。英文侧只认下划线标识（lightweight_report 等）与独立成词的产品语境，
# 不认 "lightweighting"——那是包装减重的行业术语，与产品分层无关（hkex_en 的
# materials_and_packaging 实际用到它）。
TIER_TERMS = ("轻量版", "标准版")
TIER_PATTERN = re.compile(r"lightweight(?!ing)[_\s-]*(report|version|tier|版)?", re.IGNORECASE)


def test_product_tier_never_enters_prompt():
    """产品档位名不得进入模型上下文：模型该知道「怎么写」，不该知道「这是哪个档位的商品」。

    2026-09-07 实测曾有 5/144 个块的 System 含「轻量版」——来自 prompt_profile 的 role/tone、
    report_contract 与 topic_sections 的写作口径。档位是产品包装事实，不是任务规格；
    它进上下文既无助于生成，又把商业分层暴露给模型。写作约束应直述其内容
    （「只概括治理架构与权责安排」），不冠以档位名。
    """
    template = _template(SSE_PACKAGE)
    definition = load_compiled_report_definition(SSE_PACKAGE)
    instance = _instance(with_intake=True)
    leaked: list[str] = []
    for block in template.iter_blocks():
        if block.blockType not in ("generative", "constrained"):
            continue
        try:
            ctx = build_model_context(block, template, instance, definition=definition)
            system, user = render_prompt(ctx, n=1)
        except Exception:  # noqa: BLE001 - 装配不出上下文的块不在本断言范围
            continue
        if any(term in system + user for term in TIER_TERMS):
            leaked.append(block.id)
    assert not leaked, f"以下块的 prompt 泄漏了产品档位名：{leaked[:8]}"


def test_product_tier_never_appears_in_model_facing_package_data():
    """档位名不得出现在任何进模型的包数据里。

    上一条按块渲染 paragraph prompt，覆盖不到 module_title_generation 这类独立提示词路径
    （实测：把档位名塞回 prompt_profile 的 tone，上一条仍全绿）。故本条直接扫进模型的数据面：
    prompt_profile 全文、写作口径与指标术语解释。注释行不算——它们不进上下文。
    """
    leaked: list[str] = []
    for package_id in ("sse_zh_hans", "hkex_zh_hant", "hkex_en"):
        root = KNOWLEDGE_PACKAGES_ROOT / package_id
        for path in [root / "prompt_profile.yaml", root / "quantitative_metrics.json"] + sorted(
            (root / "topic_sections").glob("*.yaml")
        ) + [root / "report_contract.yaml"]:
            if not path.is_file():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if any(term in line for term in TIER_TERMS) or TIER_PATTERN.search(line):
                    leaked.append(f"{path.name}:{lineno}")
    assert not leaked, f"以下进模型的包数据含产品档位名：{leaked[:8]}"


def test_standard_disclosure_requirements_never_enter_prompt():
    """准则披露要求不注入生成上下文：任何块的 System 都不得出现该 typed 片段。

    2026-09-07 A/B 裁决：sse 包无可测收益（39 配对块 clean 率打平），gri 包有害
    （模型把无事实支撑的要求写成「本报告未包含…」，触发在线守卫并阻断一个块）。
    standardDisclosureRequirementKeys 仍是数据资产（加载期校验、诊断与覆盖审计消费），
    但不进生成上下文：条款编号是审计事实，不是模型判断的依据。
    """
    for block_id in ("climate.gov_structure", "climate.strategy_physical_risk"):
        block = _template(SSE_PACKAGE).find_block(block_id)
        ctx = build_model_context(
            block,
            _template(SSE_PACKAGE),
            _instance(with_intake=True),
            definition=load_compiled_report_definition(SSE_PACKAGE),
        )
        system, user = render_prompt(ctx, n=1)
        blob = "\n".join((system, user))
        assert "<standard_disclosure_requirements>" not in blob
        assert "准则披露要求" not in blob
        assert "描述识别出的气候相关风险和机遇" not in blob


def test_writing_granularity_enters_system_with_substantive_inputs():
    """写作口径作为独立 XML 段进入 System；只随实质输入出现，不进 User。"""
    block = _template(SSE_PACKAGE).find_block("climate.strategy_physical_risk")
    system, user = render_prompt(
        build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)),
        n=1,
    )

    assert "<writing_granularity>" in system
    assert "气候风险表应保持整表行文一致" in system
    assert "simplifiedWritingGuidance" not in system
    assert "气候风险表应保持整表行文一致" not in user


def test_appendix_clause_original_text_does_not_enter_prompt():
    """用户可见批注条款原文来自附录索引表，不进入模型 Prompt。"""
    clause = load_user_visible_disclosure_clause_annotations(SSE_PACKAGE)[0].clauseOriginalTexts[0].clauseOriginalText
    sentinel = "支持美丽中国建设"
    assert sentinel in clause
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    system, user = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)), n=1)
    assert sentinel not in system
    assert sentinel not in user


def test_standard_disclosure_requirement_internal_fields_do_not_enter_prompt():
    """准则披露要求的内部 key、来源标签与结构字段在任何路径下不得进入 Prompt。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    system, user = render_prompt(
        build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)),
        n=1,
    )
    blob = "\n".join((system, user))
    for forbidden in (
        "standardDisclosureRequirementKey",
        "sourceClauseReferenceLabels",
        "topicStandardDisclosureRequirementGroups",
        "sourceClauseReference",
        "clauseRef",
        "excerptFrom",
        "provenance",
        "industryBenchmarkWritingPatternBranch",
        "intakeAnswerSelectionsActivatingBranch",
    ):
        assert forbidden not in blob


def test_length_segment_from_target_chars():
    """普通段落只向模型提供上限，合同仍保留完整 targetChars 供软诊断。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, _user = render_prompt(ctx, n=1)
    assert ctx.length == (250, 500)
    assert "<length>" in system and "500" in system
    assert "250" not in system
    assert "不为达到篇幅补充导语或总结" in system


def test_structured_output_contract_is_separate_from_content_format() -> None:
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    system, _user = render_prompt(
        build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)),
        n=1,
    )

    assert "<output_contract>" in system
    assert "根对象包含 variants" in system
    assert "每个 content" in system
    assert "<content_format>" in system
    assert "content 字段" in system
    assert "仅输出连续正文" not in system
    assert "final_result" not in system


def test_filled_content_holds_user_intake_only():
    """填了清单：User 的 <filled_content> 以 <item> 承载作答；System 不含作答内容。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True))
    system, user = render_prompt(ctx, n=1)
    assert "<filled_content>" in user and "<item>" in user, "作答未以 XML item 进 filled_content"


def test_empty_filled_content_states_plain_fact():
    """未填清单：User 只保留空结构；事实状态由 EvidencePosture 单点拥有。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    ctx = build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False))
    _system, user = render_prompt(ctx, n=1)
    assert user == "<filled_content />"
    assert "本节用户未填写内容" not in user
    assert "标杆" not in user and "行业" not in user, "User 不应含走标杆指令"


def test_no_substantive_input_paragraph_prompt_requires_one_short_paragraph():
    """无实质用户事实时，段落生成的全局格式规则进入 System，不进入 User。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    system, user = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False)), n=1)

    assert "形成一个简短自然段" in system
    assert "形成一个简短自然段" not in user


def test_removed_generic_rules_do_not_leak_into_unrelated_topic_prompt():
    """员工规范不再作为混合全局规则注入气候表格。"""
    block = _template(SSE_PACKAGE).find_block("climate.strategy_physical_risk")
    system, user = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)), n=1)

    assert "员工议题以权益保障" not in system
    assert "<public_disclosure_guidance>" in system
    assert "企业具体资料用于判断风险方向" in system
    assert "风险颗粒度与当前证据强度保持一致" in system
    assert "员工议题以权益保障" not in user
    assert "ESG_SOCIAL_SENSITIVE_PATTERNS" not in system
    assert "regex:" not in system


def test_substantive_input_paragraph_prompt_does_not_limit_to_two_paragraphs():
    """有实质用户事实时，不注入无资料段落上限。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    system, user = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)), n=1)

    assert "最多输出两段" not in system
    assert "最多输出两段" not in user


def test_evidence_posture_switches_while_generation_task_stays_stable():
    """事实强度由 EvidencePosture 切换；GenerationTask 不再复制有料/缺料任务。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    sys_have, _ = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)), n=1)
    sys_none, _ = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False)), n=1)
    focus = "说明气候相关事项的监督责任、职责分工和协调安排。"
    assert "证据级别：block_facts" in sys_have
    assert "证据级别：context_only" in sys_none
    assert focus in sys_have and focus in sys_none


def test_text_missing_markers_do_not_become_evidence_but_descriptions_and_supplements_do() -> None:
    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.strategy_physical_risk")

    def context_for(answer: str, supplement: str | None = None):
        report = _instance(with_intake=False)
        report.intakeItems = [
            item.model_copy(update={"answer": answer, "supplement": supplement})
            if item.key == "climate.q_strategy_content"
            else item
            for item in report.intakeItems
        ]
        return build_model_context(block, template, report)

    for marker in ("无", "无相关资料", "暂无", "暂无。", "暂未填写", "没有", "否", "不确定"):
        context = context_for(marker)
        _system, user = render_prompt(context, n=1)
        assert context.evidence.substantive_input_present is False
        assert context.evidence.intake_facts == ()
        assert user == "<filled_content />"

    descriptive = context_for("暂未形成专项计划，目前由生产团队结合日常工作推进节能改造。")
    assert descriptive.evidence.substantive_input_present is True
    assert descriptive.evidence.intake_facts[0].text.startswith("暂未形成专项计划")

    # 补充说明与答案本体结构分离：supplement 作为用户原话备注进 Material.note，
    # 渲染为 <item> 内独立的「用户说明」行，模型据此区分企业事实与用户备注。
    supplemented = context_for("不确定", "生产团队结合日常工作推进节能改造。")
    assert supplemented.evidence.substantive_input_present is True
    assert supplemented.evidence.intake_facts[0].text == ""
    assert supplemented.evidence.intake_facts[0].note == "生产团队结合日常工作推进节能改造。"
    _system, user = render_prompt(supplemented, n=1)
    assert "用户说明：生产团队结合日常工作推进节能改造。" in user
    # supplement-only 的 <item> 不残留空事实行。
    assert "<item>\n填写项：" in user and "\n\n用户说明" not in user


def test_negative_status_supplement_is_rendered_as_user_note_with_posture_guidance() -> None:
    """否定性状态说明进入「用户说明」行；System 侧 evidence posture 声明其口径语义。"""

    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.strategy_physical_risk")
    report = _instance(with_intake=False)
    report.intakeItems = [
        item.model_copy(
            update={
                "answer": "不确定",
                "supplement": "公司暂未发布专门的气候管理制度，日常由行政部关注能耗。",
            }
        )
        if item.key == "climate.q_strategy_content"
        else item
        for item in report.intakeItems
    ]
    context = build_model_context(block, template, report)
    system, user = render_prompt(context, n=1)
    assert "用户说明：公司暂未发布专门的气候管理制度" in user
    # 元指令在 System 的证据姿态段：状态说明只定口径，正文不得出现缺失类陈述。
    # 该口径归入「当前事实不足、不恰当或不适用」情形，不再单列并列条款。
    assert "「暂无」「暂未」「尚未」类状态说明属于此种情形，只用于确定披露口径" in system
    assert "正文不写成缺失、未做类陈述" in system


def test_climate_no_input_branch_does_not_inject_benchmark_paragraph():
    """气候治理无输入时沿用统一 context-only 合同，不注入预写实践段落。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    sys_have, _user_have = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=True)), n=1)
    assert "<industry_benchmark_writing_pattern_reference>" not in sys_have

    sys_none, user_none = render_prompt(build_model_context(block, _template(SSE_PACKAGE), _instance(with_intake=False)), n=1)
    assert "<industry_benchmark_writing_pattern_reference>" not in sys_none
    assert "公司将气候相关事项纳入日常经营管理关注范围" not in sys_none
    assert user_none == "<filled_content />"


def test_context_only_calibration_uses_report_tone_not_consulting_advice() -> None:
    template = _template(SSE_PACKAGE)
    report = _instance(with_intake=False)

    strategy_block = template.find_block(
        "innovation_driven.strategy_rd_strategy_innovation_philosophy"
    )
    strategy_ctx = build_model_context(strategy_block, template, report)
    strategy_system, _ = render_prompt(strategy_ctx, n=1)

    governance_block = template.find_block(
        "rural_revitalization_social_contribution.gov_responsibility_department"
    )
    governance_ctx = build_model_context(governance_block, template, report)
    governance_system, _ = render_prompt(governance_ctx, n=1)

    assert "<context_only_calibration>" in strategy_system
    assert "公司将基础能力积累与经营质量改善作为长期关注方向" in strategy_system
    assert "后续可将基础能力积累与经营质量改善作为关注方向" not in strategy_system
    assert "建议企业后续做什么" in strategy_system
    assert "<context_only_calibration>" in governance_system
    assert "公司结合日常经营管理需要，持续关注相关基础事项" in governance_system
    assert "建议公司" not in governance_system
    assert "后续可" not in governance_system
    assert "可考虑" not in governance_system


def test_context_only_calibration_covers_iro_but_not_metric_narrative() -> None:
    template = _template(SSE_PACKAGE)
    report = _instance(with_intake=False)

    iro_block = template.find_block(
        "product_quality_safety.iro_lifecycle_quality_safety_controls"
    )
    iro_system, _ = render_prompt(build_model_context(iro_block, template, report), n=1)
    metric_block = template.find_block("innovation_driven.metrics_narrative_body")
    metric_system, _ = render_prompt(
        build_model_context(metric_block, template, report),
        n=1,
    )

    assert "<context_only_calibration>" in iro_system
    assert "持续关注适用的风险识别与改进方向" in iro_system
    assert "<context_only_calibration>" not in metric_system


def test_common_governance_content_projects_only_user_fact():
    """common 治理文本题有内容时只投影用户事实，不出现历史预写参考。"""
    block = _template(SSE_PACKAGE).find_block("climate.gov_structure")
    report = _instance(with_intake=False)
    report.intakeItems = [
        item.model_copy(update={"answer": "由其他部门或岗位兼管", "supplement": "由现有人员结合职责推进"})
        if item.key == "climate.q_governance_roles" else item
        for item in report.intakeItems
    ]
    ctx = build_model_context(block, _template(SSE_PACKAGE), report)
    system, user = render_prompt(ctx, n=1)
    assert "<industry_benchmark_writing_pattern_reference>" not in system
    assert "由现有人员结合职责推进" in user
    assert ctx.evidence_posture.level == "block_facts"
    assert ctx.section_task.endswith("说明气候相关事项的监督责任、职责分工和协调安排。")


def test_preset_catalog_table_fill_prompt_puts_anchors_in_system_only():
    """preset_catalog 表整表填充 prompt：类型/名称锚点与参考口径入 System、User 仅 filled_content。"""
    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.strategy_physical_risk")
    ctx = build_model_context(block, template, _instance(with_intake=False))
    catalog_rows = [
        {"phys_type": "急性风险", "phys_name": "台风", "referenceImpact": "台风可能破坏设施并引发停工"},
        {"phys_type": "急性风险", "phys_name": "暴雨", "referenceImpact": "暴雨影响供应链运输"},
    ]
    system, user = render_catalog_table_fill_prompt(
        ctx, catalog_rows, block.table.colDefs, kind_label="风险",
    )
    # 类别、锚点名称、参考口径入 System；正向高信号（结合主营业务与行业），不进 User（User 仅 filled_content）。
    assert "急性风险" in system and "台风" in system and "台风可能破坏设施并引发停工" in system
    assert "主营业务" in system and "所属行业" in system
    assert "phys_name" not in system and "referenceImpact" not in system
    assert "台风" not in user and user.startswith("<filled_content")
    assert "最多输出两段" not in system
    assert "最多输出两段" not in user


def test_catalog_table_prompt_uses_opportunity_kind_from_table_contract():
    """目录表整表 prompt 的条目类型来自 table.iroKind，避免机遇表沿用风险口径。"""
    template = _template(SSE_PACKAGE)
    block = template.find_block("climate.strategy_opportunity")
    instance = _instance(with_intake=False)
    ctx = build_model_context(block, template, instance)
    anchors, _ = _anchor_ai_split(block.table.colDefs)
    group_key, id_key = anchors[0].key, anchors[-1].key
    catalog_rows = [
        {group_key: seed.category or "", id_key: seed.theme, "referenceImpact": seed.referenceImpact}
        for seed in block.generation.fixedRowSeeds[:2]
    ]
    system, user = render_catalog_table_fill_prompt(
        ctx, catalog_rows, block.table.colDefs, kind_label=_table_kind_label(block, instance),
    )
    assert "下列机遇条目" in system
    assert "下列风险条目" not in system
    assert "机遇" not in user and user.startswith("<filled_content")


def test_front_chapter_blocks_know_which_section_they_write() -> None:
    """前四章块必须拿到章节位置：编译定义对它们恒为空，须回落 Section 树。

    跨章节复述的唯一防线是提示词（如 report_contract.yaml 中「法人治理结构属公司
    治理章节，不得在此复述」），而消费该提示词的块若不知道自己在写哪一节，
    这层防线形同虚设。
    """
    from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
    from sustainability_desk.llm.generate import _template

    template = _template(SSE_PACKAGE)
    instance = template.model_copy(deep=True)
    definition = load_compiled_report_definition(SSE_PACKAGE)
    for block_id, expected in (
        ("gov.structure_intro", "治理架构与权责体系"),
        ("sm.gov_arch_overview", "可持续发展治理架构"),
    ):
        ctx = build_model_context(
            instance.find_block(block_id), template, instance, definition=definition
        )
        assert ctx.section_placement is not None, block_id
        assert ctx.section_placement.reportSectionTitle == expected
        system, _user = render_prompt(ctx, n=1)
        assert expected in system
    # 议题块仍走编译定义，支柱位置不因回落而丢失。
    topic_ctx = build_model_context(
        instance.find_block("anti_bribery_anti_corruption.gov_structure_responsibilities"),
        template,
        instance,
        definition=definition,
    )
    assert topic_ctx.section_placement is not None
    assert topic_ctx.section_placement.pillarTitle == "治理"
