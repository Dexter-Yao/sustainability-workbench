# ABOUTME: 测试环境重建前的白名单盘点测试。
# ABOUTME: 盘点只能读取 Auth 与应用统计；任何未注册账号都必须阻止后续清理。
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from sustainability_desk.ops import test_baseline_preflight

ROOT = Path(__file__).resolve().parents[2]


class _Pool:
    def __init__(self, *, auth_emails: list[str], account_emails: list[str]) -> None:
        self.auth_emails = auth_emails
        self.account_emails = account_emails
        self.closed = False

    async def fetch(self, query: str):
        emails = self.auth_emails if "auth.users" in query else self.account_emails
        return [{"email": item} for item in emails]

    async def fetchval(self, query: str) -> int:
        assert "count(*)" in query
        if "material_sources" in query:
            return 3
        if "generation_runs" in query:
            return 2
        return 1

    async def close(self) -> None:
        self.closed = True


def _install_pool(monkeypatch: pytest.MonkeyPatch, pool: _Pool) -> None:
    async def create_pool(*_args: object, **_kwargs: object) -> _Pool:
        return pool

    monkeypatch.setattr(
        test_baseline_preflight,
        "persistence_settings",
        lambda: SimpleNamespace(database_url="postgresql://example.invalid/sustainability_desk"),
    )
    monkeypatch.setattr(test_baseline_preflight.asyncpg, "create_pool", create_pool)


def test_preflight_accepts_only_registry_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emails = ["internal-automation@example.com"]
    pool = _Pool(auth_emails=emails, account_emails=emails)
    _install_pool(monkeypatch, pool)

    inventory = asyncio.run(
        test_baseline_preflight.inspect_test_baseline(ROOT / "backend/data/test_accounts.yaml")
    )

    assert inventory.report_count == 1
    assert inventory.material_source_count == 3
    assert inventory.generation_run_count == 2
    assert pool.closed


def test_preflight_rejects_unregistered_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool(
        auth_emails=["internal-automation@example.com", "customer@example.com"],
        account_emails=[],
    )
    _install_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError, match="customer@example.com"):
        asyncio.run(
            test_baseline_preflight.inspect_test_baseline(
                ROOT / "backend/data/test_accounts.yaml"
            )
        )

    assert pool.closed
