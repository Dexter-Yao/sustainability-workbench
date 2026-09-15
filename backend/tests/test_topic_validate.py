# ABOUTME: 议题配置加载期引用校验测试——跨文件引用（intakeItems/standardDisclosureRequirementKeys/appears_when）必须可解析，fail-loud 防漂移。
# ABOUTME: 守护「20 议题复用同一范式」的安全：作者 typo 一个 key 即报错，不静默少喂资料/披露。
from pathlib import Path

from sustainability_desk.contract.models import (
    Block,
    Condition,
    ConditionRule,
    DerivedVisualizationSpec,
    GenerationInputs,
    GenerationSpec,
    ImageModel,
    IntakeItem,
    Section,
)
import pytest
from pydantic import ValidationError

from sustainability_desk.llm.topic_validate import (
    validate_topic_refs,
    validate_topic_templates_or_raise,
    validate_unused_topic_intake,
)
from sustainability_desk.planner import load_topic_intake, load_topic_templates
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]


def _sec(block, topic_id="t"):
    return Section(key="s", title="S", headingLevel=2, reportSectionId=topic_id, blocks=[block])


def test_real_climate_config_passes():
    """真实气候配置全引用一致——无 dangling。"""
    templates = load_topic_templates(SSE_PACKAGE)
    keys = {i.key for i in load_topic_intake(SSE_PACKAGE) if i.contentScopeId == "climate_change"}
    assert validate_topic_refs(templates["climate_change"], keys, "climate_change", package=SSE_PACKAGE) == []


def test_generation_evidence_selector_rejects_unknown_or_mixed_fields():
    """证据选择器是严格判别联合，旧字段和未知字段不得静默通过。"""

    with pytest.raises(ValidationError):
        GenerationInputs.model_validate({"contentScopeId": "climate_change"})
    with pytest.raises(ValidationError):
        GenerationInputs.model_validate(
            {"evidence": {"kind": "report_section", "intakeItems": ["climate.q_governance_roles"]}}
        )


def test_report_section_selector_outside_concise_disclosure_is_rejected():
    block = Block(
        id="b",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(
            task={"focus": "b"},
            inputs=GenerationInputs(evidence={"kind": "report_section"}),
        ),
    )

    errors = validate_topic_refs(_sec(block), set(), "t", package=SSE_PACKAGE)

    assert errors and "仅适用于" in errors[0]


def test_dangling_intake_ref_flagged():
    block = Block(id="b", type="paragraph", blockType="generative", source="ai",
                  generation=GenerationSpec(task={"focus": "p"}, inputs=GenerationInputs(evidence={"kind": "explicit", "intakeItems":["nope"]})))
    errs = validate_topic_refs(_sec(block), {"real_key"}, "t", package=SSE_PACKAGE)
    assert errs and "nope" in errs[0]


def test_dangling_disclosure_ref_flagged():
    block = Block(id="b", type="paragraph", blockType="generative", source="ai",
                  generation=GenerationSpec(task={"focus": "p"}, standardDisclosureRequirementKeys=["climate.gov.does_not_exist"]))
    errs = validate_topic_refs(_sec(block, "climate_change"), set(), "climate_change", package=SSE_PACKAGE)
    assert errs and "does_not_exist" in errs[0]


def test_dangling_appears_when_intake_ref_flagged():
    block = Block(id="b", type="paragraph", blockType="generative", source="ai",
                  generation=GenerationSpec(task={"focus": "p"}),
                  appears_when=Condition(all=[ConditionRule(path="intakeItems.ghost", op="exists")]))
    errs = validate_topic_refs(_sec(block), {"real"}, "t", package=SSE_PACKAGE)
    assert errs and "ghost" in errs[0]


def test_dangling_derived_visualization_metric_ref_flagged():
    block = Block(
        id="b",
        type="image",
        blockType="fixed",
        source="derived",
        image=ImageModel(
            derivedVisualization=DerivedVisualizationSpec(
                kind="quantitative_metric_summary",
                metricKeys=["missing_metric"],
            )
        ),
    )

    errs = validate_topic_refs(_sec(block), set(), "t", package=SSE_PACKAGE)

    assert errs and "missing_metric" in errs[0]


def test_valid_refs_pass():
    block = Block(id="b", type="paragraph", blockType="generative", source="ai",
                  generation=GenerationSpec(task={"focus": "p"}, inputs=GenerationInputs(evidence={"kind": "explicit", "intakeItems":["k1"]}),
                                            standardDisclosureRequirementKeys=["climate.gov.*"]),
                  appears_when=Condition(all=[ConditionRule(path="intakeItems.k1", op="exists")]))
    assert validate_topic_refs(_sec(block, "climate_change"), {"k1"}, "climate_change", package=SSE_PACKAGE) == []


def test_template_collection_validation_fails_loud():
    block = Block(id="b", type="paragraph", blockType="generative", source="ai",
                  generation=GenerationSpec(task={"focus": "p"}, standardDisclosureRequirementKeys=["climate.gov.does_not_exist"]))
    with pytest.raises(ValueError, match="does_not_exist"):
        validate_topic_templates_or_raise({"climate_change": _sec(block, "climate_change")}, [], package=SSE_PACKAGE)


def test_topic_specific_unused_intake_ref_flagged():
    item = IntakeItem(key="t.q_custom", contentScopeId="t", prompt="P", kind="text")
    block = Block(
        id="b",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(task={"focus": "p"}),
    )

    errs = validate_unused_topic_intake(_sec(block), {"t.q_custom": item}, "t")

    assert errs and "t.q_custom" in errs[0]


def test_common_fixed_unused_intake_is_not_flagged_by_orphan_check():
    items = {
        key: IntakeItem(key=key, contentScopeId="t", prompt="P", kind="text")
        for key in (
            "t.q_governance_roles",
            "t.q_governance_policies",
            "t.q_governance_certifications",
            "t.q_strategy_content",
        )
    }
    block = Block(
        id="b",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(task={"focus": "p"}),
    )

    assert validate_unused_topic_intake(_sec(block), items, "t") == []


def test_removed_metrics_supplement_is_flagged_when_unused():
    item = IntakeItem(key="t.q_metrics_supplement", contentScopeId="t", prompt="P", kind="text")
    block = Block(
        id="b",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation=GenerationSpec(task={"focus": "p"}),
    )

    errs = validate_unused_topic_intake(_sec(block), {"t.q_metrics_supplement": item}, "t")

    assert errs and "t.q_metrics_supplement" in errs[0]
