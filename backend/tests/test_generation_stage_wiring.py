# ABOUTME: 校验轻量版生成主链的阶段插桩确实成树，且属性不含正文（spec §4 内容边界）。
# ABOUTME: 用真实阶段常量驱动，只替换 open_stage 记录调用；不触发模型调用与数据库。
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sustainability_desk.observability.stage_trace import read_stage_records, stage_trace_path
from sustainability_desk.observability.stages import open_stage
from sustainability_desk.lightweight_report_generation import (
    DELIVERY_RENDER_STAGE,
    EXPORT_GATE_STAGE,
    MODULE_TITLES_STAGE,
    REPORT_GENERATION_STAGE,
)

REPORT = "report-wiring-0001"


@pytest.fixture(autouse=True)
def _isolate_stage_trace(tmp_path, monkeypatch):
    """未显式传 trace_root 的用例也不得写入真实观测目录。"""
    monkeypatch.setattr(
        "sustainability_desk.llm.ai_observability.DEFAULT_OBSERVABILITY_ROOT", tmp_path
    )
    monkeypatch.setattr(
        "sustainability_desk.runtime_environment.runtime_environment",
        lambda: SimpleNamespace(observability_root=tmp_path),
    )


def test_report_generation_is_unit_root() -> None:
    """生成主链的根阶段是工作单元根——observation 的 operation 词汇由它派生。"""
    assert REPORT_GENERATION_STAGE.unit_root
    assert REPORT_GENERATION_STAGE.id == "report.generation"


def test_export_gate_attributes_carry_codes_not_messages() -> None:
    """导出闸只记 issue code；message 含报告正文片段，不得进 span。"""
    with open_stage(
        REPORT_GENERATION_STAGE,
        trace_id="t-1",
        report_id=REPORT,
        scope="full_simplified",
    ) as root:
        with open_stage(
            EXPORT_GATE_STAGE,
            trace_id="t-1",
            report_id=REPORT,
            scope="full_simplified",
            parent=root,
        ) as handle:
            handle.set_attribute("sustainability_desk.export_blocked", True)
            handle.set_attribute("sustainability_desk.export_issue_codes", ["missing_metric"])
            with pytest.raises(Exception):
                # 正文类键不在允许命名空间，写入即失败。
                handle.set_attribute("export_message", "某段正文……")
    assert handle.attributes["sustainability_desk.export_issue_codes"] == ["missing_metric"]


def test_delivery_failure_is_locatable_from_trace(tmp_path) -> None:
    """交付失败必须能从轨迹定位到具体环节——这是 tracing 要保护的用户目标。

    不断言 span 的父子字段（那是实现细节）；断言的是运行结束后，
    人能从留下的事实里查出"哪一步失败了、失败在什么上"。
    """
    with pytest.raises(RuntimeError):
        with open_stage(
            REPORT_GENERATION_STAGE,
            trace_id="t-2",
            report_id=REPORT,
            scope="full_simplified",
            trace_root=tmp_path,
        ) as root:
            with open_stage(
                DELIVERY_RENDER_STAGE,
                trace_id="t-2",
                report_id=REPORT,
                scope="full_simplified",
                parent=root,
                trace_root=tmp_path,
            ) as render:
                render.set_attribute("sustainability_desk.artifact_count", 0)
                raise RuntimeError("交付渲染失败")

    records = read_stage_records(stage_trace_path(tmp_path, "t-2"))
    failed = [r for r in records if r.status == "failed"]
    assert {r.stageId for r in failed} == {"delivery.render", "report.generation"}
    render_record = next(r for r in failed if r.stageId == "delivery.render")
    assert render_record.errorCode == "RuntimeError"
    assert render_record.attributes["sustainability_desk.artifact_count"] == 0
    assert render_record.reportId == REPORT


def test_module_titles_stage_runs_in_generation_scope() -> None:
    """模块标题阶段在报告生成范围内可开启。"""
    for scope_kind in ("full_simplified",):
        with open_stage(
            REPORT_GENERATION_STAGE,
            trace_id="t-3",
            report_id=REPORT,
            scope=scope_kind,
        ):
            with open_stage(
                MODULE_TITLES_STAGE,
                trace_id="t-3",
                report_id=REPORT,
                scope=scope_kind,
            ):
                pass
