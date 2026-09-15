# ABOUTME: IRO 管理支柱测试——climate.iro 装配、轻量版仅保留减排实践 generative + 培训 constrained。
# ABOUTME: 清单接线（inputs.evidence.intakeItems）、减排 5→1 收敛、培训与减排实践按填写内容显隐。
from pathlib import Path

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir
CONTRACT = SSE_PACKAGE.report_contract_path

OLD_GRANULAR = [
    "climate.iro_zero_carbon", "climate.iro_sustainable_supply_chain_management", "climate.iro_product_footprint",
    "climate.iro_reduction", "climate.iro_green_case",
]


def _iro():
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    return next(c for c in templates["climate_change"].children if c.key == "climate.iro")


def _subsection(key):
    return next(section for section in _iro().children or [] if section.key == key)


def _block(bid):
    return next(block for section in _iro().children or [] for block in section.blocks if block.id == bid)


def test_iro_after_strategy():
    """climate.iro 在 climate.strategy 之后挂入。"""
    children = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)["climate_change"].children
    keys = [c.key for c in children]
    assert keys.index("climate.strategy") < keys.index("climate.iro")
    assert _iro().headingLevel == 3


def test_iro_reduction_practice_collapsed_generative():
    """减排细颗粒 5 块收敛为 1 个 generative 块，并由独立实践问题负责。"""
    blk = _block("climate.iro_reduction_practice")
    assert blk.blockType == "generative"
    assert blk.generation.inputs.evidence.intakeItems == ["climate.q_reduction_practices"]
    section = _subsection("climate.iro.reduction_practice")
    rule = section.appears_when.all[0]
    assert rule.path == "intakeItems.climate.q_reduction_practices"
    assert rule.op == "contains_any"
    assert "节能" in rule.value and "减排" in rule.value
    assert blk.appears_when is None
    ids = {block.id for child in _iro().children or [] for block in child.blocks}
    assert "climate.iro_risk_management" not in ids
    for old in OLD_GRANULAR:
        assert old not in ids, f"细颗粒块 {old} 应已收敛移除"


def test_iro_reduction_practice_keeps_only_topic_specific_guidance():
    blk = _block("climate.iro_reduction_practice")
    guidance = "\n".join(blk.generation.simplifiedWritingGuidance or [])

    assert "实践的具体程度与本块用户事实一致" not in guidance
    assert "温室气体减排、低碳运营" in guidance
    assert "产品全生命周期碳足迹管理" not in guidance


def test_iro_reduction_practice_visibility_requires_action_terms():
    """宽泛战略文本不显示减排实践；明确节能减排行动文本才显示。"""
    from sustainability_desk.contract.models import IntakeItem, Report
    from sustainability_desk.contract.visibility import visible

    section = _subsection("climate.iro.reduction_practice")

    def _rep(answer):
        return Report(knowledgePackageId=SSE_PACKAGE.id, 
            title="t",
            intakeItems=[
                IntakeItem(
                    key="climate.q_reduction_practices",
                    contentScopeId="climate_change",
                    prompt="q",
                    kind="text",
                    answer=answer,
                )
            ],
            sections=[],
        )

    assert visible(section, _rep("公司关注气候相关风险与机遇，逐步完善战略管理。")) is False
    assert visible(section, _rep("公司推进节能改造和能源效率提升，降低运营环节资源消耗。")) is True


def test_iro_training_constrained_hidden_unless_conducted():
    """培训 constrained，由培训活动题控制显隐。"""
    from sustainability_desk.contract.models import IntakeItem, Report
    from sustainability_desk.contract.visibility import visible

    blk = _block("climate.iro_training")
    assert blk.blockType == "constrained"
    assert blk.generation.inputs.evidence.intakeItems == ["climate.q_training_activities"]
    section = _subsection("climate.iro.training")
    rule = section.appears_when.all[0]
    assert rule.path == "intakeItems.climate.q_training_activities"
    assert rule.op == "eq" and rule.value == "是"
    assert blk.appears_when is None

    def _rep(answer):
        items = [IntakeItem(
            key="climate.q_training_activities",
            contentScopeId="climate_change",
            prompt="q",
            kind="single_select",
            options=["是", "否", "不确定"],
            answer=answer,
        )]
        return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", intakeItems=items, sections=[])

    assert visible(section, _rep(None)) is False       # 未作答 → 隐藏
    assert visible(section, _rep("否")) is False
    assert visible(section, _rep("是")) is True
