# ABOUTME: 内部审计包对轨迹缺失的降级合同——证据取不到不得否决已经完成的交付。
# ABOUTME: 报告身份不一致仍是硬失败：那是完整性违约，不是证据缺失。
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4
import zipfile

import pytest

from sustainability_desk.report_review_packages import InternalTraceReference
from sustainability_desk.lightweight_report_generation import (
    ReportGenerationServiceError,
    _write_internal_audit_zip,
)


def _reference(**overrides) -> InternalTraceReference:
    base = {
        "stage": "mapping",
        "trace_id": "run-1",
        "contract": "sustainability_desk.ai_observability.v3",
        "input_fingerprint": "a" * 64,
        "output_fingerprint": "b" * 64,
    }
    base.update(overrides)
    return InternalTraceReference(**base)


def _manifest(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as archive:
        return json.loads(archive.read("traces/manifest.json"))["entries"]


def test_missing_trace_degrades_instead_of_blocking_delivery(tmp_path) -> None:
    """引用已在解析边界降级：审计包照常产出，并如实记录该引用不可用。"""

    zip_path = tmp_path / "内部审计包.zip"
    _write_internal_audit_zip(
        zip_path,
        internal_json="{}",
        internal_markdown="# audit",
        customer_commentary_json="{}",
        trace_references=(_reference(unavailable_reason="轨迹在打包时不可读取"),),
        report_id=uuid4(),
    )

    assert zip_path.is_file(), "轨迹缺失不得阻断审计包产出"
    entries = _manifest(zip_path)
    assert entries == [
        {
            "stage": "mapping",
            "traceId": "run-1",
            "available": False,
            "unavailableReason": "轨迹在打包时不可读取",
        }
    ]


def test_trace_that_vanished_after_resolution_also_degrades(tmp_path) -> None:
    """解析时还在、打包时没了（轮转/清理）同样降级，不阻断。"""

    zip_path = tmp_path / "内部审计包.zip"
    _write_internal_audit_zip(
        zip_path,
        internal_json="{}",
        internal_markdown="# audit",
        customer_commentary_json="{}",
        trace_references=(_reference(storage_ref=str(tmp_path / "gone.jsonl")),),
        report_id=uuid4(),
    )

    assert zip_path.is_file()
    assert _manifest(zip_path)[0]["available"] is False


def test_trace_belonging_to_another_report_still_fails_hard(tmp_path) -> None:
    """报告身份不一致是完整性违约，必须继续阻断——这不是证据缺失。"""

    other_report = uuid4()
    trace = tmp_path / "run-1.jsonl"
    trace.write_text(
        json.dumps(
            {
                "schemaVersion": "sustainability_desk.ai_observability.v3",
                "eventType": "generation_started",
                "runId": "run-1",
                "traceId": "run-1",
                "requestId": "req-1",
                "workloadKind": "product_generation",
                "reportId": str(other_report),
                "blockId": "b",
                "operation": "material.mapping_agent",
                "environment": "test",
                "releaseId": "r",
                "gitSha": "g",
                "contractVersion": "c",
                "timestamp": "2026-08-20T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReportGenerationServiceError, match="报告身份不一致"):
        _write_internal_audit_zip(
            tmp_path / "内部审计包.zip",
            internal_json="{}",
            internal_markdown="# audit",
            customer_commentary_json="{}",
            trace_references=(_reference(storage_ref=str(trace)),),
            report_id=uuid4(),
        )
