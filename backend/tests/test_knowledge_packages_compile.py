# ABOUTME(en): Every knowledge package must compile and audit through the production loaders, declare both
# ABOUTME(en): profiles with its own id and language, and render its sample values to Word. The HKEX packages
# ABOUTME(en): additionally anchor every requirement to Appendix C2 and number their KPIs.
from __future__ import annotations

import pytest
import yaml

from sustainability_desk.contract.build_report import build_report
from sustainability_desk.contract.company_inputs import parse_company_inputs
from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.disclosure_coverage import evaluate_disclosure_coverage
from sustainability_desk.contract.disclosure_standards_index import load_disclosure_standards_index
from sustainability_desk.contract.fill import ReportContent, apply_report_content
from sustainability_desk.contract.knowledge_packages import all_knowledge_package_ids, load_knowledge_package
from sustainability_desk.contract.loader import assessment_vocabulary, load_package_contract
from sustainability_desk.contract.report_profiles import load_report_profile_registry
from sustainability_desk.contract.topic_registry import load_topic_contract
from sustainability_desk.export.docx_renderer import load_values, render_docx
from sustainability_desk.export.format_profile import load_format_profile
from sustainability_desk.export.normalize_template import normalize_template
from sustainability_desk.llm.generate import _template
from sustainability_desk.llm.prompt_profiles import load_prompt_profile
from sustainability_desk.llm.prompts import build_model_context, render_complete_prompt, render_prompt
from sustainability_desk.llm.table_gen import _assessment_iro_row_seeds, _resolve_block, prepare_table_model_context
from sustainability_desk.quantitative_metrics import all_quantitative_metrics
from sustainability_desk.report_review_packages import build_standards_compliance_notice

PACKAGE_IDS = all_knowledge_package_ids()


def test_every_unsealed_package_is_bound_to_a_report_profile() -> None:
    """未封存的包必须恰好绑定 report profile；封存包留在仓库但不可建报。

    封存不等于停止验证——PACKAGE_IDS 仍枚举全部包，下面的编译审计对封存包照常生效，
    防其在无人建报的情况下悄悄烂掉。
    """
    bound = {profile.knowledge_package for profile in load_report_profile_registry().profiles.values()}
    unsealed = {pid for pid in PACKAGE_IDS if not load_knowledge_package(pid).manifest.sealed}
    assert unsealed == bound
    sealed = set(PACKAGE_IDS) - unsealed
    assert not (sealed & bound), f"封存包不得绑定 profile：{sorted(sealed & bound)}"


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_package_compiles_and_audits(package_id: str) -> None:
    package = load_knowledge_package(package_id)
    definition = load_compiled_report_definition(package)
    assert definition.package_id == package_id
    assert definition.generation_contracts
    contract = load_topic_contract(package)
    assert contract.source.assessmentTopics
    assert assessment_vocabulary(package).materiality.dual


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_package_profiles_carry_its_identity(package_id: str) -> None:
    package = load_knowledge_package(package_id)
    prompt_profile = load_prompt_profile(package)
    format_profile = load_format_profile(package)
    assert prompt_profile.profile_id == package_id
    assert format_profile.profile_id == package_id
    assert format_profile.language == package.language
    assert package.base_template_path.is_file()


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_package_sample_values_render_prompts_and_word(package_id: str, tmp_path) -> None:
    package = load_knowledge_package(package_id)
    definition = load_compiled_report_definition(package)
    template = _template(package)
    raw = load_values(package.sample_values_path)
    report = build_report(parse_company_inputs(raw["inputs"], package=package))
    report = apply_report_content(report, ReportContent.model_validate(raw.get("content") or {}))
    block = next(b for b in report.iter_blocks() if b.type == "paragraph" and b.generation is not None)
    ctx = build_model_context(template.find_block(block.id) or block, template, report, definition=definition)
    assert ctx.output_language == package.language
    system, _user = render_prompt(ctx, n=1)
    assert system.startswith("<output_language>")
    coverage = evaluate_disclosure_coverage(report)
    notice = build_standards_compliance_notice(coverage, package=package)
    assert notice.heading
    shell = normalize_template(package.base_template_path, tmp_path / "base.docx", profile=load_format_profile(package))
    out = render_docx(report, shell, tmp_path / "sample.docx")
    assert out.is_file() and out.stat().st_size > 10_000


HKEX_PACKAGE_IDS = [pid for pid in PACKAGE_IDS if pid.startswith("hkex_")]


@pytest.mark.parametrize("package_id", HKEX_PACKAGE_IDS)
def test_hkex_requirements_anchor_appendix_c2(package_id: str) -> None:
    package = load_knowledge_package(package_id)
    for path in sorted(package.standard_disclosure_requirements_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in raw["topicStandardDisclosureRequirementGroups"]:
            for requirement in group["standardDisclosureRequirements"]:
                assert "C2" in requirement["excerptFrom"], (path.name, requirement["standardDisclosureRequirementKey"])
                assert {label["standard"] for label in requirement["sourceClauseReferenceLabels"]} == {"HKEX"}


@pytest.mark.parametrize("package_id", HKEX_PACKAGE_IDS)
def test_hkex_metrics_carry_kpi_codes_and_index_matches_sections(package_id: str) -> None:
    package = load_knowledge_package(package_id)
    metrics = all_quantitative_metrics(package)
    coded = [metric for metric in metrics if metric.kpiCode]
    assert len(coded) >= len(metrics) - 2  # only the economic denominators are uncoded
    contract = load_topic_contract(package)
    section_titles = {section.title for section in contract.source.reportSections}
    fixed_titles = {section.title for section in load_package_contract(package).sections}
    for chapter in load_disclosure_standards_index(package):
        for index_section in chapter.sections:
            for clause in index_section.clauses:
                for name in clause.reportSections:
                    assert name in section_titles | fixed_titles, (chapter.title, clause.clause, name)


@pytest.mark.parametrize("package_id", HKEX_PACKAGE_IDS)
def test_hkex_packages_have_no_mainland_standard_choice(package_id: str) -> None:
    package = load_knowledge_package(package_id)
    assert package.manifest.disclosure_basis.mainland_standard_selectable is False
    assert package.manifest.disclosure_basis.primary_standard_names


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_package_iro_table_resolves_its_own_template_and_seeds(package_id: str) -> None:
    """Table generation must resolve the template from the report's package (no default package)."""

    package = load_knowledge_package(package_id)
    raw = load_values(package.sample_values_path)
    report = build_report(parse_company_inputs(raw["inputs"], package=package))
    block, template = _resolve_block("sm.iro_table", report)
    assert template.knowledgePackageId == package_id
    seeds = _assessment_iro_row_seeds(block, report)
    assert seeds, "the sample assessment must yield material topics for the IRO table"
    ctx = prepare_table_model_context("sm.iro_table", report)
    assert ctx.output_language == package.language
    system, user = render_complete_prompt(
        ctx.model_copy(update={"row_context": {"theme": seeds[0].theme, "category": seeds[0].category or "", "driver_hint": ""}}),
        block.table.colDefs,
        expansion=block.generation.rowExpansion,
    )
    assert system.startswith("<output_language>") and seeds[0].theme in user


# Categories that deliberately name no report section: denominator-style basics no topic chapter owns.
# Anything else must match a section title exactly — a category spelled differently prints as declared
# into the Word appendix's first column instead of merging under its topic.
UNOWNED_METRIC_CATEGORIES: dict[str, frozenset[str]] = {
    "sse_zh_hans": frozenset({"经济绩效", "公司治理-董事会"}),
    "hkex_en": frozenset({"Economic Performance"}),
    "hkex_zh_hant": frozenset({"經濟績效"}),
    # gri_en is sealed and its metric catalogue is still a copy of hkex_en's, so eleven categories name
    # HKEX chapters rather than GRI ones. Listing them keeps this guard strict for the three packages on
    # sale without pretending the sealed package is clean; unsealing must fix the catalogue and shrink
    # this set back to the economic denominator when the sealed GRI package is unsealed.
    "gri_en": frozenset(
        {
            "Economic Performance",
            "Community Investment",
            "Data Protection and Privacy",
            "Development and Training",
            "Emissions",
            "Energy Management",
            "Health and Safety",
            "Materials and Packaging",
            "Product Responsibility",
            "Supply Chain Management",
            "Waste Management",
            "Water Management",
        }
    ),
}


@pytest.mark.parametrize("package_id", PACKAGE_IDS)
def test_metric_categories_name_a_report_section_or_are_declared_unowned(package_id: str) -> None:
    """附录首列按 category 归并到议题；用字与章节名不符的 category 会原样打进交付物。

    历史上 sse_zh_hans 有三条这样的漂移（「乡村振兴和社会贡献」对章节「乡村振兴与社会贡献」、
    「反商业贿赂及反贪腐」对「反商业贿赂与反贪污」，以及含字面换行符的「公司治理\n-董事会」）。
    这类错配不报错、不进日志，只体现在 Word 附录里，因此必须由测试守护。
    """

    package = load_knowledge_package(package_id)
    section_titles = {section.title for section in load_topic_contract(package).source.reportSections}
    unowned = UNOWNED_METRIC_CATEGORIES[package_id]

    offenders = sorted(
        {
            metric.category
            for metric in all_quantitative_metrics(package)
            # 与 _metric_topic_name 同构：命中章节名即可，否则取连字符前段再比一次。
            if metric.category not in section_titles
            and metric.category.split("-", 1)[0].strip() not in section_titles
            and metric.category not in unowned
        }
    )

    assert not offenders, f"{package_id} 的 category 既非章节名也未登记为无归属：{offenders}"
