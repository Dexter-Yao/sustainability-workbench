# ABOUTME(en): Every committed synthetic corpus must pass the production input path headlessly: recipe writes
# ABOUTME(en): through the adapter, scoring and KPI workbooks round-trip, materials clear the ingress gate,
# ABOUTME(en): the report is generation-ready and renders to Word on its own package.
from __future__ import annotations

from pathlib import Path

import pytest

from sustainability_desk.contract.build_report import build_report
from sustainability_desk.contract.disclosure_coverage import evaluate_disclosure_coverage
from local_e2e_fixture import (
    load_local_e2e_fixture_recipe,
    load_local_e2e_selection_manifest,
    synthesize_company_inputs,
    verify_selected_materials,
)
from sustainability_desk.export.docx_renderer import render_docx
from sustainability_desk.export.format_profile import load_format_profile
from sustainability_desk.export.normalize_template import normalize_template
from sustainability_desk.lightweight_report_readiness import parse_lightweight_report_readiness

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "local_e2e"
CORPORA = [
    pytest.param("shengyuan/shengyuan_report_inputs.yaml", "shengyuan/shengyuan_materials.yaml", id="shengyuan"),
    pytest.param("jinli/jinli_report_inputs.zh-Hant.yaml", "jinli/jinli_materials.yaml", id="jinli-zh-Hant"),
    pytest.param("jinli/jinli_report_inputs.en.yaml", "jinli/jinli_materials.yaml", id="jinli-en"),
]


@pytest.mark.parametrize(("recipe_path", "manifest_path"), CORPORA)
def test_corpus_recipe_synthesizes_a_generation_ready_report(recipe_path: str, manifest_path: str, tmp_path) -> None:
    recipe = load_local_e2e_fixture_recipe(FIXTURE_ROOT / recipe_path)
    package = recipe.knowledge_package
    inputs = synthesize_company_inputs(recipe)
    assert inputs.knowledgePackageId == package.id
    assert len(inputs.assessmentInput.scores) == len(recipe.assessmentScores)
    written_metric_keys = {write.target_key.removeprefix("metric.") for write in recipe.inputWrites if write.target_key.startswith("metric.")}
    valued = {key for key, draft in inputs.quantitativeMetrics.metrics.items() if draft.value is not None}
    assert written_metric_keys <= valued

    report = build_report(inputs)
    assert report.assessment is not None and report.assessment.topics
    readiness = parse_lightweight_report_readiness(report)
    assert readiness.readyForWorkbench, [issue.model_dump() for issue in readiness.issues]
    assert not evaluate_disclosure_coverage(report).attention_findings

    manifest = load_local_e2e_selection_manifest(FIXTURE_ROOT / manifest_path)
    verified = verify_selected_materials(manifest, package=package)
    assert len(verified) == manifest.selectedFileCount

    shell = normalize_template(package.base_template_path, tmp_path / "base.docx", profile=load_format_profile(package))
    out = render_docx(report, shell, tmp_path / "sample.docx")
    assert out.is_file() and out.stat().st_size > 10_000
