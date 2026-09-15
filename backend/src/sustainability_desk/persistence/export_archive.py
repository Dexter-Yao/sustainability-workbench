# ABOUTME: 导出存档——docx 字节流写入 Supabase Storage exports 桶并以 sha256 指纹记 report_exported 审计事件。
# ABOUTME: 上传失败不阻断用户下载，但事件必须落库（archived=false 亦可审计）；对象路径 exports/{report_id}/{utc时间戳}.docx。
# ABOUTME(en): Export archive — writes docx bytes to the Supabase Storage exports bucket and records a
# ABOUTME(en): report_exported audit event with a sha256 fingerprint. Upload failure never blocks download.
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import httpx

from sustainability_desk.persistence.settings import PersistenceSettings

logger = logging.getLogger(__name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _upload(settings: PersistenceSettings, object_path: str, data: bytes) -> bool:
    if not (settings.supabase_url and settings.supabase_service_key):
        return False
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/exports/{object_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            url,
            content=data,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": DOCX_MIME,
            },
        )
    if res.status_code not in (200, 201):
        logger.error("导出存档上传失败 %s: HTTP %s %s", object_path, res.status_code, res.text[:200])
        return False
    return True


async def archive_export(
    pool: asyncpg.Pool,
    settings: PersistenceSettings,
    report_id: UUID,
    data: bytes,
) -> None:
    """上传导出产物并记审计事件；上传失败仍记事件（archived=false）。"""
    digest = hashlib.sha256(data).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    object_path = f"{report_id}/{stamp}.docx"
    archived = False
    try:
        archived = await _upload(settings, object_path, data)
    except Exception:
        logger.exception("导出存档上传异常 %s", object_path)
    await pool.execute(
        "insert into report_events (report_id, actor, event_type, payload) values ($1, 'system', 'report_exported', $2)",
        report_id,
        {"sha256": digest, "bytes": len(data), "objectPath": object_path if archived else None,
         "archived": archived},
    )
