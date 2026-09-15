# ABOUTME: 认证适配层按令牌算法路由：ES256/RS256 走 JWKS 公钥，HS256 供本地自托管栈验签。
# ABOUTME: 校验失败一律 401，认证配置缺失 503；成功后只向产品层暴露认证 subject 与邮箱。
# ABOUTME(en): Auth adapter routing by token algorithm: ES256/RS256 use JWKS public keys, HS256 verifies locally.
# ABOUTME(en): Any verification failure is 401 and missing auth config is 503; only subject and email are exposed.
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Header
from jwt import PyJWKClient

from sustainability_desk.persistence.settings import persistence_settings

_ASYMMETRIC_ALGS = ("ES256", "RS256")
_JWT_CLOCK_SKEW_SECONDS = 5


@dataclass(frozen=True)
class AuthenticatedUser:
    subject: UUID
    email: str | None


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    return PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def _decode(token: str) -> dict:
    settings = persistence_settings()
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")
    if alg in _ASYMMETRIC_ALGS:
        if not settings.supabase_url:
            raise HTTPException(status_code=503, detail="认证服务未配置")
        key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=list(_ASYMMETRIC_ALGS),
            audience=settings.jwt_audience,
            leeway=_JWT_CLOCK_SKEW_SECONDS,
        )
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise HTTPException(status_code=503, detail="认证服务未配置")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            leeway=_JWT_CLOCK_SKEW_SECONDS,
        )
    raise jwt.InvalidTokenError(f"不支持的签名算法: {alg}")


def current_user(authorization: Annotated[str, Header()] = "") -> AuthenticatedUser:
    settings = persistence_settings()
    if not settings.auth_configured:
        raise HTTPException(status_code=503, detail="认证服务未配置")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="缺少访问令牌")
    try:
        claims = _decode(token)
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="访问令牌无效")
    try:
        user_id = UUID(str(claims.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="访问令牌无效")
    return AuthenticatedUser(subject=user_id, email=claims.get("email"))


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
