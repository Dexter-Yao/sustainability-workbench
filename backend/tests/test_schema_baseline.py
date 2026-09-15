# ABOUTME: 单份 schema 基线的静态合同测试——终态表集合、浏览器角色零授权与已退场表不得回流。
# ABOUTME: 真实 RLS 与授权仍由本地 Supabase reset 后的 catalog 集成测试（test_database_access_boundary）验证。
import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
BASELINE = MIGRATIONS / "20260904000000_local_single_user_baseline.sql"

LIVE_TABLES = {
    "accounts", "account_identities", "account_entitlement_grants", "account_events",
    "account_operator_permissions",
    "reports", "report_states", "report_events", "generation_runs", "section_regeneration_batches",
    "report_lineage_edges",
    "lightweight_report_generation_runs", "lightweight_report_revisions",
    "lightweight_report_generation_events", "lightweight_report_artifacts",
    "material_workspaces", "material_sources", "material_events", "report_material_bindings",
    "user_file_declaration_revisions", "file_agent_runs", "file_dossiers", "image_agent_runs",
    "material_set_snapshots", "material_mapping_runs",
    "block_material_decisions", "block_material_decision_materials", "evidence_assets",
}
RETIRED_TABLES = {
    "account_registration_requests", "account_consents", "account_phone_verification_codes",
    "app_schema_releases", "material_source_backups", "material_jobs",
    "report_workflow_runs", "report_stage_runs", "report_blueprints", "report_authoring_drafts",
    "report_content_review_snapshots", "report_export_artifacts", "evidence_facts", "readiness_gaps",
    "standard_requirements", "standard_packages",
}


def _sql() -> str:
    return BASELINE.read_text("utf-8").lower()


def test_schema_is_a_single_baseline_file() -> None:
    assert [path.name for path in sorted(MIGRATIONS.glob("*.sql"))] == [BASELINE.name]


def test_baseline_creates_exactly_the_live_tables() -> None:
    sql = _sql()
    created = set(
        line.split('"public"."')[1].split('"')[0]
        for line in sql.splitlines()
        if line.startswith('create table if not exists "public"."')
    )
    assert created == LIVE_TABLES
    for table in RETIRED_TABLES:
        assert f'"public"."{table}"' not in sql, table


def test_accounts_keep_email_only_contact_and_reports_are_lightweight_only() -> None:
    sql = _sql()
    assert '"email" "text" not null' in sql
    assert '"phone"' not in sql and '"wechat_id"' not in sql and '"marketing_session_id"' not in sql
    assert "check ((\"report_type\" = 'lightweight'::\"text\"))" in sql
    assert "'professional'" not in sql


def test_browser_roles_have_no_business_table_grants() -> None:
    sql = _sql()
    assert 'revoke all privileges on all tables in schema "public" from "anon", "authenticated"' in sql
    assert not re.search(r'on table "public"\."[a-z_]+" to "(anon|authenticated)"', sql)
    assert 'create schema if not exists "private"' in sql
    assert 'function "private"."current_account_id"()' in sql
    assert "security definer" in sql


def test_baseline_declares_private_storage_buckets() -> None:
    sql = _sql()
    assert "values ('exports', 'exports', false)" in sql
    assert "values (\n  'materials', 'materials', false, 20971520," in sql
    assert "'public', true" not in sql
