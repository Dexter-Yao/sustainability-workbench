# ABOUTME: 议题指标支柱派生图守护——声明 ESG 定量指标的 metrics 支柱必须配置确定性 PNG 图。
# ABOUTME: 防止新增指标与目标生成块只进 LLM 上下文、没有同步进入用户可见 artifact。
from pathlib import Path

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from

BACKEND = Path(__file__).resolve().parents[1]
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir


def _walk(section):
    yield section
    for child in section.children or []:
        yield from _walk(child)


def test_metrics_sections_with_quantitative_metrics_have_derived_summary_images():
    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    checked: set[str] = set()
    for topic in templates.values():
        for section in _walk(topic):
            visualized: set[str] = set()
            for block in section.blocks:
                spec = block.image.derivedVisualization if block.image and block.image.derivedVisualization else None
                if spec and spec.kind == "quantitative_metric_summary":
                    visualized.update(spec.metricKeys)
            if not visualized:
                continue
            checked.add(section.key)
            narrative = next(
                block
                for block in section.blocks
                if block.id.endswith(".metrics_narrative_body")
            )
            inputs = narrative.generation.inputs
            assert set(inputs.evidence.quantitativeMetrics or []) == visualized

    assert checked == {
        "anti_bribery_anti_corruption.metrics",
        "anti_unfair_competition.metrics",
        "climate_change.metrics",
        "customer_service_quality_management.metrics",
        "data_security_customer_privacy_protection.metrics",
        "energy_management.metrics",
        "human_capital_development.metrics",
        "innovation_driven.metrics",
        "occupational_health_safety.metrics",
        "pollutant_emissions_management.metrics",
        "product_quality_safety.metrics",
        "risk_management.metrics",
        "rural_revitalization_social_contribution.metrics",
        "sustainable_supply_chain_management.metrics",
        "waste_management.metrics",
        "water_resource_management.metrics",
    }


def test_metric_summary_images_carry_no_caption():
    """指标摘要图不设题注：所属议题与「指标与目标」小节标题已给全该图的身份。

    该图是小节内唯一一幅，题注只会把上两级标题再念一遍。
    """

    templates = load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE)
    captioned: list[str] = []
    summaries = 0
    for topic in templates.values():
        for section in _walk(topic):
            for block in section.blocks:
                image = block.image
                spec = image.derivedVisualization if image else None
                if spec is None or spec.kind != "quantitative_metric_summary":
                    continue
                summaries += 1
                if image.caption is not None:
                    captioned.append(block.id)

    assert summaries > 0, "指标摘要图消失了，本断言会静默通过——先确认图还在"
    assert captioned == []
