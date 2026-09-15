# ABOUTME: 持久化配置与 Supabase JWT 校验依赖的合同测试——HS256/ES256 双路径验签、audience、过期、未配置分支。
# ABOUTME: 不触碰真实数据库；persistence_settings 为 lru_cache，用例前后必须清缓存防串扰。
from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from fastapi import HTTPException

import sustainability_desk.api.auth as auth_module
from sustainability_desk.api.auth import current_user
from sustainability_desk.persistence.settings import PersistenceSettings, persistence_settings

SECRET = "test-secret-with-at-least-32-characters!"


@pytest.fixture(autouse=True)
def _configure_auth(monkeypatch):
    monkeypatch.setenv("SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("SUSTAINABILITY_DESK_DATABASE_URL", "postgresql://placeholder/db")
    monkeypatch.setenv("SUSTAINABILITY_DESK_SUPABASE_URL", "")
    persistence_settings.cache_clear()
    yield
    persistence_settings.cache_clear()


def _token(secret: str = SECRET, aud: str = "authenticated", **overrides) -> str:
    claims = {
        "sub": str(uuid4()),
        "aud": aud,
        "email": "user@example.com",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_settings_configured_from_env():
    settings = PersistenceSettings()
    assert settings.configured
    assert settings.jwt_audience == "authenticated"


def test_settings_unconfigured_without_env(monkeypatch):
    monkeypatch.delenv("SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET")
    monkeypatch.delenv("SUSTAINABILITY_DESK_DATABASE_URL")
    settings = PersistenceSettings(_env_file=None)
    assert not settings.configured


def test_current_user_accepts_valid_token():
    token = _token()
    user = current_user(authorization=f"Bearer {token}")
    assert user.email == "user@example.com"


def test_current_user_accepts_small_auth_clock_skew():
    token = _token(iat=int(time.time()) + 4)

    user = current_user(authorization=f"Bearer {token}")

    assert user.email == "user@example.com"


def test_current_user_rejects_token_too_far_in_future():
    token = _token(iat=int(time.time()) + 10)

    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")

    assert exc.value.status_code == 401


def test_current_user_rejects_missing_header():
    with pytest.raises(HTTPException) as exc:
        current_user(authorization="")
    assert exc.value.status_code == 401


def test_current_user_rejects_wrong_secret():
    token = _token(secret="another-secret-with-32-characters-xx")
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


def test_current_user_rejects_wrong_audience():
    token = _token(aud="anon")
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


def test_current_user_rejects_expired_token():
    token = _token(exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


def test_current_user_rejects_non_uuid_sub():
    token = _token(sub="not-a-uuid")
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


def test_current_user_503_when_unconfigured(monkeypatch):
    monkeypatch.setenv("SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET", "")
    persistence_settings.cache_clear()
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {_token()}")
    assert exc.value.status_code == 503


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return _FakeSigningKey(self._public_key)


def test_current_user_accepts_es256_via_jwks(monkeypatch):
    monkeypatch.setenv("SUSTAINABILITY_DESK_SUPABASE_URL", "http://127.0.0.1:54321")
    persistence_settings.cache_clear()
    private_key = generate_private_key(SECP256R1())
    claims = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "email": "es@example.com",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "test-kid"})
    monkeypatch.setattr(
        auth_module, "_jwks_client", lambda _url: _FakeJWKSClient(private_key.public_key())
    )
    user = current_user(authorization=f"Bearer {token}")
    assert user.email == "es@example.com"


def test_current_user_es256_503_without_supabase_url(monkeypatch):
    private_key = generate_private_key(SECP256R1())
    token = jwt.encode(
        {"sub": str(uuid4()), "aud": "authenticated", "exp": int(time.time()) + 3600},
        private_key,
        algorithm="ES256",
    )
    with pytest.raises(HTTPException) as exc:
        current_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 503


def test_current_user_rejects_unknown_algorithm():
    with pytest.raises(HTTPException) as exc:
        current_user(authorization="Bearer not.a.jwt")
    assert exc.value.status_code == 401
