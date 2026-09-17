# ABOUTME: 持久化与认证配置（pydantic-settings）——数据库连接串与 Supabase JWT 密钥，从 backend/.env 读取。
# ABOUTME: 未配置时 configured=False，持久化端点应 503 fail-loud；不影响无数据库的既有生成/导出链路。
# ABOUTME(en): Persistence and auth settings (pydantic-settings) — database URL and Supabase JWT secret, from
# ABOUTME(en): backend/.env. Unconfigured means configured=False so persistence endpoints fail loud with 503.
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[3]


class PersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUSTAINABILITY_DESK_",
        env_file=BACKEND / ".env",
        extra="ignore",
    )

    database_url: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_key: str = ""
    public_supabase_url: str = ""
    public_supabase_anon_key: str = ""
    environment: str = "development"
    supabase_project: str = ""
    jwt_audience: str = "authenticated"
    #: 私有资料对象的存放位置。留空即用 Supabase Storage；给绝对路径则存本机磁盘，
    #: 那样安装时可以不拉 storage-api 镜像（约 818 MB）。默认走本地：本产品对对象存储
    #: 的全部用法只有写、读、删三件事，自用安装没有理由为此多装一个服务。
    local_storage_root: str = str(BACKEND / "out" / "object-storage")

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_url or self.supabase_jwt_secret)

    @property
    def configured(self) -> bool:
        return bool(self.database_url and self.auth_configured)


    @property
    def uses_local_object_storage(self) -> bool:
        """私有对象是否走本机磁盘。配了根目录即走本地，留空回到 Supabase Storage。"""

        return bool(self.local_storage_root)

    @property
    def public_client_configured(self) -> bool:
        return bool(self.public_supabase_url and self.public_supabase_anon_key)


@lru_cache(maxsize=1)
def persistence_settings() -> PersistenceSettings:
    return PersistenceSettings()
