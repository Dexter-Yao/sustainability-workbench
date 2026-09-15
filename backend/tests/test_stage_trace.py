# ABOUTME: 校验阶段轨迹落盘与回读——收束断言与轨迹一致性校验赖以比对的事实基础。
# ABOUTME: 关注运行结束后留下了什么可查证事实，而非 span 对象的内部形状。
from __future__ import annotations

import pytest

from sustainability_desk.observability.stage_trace import (
    SCHEMA_VERSION,
    executed_stage_ids,
    read_stage_records,
    stage_trace_path,
)
from sustainability_desk.observability.stages import open_stage
from sustainability_desk.lightweight_report_generation import (
    EXPORT_GATE_STAGE,
    REPORT_GENERATION_STAGE,
)

TRACE = "trace-persist-0001"
REPORT = "report-persist-0001"


def _path(tmp_path):
    return stage_trace_path(tmp_path, TRACE)


def test_completed_run_leaves_queryable_facts(tmp_path) -> None:
    """一次运行结束后必须留下阶段事实，而不只是过程中的内存句柄。"""
    with open_stage(
        REPORT_GENERATION_STAGE,
        trace_id=TRACE,
        report_id=REPORT,
        scope="full_simplified",
        trace_root=tmp_path,
    ) as root:
        with open_stage(
            EXPORT_GATE_STAGE,
            trace_id=TRACE,
            report_id=REPORT,
            scope="full_simplified",
            parent=root,
            trace_root=tmp_path,
        ) as gate:
            gate.set_attribute("sustainability_desk.export_blocked", False)

    records = read_stage_records(_path(tmp_path))
    assert {r.stageId for r in records} == {"report.generation", "delivery.export_gate"}
    gate_record = next(r for r in records if r.stageId == "delivery.export_gate")
    assert gate_record.schemaVersion == SCHEMA_VERSION == "sustainability_desk.stage_trace.v2"
    assert gate_record.status == "succeeded"
    assert gate_record.attributes["sustainability_desk.export_blocked"] is False
    assert gate_record.traceId == TRACE
    # v2：reportId 是顶级聚合键，跨工作单元检索靠它而非伪造的父子。
    assert all(r.reportId == REPORT for r in records)


def test_failed_stage_records_error_code(tmp_path) -> None:
    """失败阶段必须留下可归因的错误类型，而不是消失。"""
    with pytest.raises(ValueError):
        with open_stage(
            REPORT_GENERATION_STAGE,
            trace_id=TRACE,
            report_id=REPORT,
            scope="full_simplified",
            trace_root=tmp_path,
        ):
            raise ValueError("boom")

    (record,) = read_stage_records(_path(tmp_path))
    assert record.status == "failed"
    assert record.errorCode == "ValueError"


def test_executed_stage_ids_supports_completeness_check(tmp_path) -> None:
    """收束断言与轨迹校验要比对实际执行集合，前提是能从轨迹回读出来。"""
    with open_stage(
        REPORT_GENERATION_STAGE,
        trace_id=TRACE,
        report_id=REPORT,
        scope="full_simplified",
        trace_root=tmp_path,
    ):
        pass
    executed = executed_stage_ids(_path(tmp_path))
    assert "report.generation" in executed
    assert "delivery.toc.finalize" not in executed


def test_corrupt_trace_line_fails_loud(tmp_path) -> None:
    """轨迹损坏必须当场报错；静默跳过会让完整性比对误判为阶段未执行。"""
    path = _path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"not": "a stage record"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不可解析"):
        read_stage_records(path)


def test_missing_trace_reads_as_empty(tmp_path) -> None:
    assert read_stage_records(_path(tmp_path)) == ()


def test_persist_failure_is_recorded_not_swallowed(tmp_path) -> None:
    """落盘失败不拖垮业务，但必须留痕——否则轨迹缺口无从察觉。"""
    blocked = tmp_path / "blocked"
    blocked.write_text("不是目录", encoding="utf-8")
    with open_stage(
        REPORT_GENERATION_STAGE,
        trace_id=TRACE,
        report_id=REPORT,
        scope="full_simplified",
        trace_root=blocked,
    ) as handle:
        pass
    assert handle.persist_error, "落盘失败必须记录原因"
    assert handle.status == "succeeded", "业务结果不受观测故障影响"
