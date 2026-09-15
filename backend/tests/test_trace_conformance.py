# ABOUTME: 轨迹一致性校验器的合同测试——树形、聚合键、逐块完整性与两类事实的 join。
# ABOUTME: 用合成轨迹文件驱动；金样 E2E 的真实轨迹由同一校验器在验收时检查。
from __future__ import annotations

import json
from pathlib import Path

from sustainability_desk.observability.trace_conformance import validate_trace_directory


def _stage_record(**overrides) -> dict:
    record = {
        "schemaVersion": "sustainability_desk.stage_trace.v2",
        "traceId": "run-1",
        "spanId": "aa" * 8,
        "parentSpanId": None,
        "stageId": "report.generation",
        "kind": "orchestration",
        "reportId": "r-1",
        "scope": "full_simplified",
        "status": "succeeded",
        "errorCode": "",
        "durationMs": 10,
        "startedAt": "2026-08-05T00:00:00+00:00",
        "attributes": {"sustainability_desk.block_count": 1},
    }
    record.update(overrides)
    return record


def _write(directory: Path, name: str, records: list[dict]) -> None:
    path = directory / name
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def _invocation(span_id: str) -> dict:
    return {"eventType": "model_invocation", "spanId": span_id, "stageId": "generation.block"}


def test_clean_unit_trace_passes(tmp_path: Path) -> None:
    block = _stage_record(
        spanId="bb" * 8,
        parentSpanId="aa" * 8,
        stageId="generation.block",
        kind="llm",
        attributes={"sustainability_desk.block_id": "p.x"},
    )
    _write(tmp_path, "run-1.stages.jsonl", [_stage_record(), block])
    _write(tmp_path, "run-1.jsonl", [_invocation("bb" * 8)])
    report = validate_trace_directory(tmp_path)
    assert report.stage_trace_count == 1
    assert report.is_clean(), report.findings


def test_orphan_span_and_multiple_roots_detected(tmp_path: Path) -> None:
    orphan = _stage_record(spanId="cc" * 8, parentSpanId="ee" * 8, stageId="delivery.render")
    second_root = _stage_record(spanId="dd" * 8, stageId="delivery.export_gate")
    _write(tmp_path, "run-2.stages.jsonl", [_stage_record(), orphan, second_root])
    _write(tmp_path, "run-2.jsonl", [])
    report = validate_trace_directory(tmp_path)
    checks = {finding.check for finding in report.findings}
    assert "single_root" in checks
    assert "no_orphans" in checks


def test_block_span_count_must_match_declared(tmp_path: Path) -> None:
    _write(tmp_path, "run-3.stages.jsonl", [_stage_record()])  # 声明 1 块，零块 span
    _write(tmp_path, "run-3.jsonl", [])
    report = validate_trace_directory(tmp_path)
    assert any(f.check == "block_span_completeness" for f in report.findings)


def test_invocation_must_join_to_stage_span(tmp_path: Path) -> None:
    _write(tmp_path, "run-4.stages.jsonl", [_stage_record(attributes={})])
    _write(tmp_path, "run-4.jsonl", [_invocation("99" * 8)])
    report = validate_trace_directory(tmp_path)
    checks = {finding.check for finding in report.findings}
    assert "invocation_span_join" in checks
    assert "block_count_declared" in checks


def test_missing_report_id_on_scoped_span_detected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "run-5.stages.jsonl",
        [_stage_record(reportId="", attributes={"sustainability_desk.block_count": 0})],
    )
    _write(tmp_path, "run-5.jsonl", [])
    report = validate_trace_directory(tmp_path)
    assert any(f.check == "report_id_present" for f in report.findings)
