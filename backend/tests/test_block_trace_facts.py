# ABOUTME: 生成轨迹到逐块事实的解析边界测试：按块聚合调用次数、守卫结论与阶段属性，缺失或损坏即返回 None。
# ABOUTME: 事件用生产合同模型构造后落盘，确保解析与写入合同同源。
from __future__ import annotations

import json
from pathlib import Path

from sustainability_desk.llm.ai_observability import (
    GuardrailEvaluationEvent,
    ModelInvocationEvent,
    ModelTraceRequest,
    ModelTraceResult,
)
from sustainability_desk.observability.block_trace_facts import read_block_trace_facts
from sustainability_desk.observability.stage_trace import StageRecord, append_stage_record

RUN_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "22222222-2222-4222-8222-222222222222"
DAY = "2026-09-05"


def _invocation(block_id: str, ordinal: int, **facts) -> ModelInvocationEvent:
    return ModelInvocationEvent(
        runId=RUN_ID,
        traceId=RUN_ID,
        requestId="req",
        workloadKind="product_generation",
        reportId=REPORT_ID,
        blockId=block_id,
        operation="generation.block",
        environment="test",
        releaseId="r",
        gitSha="sha",
        contractVersion="c",
        timestamp="2026-09-05T09:00:00+00:00",
        status="succeeded",
        modelId="luna",
        invocationOrdinal=ordinal,
        promptFingerprint="sha256:p",
        spanId="span-1",
        stageId="generation.block",
        request=ModelTraceRequest(systemPrompt="system", userPrompt="user"),
        result=ModelTraceResult(structuredOutput={"content": "x"}),
        **facts,
    )


def _evaluation(block_id: str, ordinal: int, status: str, keys: tuple[str, ...] = ()) -> GuardrailEvaluationEvent:
    return GuardrailEvaluationEvent(
        runId=RUN_ID,
        traceId=RUN_ID,
        requestId="req",
        workloadKind="product_generation",
        reportId=REPORT_ID,
        blockId=block_id,
        operation="generation.block",
        environment="test",
        releaseId="r",
        gitSha="sha",
        contractVersion="c",
        timestamp="2026-09-05T09:00:01+00:00",
        status=status,
        modelId="luna",
        invocationOrdinal=ordinal,
        issues=[{"key": key, "message": "问题"} for key in keys],
        retryInstruction="请修正" if status == "rejected" else "",
    )


def _stage(block_id: str, status: str = "succeeded", **attributes) -> StageRecord:
    return StageRecord(
        traceId=RUN_ID,
        spanId=f"span-{block_id}",
        parentSpanId="root",
        stageId="generation.block",
        kind="llm",
        reportId=REPORT_ID,
        scope="full_simplified",
        status=status,
        errorCode="",
        durationMs=10,
        startedAt="2026-09-05T09:00:00+00:00",
        attributes={"sustainability_desk.block_id": block_id, **attributes},
    )


def _write_trace(root: Path, events, stages) -> None:
    day_dir = root / DAY
    day_dir.mkdir(parents=True)
    (day_dir / f"{RUN_ID}.jsonl").write_text(
        "".join(event.model_dump_json() + "\n" for event in events), encoding="utf-8"
    )
    for record in stages:
        append_stage_record(day_dir / f"{RUN_ID}.stages.jsonl", record)


def test_aggregates_attempts_guardrail_and_stage_facts_per_block(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        events=[
            _invocation("p.a", 1, intakeFactCount=2, metricEvidenceCount=0, evidenceSelectorKind="explicit", evidenceLevel="block_facts"),
            _evaluation("p.a", 1, "rejected", ("placeholder_output", "template_residue")),
            _invocation("p.a", 2, intakeFactCount=2, metricEvidenceCount=1, evidenceSelectorKind="explicit", evidenceLevel="block_facts", priorDisclosureCount=4),
            _evaluation("p.a", 2, "accepted"),
            _invocation("p.b", 1),
            _evaluation("p.b", 1, "accepted"),
        ],
        stages=[
            _stage("p.a"),
            _stage("p.gated", **{
                "sustainability_desk.block_status": "omitted",
                "sustainability_desk.material_gate.file_arm": "context_only",
                "sustainability_desk.material_gate.intake_arm": "no_substantive_answer",
            }),
        ],
    )

    facts = read_block_trace_facts(RUN_ID, root=tmp_path)

    assert facts is not None
    by_block = {item.block_id: item for item in facts}
    assert by_block["p.a"].attempt_count == 2
    assert by_block["p.a"].guardrail == "accepted_after_retry"
    assert by_block["p.a"].guardrail_issue_keys == ("placeholder_output", "template_residue")
    # Facts come from the latest invocation, not the first.
    assert by_block["p.a"].metric_evidence_count == 1
    assert by_block["p.a"].prior_disclosure_count == 4
    assert by_block["p.a"].stage_status == "succeeded"
    assert by_block["p.b"].guardrail == "accepted"
    assert by_block["p.b"].guardrail_issue_keys == ()
    assert by_block["p.b"].stage_status is None
    gated = by_block["p.gated"]
    assert gated.attempt_count == 0
    assert gated.guardrail == "not_evaluated"
    assert gated.material_gate_file_arm == "context_only"
    assert gated.material_gate_intake_arm == "no_substantive_answer"


def test_missing_trace_returns_none(tmp_path: Path) -> None:
    assert read_block_trace_facts(RUN_ID, root=tmp_path) is None


def test_corrupt_line_returns_none_instead_of_partial_facts(tmp_path: Path) -> None:
    _write_trace(tmp_path, events=[_invocation("p.a", 1)], stages=[])
    path = tmp_path / DAY / f"{RUN_ID}.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + json.dumps({"eventType": "unknown"}) + "\n", encoding="utf-8")

    assert read_block_trace_facts(RUN_ID, root=tmp_path) is None


def test_last_rejected_evaluation_is_reported_as_rejected(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        events=[_invocation("p.a", 1), _evaluation("p.a", 1, "rejected", ("empty_output",))],
        stages=[_stage("p.a", status="failed")],
    )
    facts = read_block_trace_facts(RUN_ID, root=tmp_path)
    assert facts is not None
    assert facts[0].guardrail == "rejected"
    assert facts[0].stage_status == "failed"
