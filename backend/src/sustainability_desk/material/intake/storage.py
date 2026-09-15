# ABOUTME: 私有 materials bucket 的后端专用对象客户端。
# ABOUTME: 对象路径仅含内部 UUID；所有失败显式抛出，service key 不得进入浏览器或日志。
# ABOUTME(en): Backend-only object client for the private materials bucket.
# ABOUTME(en): Object paths carry internal UUIDs only; failures raise explicitly and the service key stays server-side.
from __future__ import annotations

from uuid import UUID

import httpx

from sustainability_desk.material.intake.models import MaterialKind
from sustainability_desk.persistence.private_storage_transport import (
    PrivateStorageTransport,
    PrivateStorageTransportError,
)
from sustainability_desk.persistence.settings import PersistenceSettings

MATERIALS_BUCKET = "materials"


class MaterialStorageError(RuntimeError):
    """私有资料对象操作失败。"""


class MaterialStorageClient:
    """通过 Supabase Storage REST 操作私有资料，允许测试注入 MockTransport。"""

    def __init__(
        self,
        settings: PersistenceSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        try:
            self._transport = PrivateStorageTransport(settings, client=client)
        except PrivateStorageTransportError as error:
            raise MaterialStorageError(str(error)) from error

    @staticmethod
    def object_path(
        account_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        kind: MaterialKind,
    ) -> str:
        """从内部 ID 生成不可由用户文件名操纵的对象路径。"""
        suffix = "jpg" if kind == "jpeg" else kind
        return f"{account_id}/{workspace_id}/{source_id}.{suffix}"

    async def upload(self, object_path: str, data: bytes, media_type: str) -> None:
        """创建新对象，禁止 upsert 遮盖去重或所有权错误。"""
        try:
            await self._transport.create(
                MATERIALS_BUCKET, object_path, data, media_type=media_type
            )
        except PrivateStorageTransportError as error:
            raise MaterialStorageError(str(error)) from error

    async def download(
        self,
        object_path: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        try:
            return await self._transport.read(
                MATERIALS_BUCKET,
                object_path,
                max_bytes=max_bytes,
            )
        except PrivateStorageTransportError as error:
            raise MaterialStorageError(str(error)) from error

    async def delete(self, object_path: str) -> None:
        try:
            await self._transport.delete(MATERIALS_BUCKET, object_path)
        except PrivateStorageTransportError as error:
            raise MaterialStorageError(str(error)) from error
