# ABOUTME: 校验资料链路的阶段接线：一个工作单元一条 trace、reportId 聚合键、装配期失败留痕。
# ABOUTME: 关注运行结束后能否归因，不断言 span 对象的内部形状。
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sustainability_desk.material.agent_pipeline import (
    FILE_AGENT_STAGE,
    IMAGE_AGENT_STAGE,
    MAPPING_RUN_STAGE,
    MAPPING_SCOPE_CHECK_STAGE,
)
from sustainability_desk.observability.stage_trace import read_stage_records, stage_trace_path
from sustainability_desk.observability.stages import open_stage

REPORT = "924f272c-b6c4-48fe-ae22-d92ee1f97b2f"


@pytest.fixture(autouse=True)
def _isolate_stage_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sustainability_desk.llm.ai_observability.DEFAULT_OBSERVABILITY_ROOT", tmp_path
    )
    monkeypatch.setattr(
        "sustainability_desk.runtime_environment.runtime_environment",
        lambda: SimpleNamespace(observability_root=tmp_path),
    )


def test_material_unit_roots_are_registered() -> None:
    """三类资料工作单元的根阶段必须声明 unit_root——observation 词汇由其派生。"""
    for stage in (FILE_AGENT_STAGE, IMAGE_AGENT_STAGE, MAPPING_RUN_STAGE):
        assert stage.unit_root, f"{stage.id} 未声明 unit_root"
    assert not MAPPING_SCOPE_CHECK_STAGE.unit_root


def test_each_unit_run_is_its_own_trace(tmp_path) -> None:
    """一个工作单元一条 trace（traceId=run_id）；报告级聚合靠 reportId 字段。"""
    run_ids = ("file-run-1", "image-run-1", "mapping-run-1")
    for stage, run_id in zip(
        (FILE_AGENT_STAGE, IMAGE_AGENT_STAGE, MAPPING_RUN_STAGE), run_ids
    ):
        with open_stage(
            stage,
            trace_id=run_id,
            report_id=REPORT,
            scope="full_simplified",
            trace_root=tmp_path,
        ):
            pass

    for stage, run_id in zip(
        (FILE_AGENT_STAGE, IMAGE_AGENT_STAGE, MAPPING_RUN_STAGE), run_ids
    ):
        (record,) = read_stage_records(stage_trace_path(tmp_path, run_id))
        assert record.stageId == stage.id
        assert record.traceId == run_id, "traceId 必须是该单元的 run_id"
        assert record.reportId == REPORT, "跨单元聚合靠 reportId 字段"


def test_mapping_scope_check_nests_under_unit_root(tmp_path) -> None:
    """scope 一致性校验是 mapping 单元根的子 span，装配期失败与模型调用同树可归因。

    回归：report-area 因合同变更导致冻结 scope 不一致而失败时，
    若该校验位于观测建立之前，整条运行零轨迹。
    """
    with pytest.raises(ValueError):
        with open_stage(
            MAPPING_RUN_STAGE,
            trace_id="mapping-run-2",
            report_id=REPORT,
            scope="full_simplified",
            trace_root=tmp_path,
            **{"sustainability_desk.scope_id": "report-area:sustainability_mgmt"},
        ):
            with open_stage(
                MAPPING_SCOPE_CHECK_STAGE,
                trace_id="mapping-run-2",
                report_id=REPORT,
                scope="full_simplified",
                trace_root=tmp_path,
            ):
                raise ValueError("冻结 Mapping scope 的 Block 或语义任务已变化")

    records = read_stage_records(stage_trace_path(tmp_path, "mapping-run-2"))
    by_stage = {record.stageId: record for record in records}
    check_record = by_stage["material.mapping.scope_check"]
    root_record = by_stage["material.mapping_agent"]
    assert check_record.status == "failed"
    assert check_record.errorCode == "ValueError"
    assert check_record.parentSpanId == root_record.spanId, "校验必须嵌套在单元根下"
    assert root_record.status == "failed", "子阶段失败沿树上抛，单元根同样留痕"
