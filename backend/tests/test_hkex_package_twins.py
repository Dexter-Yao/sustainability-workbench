# ABOUTME(en): hkex_zh_hant and hkex_en are one skeleton in two languages: every id-bearing structure (sections,
# ABOUTME(en): blocks, intake items with kinds and option counts, metrics, requirements, coverage, obligations,
# ABOUTME(en): stakeholders, index shape) must be identical; only the words may differ.
from __future__ import annotations

import json

import yaml

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.disclosure_standards_index import load_disclosure_standards_index
from sustainability_desk.contract.knowledge_packages import load_knowledge_package
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.disclosure_coverage import load_report_level_obligations
from sustainability_desk.contract.stakeholder_engagement import load_stakeholder_engagement_catalog
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.planner import load_topic_intake
from sustainability_desk.quantitative_metrics import all_quantitative_metrics

ZH = load_knowledge_package("hkex_zh_hant")
EN = load_knowledge_package("hkex_en")


def _section_shape(sections) -> list:
    return [
        (section.key, section.headingLevel, section.pillar, [(block.id, block.type, block.blockType) for block in section.blocks or []], _section_shape(section.children or []))
        for section in sections
    ]


def test_report_skeletons_are_identical() -> None:
    zh, en = load_package_contract(ZH), load_package_contract(EN)
    assert _section_shape(zh.sections) == _section_shape(en.sections)
    assert list(zh.fields) == list(en.fields)
    assert [(f.type, f.source, f.required, len(f.options or [])) for f in zh.fields.values()] == [(f.type, f.source, f.required, len(f.options or [])) for f in en.fields.values()]
    assert [(i.key, i.kind, i.collectionPriority) for i in zh.intakeItems] == [(i.key, i.kind, i.collectionPriority) for i in en.intakeItems]


def test_topic_registry_and_intake_are_identical_in_shape() -> None:
    zh, en = load_topic_contract(ZH).source, load_topic_contract(EN).source
    assert [m.id for m in zh.reportModules] == [m.id for m in en.reportModules]
    assert [(d.id, d.order) for d in zh.dimensions] == [(d.id, d.order) for d in en.dimensions]
    assert [(t.id, t.dimension, t.reportSectionId, t.materialityDetermination.kind) for t in zh.assessmentTopics] == [(t.id, t.dimension, t.reportSectionId, t.materialityDetermination.kind) for t in en.assessmentTopics]
    assert [(s.id, s.reportModuleId, s.sectionPrefix) for s in zh.reportSections] == [(s.id, s.reportModuleId, s.sectionPrefix) for s in en.reportSections]
    zh_intake, en_intake = load_topic_intake(ZH), load_topic_intake(EN)
    assert [(i.key, i.kind, len(i.options or []), i.collectionPriority) for i in zh_intake] == [(i.key, i.kind, len(i.options or []), i.collectionPriority) for i in en_intake]


def test_compiled_generation_contracts_share_keys() -> None:
    zh, en = load_compiled_report_definition(ZH), load_compiled_report_definition(EN)
    assert set(zh.generation_contracts) == set(en.generation_contracts)
    for block_id, zh_contract in zh.generation_contracts.items():
        en_contract = en.generation_contracts[block_id]
        assert (zh_contract.intake_item_ids, zh_contract.quantitative_metric_ids, zh_contract.standard_requirement_refs, zh_contract.absence_behavior) == (en_contract.intake_item_ids, en_contract.quantitative_metric_ids, en_contract.standard_requirement_refs, en_contract.absence_behavior), block_id


def test_metric_catalogs_are_identical_apart_from_words() -> None:
    zh, en = all_quantitative_metrics(ZH), all_quantitative_metrics(EN)
    shape = lambda m: (m.key, m.kpiCode, m.sumOfMetricKeys, m.requiresGreenhouseGasAccountingStandard, len(m.groupPath))  # noqa: E731
    assert [shape(m) for m in zh] == [shape(m) for m in en]
    zh_sheets = [m.sheet for m in zh]
    en_sheets = [m.sheet for m in en]
    assert [zh_sheets.index(s) for s in dict.fromkeys(zh_sheets)] == [en_sheets.index(s) for s in dict.fromkeys(en_sheets)]


def test_requirements_coverage_obligations_and_stakeholders_are_identical_in_shape() -> None:
    def requirement_shape(package):
        shape = {}
        for path in sorted(package.standard_disclosure_requirements_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            shape[path.name] = [
                (group["topicSectionKey"], group["pillar"], [(r["standardDisclosureRequirementKey"], r["disclosureRequirementObligationLevel"], r["sourceClauseReferenceLabels"][0]["standard"]) for r in group["standardDisclosureRequirements"]])
                for group in raw["topicStandardDisclosureRequirementGroups"]
            ]
        return shape

    assert requirement_shape(ZH) == requirement_shape(EN)
    zh_cov = yaml.safe_load((ZH.root / "standard_disclosure_requirement_coverage.yaml").read_text(encoding="utf-8"))
    en_cov = yaml.safe_load((EN.root / "standard_disclosure_requirement_coverage.yaml").read_text(encoding="utf-8"))
    assert zh_cov == en_cov
    assert [(o.obligationKey, o.obligationKind, o.carrierSectionKeys, o.carrierBlockIds) for o in load_report_level_obligations(ZH)] == [(o.obligationKey, o.obligationKind, o.carrierSectionKeys, o.carrierBlockIds) for o in load_report_level_obligations(EN)]
    zh_cat, en_cat = load_stakeholder_engagement_catalog(ZH), load_stakeholder_engagement_catalog(EN)
    assert [(s.id, s.defaultMethodIds) for s in zh_cat.stakeholders] == [(s.id, s.defaultMethodIds) for s in en_cat.stakeholders]
    assert [(m.id, m.kind, m.allowedStakeholderTypes) for m in zh_cat.methods] == [(m.id, m.kind, m.allowedStakeholderTypes) for m in en_cat.methods]
    assert zh_cat.defaultTopicStakeholders == en_cat.defaultTopicStakeholders
    zh_index = [[len(s.clauses) for s in c.sections] for c in load_disclosure_standards_index(ZH)]
    en_index = [[len(s.clauses) for s in c.sections] for c in load_disclosure_standards_index(EN)]
    assert zh_index == en_index


def test_json_catalog_files_have_no_stray_keys() -> None:
    for package in (ZH, EN):
        for item in json.loads(package.quantitative_metrics_path.read_text(encoding="utf-8")):
            assert set(item) <= {"key", "sheet", "category", "groupPath", "metricLabel", "unit", "sumOfMetricKeys", "requiresGreenhouseGasAccountingStandard", "kpiCode", "metricDefinition", "termExplanation"}, item["key"]
