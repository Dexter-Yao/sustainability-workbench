# ABOUTME: 逐块溯源投影的装配与加载：把生成修订、Mapping 决定、资料 Dossier 与轨迹事实合成用户安全视图。
# ABOUTME: 判定规则与审阅批注同源（report_review_packages）；不写库、不改 Report，轨迹不可用时如实标注。
# ABOUTME(en): Assembles and loads the per-block provenance projection from the revision, Mapping decisions, dossiers and trace facts.
# ABOUTME(en): Shares its basis rule with the review commentary; writes nothing and flags an unavailable trace honestly.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from sustainability_desk.accounts.service import (
    AccountEntitlementError,
    AccountNotFoundError,
    effective_report_scope,
    get_account_context_for_account,
)
from sustainability_desk.contract.block_provenance import (
    GUARDRAIL_ISSUE_CODES,
    BlockProvenanceEntry,
    BlockProvenanceIntakeItem,
    BlockProvenanceMetric,
    BlockProvenanceRun,
    BlockProvenanceSource,
    ReportBlockProvenanceProjection,
)
from sustainability_desk.contract.compiled_definition import (
    CompiledReportDefinition,
    load_compiled_report_definition,
)
from sustainability_desk.contract.evidence_resolution import (
    generation_evidence_keys,
    intake_has_gate_opening_evidence,
)
from sustainability_desk.contract.models import Block, Report
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.material.intake.file_agent_contract import FileDossier
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision
from sustainability_desk.observability.block_trace_facts import (
    BlockTraceFacts,
    read_block_trace_facts,
)
from sustainability_desk.persistence import lightweight_report_generations as generation_dal
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.report_review_packages import block_evidence_basis, consumed_metrics


class BlockProvenanceServiceError(RuntimeError):
    """The provenance projection cannot be assembled for this report."""


@dataclass(frozen=True)
class ProvenanceDossier:
    """A frozen dossier together with the user-visible file name it came from."""

    filename: str
    dossier: FileDossier


@dataclass(frozen=True)
class BlockProvenanceInputs:
    """Everything the pure assembler needs; loaded once, never re-queried during assembly."""

    report_id: UUID
    revision: int
    generated_report_state_seq: int
    generated_at: datetime
    report: Report
    generated_state: StoredReportStateV4
    block_results: tuple[dict, ...]
    block_decisions: tuple[BlockMaterialDecision, ...]
    dossiers: tuple[ProvenanceDossier, ...]
    definition: CompiledReportDefinition | None
    trace: tuple[BlockTraceFacts, ...] | None


def _walk_blocks(report: Report) -> list[Block]:
    blocks: list[Block] = []

    def walk(sections) -> None:
        for section in sections or ():
            blocks.extend(section.blocks or ())
            walk(section.children)

    walk(report.sections)
    return blocks


def _sources(
    decision: BlockMaterialDecision | None,
    dossiers: tuple[ProvenanceDossier, ...],
) -> tuple[BlockProvenanceSource, ...]:
    if decision is None:
        return ()
    filename_by_material: dict[UUID, str] = {
        material.material_id: item.filename
        for item in dossiers
        for material in item.dossier.materials
    }
    counts: dict[str, int] = {}
    for material_id in decision.material_ids:
        filename = filename_by_material.get(material_id)
        if filename is None:
            raise BlockProvenanceServiceError(
                f"Block {decision.block_id} 的 Mapping 决定引用了快照外资料"
            )
        counts[filename] = counts.get(filename, 0) + 1
    return tuple(
        BlockProvenanceSource(material_name=name, adopted_material_count=count)
        for name, count in counts.items()
    )


def _intake_items(
    block: Block, report: Report, definition: CompiledReportDefinition | None
) -> tuple[BlockProvenanceIntakeItem, ...]:
    if block.generation is None:
        return ()
    # Substantive-answer wording is per package language (non-substantive markers differ by language).
    language = knowledge_package_of(report).language
    try:
        intake_keys, _metric_keys = generation_evidence_keys(block, report, report, definition)
    except (ValueError, KeyError):
        return ()
    items_by_key = {item.key: item for item in report.intakeItems}
    projected: list[BlockProvenanceIntakeItem] = []
    for key in intake_keys:
        item = items_by_key.get(key)
        if item is None:
            continue
        projected.append(
            BlockProvenanceIntakeItem(
                question=item.prompt,
                answered=intake_has_gate_opening_evidence(item, language),
            )
        )
    return tuple(projected)


def _run_facts(facts: BlockTraceFacts | None, *, outcome: str) -> BlockProvenanceRun | None:
    if facts is None:
        return None
    unknown = set(facts.guardrail_issue_keys) - GUARDRAIL_ISSUE_CODES
    if unknown:
        raise BlockProvenanceServiceError(
            "守卫问题类别未登记于溯源合同：" + ", ".join(sorted(unknown))
        )
    stage_status = facts.stage_status
    if stage_status is None:
        # The run committed, so a block without its own span still finished successfully.
        stage_status = "succeeded" if outcome in {"ready", "omitted"} else "failed"
    return BlockProvenanceRun(
        stage_status=stage_status,  # type: ignore[arg-type]
        attempt_count=facts.attempt_count,
        guardrail=facts.guardrail,  # type: ignore[arg-type]
        guardrail_issue_codes=tuple(facts.guardrail_issue_keys),  # type: ignore[arg-type]
        evidence_selector_kind=facts.evidence_selector_kind or None,  # type: ignore[arg-type]
        evidence_level=facts.evidence_level or None,  # type: ignore[arg-type]
        intake_fact_count=facts.intake_fact_count,
        metric_evidence_count=facts.metric_evidence_count,
        prior_disclosure_count=facts.prior_disclosure_count,
    )


def _omission(block: Block, facts: BlockTraceFacts | None) -> str:
    if facts is not None and facts.material_gate_file_arm is not None:
        return "no_supporting_material"
    if block.type == "table":
        return "empty_table"
    return "no_supporting_material"


def _entry(
    block: Block,
    inputs: BlockProvenanceInputs,
    *,
    decision: BlockMaterialDecision | None,
    result: dict | None,
    facts: BlockTraceFacts | None,
) -> BlockProvenanceEntry:
    outcome = "not_generated"
    if (
        block.source == "ai"
        and result is not None
        and result.get("status") in {"ready", "omitted"}
    ):
        outcome = str(result["status"])
    sources = _sources(decision, inputs.dossiers)
    metrics = (
        tuple(
            BlockProvenanceMetric(metric_name=item.metric_name, value=item.value, unit=item.unit)
            for item in consumed_metrics(block, inputs.report, inputs.definition)
        )
        if block.source == "ai"
        else ()
    )
    basis = block_evidence_basis(
        block, decision, has_sources=bool(sources), has_metrics=bool(metrics)
    )
    attention = bool(
        decision is not None and decision.disposition == "needs_attention"
    ) or bool(sources and any(item.dossier.attention_items for item in inputs.dossiers))
    generated = None
    if block.source == "ai" and block.type == "paragraph":
        stored = inputs.generated_state.generatedBlocks.get(block.id)
        generated = list(stored.content) if stored is not None and stored.content else None
    return BlockProvenanceEntry(
        block_id=block.id,
        basis=basis,
        generation_outcome=outcome,  # type: ignore[arg-type]
        omission=_omission(block, facts) if outcome == "omitted" else None,  # type: ignore[arg-type]
        material_disposition=decision.disposition if decision is not None else "no_decision",
        sources=sources,
        intake_items=(
            _intake_items(block, inputs.report, inputs.definition)
            if block.source == "ai"
            else ()
        ),
        metrics=metrics,
        attention_note=attention,
        generated_content=generated,
        run=_run_facts(facts, outcome=outcome) if outcome != "not_generated" else None,
    )


def build_block_provenance_projection(
    inputs: BlockProvenanceInputs,
) -> ReportBlockProvenanceProjection:
    """Pure assembly: every block of the revision report gets one entry."""

    decisions = {item.block_id: item for item in inputs.block_decisions}
    results = {str(item.get("blockId")): item for item in inputs.block_results}
    facts_by_block = (
        {item.block_id: item for item in inputs.trace} if inputs.trace is not None else {}
    )
    entries = tuple(
        _entry(
            block,
            inputs,
            decision=decisions.get(block.id),
            result=results.get(block.id),
            facts=facts_by_block.get(block.id),
        )
        for block in _walk_blocks(inputs.report)
    )
    return ReportBlockProvenanceProjection(
        report_id=inputs.report_id,
        revision=inputs.revision,
        generated_report_state_seq=inputs.generated_report_state_seq,
        generated_at=inputs.generated_at,
        trace_availability="available" if inputs.trace is not None else "unavailable",
        blocks=entries,
    )


async def load_report_block_provenance(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    run: generation_dal.ReportGenerationRunRecord,
    observability_root: Path | None = None,
) -> ReportBlockProvenanceProjection:
    """Load every input the assembler needs for a successful run, then assemble."""

    if run.status != "succeeded" or run.result_revision_id is None:
        raise BlockProvenanceServiceError("只能为成功完成的生成运行装配溯源")
    try:
        context = await get_account_context_for_account(pool, account_id)
        summary = await reports_dal.get_report_summary(pool, account_id, report_id)
    except (AccountNotFoundError, AccountEntitlementError) as error:
        raise BlockProvenanceServiceError("Account 权益状态异常") from error
    scope = effective_report_scope(
        context, created_under_profile_id=summary.created_under_profile_id
    )
    revision = await generation_dal.revision_state(
        pool, account_id=account_id, report_id=report_id, revision_id=run.result_revision_id
    )
    package = scope.knowledge_package
    report = scope.prepare_deliverable_report(
        build_report_revision(revision.state, package=package)
    )
    snapshot = await pipeline_dal.get_material_set_snapshot(
        pool,
        account_id=account_id,
        report_id=report_id,
        snapshot_id=run.material_set_snapshot_id,
    )
    dossier_records = await pipeline_dal.load_dossiers(
        pool,
        account_id=account_id,
        report_id=report_id,
        dossier_ids=tuple(member.dossier_id for member in snapshot.snapshot.members),
    )
    mapping_results = await pipeline_dal.current_mapping_results(
        pool,
        account_id=account_id,
        report_id=report_id,
        snapshot_id=run.material_set_snapshot_id,
    )
    expected = set(run.expected_block_ids)
    decisions = tuple(
        decision
        for result in mapping_results
        for decision in result.block_decisions
        if decision.block_id in expected
    )
    try:
        definition = load_compiled_report_definition(package)
    except Exception:  # noqa: BLE001 — provenance degrades to "no metrics" rather than failing
        definition = None
    inputs = BlockProvenanceInputs(
        report_id=report_id,
        revision=revision.revision,
        generated_report_state_seq=revision.report_state_seq,
        generated_at=revision.created_at,
        report=report,
        generated_state=revision.state,
        block_results=run.block_results,
        block_decisions=decisions,
        dossiers=tuple(
            ProvenanceDossier(filename=record.filename, dossier=record.dossier)
            for record in dossier_records
        ),
        definition=definition,
        trace=read_block_trace_facts(str(run.run_id), root=observability_root),
    )
    return build_block_provenance_projection(inputs)
