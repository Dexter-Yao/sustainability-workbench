# ABOUTME: 报告谱系边的持久化与受限投影；各领域对象仍为事实 owner，本模块只维护跨域关系。
# ABOUTME: 所有读取均以 Report/Account 所有权裁决，绝不返回 Storage 路径、模型上下文或审计轨迹正文。
# ABOUTME(en): Persists and narrowly projects report lineage edges; domain objects stay the fact owners here.
# ABOUTME(en): Reads are gated on Report/Account ownership; never returns Storage paths or trace bodies.
from __future__ import annotations

from collections import defaultdict
from typing import Iterable
from uuid import UUID

import asyncpg

from sustainability_desk.contract.report_lineage import (
    ReportLineageBlockProjection,
    ReportLineageEdge,
    ReportLineageEdgeProjection,
    ReportLineageProjection,
)


async def append_edges(
    connection: asyncpg.Connection,
    *,
    account_id: UUID,
    edges: Iterable[ReportLineageEdge],
) -> None:
    """同一领域事务内追加 immutable 谱系边；相同 edge ID 可安全重放。"""

    for edge in edges:
        await connection.execute(
            """
            insert into report_lineage_edges (
              id, account_id, report_id, adapter_id, edge_kind,
              from_kind, from_ref, to_kind, to_ref, decision, reason_code, explanation,
              source_id, source_sha256, fragment_id, fragment_locator, run_id,
              report_state_seq, input_fingerprint, context_fingerprint, status
            ) values (
              $1, $2, $3, $4, $5,
              $6, $7, $8, $9, $10, $11, $12,
              $13, $14, $15, $16, $17,
              $18, $19, $20, $21
            ) on conflict (id) do nothing
            """,
            edge.id,
            account_id,
            edge.report_id,
            edge.adapter_id,
            edge.edge_kind,
            edge.from_kind,
            edge.from_ref,
            edge.to_kind,
            edge.to_ref,
            edge.decision,
            edge.reason_code,
            edge.explanation,
            edge.source_id,
            edge.source_sha256,
            edge.fragment_id,
            edge.fragment_locator.model_dump(mode="json") if edge.fragment_locator else None,
            edge.run_id,
            edge.report_state_seq,
            edge.input_fingerprint,
            edge.context_fingerprint,
            edge.status,
        )


async def mark_source_stale(
    connection: asyncpg.Connection,
    *,
    account_id: UUID,
    source_id: UUID,
) -> None:
    """资料被删除后保留最小历史关系，但明确标记为不可再核验。"""

    await connection.execute(
        """
        update report_lineage_edges
        set status = 'stale'
        where account_id = $1 and source_id = $2 and status = 'active'
        """,
        account_id,
        source_id,
    )


async def get_projection(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
) -> ReportLineageProjection:
    """从谱系边和当前 Report 版本派生用户可见链路。"""

    report = await pool.fetchrow(
        """
        select state_seq from report_states s
        join reports r on r.id = s.report_id
        where s.report_id = $1 and r.account_id = $2
        """,
        report_id,
        account_id,
    )
    if report is None:
        raise ValueError("报告不存在或无权读取谱系")
    rows = await pool.fetch(
        """
        select e.*, s.original_filename as source_name, s.status as source_status
        from report_lineage_edges e
        left join material_sources s on s.id = e.source_id
        where e.report_id = $1 and e.account_id = $2
        order by e.created_at asc, e.id asc
        """,
        report_id,
        account_id,
    )
    current_state_seq = int(report["state_seq"])
    edges: list[ReportLineageEdgeProjection] = []
    block_edges: dict[str, list[asyncpg.Record]] = defaultdict(list)
    for row in rows:
        status = "stale" if row["source_status"] == "deleted" else row["status"]
        edge = ReportLineageEdgeProjection(
            id=row["id"],
            edge_kind=row["edge_kind"],
            from_kind=row["from_kind"],
            from_ref=row["from_ref"],
            to_kind=row["to_kind"],
            to_ref=row["to_ref"],
            decision=row["decision"],
            reason_code=row["reason_code"],
            explanation=row["explanation"],
            status=status,
            source_id=row["source_id"],
            source_name=row["source_name"],
            fragment_id=row["fragment_id"],
            fragment_locator=row["fragment_locator"],
            report_state_seq=row["report_state_seq"],
            created_at=row["created_at"],
        )
        edges.append(edge)
        if edge.edge_kind == "report_input_to_block":
            block_edges[edge.to_ref].append(row)

    blocks: list[ReportLineageBlockProjection] = []
    for block_id, links in sorted(block_edges.items()):
        seqs = {int(row["report_state_seq"]) for row in links if row["report_state_seq"] is not None}
        generated_seq = max(seqs) if seqs else None
        if generated_seq is not None and generated_seq < current_state_seq:
            status = "changed_after_generation"
        elif any(row["decision"] == "held_low_confidence" for row in links):
            status = "no_user_provided_content"
        else:
            status = "linked"
        source_ids = {row["source_id"] for row in links if row["source_id"] is not None}
        input_refs = {row["from_ref"] for row in links}
        blocks.append(
            ReportLineageBlockProjection(
                block_id=block_id,
                status=status,
                source_count=len(source_ids),
                input_count=len(input_refs),
                generated_report_state_seq=generated_seq,
            )
        )
    return ReportLineageProjection(
        report_id=report_id,
        report_state_seq=current_state_seq,
        edges=tuple(edges),
        blocks=tuple(blocks),
    )
