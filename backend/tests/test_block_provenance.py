# ABOUTME: 逐块溯源投影装配的纯逻辑测试：资料文件与单元数、指标、填写题、省略、守卫与轨迹缺失。
# ABOUTME: 同时守护契约词表与用户可见边界：守卫 code 与源码全等，序列化不含内部标识。
from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from knowledge_package_fixtures import SSE_PACKAGE

from sustainability_desk.block_provenance import (
    BlockProvenanceInputs,
    BlockProvenanceServiceError,
    ProvenanceDossier,
    build_block_provenance_projection,
)
from sustainability_desk.contract.block_provenance import GUARDRAIL_ISSUE_CODES
from sustainability_desk.contract.models import (
    Block,
    ExplicitGenerationEvidenceSelector,
    GenerationInputs,
    GenerationSpec,
    GenerationTask,
    Inline,
    IntakeItem,
    QuantitativeMetricDraft,
    QuantitativeMetricsMeta,
    Report,
    ReportMeta,
    Section,
)
from sustainability_desk.contract.stored_report_state import (
    StoredGeneratedBlock,
    StoredReportStateV4,
)
from sustainability_desk.material.intake.file_agent_contract import (
    AttentionItem,
    FileDossier,
    FileMaterial,
    FileSourceRevision,
    file_dossier_fingerprint,
)
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.observability.block_trace_facts import BlockTraceFacts

SRC = Path(__file__).resolve().parents[1] / "src" / "sustainability_desk"
NOW = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
SHA = "b" * 64
REPORT_ID = uuid4()
BLOCK_ID = "human_capital_development.metrics_narrative_body"
GATED_TABLE_ID = "climate.risk_table"
FIXED_ID = "about_report.intro"


def _dossier(filename: str, *, attention: bool = False) -> tuple[ProvenanceDossier, tuple[FileMaterial, ...]]:
    source_revision = FileSourceRevision(source_id=uuid4(), source_sha256=SHA, declaration_revision=1)
    materials = tuple(
        FileMaterial(
            material_id=uuid4(),
            applicable_scope_ids=("report-section:human_capital",),
            content_markdown=f"{filename} 资料单元 {index}",
        )
        for index in range(2)
    )
    attention_items = (
        (AttentionItem(code="period_mismatch", message="口径超出报告期。", next_action="请确认。"),)
        if attention
        else ()
    )
    dossier = FileDossier(
        source_revision=source_revision,
        relevance="relevant",
        relevance_reason="含人力资本资料。",
        materials=materials,
        attention_items=attention_items,
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=source_revision,
            relevance="relevant",
            relevance_reason="含人力资本资料。",
            materials=materials,
            attention_items=attention_items,
        ),
    )
    return ProvenanceDossier(filename=filename, dossier=dossier), materials


def _report(*, answered: bool, metric_value: str | None) -> Report:
    return Report(
        knowledgePackageId=SSE_PACKAGE.id,
        title="示例企业 ESG 报告",
        meta=ReportMeta(
            quantitativeMetrics=QuantitativeMetricsMeta(
                metrics={"social_r02": QuantitativeMetricDraft(value=metric_value)}
            )
        ),
        intakeItems=[
            IntakeItem(
                key="hc.training",
                contentScopeId="report-section:human_capital",
                prompt="公司如何组织员工培训？",
                kind="text",
                answer="每季度组织一次全员培训。" if answered else None,
            )
        ],
        sections=[
            Section(
                key="about_report",
                title="关于本报告",
                headingLevel=1,
                blocks=[
                    Block(
                        id=FIXED_ID,
                        type="paragraph",
                        blockType="fixed",
                        source="template",
                        content=[Inline(kind="text", text="本报告依据……编制。")],
                    )
                ],
            ),
            Section(
                key="human_capital",
                title="人力资本发展",
                headingLevel=1,
                blocks=[
                    Block(
                        id=BLOCK_ID,
                        type="paragraph",
                        blockType="constrained",
                        source="ai",
                        state="ready",
                        content=[Inline(kind="text", text="用户改过的正文。")],
                        generation=GenerationSpec(
                            task=GenerationTask(mode="metric_narrative", focus="人力资本"),
                            inputs=GenerationInputs(
                                evidence=ExplicitGenerationEvidenceSelector(
                                    kind="explicit",
                                    intakeItems=["hc.training"],
                                    quantitativeMetrics=["social_r02"],
                                )
                            ),
                        ),
                    ),
                    Block(
                        id=GATED_TABLE_ID,
                        type="table",
                        blockType="generative",
                        source="ai",
                        state="omitted",
                        generation=GenerationSpec(
                            task=GenerationTask(focus="气候风险"),
                            inputs=GenerationInputs(
                                evidence=ExplicitGenerationEvidenceSelector(kind="explicit")
                            ),
                        ),
                    ),
                ],
            ),
        ],
    )


def _facts(block_id: str, **overrides) -> BlockTraceFacts:
    base = dict(
        block_id=block_id,
        attempt_count=2,
        guardrail="accepted_after_retry",
        guardrail_issue_keys=("placeholder_output",),
        evidence_selector_kind="explicit",
        evidence_level="metric_narrative",
        intake_fact_count=1,
        metric_evidence_count=1,
        prior_disclosure_count=3,
        stage_status="succeeded",
        material_gate_file_arm=None,
        material_gate_intake_arm=None,
    )
    base.update(overrides)
    return BlockTraceFacts(**base)


def _inputs(
    *,
    answered: bool = True,
    metric_value: str | None = "1500",
    trace: tuple[BlockTraceFacts, ...] | None = None,
    attention: bool = False,
) -> BlockProvenanceInputs:
    dossier_a, materials_a = _dossier("员工手册.docx", attention=attention)
    dossier_b, materials_b = _dossier("培训记录.xlsx")
    decision = BlockMaterialDecision(
        scope_id="report-section:human_capital",
        block_id=BLOCK_ID,
        disposition="supported",
        material_ids=(materials_a[0].material_id, materials_a[1].material_id, materials_b[0].material_id),
        reason="资料直接支持。",
    )
    generated_state = StoredReportStateV4(
        version=4,
        generatedBlocks={
            BLOCK_ID: StoredGeneratedBlock(
                content=[Inline(kind="text", text="生成时的正文。")], state="ready"
            )
        },
    )
    return BlockProvenanceInputs(
        report_id=REPORT_ID,
        revision=1,
        generated_report_state_seq=7,
        generated_at=NOW,
        report=_report(answered=answered, metric_value=metric_value),
        generated_state=generated_state,
        block_results=(
            {"blockId": BLOCK_ID, "status": "ready", "kind": "paragraph"},
            {"blockId": GATED_TABLE_ID, "status": "omitted", "kind": "table", "reason": "省略。", "rows": []},
        ),
        block_decisions=(decision,),
        dossiers=(dossier_a, dossier_b),
        definition=None,
        trace=trace,
    )


def test_projection_lists_adopted_files_with_material_counts_and_consumed_metrics() -> None:
    projection = build_block_provenance_projection(_inputs(trace=(_facts(BLOCK_ID),)))
    entry = next(item for item in projection.blocks if item.block_id == BLOCK_ID)

    assert projection.trace_availability == "available"
    assert entry.generation_outcome == "ready"
    assert entry.material_disposition == "supported"
    assert [(s.material_name, s.adopted_material_count) for s in entry.sources] == [
        ("员工手册.docx", 2),
        ("培训记录.xlsx", 1),
    ]
    assert entry.basis == ("validated_material", "quantitative_metric", "structured_input")
    assert [(m.metric_name, m.value) for m in entry.metrics] == [("员工总数", "1500")]
    assert [(i.question, i.answered) for i in entry.intake_items] == [("公司如何组织员工培训？", True)]
    assert entry.generated_content == [Inline(kind="text", text="生成时的正文。")]
    assert entry.run is not None
    assert entry.run.guardrail == "accepted_after_retry"
    assert entry.run.guardrail_issue_codes == ("placeholder_output",)
    assert entry.run.attempt_count == 2
    assert entry.run.evidence_level == "metric_narrative"


def test_unfilled_metric_and_unanswered_item_are_reported_honestly() -> None:
    projection = build_block_provenance_projection(_inputs(answered=False, metric_value=None))
    entry = next(item for item in projection.blocks if item.block_id == BLOCK_ID)

    assert entry.metrics == ()
    assert entry.basis == ("validated_material", "structured_input")
    assert [(i.question, i.answered) for i in entry.intake_items] == [("公司如何组织员工培训？", False)]


def test_fixed_template_block_is_a_deterministic_projection_without_run_facts() -> None:
    projection = build_block_provenance_projection(_inputs(trace=(_facts(FIXED_ID),)))
    entry = next(item for item in projection.blocks if item.block_id == FIXED_ID)

    assert entry.generation_outcome == "not_generated"
    assert entry.basis == ("deterministic_report_projection",)
    assert entry.material_disposition == "no_decision"
    assert entry.sources == () and entry.metrics == () and entry.intake_items == ()
    assert entry.generated_content is None
    assert entry.run is None


def test_material_gated_omission_projects_gate_reason_from_stage_attributes() -> None:
    facts = _facts(
        GATED_TABLE_ID,
        attempt_count=0,
        guardrail="not_evaluated",
        guardrail_issue_keys=(),
        evidence_selector_kind="",
        evidence_level="",
        material_gate_file_arm="no_decision",
        material_gate_intake_arm="not_declared",
    )
    projection = build_block_provenance_projection(_inputs(trace=(facts,)))
    entry = next(item for item in projection.blocks if item.block_id == GATED_TABLE_ID)

    assert entry.generation_outcome == "omitted"
    assert entry.omission == "no_supporting_material"
    assert entry.run is not None
    assert entry.run.guardrail == "not_evaluated"
    assert entry.run.evidence_selector_kind is None


def test_empty_table_omission_without_gate_attributes() -> None:
    projection = build_block_provenance_projection(_inputs(trace=()))
    entry = next(item for item in projection.blocks if item.block_id == GATED_TABLE_ID)

    assert entry.omission == "empty_table"
    # Trace is available but holds no facts for this block: no run facts rather than invented ones.
    assert entry.run is None


def test_missing_trace_is_flagged_and_carries_no_run_facts() -> None:
    projection = build_block_provenance_projection(_inputs(trace=None))

    assert projection.trace_availability == "unavailable"
    assert all(item.run is None for item in projection.blocks)


def test_attention_note_follows_dossier_attention_items() -> None:
    projection = build_block_provenance_projection(_inputs(attention=True))
    entry = next(item for item in projection.blocks if item.block_id == BLOCK_ID)
    assert entry.attention_note is True


def test_unknown_guardrail_key_fails_loud_instead_of_leaking() -> None:
    with pytest.raises(BlockProvenanceServiceError):
        build_block_provenance_projection(
            _inputs(trace=(_facts(BLOCK_ID, guardrail_issue_keys=("brand_new_rule",)),))
        )


def test_serialized_projection_exposes_no_internal_identifiers() -> None:
    projection = build_block_provenance_projection(_inputs(trace=(_facts(BLOCK_ID),)))
    payload = json.dumps(projection.model_dump(mode="json"), ensure_ascii=False)
    text_without_report_id = payload.replace(str(REPORT_ID), "")

    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text_without_report_id)
    for banned in ("run_id", "span", "prompt", "gen_ai", "/out/", "modelId", "storage_ref"):
        assert banned not in payload


def test_guardrail_issue_codes_match_the_guardrail_source() -> None:
    """Adding a guardrail without registering its key in the contract must fail here, not at runtime."""

    pattern = re.compile(r'GuardrailIssue\(\s*(?:key=)?"([a-z_0-9]+)"')
    seen: set[str] = set()
    for module in ("llm/generation_guardrails.py", "llm/generate.py", "llm/table_validate.py"):
        seen |= set(pattern.findall((SRC / module).read_text(encoding="utf-8")))
    assert seen, "未在源码里找到任何守卫 issue key，匹配模式失效"
    assert seen == GUARDRAIL_ISSUE_CODES
