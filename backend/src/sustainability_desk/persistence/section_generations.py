# ABOUTME: 整节生成用量账本与原子页面写回——预留批次、完整成功计数、失败释放、state_seq 冲突不污染报告。
# ABOUTME: Report 是正文 SSOT；批次表只保存幂等、状态与块清单，不复制模型正文。
# ABOUTME(en): Whole-section generation quota ledger and atomic write-back — reserved batches, success counting,
# ABOUTME(en): failure release. Report is the prose SSOT; the batch table keeps idempotency, status, block lists.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Literal
from uuid import UUID

import asyncpg


from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.section_titles import paragraph_fingerprint
from sustainability_desk.contract.models import Report
from sustainability_desk.contract.stored_report_state import StoredTableRow


def material_gated_block_ids(package: KnowledgePackage) -> frozenset[str]:
    """按报告合同声明 omit_if_unsupported 的块集合；受控省略资格以合同为准，不信任结果自述。

    整节重写的 fail-closed 前置也用本函数判定「本节是否含门控块」——两处若各用一套口径
    （一处读编译合同、一处嗅探运行期 selector），迟早在某个块上给出相反答案。
    """

    return frozenset(
        contract.block_id
        for contract in load_compiled_report_definition(package).generation_contracts.values()
        if contract.absence_behavior == "omit_if_unsupported"
    )

BATCH_LEASE = timedelta(minutes=15)

_TABLE_ROW_KEYS = frozenset(
    {"type", "headerRow", "state", "origin", "generation", "appears_when", "children"}
)
_TABLE_CELL_KEYS = frozenset(
    {"type", "colKey", "value", "options", "colSpan", "rowSpan", "cellState", "children"}
)


def _stored_table_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """将运行时表格节点投影为 V4 可持久化行，拒绝未声明的模型或模板字段。"""

    stored_rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, dict):
            raise ValueError(f"表格第 {index + 1} 行不是对象")
        unknown_row_keys = set(raw_row) - _TABLE_ROW_KEYS
        if unknown_row_keys:
            raise ValueError(f"表格第 {index + 1} 行包含未声明字段")
        raw_cells = raw_row.get("children")
        if not isinstance(raw_cells, list):
            raise ValueError(f"表格第 {index + 1} 行缺少单元格")
        cells: list[dict[str, Any]] = []
        for cell_index, raw_cell in enumerate(raw_cells):
            if not isinstance(raw_cell, dict):
                raise ValueError(f"表格第 {index + 1} 行第 {cell_index + 1} 格不是对象")
            unknown_cell_keys = set(raw_cell) - _TABLE_CELL_KEYS
            if unknown_cell_keys:
                raise ValueError(f"表格第 {index + 1} 行第 {cell_index + 1} 格包含未声明字段")
            cells.append(
                {
                    key: raw_cell[key]
                    for key in ("type", "colKey", "value", "options", "colSpan", "rowSpan", "cellState")
                    if key in raw_cell
                }
            )
        row_payload = {
            key: raw_row[key]
            for key in ("type", "headerRow", "state", "origin")
            if key in raw_row
        }
        row_payload["children"] = cells
        try:
            stored = StoredTableRow.model_validate(row_payload)
        except ValueError as error:
            raise ValueError(f"表格第 {index + 1} 行不符合持久化合同") from error
        stored_rows.append(stored.model_dump(mode="json", by_alias=True))
    return stored_rows


class GenerationBatchError(Exception):
    """整节生成账本的业务错误基类。"""


class GenerationAlreadyRunningError(GenerationBatchError):
    """同一报告页面已有未过期的生成批次。"""


class GenerationIdempotencyConflictError(GenerationBatchError):
    """幂等键已用于其他报告、页面或失败请求。"""


class GenerationQuotaExceededError(GenerationBatchError):
    """完整成功的重写次数与当前预留已达到权益上限。"""


class GenerationStateConflictError(GenerationBatchError):
    """客户端基于的状态快照已过期。"""


class GenerationBatchStatusConflictError(GenerationBatchError):
    """批次租约已过期，或批次已被其他事务终结。"""


@dataclass(frozen=True)
class GenerationBatch:
    id: UUID
    account_id: UUID
    report_id: UUID
    section_key: str
    mode: Literal["initial", "regeneration"]
    expected_block_ids: tuple[str, ...]
    status: Literal["started", "succeeded", "failed"]
    idempotency_key: UUID
    base_state_seq: int
    input_fingerprint: str
    replayed: bool = False


@dataclass(frozen=True)
class RewriteAllowance:
    quota: int
    used: int
    reserved: int

    @property
    def remaining(self) -> int:
        return max(0, self.quota - self.used - self.reserved)


def _batch(row: asyncpg.Record, *, replayed: bool = False) -> GenerationBatch:
    return GenerationBatch(
        id=row["id"],
        account_id=row["account_id"],
        report_id=row["report_id"],
        section_key=row["section_key"],
        mode=row["mode"],
        expected_block_ids=tuple(row["expected_block_ids"]),
        status=row["status"],
        idempotency_key=row["idempotency_key"],
        base_state_seq=row["base_state_seq"],
        input_fingerprint=row["input_fingerprint"],
        replayed=replayed,
    )


def section_generation_input_fingerprint(
    report: Report,
    section_key: str,
    *,
    allow_synthetic_definition_fallback: bool = False,
    material_set_fingerprint: str | None = None,
) -> str:
    """用目标页面每个生成块实际可见的 ModelContext 计算稳定输入指纹。

    ``allow_synthetic_definition_fallback`` 仅供合成模板测试使用；产品调用必须保持默认值。

    ``material_set_fingerprint`` 是冻结资料集合的指纹。整节重写开始消费冻结 Mapping 之后，
    资料变化必须让指纹变化，否则新鲜度会在资料已更新时恒报 `fresh`——用户看不到「可更新」。
    报告级指纹同样把 `materialSet` 折进去（见 `lightweight_report_generation`）。
    """
    from sustainability_desk.llm.generate_all import blocks_for_section
    from sustainability_desk.llm.generate import prepare_generation_context
    from sustainability_desk.llm.table_gen import prepare_table_model_context

    contexts = [
        {
            "blockId": block.id,
            "context": (
                prepare_table_model_context(block.id, report)
                if block.type == "table"
                else prepare_generation_context(
                    block.id,
                    report,
                    allow_synthetic_definition_fallback=allow_synthetic_definition_fallback,
                )[1]
            ).model_dump(mode="json"),
        }
        for block in blocks_for_section(report, section_key)
    ]
    encoded = json.dumps(
        {"contexts": contexts, "materialSet": material_set_fingerprint},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


async def reserve_batch(
    pool: asyncpg.Pool,
    *,
    account_id: UUID,
    report_id: UUID,
    section_key: str,
    expected_block_ids: tuple[str, ...],
    idempotency_key: UUID,
    base_state_seq: int,
    regeneration_quota: int,
    input_fingerprint: str,
) -> GenerationBatch:
    """事务内预留整节批次；过期租约先失败化，成功重写和活动预留共同占用额度。"""
    async with pool.acquire() as conn, conn.transaction():
        await conn.fetchval(
            "select id from reports where id = $1 and account_id = $2 and status = 'active' for update",
            report_id,
            account_id,
        )
        known = await conn.fetchrow(
            "select * from section_regeneration_batches where account_id = $1 and idempotency_key = $2",
            account_id,
            idempotency_key,
        )
        if known is not None:
            same_scope = (
                known["report_id"] == report_id and known["section_key"] == section_key
            )
            if (
                not same_scope
                or tuple(known["expected_block_ids"]) != expected_block_ids
            ):
                raise GenerationIdempotencyConflictError(str(idempotency_key))
            if known["status"] == "succeeded":
                return _batch(known, replayed=True)
            if known["status"] == "started":
                raise GenerationAlreadyRunningError(section_key)
            raise GenerationIdempotencyConflictError(str(idempotency_key))

        current_seq = await conn.fetchval(
            "select state_seq from report_states where report_id = $1", report_id
        )
        if current_seq != base_state_seq:
            raise GenerationStateConflictError(section_key)

        await conn.execute(
            """
            update section_regeneration_batches
            set status = 'failed', failure_reason = 'lease_expired', finished_at = now()
            where report_id = $1 and section_key = $2 and status = 'started'
              and lease_expires_at <= now()
            """,
            report_id,
            section_key,
        )
        active = await conn.fetchval(
            """
            select 1 from section_regeneration_batches
            where report_id = $1 and section_key = $2 and status = 'started'
            """,
            report_id,
            section_key,
        )
        if active is not None:
            raise GenerationAlreadyRunningError(section_key)

        has_initial = await conn.fetchval(
            """
            select 1 from section_regeneration_batches
            where report_id = $1 and section_key = $2 and status = 'succeeded'
            limit 1
            """,
            report_id,
            section_key,
        )
        mode = "regeneration" if has_initial is not None else "initial"
        if mode == "regeneration":
            used = await conn.fetchval(
                """
                select count(*) from section_regeneration_batches
                where report_id = $1 and section_key = $2
                  and mode = 'regeneration' and status = 'succeeded'
                """,
                report_id,
                section_key,
            )
            if used >= regeneration_quota:
                raise GenerationQuotaExceededError(section_key)

        row = await conn.fetchrow(
            """
            insert into section_regeneration_batches
              (account_id, report_id, section_key, mode, expected_block_ids, status,
               idempotency_key, base_state_seq, lease_expires_at, input_fingerprint)
            values ($1, $2, $3, $4, $5, 'started', $6, $7, now() + $8::interval, $9)
            returning *
            """,
            account_id,
            report_id,
            section_key,
            mode,
            list(expected_block_ids),
            idempotency_key,
            base_state_seq,
            BATCH_LEASE,
            input_fingerprint,
        )
    return _batch(row)


async def fail_batch(pool: asyncpg.Pool, batch_id: UUID, reason: str) -> None:
    """失败化活动批次并释放预留；已成功批次不可回退。"""
    await pool.execute(
        """
        update section_regeneration_batches
        set status = 'failed', failure_reason = left($2, 500), finished_at = now()
        where id = $1 and status = 'started'
        """,
        batch_id,
        reason,
    )


def _is_allowed_omission(
    item: dict[str, Any], *, allow_contract_omissions: bool, package: KnowledgePackage
) -> bool:
    """带理由的受控省略算成功：证据门控块按合同恒可省略，表格省略只在自动建报语义下允许。"""

    if item.get("status") != "omitted":
        return False
    if not (isinstance(item.get("reason"), str) and item["reason"].strip()):
        return False
    if item.get("blockId") in material_gated_block_ids(package):
        return True
    return allow_contract_omissions and item.get("kind") == "table"


def unsuccessful_generation_results(
    results: list[dict[str, Any]],
    *,
    allow_contract_omissions: bool,
    package: KnowledgePackage,
) -> list[dict[str, Any]]:
    """返回未成功生成的结果项；成功语义与 apply_generation_results 共用本判定。"""

    return [
        item
        for item in results
        if item.get("status") != "ready"
        and not _is_allowed_omission(
            item, allow_contract_omissions=allow_contract_omissions, package=package
        )
    ]


def apply_generation_results(
    state: dict[str, Any],
    expected_block_ids: tuple[str, ...],
    results: list[dict[str, Any]],
    *,
    package: KnowledgePackage,
    company_business_summary: str | None = None,
    allow_contract_omissions: bool = False,
) -> dict[str, Any]:
    """只把完整整节结果原子投影进 V4；标题与其正文候选不可拆分。

    自动建报可显式持久化“无数据行”的表格省略；常规整节重写仍保持
    ``ready`` 全成功门槛，避免意外改变已有工作台的失败语义。
    """
    by_id = {item.get("blockId"): item for item in results}
    if set(by_id) != set(expected_block_ids) or len(by_id) != len(results):
        raise ValueError("整节生成结果与服务端块清单不一致")
    if unsuccessful_generation_results(
        results, allow_contract_omissions=allow_contract_omissions, package=package
    ):
        raise ValueError("整节存在未成功生成的块")

    patched = dict(state)
    generated = dict(patched.get("generatedBlocks") or {})
    tables = dict(patched.get("tableBlocks") or {})
    section_titles = dict(patched.get("sectionTitles") or {})
    for block_id in expected_block_ids:
        item = by_id[block_id]
        if item.get("kind") == "table":
            if _is_allowed_omission(
                item, allow_contract_omissions=allow_contract_omissions, package=package
            ):
                tables[block_id] = {
                    "children": [],
                    "state": "omitted",
                }
                continue
            rows = item.get("rows")
            if not isinstance(rows, list):
                raise ValueError(f"表格块 {block_id} 缺少 rows")
            tables[block_id] = {
                "children": _stored_table_rows(rows),
                "state": "ready",
            }
            continue
        if _is_allowed_omission(
            item, allow_contract_omissions=allow_contract_omissions, package=package
        ):
            # 证据门控段落的受控省略：state 即处置，正文为空；renderability 据此
            # 让所在内容单元从正文与目录消失。
            generated[block_id] = {"state": "omitted"}
            continue
        variants = item.get("variants")
        if (
            not isinstance(variants, list)
            or not variants
            or not isinstance(variants[0], dict)
        ):
            raise ValueError(f"段落块 {block_id} 缺少正文候选")
        selected = variants[0]
        content = selected.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"段落块 {block_id} 缺少正文候选")
        generated[block_id] = {
            "content": [{"kind": "text", "text": content}],
            "state": "ready",
        }
        title_section_key = item.get("titleSectionKey")
        display_title = selected.get("displayTitle")
        if title_section_key is not None:
            if not isinstance(display_title, str) or not display_title.strip():
                raise ValueError(f"段落块 {block_id} 缺少配对标题")
            section_titles[title_section_key] = {
                "text": display_title.strip(),
                "origin": "generated",
                "inputFingerprint": paragraph_fingerprint(
                    [{"kind": "text", "text": content}]
                ),
            }
    patched["generatedBlocks"] = generated
    patched["tableBlocks"] = tables
    patched["sectionTitles"] = section_titles
    if company_business_summary:
        fields = dict(patched.get("fields") or {})
        fields["company_business_summary"] = company_business_summary
        patched["fields"] = fields
    return patched


def public_results_from_state(
    state: dict[str, Any], expected_block_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    """从 Report 状态 SSOT 投影整节 API 响应；用于成功响应与幂等重放。"""
    generated = state.get("generatedBlocks") or {}
    tables = state.get("tableBlocks") or {}
    out: list[dict[str, Any]] = []
    for block_id in expected_block_ids:
        if block_id in tables:
            out.append(
                {"block_id": block_id, "rows": tables[block_id].get("children") or []}
            )
            continue
        block = generated.get(block_id) or {}
        content = block.get("content") or []
        text = "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("kind") == "text"
        )
        out.append({"block_id": block_id, "text": text})
    return out


async def complete_batch(
    pool: asyncpg.Pool,
    *,
    batch: GenerationBatch,
    results: list[dict[str, Any]],
    package: KnowledgePackage,
    company_business_summary: str | None = None,
    input_fingerprint: str | None = None,
) -> int:
    """同一事务内以 state_seq 写入页面补丁并把批次成功化；冲突时只留下 failed 批次。"""
    conflict = False
    batch_conflict = False
    new_seq: int | None = None
    async with pool.acquire() as conn, conn.transaction():
        # 与 reserve_batch 保持相同加锁顺序，避免租约替换与完成事务互相等待。
        await conn.fetchval(
            "select id from reports where id = $1 and account_id = $2 for update",
            batch.report_id,
            batch.account_id,
        )
        ledger = await conn.fetchrow(
            "select status, lease_expires_at from section_regeneration_batches where id = $1 for update",
            batch.id,
        )
        if (
            ledger is None
            or ledger["status"] != "started"
            or ledger["lease_expires_at"] <= datetime.now(timezone.utc)
        ):
            batch_conflict = True
            await conn.execute(
                """
                update section_regeneration_batches
                set status = 'failed', failure_reason = 'lease_expired', finished_at = now()
                where id = $1 and status = 'started'
                """,
                batch.id,
            )
        else:
            row = await conn.fetchrow(
                "select state, state_seq from report_states where report_id = $1 for update",
                batch.report_id,
            )
        if not batch_conflict and (
            row is None or row["state_seq"] != batch.base_state_seq
        ):
            conflict = True
            await conn.execute(
                """
                update section_regeneration_batches
                set status = 'failed', failure_reason = 'state_conflict', finished_at = now()
                where id = $1 and status = 'started'
                """,
                batch.id,
            )
        elif not batch_conflict:
            patched = apply_generation_results(
                dict(row["state"]),
                batch.expected_block_ids,
                results,
                package=package,
                company_business_summary=company_business_summary,
            )
            new_seq = await conn.fetchval(
                """
                update report_states
                set state = $1, state_seq = state_seq + 1, updated_at = now()
                where report_id = $2 and state_seq = $3
                returning state_seq
                """,
                patched,
                batch.report_id,
                batch.base_state_seq,
            )
            if new_seq is None:
                raise RuntimeError("已持有报告状态锁但 state_seq 更新失败")
            await conn.execute(
                """
                update section_regeneration_batches
                set status = 'succeeded', failure_reason = '', finished_at = now(),
                    input_fingerprint = coalesce($3, input_fingerprint),
                    result = jsonb_build_object(
                      'stateSeq', $2::bigint,
                      'inputFingerprint', coalesce($3, input_fingerprint)
                    )
                where id = $1 and status = 'started'
                """,
                batch.id,
                new_seq,
                input_fingerprint,
            )
            await conn.execute(
                """
                insert into report_events (report_id, actor, event_type, payload)
                values ($1, 'llm', 'section_generation_succeeded', $2)
                """,
                batch.report_id,
                {
                    "batchId": str(batch.id),
                    "sectionKey": batch.section_key,
                    "mode": batch.mode,
                    "blockCount": len(batch.expected_block_ids),
                    "stateSeq": new_seq,
                },
            )
    if conflict:
        raise GenerationStateConflictError(batch.section_key)
    if batch_conflict:
        raise GenerationBatchStatusConflictError(batch.section_key)
    assert new_seq is not None
    return new_seq


async def rewrite_allowance(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    section_key: str,
    quota: int,
) -> RewriteAllowance:
    """只从成功重写与未过期预留派生额度；initial 与 failed 永不计入。"""
    row = await pool.fetchrow(
        """
        select
          count(*) filter (where mode = 'regeneration' and status = 'succeeded') as used,
          count(*) filter (
            where mode = 'regeneration' and status = 'started' and lease_expires_at > now()
          ) as reserved
        from section_regeneration_batches
        where report_id = $1 and section_key = $2
        """,
        report_id,
        section_key,
    )
    return RewriteAllowance(quota=quota, used=row["used"], reserved=row["reserved"])


async def latest_successful_input_fingerprint(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    section_key: str,
) -> str | None:
    """读取目标页面最近一次完整成功生成所冻结的输入指纹。"""
    value = await pool.fetchval(
        """
        select input_fingerprint
        from section_regeneration_batches
        where report_id = $1 and section_key = $2 and status = 'succeeded'
        -- 次序列用 started_at：本表没有 created_at，它就是创建时刻（DEFAULT now()），
        -- 且与迁移里的 section_regeneration_batches_section_idx 同序，可直接走该索引。
        order by finished_at desc, started_at desc
        limit 1
        """,
        report_id,
        section_key,
    )
    return value or None
