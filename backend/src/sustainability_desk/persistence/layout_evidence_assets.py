# ABOUTME: 持久化排版素材在 evidence_assets 的轻量版提升——题注、替代文本、识别类别与放置范围。
# ABOUTME: 用户以排版素材角色上传即声明其为报告主体自有或经授权使用；本模块不重新校验权利归属。
# ABOUTME(en): Promotes a layout asset into evidence_assets — caption, alt text, recognized category, scope.
# ABOUTME(en): Uploading as a layout asset declares owned or licensed use; this module does not re-verify rights.
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg


class LayoutEvidenceAssetError(RuntimeError):
    """排版素材证据资产的持久化状态与调用合同不一致。"""


@dataclass(frozen=True)
class LayoutAssetRecord:
    """confirmed 状态的排版素材证据资产，供准备中心与内部审计投影。"""

    asset_id: UUID
    material_source_id: UUID
    placement_scope_id: str | None
    category: str | None
    caption: str | None
    caption_source: Literal["agent", "user"]
    alt_text: str
    # 证书类素材在入口解析出的 typed 事实；非证书素材为 None。
    certificate_fact: dict | None
    version: int
    fingerprint: str
    width_px: int | None
    height_px: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CurrentLayoutAssetRecord(LayoutAssetRecord):
    """生成期放置所需的排版素材记录，附带承载 binding 的建立时间供排序。"""

    binding_created_at: datetime = None  # type: ignore[assignment]


def _certificate_fact(value: object) -> dict | None:
    """jsonb 列在驱动侧可能回 str，也可能回 dict；在此边界统一解析成领域可用形态。"""

    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _record(row: asyncpg.Record) -> LayoutAssetRecord:
    return LayoutAssetRecord(
        asset_id=row["id"],
        material_source_id=row["material_source_id"],
        placement_scope_id=row["placement_scope_id"],
        category=row["category"],
        caption=row["caption"],
        caption_source=row["caption_source"],
        alt_text=row["alt_text"],
        certificate_fact=_certificate_fact(row["certificate_fact"]),
        version=int(row["version"]),
        fingerprint=row["fingerprint"],
        width_px=row["width_px"],
        height_px=row["height_px"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def promote_layout_asset(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    account_id: UUID,
    material_source_id: UUID,
    caption: str,
    alt_text: str,
    width_px: int,
    height_px: int,
    category: str,
    placement_scope_id: str,
    fingerprint: str,
    certificate_fact: dict | None = None,
) -> UUID:
    """把一次成功的 Image Agent 识别结果提升为 confirmed 排版素材证据资产。

    信任前提：用户以排版素材角色上传该文件，即已声明其为报告主体自有或经授权使用；
    本函数不重新校验权利归属，intended_use 固定为 layout_asset 且 rights_confirmed=true。
    重跑同一 material_source 时按 version+1 覆盖；caption 仅在既有 caption_source
    仍为 'agent' 时才被新识别结果覆盖，用户手动题注（caption_source='user'）不因重跑翻转。
    category 是识别类别，除触发证书事实解析外只用于素材归档与人工核对。
    certificate_fact 与 caption 同型受保护：用户在资料处理页更正过的证书事实
    （certificate_fact_source='user'）不因识别重跑被覆盖。
    """

    row = await pool.fetchrow(
        """
        insert into evidence_assets (
          id, account_id, report_id, material_source_id, intended_use,
          rights_confirmed, approved, alt_text, created_by_identity,
          caption, caption_source, width_px, height_px, category,
          placement_scope_id, status, version, fingerprint,
          certificate_fact, certificate_fact_source
        ) values (
          gen_random_uuid(), $1, $2, $3, 'layout_asset',
          true, true, $4, null,
          $5, 'agent', $6, $7, $8,
          $9, 'confirmed', 1, $10,
          $11, case when $11::jsonb is null then null else 'agent' end
        )
        on conflict (report_id, material_source_id) do update
        set alt_text = excluded.alt_text,
            caption = case
                        when evidence_assets.caption_source = 'agent'
                        then excluded.caption
                        else evidence_assets.caption
                      end,
            width_px = excluded.width_px,
            height_px = excluded.height_px,
            category = excluded.category,
            certificate_fact = case
                                 when evidence_assets.certificate_fact_source = 'user'
                                 then evidence_assets.certificate_fact
                                 else excluded.certificate_fact
                               end,
            certificate_fact_source = case
                                        when evidence_assets.certificate_fact_source = 'user'
                                        then 'user'
                                        else excluded.certificate_fact_source
                                      end,
            placement_scope_id = excluded.placement_scope_id,
            status = 'confirmed',
            approved = true,
            rights_confirmed = true,
            created_by_identity = null,
            version = evidence_assets.version + 1,
            fingerprint = excluded.fingerprint,
            updated_at = now()
        returning id
        """,
        account_id,
        report_id,
        material_source_id,
        alt_text,
        caption,
        width_px,
        height_px,
        category,
        placement_scope_id,
        fingerprint,
        json.dumps(certificate_fact, ensure_ascii=False) if certificate_fact else None,
    )
    if row is None:
        raise LayoutEvidenceAssetError("排版素材证据资产写入后无法读取")
    return row["id"]


async def update_layout_asset_caption(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    asset_id: UUID,
    caption: str,
) -> None:
    """用户手动改写题注；caption_source 转为 'user'，后续重跑不再覆盖。"""

    result = await pool.execute(
        """
        update evidence_assets
        set caption = $3, caption_source = 'user', updated_at = now()
        where id = $1 and report_id = $2 and status = 'confirmed'
        """,
        asset_id,
        report_id,
        caption,
    )
    if result != "UPDATE 1":
        raise LayoutEvidenceAssetError(str(asset_id))


async def update_layout_asset_certificate_fact(
    pool: asyncpg.Pool,
    *,
    report_id: UUID,
    asset_id: UUID,
    certificate_fact: dict,
) -> None:
    """用户更正证书事实；certificate_fact_source 转为 'user'，后续重跑不再覆盖。

    与题注同型：识别结论进报告正文与成果章，用户有权更正且更正不被机器覆盖。
    """

    result = await pool.execute(
        """
        update evidence_assets
        set certificate_fact = $3,
            certificate_fact_source = 'user',
            updated_at = now()
        where id = $1 and report_id = $2 and status = 'confirmed'
        """,
        asset_id,
        report_id,
        json.dumps(certificate_fact, ensure_ascii=False),
    )
    if result != "UPDATE 1":
        raise LayoutEvidenceAssetError(str(asset_id))


async def list_layout_assets_for_report(
    pool: asyncpg.Pool,
    report_id: UUID,
) -> tuple[LayoutAssetRecord, ...]:
    """读取当前报告全部 confirmed 排版素材证据资产，按建立时间排序。"""

    rows = await pool.fetch(
        """
        select id, material_source_id, placement_scope_id, category,
               caption, caption_source, alt_text, certificate_fact, version,
               fingerprint, width_px, height_px, created_at, updated_at
        from evidence_assets
        where report_id = $1 and intended_use = 'layout_asset' and status = 'confirmed'
        order by created_at, id
        """,
        report_id,
    )
    return tuple(_record(row) for row in rows)


async def current_layout_asset_records(
    pool: asyncpg.Pool,
    report_id: UUID,
) -> tuple[CurrentLayoutAssetRecord, ...]:
    """读取每个 active 排版素材 binding 对应的最新成功识别资产，供生成期放置使用。"""

    rows = await pool.fetch(
        """
        select asset.id, asset.material_source_id, asset.placement_scope_id,
               asset.category, asset.caption, asset.caption_source,
               asset.alt_text, asset.certificate_fact, asset.version,
               asset.fingerprint, asset.width_px, asset.height_px,
               asset.created_at, asset.updated_at, binding.created_at as binding_created_at
        from report_material_bindings binding
        join material_workspaces workspace on workspace.id = binding.workspace_id
        join lateral (
          select revision.role
          from user_file_declaration_revisions revision
          where revision.binding_id = binding.id
          order by revision.revision desc, revision.id desc
          limit 1
        ) declaration on true
        join evidence_assets asset
          on asset.material_source_id = binding.source_id
         and asset.report_id = workspace.report_id
         and asset.status = 'confirmed'
         and asset.intended_use = 'layout_asset'
        where workspace.report_id = $1
          and binding.status = 'active'
          and declaration.role = 'layout_asset'
        order by binding.created_at, binding.id
        """,
        report_id,
    )
    return tuple(
        CurrentLayoutAssetRecord(
            asset_id=row["id"],
            material_source_id=row["material_source_id"],
            placement_scope_id=row["placement_scope_id"],
            category=row["category"],
            caption=row["caption"],
            caption_source=row["caption_source"],
            alt_text=row["alt_text"],
            certificate_fact=_certificate_fact(row["certificate_fact"]),
            version=int(row["version"]),
            fingerprint=row["fingerprint"],
            width_px=row["width_px"],
            height_px=row["height_px"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            binding_created_at=row["binding_created_at"],
        )
        for row in rows
    )
