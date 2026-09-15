# ABOUTME: 金样 E2E 轨迹的一致性校验——按 spec §5 断言单元 trace 树形、聚合键与两类事实的可 join 性。
# ABOUTME: 只读校验器，不产生观测事实；发现即返回 typed findings，CLI 非零退出，不静默放过。
# ABOUTME(en): Conformance check over golden E2E traces — asserts per-unit trace tree, aggregation keys and that
# ABOUTME(en): the two kinds of facts join. Read-only validator returning typed findings; the CLI exits non-zero.
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sustainability_desk.observability.stage_trace import StageRecord, read_stage_records


@dataclass(frozen=True)
class TraceFinding:
    """一处轨迹一致性违例。"""

    trace_id: str
    check: str
    detail: str


@dataclass
class TraceConformanceReport:
    """一个轨迹目录的校验结果；findings 为空即通过。"""

    stage_trace_count: int = 0
    findings: list[TraceFinding] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not self.findings


def _model_invocation_span_ids(model_events_path: Path) -> list[tuple[str, str]]:
    """取模型事件文件中每条 model_invocation 的 (spanId, stageId)。

    只读取 join 所需两个字段，宽松于完整事件合同：本校验器面向轨迹结构，
    事件正文合法性由 parse_observability_event 的消费方负责。
    """
    pairs: list[tuple[str, str]] = []
    for line in model_events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("eventType") != "model_invocation":
            continue
        pairs.append((str(payload.get("spanId", "")), str(payload.get("stageId", ""))))
    return pairs


def _check_tree(trace_id: str, records: tuple[StageRecord, ...]) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    span_ids = {record.spanId for record in records}
    roots = [record for record in records if record.parentSpanId is None]
    if len(roots) != 1:
        findings.append(
            TraceFinding(
                trace_id,
                "single_root",
                f"单元 trace 应恰有一个根 span，实际 {len(roots)} 个"
                f"（{sorted(record.stageId for record in roots)}）",
            )
        )
    for record in records:
        if record.parentSpanId is not None and record.parentSpanId not in span_ids:
            findings.append(
                TraceFinding(
                    trace_id,
                    "no_orphans",
                    f"span {record.stageId}({record.spanId}) 的父 {record.parentSpanId} 不在本 trace 内",
                )
            )
        if record.traceId != trace_id:
            findings.append(
                TraceFinding(
                    trace_id,
                    "trace_id_matches_filename",
                    f"记录 traceId={record.traceId} 与文件名不符",
                )
            )
    return findings


def _check_report_id(trace_id: str, records: tuple[StageRecord, ...]) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    for record in records:
        if record.scope is not None and not record.reportId:
            findings.append(
                TraceFinding(
                    trace_id,
                    "report_id_present",
                    f"报告链路 span {record.stageId} 缺少 reportId 聚合键",
                )
            )
    return findings


def _check_block_completeness(
    trace_id: str, records: tuple[StageRecord, ...]
) -> list[TraceFinding]:
    """生成单元：逐块 span 数量须与根 span 声明的 block_count 一致。"""
    roots = [record for record in records if record.stageId == "report.generation"]
    if not roots:
        return []
    declared = roots[0].attributes.get("sustainability_desk.block_count")
    block_spans = [record for record in records if record.stageId == "generation.block"]
    if not isinstance(declared, int):
        return [
            TraceFinding(
                trace_id,
                "block_count_declared",
                "report.generation 根 span 缺少 sustainability_desk.block_count 属性",
            )
        ]
    if len(block_spans) != declared:
        return [
            TraceFinding(
                trace_id,
                "block_span_completeness",
                f"逐块 span {len(block_spans)} 条，与根声明的 {declared} 不符",
            )
        ]
    return []


def _check_invocation_join(
    trace_id: str, records: tuple[StageRecord, ...], model_events_path: Path
) -> list[TraceFinding]:
    if not model_events_path.is_file():
        return [
            TraceFinding(
                trace_id,
                "model_events_alignment",
                f"缺少同名模型事件文件 {model_events_path.name}",
            )
        ]
    span_ids = {record.spanId for record in records}
    findings: list[TraceFinding] = []
    for span_id, stage_id in _model_invocation_span_ids(model_events_path):
        if span_id not in span_ids:
            findings.append(
                TraceFinding(
                    trace_id,
                    "invocation_span_join",
                    f"model_invocation（stage {stage_id}）的 spanId {span_id} "
                    "无法 join 到任何阶段 span",
                )
            )
    return findings


def validate_trace_directory(day_directory: Path) -> TraceConformanceReport:
    """校验一个观测日目录下的全部单元轨迹（{run_id}.stages.jsonl + {run_id}.jsonl）。"""
    report = TraceConformanceReport()
    for stages_path in sorted(day_directory.glob("*.stages.jsonl")):
        trace_id = stages_path.name.removesuffix(".stages.jsonl")
        report.stage_trace_count += 1
        records = read_stage_records(stages_path)
        report.findings.extend(_check_tree(trace_id, records))
        report.findings.extend(_check_report_id(trace_id, records))
        report.findings.extend(_check_block_completeness(trace_id, records))
        report.findings.extend(
            _check_invocation_join(
                trace_id, records, day_directory / f"{trace_id}.jsonl"
            )
        )
    return report


def main() -> None:
    if len(sys.argv) != 2:
        print("用法：python -m sustainability_desk.observability.trace_conformance <观测日目录>")
        raise SystemExit(2)
    directory = Path(sys.argv[1])
    if not directory.is_dir():
        print(f"目录不存在：{directory}")
        raise SystemExit(2)
    report = validate_trace_directory(directory)
    print(f"已校验 {report.stage_trace_count} 条单元轨迹")
    if report.is_clean():
        print("轨迹一致性校验通过")
        return
    for finding in report.findings:
        print(f"[{finding.check}] trace {finding.trace_id}: {finding.detail}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
