# ABOUTME: 议题语义深度专项的生成配置合同测试，防止非指标块混入指标段写作边界。
# ABOUTME: 只验证 agent-readable 配置分层，不调用模型或读取前端 artifact。
from pathlib import Path


from sustainability_desk.contract.models import Block, Field, Report, Section
from sustainability_desk.llm.prompts import build_model_context
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]

def _walk_blocks(section: Section):
    yield from section.blocks or []
    for child in section.children or []:
        yield from _walk_blocks(child)


def _load_topic(topic_id: str) -> Section:
    path = SSE_PACKAGE.topic_sections_dir / f"{topic_id}.yaml"
    return load_topic_templates_from(path.parent, package=SSE_PACKAGE)[path.stem]


def _is_metric_block(block: Block) -> bool:
    generation = block.generation
    inputs = generation.inputs if generation else None
    return bool(inputs and getattr(inputs.evidence, "quantitativeMetrics", None))


def test_all_topics_keep_metric_guidance_out_of_non_metric_blocks() -> None:
    for path in sorted((SSE_PACKAGE.topic_sections_dir).glob("*.yaml")):
        section = _load_topic(path.stem)
        for block in _walk_blocks(section):
            generation = block.generation
            if not generation or _is_metric_block(block):
                continue

            guidance = "\n".join(generation.simplifiedWritingGuidance or [])

            assert "轻量版指标段" not in guidance, block.id
            assert "报告期数值" not in guidance, block.id


def test_all_mapped_metric_narratives_share_compact_target_length() -> None:
    metric_blocks: list[Block] = []
    for path in sorted((SSE_PACKAGE.topic_sections_dir).glob("*.yaml")):
        section = _load_topic(path.stem)
        metric_blocks.extend(block for block in _walk_blocks(section) if _is_metric_block(block))

    assert len(metric_blocks) == 16
    for block in metric_blocks:
        assert block.generation is not None
        assert block.generation.targetChars == (60, 160), block.id


def test_supply_chain_and_data_security_no_input_context_omits_block_specific_guidance() -> None:
    sections = (
        _load_topic("sustainable_supply_chain_management"),
        _load_topic("data_security_customer_privacy_protection"),
    )
    fields = {
        "company_short_name": Field(
            key="company_short_name", label="公司简称", type="string", source="user_input", value="测试公司"
        ),
        "industry": Field(key="industry", label="所属行业", type="string", source="derived", value="制造业"),
    }
    expected = {
        "sustainable_supply_chain_management.gov_governance_structure_responsibilities",
        "sustainable_supply_chain_management.strategy_targets",
        "sustainable_supply_chain_management.iro_resilience_risk_management",
        "sustainable_supply_chain_management.iro_supplier_training_and_capacity_building",
        "data_security_customer_privacy_protection.gov_security_management_system",
        "data_security_customer_privacy_protection.strategy_security_targets",
        "data_security_customer_privacy_protection.iro_customer_information_protection_controls",
    }

    for section in sections:
        report = Report(knowledgePackageId=SSE_PACKAGE.id, title="测试报告", fields=fields, sections=[section])
        for block in _walk_blocks(section):
            if block.id not in expected:
                continue
            context = build_model_context(block, report, report)
            guidance = "\n".join(context.writing_granularity)
            assert guidance == ""
            assert context.evidence_posture.level == "context_only"
            assert context.pillar_purpose is not None


def test_environment_governance_and_training_guidance_keeps_topic_terms_precise() -> None:
    climate = _load_topic("climate_change")
    energy = _load_topic("energy_management")
    pollutant = _load_topic("pollutant_emissions_management")
    blocks = {block.id: block for section in (climate, energy, pollutant) for block in _walk_blocks(section)}

    climate_gov_guidance = "\n".join(blocks["climate.gov_structure"].generation.simplifiedWritingGuidance or [])
    assert "ISO 50001" in climate_gov_guidance
    assert "ISO 14064-1" in climate_gov_guidance
    assert "依据该标准开展或完成温室气体核查" in climate_gov_guidance

    climate_training_guidance = "\n".join(blocks["climate.iro_training"].generation.simplifiedWritingGuidance or [])
    assert "绿色低碳、温室气体减排" in climate_training_guidance

    energy_task = blocks["energy_management.gov_system_framework"].generation.task
    assert energy_task.noFactGuidance is None
    assert "机构" not in energy_task.focus

    pollutant_task = blocks["pollutant_emissions_management.gov_responsibility_structure"].generation.task
    assert pollutant_task.noFactGuidance is None
    assert "专门部门" not in pollutant_task.focus
    assert "节能减排" not in pollutant_task.focus


def test_social_topic_guidance_keeps_adjacent_topics_and_objects_separate() -> None:
    anti_bribery = _load_topic("anti_bribery_anti_corruption")
    human_capital = _load_topic("human_capital_development")
    customer_service = _load_topic("customer_service_quality_management")
    blocks = {
        block.id: block
        for section in (anti_bribery, human_capital, customer_service)
        for block in _walk_blocks(section)
    }

    anti_gov = "\n".join(blocks["anti_bribery_anti_corruption.gov_structure_responsibilities"].generation.simplifiedWritingGuidance or [])
    assert "按补充说明解析为相应职能、人员或岗位安排" in anti_gov
    anti_training = "\n".join(blocks["anti_bribery_anti_corruption.iro_integrity_training"].generation.simplifiedWritingGuidance or [])
    assert "供应商对接相关人员" in anti_training
    assert "内外部培训范围以用户事实为准" in anti_training

    human_gov = "\n".join(blocks["human_capital_development.gov_workforce_governance"].generation.simplifiedWritingGuidance or [])
    assert "员工权益保护、福利保障、职业发展支持" in human_gov
    human_iro = "\n".join(blocks["human_capital_development.iro_employee_rights_and_inclusion"].generation.simplifiedWritingGuidance or [])
    assert "帮扶对象和支持内容来自本块用户事实" in human_iro
    assert "员工权益、平等机会、包容环境和职业发展支持" in human_iro

    customer_strategy = "\n".join(blocks["customer_service_quality_management.strategy_customer_centric_service"].generation.simplifiedWritingGuidance or [])
    assert "服务能力、交付履约、服务响应、客诉闭环" in customer_strategy
    assert "客户类型按用户资料概括为主要客户群体或相关客户" in customer_strategy
    assert "运行机制、目标和成效的具体程度" not in customer_strategy
