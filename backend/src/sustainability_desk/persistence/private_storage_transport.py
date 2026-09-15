# ABOUTME: Supabase 私有对象桶的 service-role REST transport，统一认证、HTTP 失败分类与对象读写。
# ABOUTME: 本模块不拥有 bucket、对象路径、MIME、签名 URL 使用方或对象生命周期等业务语义。
# ABOUTME(en): Service-role REST transport for Supabase private buckets, unifying auth, failure typing, object IO.
# ABOUTME(en): Owns no business semantics: not the bucket, object path, MIME, signed-URL consumer or lifecycle.
from __future__ import annotations

from urllib.parse import quote

import httpx

from sustainability_desk.persistence.settings import PersistenceSettings


class PrivateStorageTransportError(RuntimeError):
    """私有对象 Storage transport 的配置、网络或 HTTP 失败。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PrivateStorageTransport:
    """以 service-role 在服务端访问私有对象；浏览器永远不接触此 transport。"""

    def __init__(
        self, settings: PersistenceSettings, *, client: httpx.AsyncClient | None = None
    ) -> None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise PrivateStorageTransportError("Supabase Storage 未配置")
        self._base_url = settings.supabase_url.rstrip("/")
        self._service_key = settings.supabase_service_key
        self._client = client

    def object_url(self, bucket: str, object_path: str, *, action: str = "") -> str:
        """仅编码对象路径；bucket 必须由领域存储客户端固定给出。"""

        return (
            f"{self._base_url}/storage/v1/object/{action}{bucket}/"
            f"{quote(object_path, safe='/')}"
        )

    def headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._service_key}",
            "apikey": self._service_key,
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        return headers

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise PrivateStorageTransportError(
                f"Storage 网络请求失败：{type(error).__name__}"
            ) from error
        if not 200 <= response.status_code < 300:
            raise PrivateStorageTransportError(
                f"Storage HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )
        return response

    async def create(
        self, bucket: str, object_path: str, data: bytes, *, media_type: str
    ) -> None:
        """创建不可覆盖对象；对象是否允许覆盖由领域层决定且当前私有桶一律禁止。"""

        await self._request(
            "POST",
            self.object_url(bucket, object_path),
            content=data,
            headers={**self.headers(content_type=media_type), "x-upsert": "false"},
        )

    async def read(
        self,
        bucket: str,
        object_path: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """流式读取对象；给定上限时绝不在内存中接纳更多字节。"""

        if max_bytes is not None and max_bytes < 1:
            raise ValueError("Storage 读取上限必须为正数")
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        response: httpx.Response | None = None
        try:
            request = client.build_request(
                "GET",
                self.object_url(bucket, object_path),
                headers=self.headers(),
            )
            response = await client.send(request, stream=True)
            if not 200 <= response.status_code < 300:
                detail = (await self._read_limited(response, 200)).decode(
                    "utf-8", errors="replace"
                )
                raise PrivateStorageTransportError(
                    f"Storage HTTP {response.status_code}: {detail}",
                    status_code=response.status_code,
                )
            if max_bytes is None:
                return await response.aread()
            return await self._read_limited(response, max_bytes)
        except PrivateStorageTransportError:
            raise
        except httpx.HTTPError as error:
            raise PrivateStorageTransportError(
                f"Storage 网络请求失败：{type(error).__name__}"
            ) from error
        finally:
            if response is not None:
                await response.aclose()
            if owned_client:
                await client.aclose()

    @staticmethod
    async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
        """读取至精确上限后立即停止，不接纳下一字节。"""

        data = bytearray()
        async for chunk in response.aiter_bytes():
            remaining = max_bytes - len(data)
            if remaining <= 0:
                break
            data.extend(chunk[:remaining])
            if len(data) == max_bytes:
                break
        return bytes(data)

    async def delete(self, bucket: str, object_path: str) -> None:
        await self._request(
            "DELETE", self.object_url(bucket, object_path), headers=self.headers()
        )

    async def create_signed_url(
        self, bucket: str, object_path: str, *, expires_in: int
    ) -> str:
        """创建短时 URL；持续时间与是否可对外暴露由领域层裁决。"""

        response = await self._request(
            "POST",
            self.object_url(bucket, object_path, action="sign/"),
            json={"expiresIn": expires_in},
            headers=self.headers(content_type="application/json"),
        )
        payload = response.json()
        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not isinstance(signed, str) or not signed:
            raise PrivateStorageTransportError("Storage 未返回签名 URL")
        if signed.startswith("/"):
            return f"{self._base_url}/storage/v1{signed}"
        return signed
