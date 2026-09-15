# ABOUTME: 统一报告谱系的合同测试，验证用户投影只消费稳定引用并如实标记报告/来源失效。
# ABOUTME: 测试不读取原文件、Prompt 或模型观测正文，避免把审计层误作为产品谱系事实。
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sustainability_desk.contract.report_lineage import ReportLineageEdge
from sustainability_desk.material.intake.models import DocxParagraphLocator
from sustainability_desk.persistence.report_lineage import append_edges, get_projection


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> None:
        self.calls.append((query, args))


class _Pool:
    def __init__(self, *, state_seq: int, rows: list[dict]) -> None:
        self.state_seq = state_seq
        self.rows = rows

    async def fetchrow(self, _query: str, *_args: object):
        return {"state_seq": self.state_seq}

    async def fetch(self, _query: str, *_args: object):
        return self.rows


@pytest.mark.asyncio
async def test_append_edge_persists_only_reference_and_locator_contract() -> None:
    report_id = uuid4()
    source_id = uuid4()
    edge = ReportLineageEdge(
        report_id=report_id,
        adapter_id="simplified-report-input@2",
        edge_kind="source_fragment_to_fact",
        from_kind="material_fragment",
        from_ref=f"{source_id}:paragraph-3",
        to_kind="material_fact",
        to_ref=str(uuid4()),
        decision="confirmed",
        reason_code="deterministic_fact_confirmed",
        explanation="资料片段满足确定性确认规则。",
        source_id=source_id,
        source_sha256="a" * 64,
        fragment_id="paragraph-3",
        fragment_locator=DocxParagraphLocator(paragraph_index=3),
    )
    connection = _Connection()

    await append_edges(connection, account_id=uuid4(), edges=(edge,))

    assert len(connection.calls) == 1
    query, args = connection.calls[0]
    assert "report_lineage_edges" in query
    assert args[14] == "paragraph-3"
    assert args[15] == {"kind": "docx_paragraph", "paragraph_index": 3}
    assert "object_path" not in str(args)
    assert "Prompt" not in str(args)


@pytest.mark.asyncio
async def test_projection_marks_later_report_revision_and_deleted_source_without_losing_history() -> None:
    report_id = uuid4()
    source_id = uuid4()
    row = {
        "id": uuid4(),
        "edge_kind": "report_input_to_block",
        "from_kind": "report_input",
        "from_ref": "climate.q_training_activities",
        "to_kind": "report_block",
        "to_ref": "climate_change.training",
        "decision": "auto_applied",
        "reason_code": "compiled_input_consumer",
        "explanation": "当前 Block 消费该受控输入。",
        "status": "active",
        "source_id": source_id,
        "source_name": "气候制度.docx",
        "source_status": "deleted",
        "fragment_id": "paragraph-3",
        "fragment_locator": {"kind": "docx_paragraph", "paragraph_index": 3},
        "report_state_seq": 3,
        "created_at": datetime.now(timezone.utc),
    }

    projection = await get_projection(
        _Pool(state_seq=4, rows=[row]),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=report_id,
    )

    assert projection.edges[0].status == "stale"
    assert projection.edges[0].source_name == "气候制度.docx"
    assert projection.blocks == (
        projection.blocks[0].model_copy(
            update={
                "status": "changed_after_generation",
                "source_count": 1,
                "input_count": 1,
                "generated_report_state_seq": 3,
            }
        ),
    )
