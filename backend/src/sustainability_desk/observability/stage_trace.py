# ABOUTME: 阶段轨迹的落盘与回读，使一次运行结束后留下可查证的阶段事实而非仅内存句柄。
# ABOUTME: 与 ai_observability 的模型事件 JSONL 平行共存：同一 trace_id 归集，各自拥有各自的事实。
# ABOUTME(en): Persists and reads back stage records so a finished run leaves verifiable stage facts on disk.
# ABOUTME(en): Coexists with the ai_observability model-event JSONL: joined by trace_id, each owning its facts.
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sustainability_desk.accounts.report_execution_scope import ReportScopeKind

SCHEMA_VERSION = "sustainability_desk.stage_trace.v2"

_WRITE_LOCK = threading.Lock()


class StageRecord(BaseModel):
    """一个已结束阶段的事实。属性只含决策与证据，不含正文（spec §4）。

    v2：traceId 恒为工作单元 run_id（与模型事件文件名对齐）；reportId 升为顶级
    字段作为跨单元聚合键；scope 对不受报告范围约束的单元（eval 等）可为空。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: Literal["sustainability_desk.stage_trace.v2"] = SCHEMA_VERSION
    traceId: str
    spanId: str
    parentSpanId: str | None
    stageId: str
    kind: str
    reportId: str
    scope: ReportScopeKind | None
    status: str
    errorCode: str
    durationMs: int
    startedAt: str
    attributes: dict[str, object]


def stage_trace_path(root: Path, trace_id: str, *, day: str | None = None) -> Path:
    """阶段轨迹与模型事件同日同 trace 归集，以 .stages 后缀区分两类事实。"""
    resolved_day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return root / resolved_day / f"{trace_id}.stages.jsonl"


def append_stage_record(path: Path, record: StageRecord) -> None:
    """追加一条阶段事实；权限与 ai_observability 的受限目录约定一致。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    line = record.model_dump_json()
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        path.chmod(0o600)


def read_stage_records(path: Path) -> tuple[StageRecord, ...]:
    """回读一次运行的阶段轨迹。文件不存在返回空，损坏行当场抛错不静默跳过。"""
    if not path.is_file():
        return ()
    records: list[StageRecord] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(StageRecord.model_validate(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"阶段轨迹 {path} 第 {index} 行不可解析：{exc}") from exc
    return tuple(records)


def executed_stage_ids(path: Path) -> frozenset[str]:
    """本次运行实际产生过 span 的阶段集合，供闸门四比对必经阶段。"""
    return frozenset(record.stageId for record in read_stage_records(path))
