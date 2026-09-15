# ABOUTME: Supabase 业务表权限集成测试——RLS 显式 authenticated，anon/authenticated 无直接表权限。
# ABOUTME: 直连本地 Supabase catalog；本地栈未启动时跳过。
import asyncpg
import pytest
from uuid import uuid4

LOCAL_DB = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
BUSINESS_TABLES = {
    "accounts",
    "account_identities",
    "account_entitlement_grants",
    "account_events",
    "reports",
    "report_states",
    "report_events",
    "generation_runs",
    "section_regeneration_batches",
    "material_workspaces",
    "material_sources",
    "material_events",
}
APPEND_ONLY_TABLES = {"material_events"}
BACKEND_DML_TABLES = BUSINESS_TABLES - APPEND_ONLY_TABLES
OWNER_POLICY_TABLES = BUSINESS_TABLES


@pytest.fixture
async def conn():
    try:
        value = await asyncpg.connect(LOCAL_DB, timeout=3)
    except OSError:
        pytest.skip("本地 Supabase 栈未启动")
    yield value
    await value.close()


async def test_business_tables_are_not_granted_to_data_api_roles(conn) -> None:
    rows = await conn.fetch(
        """
        select grantee, table_name, privilege_type
        from information_schema.role_table_grants
        where table_schema = 'public'
          and grantee in ('anon', 'authenticated')
          and table_name = any($1::text[])
        """,
        list(BUSINESS_TABLES),
    )
    assert rows == []


async def test_service_role_has_backend_dml_on_every_business_table(conn) -> None:
    rows = await conn.fetch(
        """
        select table_name, array_agg(privilege_type order by privilege_type) as privileges
        from information_schema.role_table_grants
        where table_schema = 'public'
          and grantee = 'service_role'
          and table_name = any($1::text[])
          and privilege_type = any($2::text[])
        group by table_name
        """,
        list(BACKEND_DML_TABLES),
        ["SELECT", "INSERT", "UPDATE", "DELETE"],
    )
    expected = ["DELETE", "INSERT", "SELECT", "UPDATE"]
    assert {row["table_name"]: row["privileges"] for row in rows} == {
        table: expected for table in BACKEND_DML_TABLES
    }

    append_only_privileges = await conn.fetch(
        """
        select privilege_type from information_schema.role_table_grants
        where table_schema = 'public' and table_name = any($1::text[])
          and grantee = 'service_role'
        order by table_name, privilege_type
        """,
        sorted(APPEND_ONLY_TABLES),
    )
    assert [row["privilege_type"] for row in append_only_privileges] == ["INSERT", "SELECT"] * len(APPEND_ONLY_TABLES)

    async with conn.transaction():
        await conn.execute("set local role service_role")
        assert await conn.fetchval("select count(*) from public.generation_runs") >= 0


async def test_account_rls_isolates_account_grant_and_report_rows(conn) -> None:
    owner, other = uuid4(), uuid4()
    await conn.execute(
        "insert into auth.users (id) values ($1), ($2)", owner, other
    )
    try:
        owner_account = await conn.fetchval(
            "insert into public.accounts (email) values ($1) returning id", "owner@example.com"
        )
        other_account = await conn.fetchval(
            "insert into public.accounts (email) values ($1) returning id", "other@example.com"
        )
        await conn.execute(
            """
            insert into public.account_identities (account_id, identity_issuer, identity_subject)
            values ($1, 'primary', $2), ($3, 'primary', $4)
            """,
            owner_account, owner, other_account, other,
        )
        owner_report = await conn.fetchval(
            "insert into public.reports (account_id, title, report_profile_id, created_under_profile_id, contract_version) "
            "values ($1, 'owner', 'sse_zh_hans@1', 'local_single_user@1', 'cv-test') returning id",
            owner_account,
        )
        await conn.execute(
            "insert into public.reports (account_id, title, report_profile_id, created_under_profile_id, contract_version) "
            "values ($1, 'other', 'sse_zh_hans@1', 'local_single_user@1', 'cv-test')",
            other_account,
        )
        await conn.execute(
            """
            insert into public.account_entitlement_grants
              (account_id, profile_id, starts_at, granted_by, reason)
            values ($1, 'local_single_user@1', now(), 'test', 'rls'),
                   ($2, 'local_single_user@1', now(), 'test', 'rls')
            """,
            owner_account,
            other_account,
        )
        transaction = conn.transaction()
        await transaction.start()
        try:
            await conn.execute(
                "grant select on public.accounts, public.account_entitlement_grants, public.reports to authenticated"
            )
            await conn.execute(
                "select set_config('request.jwt.claim.sub', $1, true)", str(owner)
            )
            await conn.execute("set local role authenticated")
            visible_ids = await conn.fetch("select id from public.reports")
            assert [row["id"] for row in visible_ids] == [owner_report]
            assert await conn.fetchval("select count(*) from public.accounts") == 1
            assert await conn.fetchval("select count(*) from public.account_entitlement_grants") == 1
            await conn.execute("reset role")
        finally:
            await transaction.rollback()
    finally:
        await conn.execute(
            "delete from public.accounts where id = any($1::uuid[])",
            [owner_account, other_account],
        )
        await conn.execute("delete from auth.users where id = any($1::uuid[])", [owner, other])


async def test_rls_policies_target_authenticated_and_all_tables_enable_rls(conn) -> None:
    rls = await conn.fetch(
        """
        select relname, relrowsecurity
        from pg_class join pg_namespace on pg_namespace.oid = pg_class.relnamespace
        where nspname = 'public' and relname = any($1::text[])
        """,
        list(BUSINESS_TABLES),
    )
    assert {row["relname"] for row in rls if row["relrowsecurity"]} == BUSINESS_TABLES

    policies = await conn.fetch(
        """
        select tablename, roles
        from pg_policies
        where schemaname = 'public' and tablename = any($1::text[])
        """,
        list(BUSINESS_TABLES),
    )
    assert {row["tablename"] for row in policies} == OWNER_POLICY_TABLES
    assert all(row["roles"] == ["authenticated"] for row in policies)


async def test_rls_helper_and_storage_follow_private_baseline(conn) -> None:
    assert await conn.fetchval("select to_regprocedure('public.current_account_id()')") is None
    helper = await conn.fetchrow(
        """
        select p.prosecdef, p.proconfig
        from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'private' and p.proname = 'current_account_id'
        """
    )
    assert helper is not None and helper["prosecdef"] is True
    assert helper["proconfig"] == ["search_path=\"\""]

    buckets = await conn.fetch("select id, public from storage.buckets order by id")
    assert [(row["id"], row["public"]) for row in buckets] == [
        ("exports", False),
        ("materials", False),
    ]
