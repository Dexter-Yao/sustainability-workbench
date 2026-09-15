# ABOUTME: 测试账号注册表 provision 的 dry-run 测试。
# ABOUTME: dry-run 只读取 Auth 状态，不创建用户、不读取密码、不写入 Account/Grant/权限。
from __future__ import annotations

import argparse
import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sustainability_desk.ops import bootstrap_internal_accounts


class _Pool:
    def __init__(self) -> None:
        self.closed = False

    async def fetchrow(self, query: str, email: str) -> dict[str, object]:
        assert "from auth.users" in query
        return {"id": uuid4(), "email_confirmed_at": object()}

    async def close(self) -> None:
        self.closed = True


def test_registry_dry_run_only_reads_existing_auth(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pool = _Pool()

    async def create_pool(*_args: object, **_kwargs: object) -> _Pool:
        return pool

    monkeypatch.setattr(
        bootstrap_internal_accounts,
        "persistence_settings",
        lambda: SimpleNamespace(database_url="postgresql://example.invalid/sustainability_desk"),
    )
    monkeypatch.setattr(bootstrap_internal_accounts.asyncpg, "create_pool", create_pool)
    args = argparse.Namespace(
        registry=Path(__file__).resolve().parents[2] / "backend/data/test_accounts.yaml",
        role=[],
        apply=False,
    )

    asyncio.run(bootstrap_internal_accounts.run(args))

    assert pool.closed
    output = capsys.readouterr().out
    assert "internal-automation@example.com" in output
    assert "role=internal_automation" in output
    assert "internal-manual@example.com" in output
    assert "role=internal_manual" in output
    assert "DRY RUN：未写入" in output


def test_registry_dry_run_can_limit_to_internal_automation_accounts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pool = _Pool()

    async def create_pool(*_args: object, **_kwargs: object) -> _Pool:
        return pool

    monkeypatch.setattr(
        bootstrap_internal_accounts,
        "persistence_settings",
        lambda: SimpleNamespace(database_url="postgresql://example.invalid/sustainability_desk"),
    )
    monkeypatch.setattr(bootstrap_internal_accounts.asyncpg, "create_pool", create_pool)
    args = argparse.Namespace(
        registry=Path(__file__).resolve().parents[2] / "backend/data/test_accounts.yaml",
        role=["internal_automation"],
        apply=False,
    )

    asyncio.run(bootstrap_internal_accounts.run(args))

    output = capsys.readouterr().out
    assert output.count("internal-automation@example.com") == 1
    assert "internal-manual@example.com" not in output


def test_registry_dry_run_can_select_manual_internal_accounts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pool = _Pool()

    async def create_pool(*_args: object, **_kwargs: object) -> _Pool:
        return pool

    monkeypatch.setattr(
        bootstrap_internal_accounts,
        "persistence_settings",
        lambda: SimpleNamespace(database_url="postgresql://example.invalid/sustainability_desk"),
    )
    monkeypatch.setattr(bootstrap_internal_accounts.asyncpg, "create_pool", create_pool)
    args = argparse.Namespace(
        registry=Path(__file__).resolve().parents[2] / "backend/data/test_accounts.yaml",
        role=["internal_manual"],
        apply=False,
    )

    asyncio.run(bootstrap_internal_accounts.run(args))

    output = capsys.readouterr().out
    assert "internal-manual@example.com" in output
    assert "internal-automation@example.com" not in output


def test_password_stdin_requires_exact_selected_account_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = bootstrap_internal_accounts.load_registry(
        Path(__file__).resolve().parents[2] / "backend/data/test_accounts.yaml"
    )
    selected = (registry.accounts[0],)
    monkeypatch.setattr(
        bootstrap_internal_accounts.sys,
        "stdin",
        io.StringIO('{"other@example.com": "secret"}'),
    )

    with pytest.raises(RuntimeError, match="账号集合"):
        bootstrap_internal_accounts.load_passwords_from_stdin(specs=selected)
