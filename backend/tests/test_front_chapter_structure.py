# ABOUTME: 前四章轻量版结构回归测试，约束基础章节的生成块数量、输入消费与显隐边界。
# ABOUTME: 这些章节不走 topic_sections；测试直接读取 report_contract.yaml，防止 Word 模板式多块重复消费回流。

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.visibility import visible
from knowledge_package_fixtures import SSE_PACKAGE

CONTRACT = SSE_PACKAGE.report_contract_path


def _visible_blocks(section, report):
    out = []

    def walk(sec):
        if not visible(sec, report):
            return
        for block in sec.blocks or []:
            if visible(block, report):
                out.append(block)
        for child in sec.children or []:
            walk(child)

    walk(section)
    return out


def _visible_generation_blocks(section, report):
    return [
        block
        for block in _visible_blocks(section, report)
        if block.blockType in {"generative", "constrained"} and block.generation
    ]


def test_lightweight_governance_uses_one_generation_block_for_articles() -> None:
    """第三章轻量版只用一个生成块消费公司章程，避免逐层重复复述同一输入。"""
    report = load_contract(CONTRACT)
    section = next(sec for sec in report.sections if sec.key == "governance")

    blocks = _visible_generation_blocks(section, report)

    assert [block.id for block in blocks] == ["gov.structure_intro"]
    assert blocks[0].generation.inputs.evidence.intakeItems == ["articles"]


def test_sustainability_governance_is_semantically_separated_from_corporate_governance() -> None:
    """两个治理块的语义边界必须可执行，不能只靠 intake 分离。

    回归：用户上传《公司章程》后，Mapping Agent 依据"章程为可持续发展
    治理提供法定治理机构的责任依据"把它采纳进 sm.gov_arch_overview，正文遂把股东会/
    董事会/监事会的法人治理运作机制写成可持续发展治理架构。契约侧 intake 本已分离，
    但 semantic_task 未表达层级语义、也无缺料分支，模型缺少判别标准。
    """
    report = load_contract(CONTRACT)
    sustainability = report.find_block("sm.gov_arch_overview")
    corporate = report.find_block("gov.structure_intro")

    # semantic_task 同时供 Mapping Agent 判断资料适用性与生成使用。
    focus = sustainability.generation.task.focus
    assert "决策层" in focus and "管理层" in focus and "执行层" in focus
    assert "不描述股东会、董事会、监事会的法人治理运作机制" in focus

    # 无用户输入时按三层通用职责生成，而不是抓取任何沾边资料。
    no_fact = sustainability.generation.task.noFactGuidance or ""
    assert "决策层" in no_fact and "执行层" in no_fact
    assert "不指名具体机构、部门、岗位、委员会名称或人数" in no_fact

    # 有资料时的互斥边界（simplifiedWritingGuidance 仅在存在实质事实时注入）。
    guidance = "\n".join(sustainability.generation.simplifiedWritingGuidance or [])
    assert "属于「公司治理」章节，不得在此复述" in guidance

    # 公司治理侧保持原语义：章程映射到这里是正确的。
    assert corporate.generation.inputs.evidence.intakeItems == ["articles"]
    assert (
        sustainability.generation.inputs.evidence.intakeItems
        == ["sustainability_governance_structure", "sustainability_governance_duties"]
    )


def test_lightweight_front_chapter_intake_inputs_are_not_repeated_within_section() -> None:
    """前四章同一可见章节内，一个 intake 不应被多个 LLM 块重复消费。"""
    report = load_contract(CONTRACT)
    front_keys = {"about_report", "company_intro", "governance", "sustainability_mgmt"}

    for section in [sec for sec in report.sections if sec.key in front_keys]:
        seen: dict[str, str] = {}
        for block in _visible_generation_blocks(section, report):
            for key in block.generation.inputs.evidence.intakeItems or []:
                assert key not in seen, f"{section.key}: {key} used by {seen[key]} and {block.id}"
                seen[key] = block.id


def test_about_report_uses_template_and_slots_not_llm_generation() -> None:
    """第一章是报告边界说明；轻量版不为固定开篇调用 LLM。"""
    report = load_contract(CONTRACT)
    section = next(sec for sec in report.sections if sec.key == "about_report")

    assert _visible_generation_blocks(section, report) == []


def test_lightweight_sustainability_management_has_governance_and_iro_generation_blocks() -> None:
    """第四章分别生成治理概览与评分确定范围内的 IRO 表，不重复消费内容清单。

    IRO 表只在存在财务/双重重要性议题时出现，故模板态（无 assessment）不含它。
    """
    from sustainability_desk.contract.models import AssessmentResult, ScoredAssessmentResult

    report = load_contract(CONTRACT)
    section = next(sec for sec in report.sections if sec.key == "sustainability_mgmt")

    # 模板态无评估结果：IRO 表不可见，只剩治理概览。
    blocks = _visible_generation_blocks(section, report)
    assert [block.id for block in blocks] == ["sm.strategy", "sm.gov_arch_overview"]
    assert blocks[0].generation.inputs.evidence.intakeItems == ["sustainability_strategy"]
    assert blocks[1].generation.inputs.evidence.intakeItems == [
        "sustainability_governance_structure",
        "sustainability_governance_duties",
    ]

    # 出现双重重要性议题后，IRO 表进入生成清单。
    scored = report.model_copy(
        update={
            "assessment": AssessmentResult(
                reportingYear=2025,
                topics=[
                    ScoredAssessmentResult(
                        determination="scored",
                        assessmentTopicId="climate_change",
                        materiality="dual",
                        financialScore=4.6,
                        impactScore=4.5,
                    )
                ],
            )
        }
    )
    section = next(sec for sec in scored.sections if sec.key == "sustainability_mgmt")
    blocks = _visible_generation_blocks(section, scored)
    assert [block.id for block in blocks] == ["sm.strategy", "sm.gov_arch_overview", "sm.iro_table"]
    assert blocks[2].table.rowSource == "assessment_iro"


def test_optional_board_meeting_slot_is_hidden_until_both_values_exist() -> None:
    """董事会会议次数和出席率是可选披露；未填写时不输出空 slot。"""
    report = load_contract(CONTRACT)
    block = report.find_block("gov.board_meetings")

    assert visible(block, report) is False

    report.fields["board_meeting_count"] = report.fields["board_meeting_count"].model_copy(update={"value": 5})
    assert visible(block, report) is False

    report.fields["board_attendance_rate"] = report.fields["board_attendance_rate"].model_copy(update={"value": "98%"})
    assert visible(block, report) is True


def test_iro_blocks_appear_only_when_a_financially_material_topic_exists() -> None:
    """IRO 引导段与 IRO 表以「存在财务/双重重要性议题」为显隐条件。

    没有这类议题时整组不出现——否则固定引导语会声称已梳理一批并不存在的议题，
    且表内只剩表头。行的取舍（哪些议题进表）与块的存废是两件事，此处锁后者。
    """
    from sustainability_desk.contract.models import AssessmentResult, ScoredAssessmentResult
    from sustainability_desk.contract.visibility import visible_block_in_report

    base = load_contract(CONTRACT)

    def _with(materiality: str):
        return base.model_copy(
            update={
                "assessment": AssessmentResult(
                    reportingYear=2025,
                    topics=[
                        ScoredAssessmentResult(
                            determination="scored",
                            assessmentTopicId="climate_change",
                            materiality=materiality,
                            financialScore=4.6 if materiality != "impact" else 2.0,
                            impactScore=4.5,
                        )
                    ],
                )
            }
        )

    for materiality, expected in [("dual", True), ("financial", True), ("impact", False), ("non", False)]:
        report = _with(materiality)
        for block_id in ("sm.iro_intro", "sm.iro_table"):
            assert visible_block_in_report(report, block_id) is expected, (
                f"materiality={materiality} 时 {block_id} 可见性应为 {expected}"
            )
