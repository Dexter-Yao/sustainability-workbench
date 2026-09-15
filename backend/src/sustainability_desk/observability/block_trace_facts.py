# ABOUTME: 生成轨迹到逐块事实的解析边界：从 v3 模型事件与 v2 阶段记录聚合出每个块的运行事实。
# ABOUTME: 只产出计数、状态与守卫 key；轨迹缺失或不可解析统一返回 None，由投影层如实标注不可用。
# ABOUTME(en): Parse boundary from generation traces to per-block facts, aggregating v3 model events and v2 stage records.
# ABOUTME(en): Emits counts, statuses and guardrail keys only; a missing or unparseable trace yields None for the projection to flag.
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
from pathlib import Path

from pydantic import ValidationError

from sustainability_desk.llm.ai_observability import (
    GuardrailEvaluationEvent,
    ModelInvocationEvent,
    locate_observation_trace,
    parse_observability_event,
)
from sustainability_desk.observability.stage_trace import read_stage_records

logger = logging.getLogger(__name__)

BLOCK_STAGE_ID = "generation.block"
_BLOCK_ID_ATTRIBUTE = "sustainability_desk.block_id"
_FILE_ARM_ATTRIBUTE = "sustainability_desk.material_gate.file_arm"
_INTAKE_ARM_ATTRIBUTE = "sustainability_desk.material_gate.intake_arm"


@dataclass(frozen=True)
class BlockTraceFacts:
    """Run facts of one block as recorded by the generation trace; codes and counts only."""

    block_id: str
    attempt_count: int
    guardrail: str
    guardrail_issue_keys: tuple[str, ...]
    evidence_selector_kind: str
    evidence_level: str
    intake_fact_count: int
    metric_evidence_count: int
    prior_disclosure_count: int
    #: Status of the block's ``generation.block`` span; None when the trace has no span for it.
    stage_status: str | None
    material_gate_file_arm: str | None
    material_gate_intake_arm: str | None


def _guardrail_verdict(
    evaluations: list[GuardrailEvaluationEvent],
) -> tuple[str, tuple[str, ...]]:
    if not evaluations:
        return "not_evaluated", ()
    ordered = sorted(evaluations, key=lambda event: event.invocationOrdinal)
    rejected_keys = sorted(
        {issue.key for event in ordered if event.status == "rejected" for issue in event.issues}
    )
    last = ordered[-1]
    if last.status == "rejected":
        return "rejected", tuple(rejected_keys)
    if rejected_keys:
        return "accepted_after_retry", tuple(rejected_keys)
    return "accepted", ()


def _facts_for_block(
    block_id: str,
    *,
    invocations: list[ModelInvocationEvent],
    evaluations: list[GuardrailEvaluationEvent],
    stage: tuple[str, dict[str, object]] | None,
) -> BlockTraceFacts:
    latest = max(invocations, key=lambda event: event.invocationOrdinal, default=None)
    guardrail, issue_keys = _guardrail_verdict(evaluations)
    attributes = stage[1] if stage is not None else {}
    file_arm = attributes.get(_FILE_ARM_ATTRIBUTE)
    intake_arm = attributes.get(_INTAKE_ARM_ATTRIBUTE)
    return BlockTraceFacts(
        block_id=block_id,
        attempt_count=len(invocations),
        guardrail=guardrail,
        guardrail_issue_keys=issue_keys,
        evidence_selector_kind=latest.evidenceSelectorKind if latest else "",
        evidence_level=latest.evidenceLevel if latest else "",
        intake_fact_count=latest.intakeFactCount if latest else 0,
        metric_evidence_count=latest.metricEvidenceCount if latest else 0,
        prior_disclosure_count=latest.priorDisclosureCount if latest else 0,
        stage_status=stage[0] if stage is not None else None,
        material_gate_file_arm=str(file_arm) if isinstance(file_arm, str) else None,
        material_gate_intake_arm=str(intake_arm) if isinstance(intake_arm, str) else None,
    )


def _read_events(path: Path) -> tuple[
    dict[str, list[ModelInvocationEvent]],
    dict[str, list[GuardrailEvaluationEvent]],
]:
    invocations: dict[str, list[ModelInvocationEvent]] = defaultdict(list)
    evaluations: dict[str, list[GuardrailEvaluationEvent]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = parse_observability_event(line)
        if isinstance(event, ModelInvocationEvent):
            invocations[event.blockId].append(event)
        elif isinstance(event, GuardrailEvaluationEvent):
            evaluations[event.blockId].append(event)
    return invocations, evaluations


def _read_block_stages(path: Path) -> dict[str, tuple[str, dict[str, object]]]:
    stages: dict[str, tuple[str, dict[str, object]]] = {}
    for record in read_stage_records(path):
        if record.stageId != BLOCK_STAGE_ID:
            continue
        block_id = record.attributes.get(_BLOCK_ID_ATTRIBUTE)
        if isinstance(block_id, str) and block_id:
            # Later spans win: a retried block leaves the retry as the effective fact.
            stages[block_id] = (record.status, dict(record.attributes))
    return stages


def read_block_trace_facts(
    run_id: str, *, root: Path | None = None
) -> tuple[BlockTraceFacts, ...] | None:
    """Aggregate a generation run's trace into per-block facts.

    Returns None when the trace cannot be located or strictly parsed. That is a legal
    degraded state for the caller to surface, not an error: the report body was
    committed by the run itself and the trace is a rotated local artifact.
    """

    try:
        events_path = locate_observation_trace(run_id, root=root)
        invocations, evaluations = _read_events(events_path)
        stages = _read_block_stages(events_path.with_name(f"{run_id}.stages.jsonl"))
    except (FileNotFoundError, ValueError, ValidationError) as error:
        logger.warning("block_trace_unavailable run_id=%s reason=%s", run_id, type(error).__name__)
        return None
    block_ids = sorted(set(invocations) | set(evaluations) | set(stages))
    return tuple(
        _facts_for_block(
            block_id,
            invocations=invocations.get(block_id, []),
            evaluations=evaluations.get(block_id, []),
            stage=stages.get(block_id),
        )
        for block_id in block_ids
    )
