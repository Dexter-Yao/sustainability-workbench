# ABOUTME(en): Guards the typed identities a knowledge package must declare: pillar ids on topic H3s,
# ABOUTME(en): dimension ids in the registry, the assessment vocabulary and the disclosure basis shape.
from __future__ import annotations

import pytest
import yaml

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import DisclosureBasis, MainlandStandardNames
from sustainability_desk.contract.loader import assessment_vocabulary, load_package_contract
from sustainability_desk.contract.models import PILLARS, SOURCE_PILLARS
from sustainability_desk.contract.topic_registry import ReportModuleRef, load_topic_contract
from sustainability_desk.contract.topic_section_template import TopicSectionTemplate
from sustainability_desk.quantitative_metrics import quantitative_metric_sheets


def _template_payload(children: list[dict]) -> dict:
    return {
        "section": {
            "key": "x",
            "title": "X",
            "headingLevel": 2,
            "reportSectionId": "x",
            "conciseDisclosure": {
                "id": "x.concise_summary",
                "type": "paragraph",
                "blockType": "constrained",
                "source": "ai",
                "generation": {"task": {"focus": "摘要"}},
            },
            "children": children,
        },
        "metricDisclosure": {"catalogMetricKeys": []},
    }


def _pillar_children(*, titles=None, pillars=SOURCE_PILLARS) -> list[dict]:
    titles = titles or [SSE_PACKAGE.manifest.pillar_titles.title(p) for p in pillars]
    return [
        {"key": f"x.{pillar}", "title": title, "pillar": pillar, "headingLevel": 3}
        for pillar, title in zip(pillars, titles, strict=True)
    ]


def test_source_template_requires_pillar_ids_in_order() -> None:
    children = _pillar_children()
    del children[0]["pillar"]
    with pytest.raises(ValueError, match="三个 H3"):
        TopicSectionTemplate.model_validate(_template_payload(children), context={"package": SSE_PACKAGE})

    reordered = _pillar_children(pillars=("strategy", "governance", "iro_management"))
    with pytest.raises(ValueError, match="三个 H3"):
        TopicSectionTemplate.model_validate(_template_payload(reordered), context={"package": SSE_PACKAGE})


def test_source_template_h3_titles_follow_the_package_pillar_titles() -> None:
    children = _pillar_children()
    children[1]["title"] = "策略"
    with pytest.raises(ValueError, match="知识包声明"):
        TopicSectionTemplate.model_validate(_template_payload(children), context={"package": SSE_PACKAGE})


def test_pillar_is_only_declared_on_h3() -> None:
    children = _pillar_children()
    children[0]["children"] = [
        {"key": "x.gov.unit", "title": "单元", "pillar": "governance", "headingLevel": 4}
    ]
    with pytest.raises(ValueError, match="不是 H3"):
        TopicSectionTemplate.model_validate(_template_payload(children), context={"package": SSE_PACKAGE})


def test_compiled_topic_blocks_carry_pillar_ids_and_the_metrics_title() -> None:
    definition = load_compiled_report_definition(SSE_PACKAGE)
    seen: set[str] = set()
    for contract in definition.generation_contracts.values():
        placement = definition.placement_for_block(contract.block_id)
        if placement.report_section_id is None or placement.pillar is None:
            continue
        assert placement.pillar in PILLARS
        assert placement.pillar_purpose is not None
        assert placement.pillar_purpose.pillar == placement.pillar
        assert placement.pillar_title == SSE_PACKAGE.manifest.pillar_titles.title(placement.pillar)
        seen.add(placement.pillar)
    assert seen == set(PILLARS)


def test_registry_dimensions_are_ids_with_package_labels() -> None:
    contract = load_topic_contract(SSE_PACKAGE)
    assert {dimension.id for dimension in contract.source.dimensions} == {
        "environment",
        "social",
        "governance",
    }
    assert {topic.dimension for topic in contract.source.assessmentTopics} <= set(contract.dimensionsById)
    assert contract.dimension_label("environment") == "环境"


def test_assessment_vocabulary_agrees_with_the_assessment_table_options() -> None:
    vocabulary = assessment_vocabulary(SSE_PACKAGE)
    contract = load_package_contract(SSE_PACKAGE)
    iro_table = contract.find_block("sm.iro_table").table
    iro_class_options = set(
        next(col for col in iro_table.colDefs if col.key == "iro_class").options
    )
    assert set(vocabulary.impactClass.model_dump().values()) <= iro_class_options
    assert {vocabulary.iroKind.risk, vocabulary.iroKind.opportunity} <= iro_class_options
    topic_table = contract.find_block("sm.topic_table").table
    materiality_options = set(
        next(col for col in topic_table.colDefs if col.key == "topic_materiality").options
    )
    assert set(vocabulary.materiality.model_dump().values()) == materiality_options


def test_catalog_tables_declare_their_iro_kind() -> None:
    from sustainability_desk.planner import load_topic_templates

    for section in load_topic_templates(SSE_PACKAGE).values():
        for block in _iter_blocks(section):
            generation = block.generation
            if generation is not None and generation.rowMode in ("preset_catalog", "adaptive_catalog"):
                assert block.table.iroKind is not None, block.id


def _iter_blocks(section):
    yield from section.blocks
    for child in section.children or ():
        yield from _iter_blocks(child)


def test_metric_sheets_derive_from_the_catalog() -> None:
    assert quantitative_metric_sheets(SSE_PACKAGE) == ("经济+环境", "社会", "治理")


def test_disclosure_basis_shapes_are_mutually_exclusive() -> None:
    names = MainlandStandardNames(sse="沪", szse="深", bse="北")
    DisclosureBasis(mainland_standard_selectable=True, mainland_standard_names=names, hong_kong_guide_name="港")
    DisclosureBasis(mainland_standard_selectable=False, primary_standard_names=("HKEX C2",))
    with pytest.raises(ValueError):
        DisclosureBasis(mainland_standard_selectable=True, mainland_standard_names=names)
    with pytest.raises(ValueError):
        DisclosureBasis(mainland_standard_selectable=False)
    with pytest.raises(ValueError):
        DisclosureBasis(
            mainland_standard_selectable=False,
            primary_standard_names=("HKEX C2",),
            hong_kong_guide_name="港",
        )
    assert SSE_PACKAGE.manifest.disclosure_basis.mainland_standard_selectable is True


def test_module_title_guidance_is_optional_in_the_registry() -> None:
    module = ReportModuleRef(id="environment", navigationTitle="環境", order=10)
    assert module.titleGenerationGuidance is None
    # The SSE package still generates every module title.
    assert all(
        module.titleGenerationGuidance
        for module in load_topic_contract(SSE_PACKAGE).source.reportModules
    )


def test_sse_package_yaml_uses_ids_not_display_words() -> None:
    registry = yaml.safe_load(SSE_PACKAGE.topic_registry_path.read_text(encoding="utf-8"))
    assert all(topic["dimension"] in {"environment", "social", "governance"} for topic in registry["assessmentTopics"])
    for path in SSE_PACKAGE.standard_disclosure_requirements_dir.glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in raw["topicStandardDisclosureRequirementGroups"]:
            assert group["pillar"] in PILLARS, path.name
