-- ABOUTME: 本机单用户模式的唯一 schema 基线：账户与权益、报告与状态、资料工作区与 Agent 运行、轻量版生成与交付物。
-- ABOUTME: 由终态 catalog 导出而成；浏览器角色对业务表零授权，后端以 service_role 直连，RLS 只读策略作纵深防御。



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE SCHEMA IF NOT EXISTS "private";


ALTER SCHEMA "private" OWNER TO "postgres";


CREATE SCHEMA IF NOT EXISTS "public";


ALTER SCHEMA "public" OWNER TO "pg_database_owner";


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE OR REPLACE FUNCTION "private"."current_account_id"() RETURNS "uuid"
    LANGUAGE "sql" STABLE SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
  select account_id
  from public.account_identities
  where identity_issuer = 'primary' and identity_subject = (select auth.uid())
$$;


ALTER FUNCTION "private"."current_account_id"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."account_entitlement_grants" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "profile_id" "text" NOT NULL,
    "starts_at" timestamp with time zone NOT NULL,
    "ends_at" timestamp with time zone,
    "ended_at" timestamp with time zone,
    "granted_by" "text" NOT NULL,
    "reason" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "account_entitlement_grants_check" CHECK ((("ends_at" IS NULL) OR ("ends_at" > "starts_at"))),
    CONSTRAINT "account_entitlement_grants_check1" CHECK ((("ended_at" IS NULL) OR ("ended_at" >= "starts_at"))),
    CONSTRAINT "account_entitlement_grants_profile_id_check" CHECK (("profile_id" ~ '^[a-z_]+@[1-9][0-9]*$'::"text"))
);


ALTER TABLE "public"."account_entitlement_grants" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."account_events" (
    "id" bigint NOT NULL,
    "account_id" "uuid" NOT NULL,
    "actor" "text" NOT NULL,
    "event_type" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "account_events_actor_check" CHECK (("actor" = ANY (ARRAY['user'::"text", 'system'::"text", 'operator'::"text"])))
);


ALTER TABLE "public"."account_events" OWNER TO "postgres";


ALTER TABLE "public"."account_events" ALTER COLUMN "id" ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME "public"."account_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."account_identities" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "identity_issuer" "text" NOT NULL,
    "identity_subject" "uuid" NOT NULL,
    "linked_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."account_identities" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."account_operator_permissions" (
    "account_id" "uuid" NOT NULL,
    "permission" "text" NOT NULL,
    "granted_by" "text" NOT NULL,
    "reason" "text" NOT NULL,
    "granted_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "account_operator_permissions_granted_by_check" CHECK (("length"("btrim"("granted_by")) > 0)),
    CONSTRAINT "account_operator_permissions_permission_check" CHECK (("permission" = 'internal_audit_reviewer'::"text")),
    CONSTRAINT "account_operator_permissions_reason_check" CHECK (("length"("btrim"("reason")) > 0))
);


ALTER TABLE "public"."account_operator_permissions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."accounts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "email" "text" NOT NULL,
    "organization_name" "text",
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "registered_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "last_active_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "onboarding_seen" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    CONSTRAINT "accounts_email_check" CHECK ((("email" = "lower"("email")) AND ("email" ~ '^[^@[:space:]]+@[^@[:space:]]+$'::"text"))),
    CONSTRAINT "accounts_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'suspended'::"text"])))
);


ALTER TABLE "public"."accounts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."block_material_decision_materials" (
    "decision_id" "uuid" NOT NULL,
    "material_id" "uuid" NOT NULL,
    "ordinal" integer NOT NULL,
    CONSTRAINT "block_material_decision_materials_ordinal_check" CHECK (("ordinal" >= 1))
);


ALTER TABLE "public"."block_material_decision_materials" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."block_material_decisions" (
    "id" "uuid" NOT NULL,
    "mapping_run_id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "snapshot_id" "uuid" NOT NULL,
    "scope_id" "text" NOT NULL,
    "block_id" "text" NOT NULL,
    "disposition" "text" NOT NULL,
    "material_ids" "uuid"[] DEFAULT '{}'::"uuid"[] NOT NULL,
    "reason" "text" NOT NULL,
    "decision_payload" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "block_material_decisions_block_id_check" CHECK (("length"("btrim"("block_id")) > 0)),
    CONSTRAINT "block_material_decisions_disposition_check" CHECK (("disposition" = ANY (ARRAY['supported'::"text", 'partially_supported'::"text", 'context_only'::"text", 'needs_attention'::"text", 'not_applicable'::"text"]))),
    CONSTRAINT "block_material_decisions_payload_check" CHECK (("jsonb_typeof"("decision_payload") = 'object'::"text")),
    CONSTRAINT "block_material_decisions_reason_check" CHECK (("length"("btrim"("reason")) > 0))
);


ALTER TABLE "public"."block_material_decisions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."evidence_assets" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "material_source_id" "uuid" NOT NULL,
    "intended_use" "text" NOT NULL,
    "rights_confirmed" boolean NOT NULL,
    "approved" boolean DEFAULT false NOT NULL,
    "alt_text" "text" NOT NULL,
    "created_by_identity" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "caption" "text",
    "width_px" integer,
    "height_px" integer,
    "crop_x" double precision,
    "crop_y" double precision,
    "crop_width" double precision,
    "crop_height" double precision,
    "duplicate_of_asset_id" "uuid",
    "status" "text" DEFAULT 'confirmed'::"text" NOT NULL,
    "version" integer DEFAULT 1 NOT NULL,
    "fingerprint" "text" DEFAULT "repeat"('0'::"text", 64) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "placement_scope_id" "text",
    "caption_source" "text" DEFAULT 'agent'::"text" NOT NULL,
    "category" "text",
    "certificate_fact" "jsonb",
    "certificate_fact_source" "text",
    CONSTRAINT "evidence_assets_alt_text_check" CHECK (("length"("btrim"("alt_text")) > 0)),
    CONSTRAINT "evidence_assets_caption_source_check" CHECK (("caption_source" = ANY (ARRAY['agent'::"text", 'user'::"text"]))),
    CONSTRAINT "evidence_assets_category_check" CHECK ((("category" IS NULL) OR ("category" = ANY (ARRAY['certificate_or_award'::"text", 'photo'::"text", 'document_scan'::"text", 'other'::"text"])))),
    CONSTRAINT "evidence_assets_certificate_fact_source_check" CHECK (((("certificate_fact_source" IS NULL) AND ("certificate_fact" IS NULL)) OR ("certificate_fact_source" = ANY (ARRAY['agent'::"text", 'user'::"text"])))),
    CONSTRAINT "evidence_assets_check" CHECK (((("width_px" IS NULL) AND ("height_px" IS NULL)) OR (("width_px" > 0) AND ("height_px" > 0)))),
    CONSTRAINT "evidence_assets_check1" CHECK (((("crop_x" IS NULL) AND ("crop_y" IS NULL) AND ("crop_width" IS NULL) AND ("crop_height" IS NULL)) OR (("crop_x" >= (0)::double precision) AND ("crop_x" <= (1)::double precision) AND (("crop_y" >= (0)::double precision) AND ("crop_y" <= (1)::double precision)) AND ("crop_width" > (0)::double precision) AND ("crop_width" <= (1)::double precision) AND ("crop_height" > (0)::double precision) AND ("crop_height" <= (1)::double precision) AND (("crop_x" + "crop_width") <= (1)::double precision) AND (("crop_y" + "crop_height") <= (1)::double precision)))),
    CONSTRAINT "evidence_assets_check2" CHECK ((("duplicate_of_asset_id" IS NULL) OR ("duplicate_of_asset_id" <> "id"))),
    CONSTRAINT "evidence_assets_fingerprint_check" CHECK (("fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "evidence_assets_intended_use_check" CHECK (("length"("btrim"("intended_use")) > 0)),
    CONSTRAINT "evidence_assets_status_check" CHECK (("status" = ANY (ARRAY['confirmed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "evidence_assets_version_check" CHECK (("version" >= 1))
);


ALTER TABLE "public"."evidence_assets" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."file_agent_runs" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "binding_id" "uuid" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "declaration_revision_id" "uuid" NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    "idempotency_key" "text" NOT NULL,
    "harness_version" "text" NOT NULL,
    "status" "text" DEFAULT 'queued'::"text" NOT NULL,
    "attempt" integer DEFAULT 0 NOT NULL,
    "max_attempts" integer DEFAULT 3 NOT NULL,
    "leased_by" "text",
    "lease_token" "uuid",
    "lease_expires_at" timestamp with time zone,
    "input_payload" "jsonb" NOT NULL,
    "output_payload" "jsonb",
    "checkpoint" "jsonb",
    "receipt" "jsonb",
    "dossier_id" "uuid",
    "failure_code" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "started_at" timestamp with time zone,
    "finished_at" timestamp with time zone,
    "superseded_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "file_agent_runs_attempt_check" CHECK ((("attempt" >= 0) AND ("attempt" <= "max_attempts") AND ("max_attempts" >= 1))),
    CONSTRAINT "file_agent_runs_checkpoint_check" CHECK ((("checkpoint" IS NULL) OR ("jsonb_typeof"("checkpoint") = 'object'::"text"))),
    CONSTRAINT "file_agent_runs_harness_version_check" CHECK (("length"("btrim"("harness_version")) > 0)),
    CONSTRAINT "file_agent_runs_idempotency_key_check" CHECK (("length"("btrim"("idempotency_key")) > 0)),
    CONSTRAINT "file_agent_runs_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "file_agent_runs_input_payload_check" CHECK (("jsonb_typeof"("input_payload") = 'object'::"text")),
    CONSTRAINT "file_agent_runs_lease_check" CHECK (((("status" = 'running'::"text") AND ("leased_by" IS NOT NULL) AND ("lease_token" IS NOT NULL) AND ("lease_expires_at" IS NOT NULL)) OR (("status" <> 'running'::"text") AND ("leased_by" IS NULL) AND ("lease_token" IS NULL) AND ("lease_expires_at" IS NULL)))),
    CONSTRAINT "file_agent_runs_output_payload_check" CHECK ((("output_payload" IS NULL) OR ("jsonb_typeof"("output_payload") = 'object'::"text"))),
    CONSTRAINT "file_agent_runs_receipt_check" CHECK ((("receipt" IS NULL) OR ("jsonb_typeof"("receipt") = 'object'::"text"))),
    CONSTRAINT "file_agent_runs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'running'::"text", 'succeeded'::"text", 'needs_attention'::"text", 'failed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "file_agent_runs_superseded_check" CHECK ((("status" = 'superseded'::"text") = ("superseded_at" IS NOT NULL))),
    CONSTRAINT "file_agent_runs_terminal_check" CHECK (((("status" = ANY (ARRAY['succeeded'::"text", 'needs_attention'::"text", 'failed'::"text", 'superseded'::"text"])) AND ("finished_at" IS NOT NULL)) OR (("status" = ANY (ARRAY['queued'::"text", 'running'::"text"])) AND ("finished_at" IS NULL))))
);


ALTER TABLE "public"."file_agent_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."file_dossiers" (
    "id" "uuid" NOT NULL,
    "run_id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "binding_id" "uuid" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "source_sha256" "text" NOT NULL,
    "declaration_revision" integer NOT NULL,
    "dossier_fingerprint" "text" NOT NULL,
    "dossier_payload" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "superseded_at" timestamp with time zone,
    CONSTRAINT "file_dossiers_declaration_revision_check" CHECK (("declaration_revision" >= 1)),
    CONSTRAINT "file_dossiers_fingerprint_check" CHECK (("dossier_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "file_dossiers_payload_check" CHECK (("jsonb_typeof"("dossier_payload") = 'object'::"text")),
    CONSTRAINT "file_dossiers_source_sha256_check" CHECK (("source_sha256" ~ '^[0-9a-f]{64}$'::"text"))
);


ALTER TABLE "public"."file_dossiers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."generation_runs" (
    "id" "text" NOT NULL,
    "trace_id" "text" NOT NULL,
    "request_id" "text" DEFAULT ''::"text" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "block_id" "text" NOT NULL,
    "operation" "text" NOT NULL,
    "model_id" "text" NOT NULL,
    "model_invocations" integer DEFAULT 0 NOT NULL,
    "provider_requests" integer DEFAULT 0 NOT NULL,
    "tool_calls" integer DEFAULT 0 NOT NULL,
    "input_tokens" bigint DEFAULT 0 NOT NULL,
    "output_tokens" bigint DEFAULT 0 NOT NULL,
    "cache_write_tokens" bigint DEFAULT 0 NOT NULL,
    "cache_read_tokens" bigint DEFAULT 0 NOT NULL,
    "duration_ms" bigint DEFAULT 0 NOT NULL,
    "transport_attempts" integer DEFAULT 0 NOT NULL,
    "status" "text" DEFAULT 'running'::"text" NOT NULL,
    "error_code" "text" DEFAULT ''::"text" NOT NULL,
    "started_at" timestamp with time zone NOT NULL,
    "finished_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "generation_runs_cache_read_tokens_check" CHECK (("cache_read_tokens" >= 0)),
    CONSTRAINT "generation_runs_cache_write_tokens_check" CHECK (("cache_write_tokens" >= 0)),
    CONSTRAINT "generation_runs_check" CHECK (((("status" = 'running'::"text") AND ("finished_at" IS NULL)) OR (("status" = ANY (ARRAY['succeeded'::"text", 'failed'::"text"])) AND ("finished_at" IS NOT NULL)))),
    CONSTRAINT "generation_runs_duration_ms_check" CHECK (("duration_ms" >= 0)),
    CONSTRAINT "generation_runs_input_tokens_check" CHECK (("input_tokens" >= 0)),
    CONSTRAINT "generation_runs_model_invocations_check" CHECK (("model_invocations" >= 0)),
    CONSTRAINT "generation_runs_output_tokens_check" CHECK (("output_tokens" >= 0)),
    CONSTRAINT "generation_runs_provider_requests_check" CHECK (("provider_requests" >= 0)),
    CONSTRAINT "generation_runs_status_check" CHECK (("status" = ANY (ARRAY['running'::"text", 'succeeded'::"text", 'failed'::"text"]))),
    CONSTRAINT "generation_runs_tool_calls_check" CHECK (("tool_calls" >= 0)),
    CONSTRAINT "generation_runs_transport_attempts_check" CHECK (("transport_attempts" >= 0))
);


ALTER TABLE "public"."generation_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."image_agent_runs" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "binding_id" "uuid" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "declaration_revision_id" "uuid" NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    "idempotency_key" "text" NOT NULL,
    "harness_version" "text" NOT NULL,
    "status" "text" DEFAULT 'queued'::"text" NOT NULL,
    "attempt" integer DEFAULT 0 NOT NULL,
    "max_attempts" integer DEFAULT 3 NOT NULL,
    "leased_by" "text",
    "lease_token" "uuid",
    "lease_expires_at" timestamp with time zone,
    "input_payload" "jsonb" NOT NULL,
    "output_payload" "jsonb",
    "receipt" "jsonb",
    "failure_code" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "started_at" timestamp with time zone,
    "finished_at" timestamp with time zone,
    "superseded_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "image_agent_runs_attempt_check" CHECK ((("attempt" >= 0) AND ("attempt" <= "max_attempts") AND ("max_attempts" >= 1))),
    CONSTRAINT "image_agent_runs_harness_version_check" CHECK (("length"("btrim"("harness_version")) > 0)),
    CONSTRAINT "image_agent_runs_idempotency_key_check" CHECK (("length"("btrim"("idempotency_key")) > 0)),
    CONSTRAINT "image_agent_runs_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "image_agent_runs_input_payload_check" CHECK (("jsonb_typeof"("input_payload") = 'object'::"text")),
    CONSTRAINT "image_agent_runs_lease_check" CHECK (((("status" = 'running'::"text") AND ("leased_by" IS NOT NULL) AND ("lease_token" IS NOT NULL) AND ("lease_expires_at" IS NOT NULL)) OR (("status" <> 'running'::"text") AND ("leased_by" IS NULL) AND ("lease_token" IS NULL) AND ("lease_expires_at" IS NULL)))),
    CONSTRAINT "image_agent_runs_output_payload_check" CHECK ((("output_payload" IS NULL) OR ("jsonb_typeof"("output_payload") = 'object'::"text"))),
    CONSTRAINT "image_agent_runs_receipt_check" CHECK ((("receipt" IS NULL) OR ("jsonb_typeof"("receipt") = 'object'::"text"))),
    CONSTRAINT "image_agent_runs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'running'::"text", 'succeeded'::"text", 'failed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "image_agent_runs_superseded_check" CHECK ((("status" = 'superseded'::"text") = ("superseded_at" IS NOT NULL))),
    CONSTRAINT "image_agent_runs_terminal_check" CHECK (((("status" = ANY (ARRAY['succeeded'::"text", 'failed'::"text", 'superseded'::"text"])) AND ("finished_at" IS NOT NULL)) OR (("status" = ANY (ARRAY['queued'::"text", 'running'::"text"])) AND ("finished_at" IS NULL))))
);


ALTER TABLE "public"."image_agent_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."material_events" (
    "id" bigint NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "source_id" "uuid",
    "actor" "text" NOT NULL,
    "event_type" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "material_events_actor_check" CHECK (("actor" = ANY (ARRAY['user'::"text", 'operator'::"text", 'system'::"text", 'agent'::"text"]))),
    CONSTRAINT "material_events_event_type_check" CHECK (("length"("btrim"("event_type")) > 0))
);


ALTER TABLE "public"."material_events" OWNER TO "postgres";


ALTER TABLE "public"."material_events" ALTER COLUMN "id" ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME "public"."material_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."material_mapping_runs" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "snapshot_id" "uuid" NOT NULL,
    "scope_id" "text" NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    "idempotency_key" "text" NOT NULL,
    "mapping_policy_id" "text" NOT NULL,
    "harness_version" "text" NOT NULL,
    "status" "text" DEFAULT 'queued'::"text" NOT NULL,
    "attempt" integer DEFAULT 0 NOT NULL,
    "max_attempts" integer DEFAULT 3 NOT NULL,
    "leased_by" "text",
    "lease_token" "uuid",
    "lease_expires_at" timestamp with time zone,
    "input_payload" "jsonb" NOT NULL,
    "result_payload" "jsonb",
    "receipt" "jsonb",
    "failure_code" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "started_at" timestamp with time zone,
    "finished_at" timestamp with time zone,
    "superseded_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "material_mapping_runs_attempt_check" CHECK ((("attempt" >= 0) AND ("attempt" <= "max_attempts") AND ("max_attempts" >= 1))),
    CONSTRAINT "material_mapping_runs_harness_version_check" CHECK (("length"("btrim"("harness_version")) > 0)),
    CONSTRAINT "material_mapping_runs_idempotency_key_check" CHECK (("length"("btrim"("idempotency_key")) > 0)),
    CONSTRAINT "material_mapping_runs_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "material_mapping_runs_input_payload_check" CHECK (("jsonb_typeof"("input_payload") = 'object'::"text")),
    CONSTRAINT "material_mapping_runs_lease_check" CHECK (((("status" = 'running'::"text") AND ("leased_by" IS NOT NULL) AND ("lease_token" IS NOT NULL) AND ("lease_expires_at" IS NOT NULL)) OR (("status" <> 'running'::"text") AND ("leased_by" IS NULL) AND ("lease_token" IS NULL) AND ("lease_expires_at" IS NULL)))),
    CONSTRAINT "material_mapping_runs_policy_id_check" CHECK (("length"("btrim"("mapping_policy_id")) > 0)),
    CONSTRAINT "material_mapping_runs_receipt_check" CHECK ((("receipt" IS NULL) OR ("jsonb_typeof"("receipt") = 'object'::"text"))),
    CONSTRAINT "material_mapping_runs_result_payload_check" CHECK ((("result_payload" IS NULL) OR ("jsonb_typeof"("result_payload") = 'object'::"text"))),
    CONSTRAINT "material_mapping_runs_scope_id_check" CHECK (("length"("btrim"("scope_id")) > 0)),
    CONSTRAINT "material_mapping_runs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'running'::"text", 'succeeded'::"text", 'needs_attention'::"text", 'failed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "material_mapping_runs_superseded_check" CHECK ((("status" = 'superseded'::"text") = ("superseded_at" IS NOT NULL))),
    CONSTRAINT "material_mapping_runs_terminal_check" CHECK (((("status" = ANY (ARRAY['succeeded'::"text", 'needs_attention'::"text", 'failed'::"text", 'superseded'::"text"])) AND ("finished_at" IS NOT NULL)) OR (("status" = ANY (ARRAY['queued'::"text", 'running'::"text"])) AND ("finished_at" IS NULL))))
);


ALTER TABLE "public"."material_mapping_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."material_set_snapshots" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    "snapshot_payload" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "material_set_snapshots_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "material_set_snapshots_payload_check" CHECK (("jsonb_typeof"("snapshot_payload") = 'object'::"text"))
);


ALTER TABLE "public"."material_set_snapshots" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."material_sources" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "source_label" "text" NOT NULL,
    "original_filename" "text" NOT NULL,
    "object_path" "text" NOT NULL,
    "kind" "text" NOT NULL,
    "media_type" "text" NOT NULL,
    "size_bytes" bigint NOT NULL,
    "sha256" "text" NOT NULL,
    "scope_kind" "text" DEFAULT 'uncertain'::"text" NOT NULL,
    "report_section_ids" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "status" "text" DEFAULT 'uploading'::"text" NOT NULL,
    "normalized_material" "jsonb",
    "processing_steps" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "error" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "deleted_at" timestamp with time zone,
    CONSTRAINT "material_sources_check" CHECK ((("status" = 'deleted'::"text") = ("deleted_at" IS NOT NULL))),
    CONSTRAINT "material_sources_check1" CHECK (((("scope_kind" = 'topics'::"text") AND ("cardinality"("report_section_ids") > 0)) OR (("scope_kind" <> 'topics'::"text") AND ("cardinality"("report_section_ids") = 0)))),
    CONSTRAINT "material_sources_kind_check" CHECK (("kind" = ANY (ARRAY['pdf'::"text", 'docx'::"text", 'xlsx'::"text", 'pptx'::"text", 'png'::"text", 'jpeg'::"text", 'webp'::"text"]))),
    CONSTRAINT "material_sources_object_path_check" CHECK (("object_path" !~ '(^|/)\.\.(/|$)'::"text")),
    CONSTRAINT "material_sources_original_filename_check" CHECK (("length"("btrim"("original_filename")) > 0)),
    CONSTRAINT "material_sources_scope_kind_check" CHECK (("scope_kind" = ANY (ARRAY['profile'::"text", 'topics'::"text", 'uncertain'::"text"]))),
    CONSTRAINT "material_sources_sha256_check" CHECK (("sha256" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "material_sources_size_bytes_check" CHECK ((("size_bytes" > 0) AND ("size_bytes" <= 20971520))),
    CONSTRAINT "material_sources_source_label_check" CHECK (("length"("btrim"("source_label")) > 0)),
    CONSTRAINT "material_sources_status_check" CHECK (("status" = ANY (ARRAY['uploading'::"text", 'queued'::"text", 'processing'::"text", 'ready'::"text", 'needs_attention'::"text", 'failed'::"text", 'deleted'::"text"])))
);


ALTER TABLE "public"."material_sources" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."material_workspaces" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "adapter_id" "text" NOT NULL,
    "contract_version" "text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "state" "jsonb" DEFAULT '{"gaps": [], "facts": [], "turns": [], "version": 1, "proposals": [], "clarifications": [], "topic_primary_input_modes": {}}'::"jsonb" NOT NULL,
    "state_seq" bigint DEFAULT 1 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "material_set_confirmed_at" timestamp with time zone,
    "material_set_confirmed_fingerprint" "text",
    CONSTRAINT "material_workspaces_adapter_id_check" CHECK (("length"("btrim"("adapter_id")) > 0)),
    CONSTRAINT "material_workspaces_state_seq_check" CHECK (("state_seq" >= 1)),
    CONSTRAINT "material_workspaces_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'completed'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."material_workspaces" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."report_events" (
    "id" bigint NOT NULL,
    "report_id" "uuid" NOT NULL,
    "actor" "text" NOT NULL,
    "event_type" "text" NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "report_events_actor_check" CHECK (("actor" = ANY (ARRAY['user'::"text", 'system'::"text", 'llm'::"text"])))
);


ALTER TABLE "public"."report_events" OWNER TO "postgres";


ALTER TABLE "public"."report_events" ALTER COLUMN "id" ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME "public"."report_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."report_lineage_edges" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "adapter_id" "text" NOT NULL,
    "edge_kind" "text" NOT NULL,
    "from_kind" "text" NOT NULL,
    "from_ref" "text" NOT NULL,
    "to_kind" "text" NOT NULL,
    "to_ref" "text" NOT NULL,
    "decision" "text" NOT NULL,
    "reason_code" "text" NOT NULL,
    "explanation" "text" NOT NULL,
    "source_id" "uuid",
    "source_sha256" "text",
    "fragment_id" "text",
    "fragment_locator" "jsonb",
    "run_id" "uuid",
    "report_state_seq" bigint,
    "input_fingerprint" "text",
    "context_fingerprint" "text",
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "report_lineage_edges_adapter_check" CHECK (("adapter_id" = ANY (ARRAY['simplified-report-input@2'::"text", 'comprehensive-evidence@2'::"text"]))),
    CONSTRAINT "report_lineage_edges_context_fingerprint_check" CHECK ((("context_fingerprint" IS NULL) OR ("context_fingerprint" ~ '^[0-9a-f]{64}$'::"text"))),
    CONSTRAINT "report_lineage_edges_decision_check" CHECK (("decision" = ANY (ARRAY['candidate'::"text", 'confirmed'::"text", 'auto_applied'::"text", 'held_low_confidence'::"text", 'blocked_conflict'::"text", 'invalid'::"text", 'not_applicable'::"text"]))),
    CONSTRAINT "report_lineage_edges_edge_kind_check" CHECK (("edge_kind" = ANY (ARRAY['source_fragment_to_input_resolution'::"text", 'input_resolution_to_report_input'::"text", 'source_fragment_to_fact'::"text", 'fact_to_report_input'::"text", 'report_input_to_block'::"text", 'evidence_fact_to_requirement'::"text", 'requirement_to_gap'::"text", 'blueprint_to_block'::"text", 'block_to_claim'::"text", 'block_to_artifact'::"text"]))),
    CONSTRAINT "report_lineage_edges_input_fingerprint_check" CHECK ((("input_fingerprint" IS NULL) OR ("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text"))),
    CONSTRAINT "report_lineage_edges_refs_check" CHECK ((("length"("btrim"("from_kind")) > 0) AND ("length"("btrim"("from_ref")) > 0) AND ("length"("btrim"("to_kind")) > 0) AND ("length"("btrim"("to_ref")) > 0) AND ("length"("btrim"("reason_code")) > 0) AND ("length"("btrim"("explanation")) > 0))),
    CONSTRAINT "report_lineage_edges_report_state_seq_check" CHECK ((("report_state_seq" IS NULL) OR ("report_state_seq" >= 1))),
    CONSTRAINT "report_lineage_edges_source_sha256_check" CHECK ((("source_sha256" IS NULL) OR ("source_sha256" ~ '^[0-9a-f]{64}$'::"text"))),
    CONSTRAINT "report_lineage_edges_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'stale'::"text", 'superseded'::"text"])))
);


ALTER TABLE "public"."report_lineage_edges" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."report_material_bindings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "source_id" "uuid" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "removed_at" timestamp with time zone,
    "superseded_at" timestamp with time zone,
    CONSTRAINT "report_material_bindings_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'removed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "report_material_bindings_status_timestamp_check" CHECK (((("status" = 'active'::"text") AND ("removed_at" IS NULL) AND ("superseded_at" IS NULL)) OR (("status" = 'removed'::"text") AND ("removed_at" IS NOT NULL) AND ("superseded_at" IS NULL)) OR (("status" = 'superseded'::"text") AND ("removed_at" IS NULL) AND ("superseded_at" IS NOT NULL))))
);


ALTER TABLE "public"."report_material_bindings" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."report_states" (
    "report_id" "uuid" NOT NULL,
    "state" "jsonb" NOT NULL,
    "state_seq" bigint DEFAULT 1 NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "report_states_state_seq_check" CHECK (("state_seq" >= 1))
);


ALTER TABLE "public"."report_states" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."reports" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "title" "text" DEFAULT ''::"text" NOT NULL,
    "report_type" "text" DEFAULT 'lightweight'::"text" NOT NULL,
    "data_classification" "text" DEFAULT 'customer'::"text" NOT NULL,
    "created_under_profile_id" "text" NOT NULL,
    "contract_version" "text" NOT NULL,
    "status" "text" DEFAULT 'active'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "report_profile_id" "text" NOT NULL,
    CONSTRAINT "reports_created_under_profile_id_check" CHECK (("created_under_profile_id" ~ '^[a-z_]+@[1-9][0-9]*$'::"text")),
    CONSTRAINT "reports_data_classification_check" CHECK (("data_classification" = ANY (ARRAY['customer'::"text", 'synthetic'::"text"]))),
    CONSTRAINT "reports_report_profile_id_check" CHECK (("report_profile_id" ~ '^[a-z_]+@[1-9][0-9]*$'::"text")),
    CONSTRAINT "reports_report_type_check" CHECK (("report_type" = 'lightweight'::"text")),
    CONSTRAINT "reports_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."reports" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."section_regeneration_batches" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "section_key" "text" NOT NULL,
    "mode" "text" NOT NULL,
    "expected_block_ids" "text"[] NOT NULL,
    "status" "text" NOT NULL,
    "idempotency_key" "uuid" NOT NULL,
    "base_state_seq" bigint NOT NULL,
    "lease_expires_at" timestamp with time zone NOT NULL,
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "finished_at" timestamp with time zone,
    "failure_reason" "text",
    "result" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    CONSTRAINT "section_regeneration_batches_base_state_seq_check" CHECK (("base_state_seq" >= 1)),
    CONSTRAINT "section_regeneration_batches_check" CHECK (((("status" = 'started'::"text") AND ("finished_at" IS NULL)) OR (("status" = ANY (ARRAY['succeeded'::"text", 'failed'::"text"])) AND ("finished_at" IS NOT NULL)))),
    CONSTRAINT "section_regeneration_batches_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "section_regeneration_batches_mode_check" CHECK (("mode" = ANY (ARRAY['initial'::"text", 'regeneration'::"text"]))),
    CONSTRAINT "section_regeneration_batches_status_check" CHECK (("status" = ANY (ARRAY['started'::"text", 'succeeded'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."section_regeneration_batches" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."lightweight_report_artifacts" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "report_revision_id" "uuid" NOT NULL,
    "generation_run_id" "uuid" NOT NULL,
    "kind" "text" NOT NULL,
    "filename" "text" NOT NULL,
    "media_type" "text" NOT NULL,
    "content_fingerprint" "text" NOT NULL,
    "storage_ref" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "lightweight_report_artifacts_filename_check" CHECK (("length"("btrim"("filename")) > 0)),
    CONSTRAINT "lightweight_report_artifacts_fingerprint_check" CHECK (("content_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "lightweight_report_artifacts_kind_check" CHECK (("kind" = ANY (ARRAY['word'::"text", 'review'::"text", 'internal_audit'::"text"]))),
    CONSTRAINT "lightweight_report_artifacts_media_type_check" CHECK (("length"("btrim"("media_type")) > 0)),
    CONSTRAINT "lightweight_report_artifacts_storage_ref_check" CHECK (("length"("btrim"("storage_ref")) > 0))
);


ALTER TABLE "public"."lightweight_report_artifacts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."lightweight_report_generation_events" (
    "id" bigint NOT NULL,
    "run_id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "event_type" "text" NOT NULL,
    "user_message" "text" NOT NULL,
    "current_object" "text",
    "action_required" boolean DEFAULT false NOT NULL,
    "payload" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "lightweight_report_generation_events_message_check" CHECK (("length"("btrim"("user_message")) > 0)),
    CONSTRAINT "lightweight_report_generation_events_payload_check" CHECK (("jsonb_typeof"("payload") = 'object'::"text")),
    CONSTRAINT "lightweight_report_generation_events_type_check" CHECK (("event_type" = ANY (ARRAY['queued'::"text", 'started'::"text", 'block_started'::"text", 'block_completed'::"text", 'report_saved'::"text", 'artifacts_ready'::"text", 'export_blocked'::"text", 'failed'::"text", 'superseded'::"text"])))
);


ALTER TABLE "public"."lightweight_report_generation_events" OWNER TO "postgres";


ALTER TABLE "public"."lightweight_report_generation_events" ALTER COLUMN "id" ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME "public"."lightweight_report_generation_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."lightweight_report_generation_runs" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "material_set_snapshot_id" "uuid" NOT NULL,
    "base_report_state_seq" bigint NOT NULL,
    "input_fingerprint" "text" NOT NULL,
    "idempotency_key" "uuid" NOT NULL,
    "model_id" "text" NOT NULL,
    "status" "text" DEFAULT 'queued'::"text" NOT NULL,
    "attempt" integer DEFAULT 0 NOT NULL,
    "max_attempts" integer DEFAULT 2 NOT NULL,
    "leased_by" "text",
    "lease_token" "uuid",
    "lease_expires_at" timestamp with time zone,
    "expected_block_ids" "text"[] NOT NULL,
    "block_results" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "result_report_state_seq" bigint,
    "result_revision_id" "uuid",
    "failure_code" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "started_at" timestamp with time zone,
    "finished_at" timestamp with time zone,
    "superseded_at" timestamp with time zone,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "lightweight_report_generation_runs_attempt_check" CHECK ((("attempt" >= 0) AND ("attempt" <= "max_attempts") AND ("max_attempts" >= 1))),
    CONSTRAINT "lightweight_report_generation_runs_base_seq_check" CHECK (("base_report_state_seq" >= 1)),
    CONSTRAINT "lightweight_report_generation_runs_blocks_check" CHECK (("cardinality"("expected_block_ids") >= 1)),
    CONSTRAINT "lightweight_report_generation_runs_input_fingerprint_check" CHECK (("input_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "lightweight_report_generation_runs_model_id_check" CHECK (("length"("btrim"("model_id")) > 0)),
    CONSTRAINT "lightweight_report_generation_runs_lease_check" CHECK (((("status" = 'running'::"text") AND ("leased_by" IS NOT NULL) AND ("lease_token" IS NOT NULL) AND ("lease_expires_at" IS NOT NULL)) OR (("status" <> 'running'::"text") AND ("leased_by" IS NULL) AND ("lease_token" IS NULL) AND ("lease_expires_at" IS NULL)))),
    CONSTRAINT "lightweight_report_generation_runs_result_seq_check" CHECK ((("result_report_state_seq" IS NULL) OR ("result_report_state_seq" >= 2))),
    CONSTRAINT "lightweight_report_generation_runs_results_check" CHECK (("jsonb_typeof"("block_results") = 'array'::"text")),
    CONSTRAINT "lightweight_report_generation_runs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'running'::"text", 'succeeded'::"text", 'failed'::"text", 'superseded'::"text"]))),
    CONSTRAINT "lightweight_report_generation_runs_success_check" CHECK ((("status" <> 'succeeded'::"text") OR (("result_report_state_seq" IS NOT NULL) AND ("result_revision_id" IS NOT NULL) AND ("jsonb_array_length"("block_results") = "cardinality"("expected_block_ids"))))),
    CONSTRAINT "lightweight_report_generation_runs_superseded_check" CHECK ((("status" = 'superseded'::"text") = ("superseded_at" IS NOT NULL))),
    CONSTRAINT "lightweight_report_generation_runs_terminal_check" CHECK (((("status" = ANY (ARRAY['succeeded'::"text", 'failed'::"text", 'superseded'::"text"])) AND ("finished_at" IS NOT NULL)) OR (("status" = ANY (ARRAY['queued'::"text", 'running'::"text"])) AND ("finished_at" IS NULL))))
);


ALTER TABLE "public"."lightweight_report_generation_runs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."lightweight_report_revisions" (
    "id" "uuid" NOT NULL,
    "account_id" "uuid" NOT NULL,
    "report_id" "uuid" NOT NULL,
    "generation_run_id" "uuid" NOT NULL,
    "revision" integer NOT NULL,
    "report_state_seq" bigint NOT NULL,
    "content_fingerprint" "text" NOT NULL,
    "state_payload" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "lightweight_report_revisions_fingerprint_check" CHECK (("content_fingerprint" ~ '^[0-9a-f]{64}$'::"text")),
    CONSTRAINT "lightweight_report_revisions_payload_check" CHECK (("jsonb_typeof"("state_payload") = 'object'::"text")),
    CONSTRAINT "lightweight_report_revisions_revision_check" CHECK (("revision" >= 1)),
    CONSTRAINT "lightweight_report_revisions_state_seq_check" CHECK (("report_state_seq" >= 2))
);


ALTER TABLE "public"."lightweight_report_revisions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_file_declaration_revisions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "binding_id" "uuid" NOT NULL,
    "workspace_id" "uuid" NOT NULL,
    "revision" integer NOT NULL,
    "description" "text" NOT NULL,
    "role" "text" NOT NULL,
    "topic_tags" "text"[] NOT NULL,
    "asset_title" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "user_file_declaration_revisions_asset_title_check" CHECK (((("role" = 'layout_asset'::"text") AND (("asset_title" IS NULL) OR (("length"("btrim"("asset_title")) >= 1) AND ("length"("btrim"("asset_title")) <= 100)))) OR (("role" = 'semantic_material'::"text") AND ("asset_title" IS NULL)))),
    CONSTRAINT "user_file_declaration_revisions_description_check" CHECK ((("length"("btrim"("description")) = 0) OR (("length"("btrim"("description")) >= 10) AND ("length"("btrim"("description")) <= 140)))),
    CONSTRAINT "user_file_declaration_revisions_revision_check" CHECK (("revision" >= 1)),
    CONSTRAINT "user_file_declaration_revisions_role_check" CHECK (("role" = ANY (ARRAY['semantic_material'::"text", 'layout_asset'::"text"]))),
    CONSTRAINT "user_file_declaration_revisions_topic_tags_check" CHECK ((("cardinality"("topic_tags") >= 1) AND ("cardinality"("topic_tags") <= 24)))
);


ALTER TABLE "public"."user_file_declaration_revisions" OWNER TO "postgres";


ALTER TABLE ONLY "public"."account_entitlement_grants"
    ADD CONSTRAINT "account_entitlement_grants_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."account_events"
    ADD CONSTRAINT "account_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."account_identities"
    ADD CONSTRAINT "account_identities_account_id_identity_issuer_key" UNIQUE ("account_id", "identity_issuer");



ALTER TABLE ONLY "public"."account_identities"
    ADD CONSTRAINT "account_identities_identity_issuer_identity_subject_key" UNIQUE ("identity_issuer", "identity_subject");



ALTER TABLE ONLY "public"."account_identities"
    ADD CONSTRAINT "account_identities_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."account_operator_permissions"
    ADD CONSTRAINT "account_operator_permissions_pkey" PRIMARY KEY ("account_id", "permission");



ALTER TABLE ONLY "public"."accounts"
    ADD CONSTRAINT "accounts_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."accounts"
    ADD CONSTRAINT "accounts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."block_material_decision_materials"
    ADD CONSTRAINT "block_material_decision_materials_ordinal_key" UNIQUE ("decision_id", "ordinal");



ALTER TABLE ONLY "public"."block_material_decision_materials"
    ADD CONSTRAINT "block_material_decision_materials_pkey" PRIMARY KEY ("decision_id", "material_id");



ALTER TABLE ONLY "public"."block_material_decisions"
    ADD CONSTRAINT "block_material_decisions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."block_material_decisions"
    ADD CONSTRAINT "block_material_decisions_run_block_key" UNIQUE ("mapping_run_id", "block_id");



ALTER TABLE ONLY "public"."evidence_assets"
    ADD CONSTRAINT "evidence_assets_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."evidence_assets"
    ADD CONSTRAINT "evidence_assets_report_id_material_source_id_key" UNIQUE ("report_id", "material_source_id");



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_report_idempotency_key" UNIQUE ("report_id", "idempotency_key");



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_run_id_key" UNIQUE ("run_id");



ALTER TABLE ONLY "public"."generation_runs"
    ADD CONSTRAINT "generation_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_report_idempotency_key" UNIQUE ("report_id", "idempotency_key");



ALTER TABLE ONLY "public"."material_events"
    ADD CONSTRAINT "material_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."material_mapping_runs"
    ADD CONSTRAINT "material_mapping_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."material_mapping_runs"
    ADD CONSTRAINT "material_mapping_runs_report_idempotency_key" UNIQUE ("report_id", "idempotency_key");



ALTER TABLE ONLY "public"."material_set_snapshots"
    ADD CONSTRAINT "material_set_snapshots_id_report_account_key" UNIQUE ("id", "report_id", "account_id");



ALTER TABLE ONLY "public"."material_set_snapshots"
    ADD CONSTRAINT "material_set_snapshots_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."material_set_snapshots"
    ADD CONSTRAINT "material_set_snapshots_report_input_key" UNIQUE ("report_id", "input_fingerprint");



ALTER TABLE ONLY "public"."material_sources"
    ADD CONSTRAINT "material_sources_id_workspace_id_key" UNIQUE ("id", "workspace_id");



ALTER TABLE ONLY "public"."material_sources"
    ADD CONSTRAINT "material_sources_object_path_key" UNIQUE ("object_path");



ALTER TABLE ONLY "public"."material_sources"
    ADD CONSTRAINT "material_sources_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."material_workspaces"
    ADD CONSTRAINT "material_workspaces_id_account_id_key" UNIQUE ("id", "account_id");



ALTER TABLE ONLY "public"."material_workspaces"
    ADD CONSTRAINT "material_workspaces_id_report_id_key" UNIQUE ("id", "report_id");



ALTER TABLE ONLY "public"."material_workspaces"
    ADD CONSTRAINT "material_workspaces_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."report_events"
    ADD CONSTRAINT "report_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."report_lineage_edges"
    ADD CONSTRAINT "report_lineage_edges_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."report_material_bindings"
    ADD CONSTRAINT "report_material_bindings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."report_states"
    ADD CONSTRAINT "report_states_pkey" PRIMARY KEY ("report_id");



ALTER TABLE ONLY "public"."reports"
    ADD CONSTRAINT "reports_id_account_id_key" UNIQUE ("id", "account_id");



ALTER TABLE ONLY "public"."reports"
    ADD CONSTRAINT "reports_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."section_regeneration_batches"
    ADD CONSTRAINT "section_regeneration_batches_account_id_idempotency_key_key" UNIQUE ("account_id", "idempotency_key");



ALTER TABLE ONLY "public"."section_regeneration_batches"
    ADD CONSTRAINT "section_regeneration_batches_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."lightweight_report_artifacts"
    ADD CONSTRAINT "lightweight_report_artifacts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."lightweight_report_artifacts"
    ADD CONSTRAINT "lightweight_report_artifacts_revision_kind_key" UNIQUE ("report_revision_id", "kind");



ALTER TABLE ONLY "public"."lightweight_report_generation_events"
    ADD CONSTRAINT "lightweight_report_generation_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_id_report_account_key" UNIQUE ("id", "report_id", "account_id");



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_report_idempotency_key" UNIQUE ("report_id", "idempotency_key");



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_generation_key" UNIQUE ("generation_run_id");



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_lineage_key" UNIQUE ("id", "report_id", "account_id", "generation_run_id");



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_report_revision_key" UNIQUE ("report_id", "revision");



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_report_state_key" UNIQUE ("report_id", "report_state_seq");



ALTER TABLE ONLY "public"."user_file_declaration_revisions"
    ADD CONSTRAINT "user_file_declaration_revisions_binding_revision_key" UNIQUE ("binding_id", "revision");



ALTER TABLE ONLY "public"."user_file_declaration_revisions"
    ADD CONSTRAINT "user_file_declaration_revisions_pkey" PRIMARY KEY ("id");



CREATE INDEX "account_entitlement_grants_history_idx" ON "public"."account_entitlement_grants" USING "btree" ("account_id", "starts_at" DESC);



CREATE UNIQUE INDEX "account_entitlement_grants_one_current_idx" ON "public"."account_entitlement_grants" USING "btree" ("account_id") WHERE ("ended_at" IS NULL);



CREATE INDEX "account_events_account_idx" ON "public"."account_events" USING "btree" ("account_id", "id");



CREATE INDEX "account_identities_account_idx" ON "public"."account_identities" USING "btree" ("account_id");



CREATE INDEX "block_material_decisions_block_idx" ON "public"."block_material_decisions" USING "btree" ("report_id", "block_id", "created_at" DESC);



CREATE INDEX "file_agent_runs_binding_idx" ON "public"."file_agent_runs" USING "btree" ("report_id", "binding_id", "created_at" DESC);



CREATE INDEX "file_agent_runs_queue_idx" ON "public"."file_agent_runs" USING "btree" ("status", "created_at") WHERE ("status" = 'queued'::"text");



CREATE UNIQUE INDEX "file_dossiers_one_current_binding_idx" ON "public"."file_dossiers" USING "btree" ("binding_id") WHERE ("superseded_at" IS NULL);



CREATE INDEX "file_dossiers_report_idx" ON "public"."file_dossiers" USING "btree" ("account_id", "report_id", "created_at" DESC);



CREATE INDEX "generation_runs_observation_idx" ON "public"."generation_runs" USING "btree" ("created_at", "operation", "model_id");



CREATE INDEX "generation_runs_report_idx" ON "public"."generation_runs" USING "btree" ("report_id", "created_at");



CREATE INDEX "image_agent_runs_binding_idx" ON "public"."image_agent_runs" USING "btree" ("report_id", "binding_id", "created_at" DESC);



CREATE INDEX "image_agent_runs_queue_idx" ON "public"."image_agent_runs" USING "btree" ("status", "created_at") WHERE ("status" = 'queued'::"text");



CREATE INDEX "material_events_workspace_idx" ON "public"."material_events" USING "btree" ("workspace_id", "id");



CREATE UNIQUE INDEX "material_mapping_runs_one_current_scope_idx" ON "public"."material_mapping_runs" USING "btree" ("report_id", "scope_id") WHERE ("status" = 'succeeded'::"text");



CREATE INDEX "material_mapping_runs_queue_idx" ON "public"."material_mapping_runs" USING "btree" ("status", "created_at") WHERE ("status" = 'queued'::"text");



CREATE INDEX "material_mapping_runs_scope_idx" ON "public"."material_mapping_runs" USING "btree" ("report_id", "scope_id", "created_at" DESC);



CREATE INDEX "material_set_snapshots_report_idx" ON "public"."material_set_snapshots" USING "btree" ("account_id", "report_id", "created_at" DESC);



CREATE INDEX "material_sources_workspace_idx" ON "public"."material_sources" USING "btree" ("workspace_id", "created_at");



CREATE UNIQUE INDEX "material_sources_workspace_sha256_active_idx" ON "public"."material_sources" USING "btree" ("workspace_id", "sha256") WHERE ("status" <> 'deleted'::"text");



CREATE INDEX "material_workspaces_account_idx" ON "public"."material_workspaces" USING "btree" ("account_id", "updated_at" DESC);



CREATE UNIQUE INDEX "material_workspaces_one_active_report_idx" ON "public"."material_workspaces" USING "btree" ("report_id") WHERE ("status" = 'active'::"text");



CREATE INDEX "report_events_report_idx" ON "public"."report_events" USING "btree" ("report_id", "id");



CREATE INDEX "report_lineage_edges_report_idx" ON "public"."report_lineage_edges" USING "btree" ("account_id", "report_id", "created_at");



CREATE INDEX "report_lineage_edges_source_idx" ON "public"."report_lineage_edges" USING "btree" ("source_id") WHERE ("source_id" IS NOT NULL);



CREATE UNIQUE INDEX "report_material_bindings_one_active_source_idx" ON "public"."report_material_bindings" USING "btree" ("source_id") WHERE ("status" = 'active'::"text");



CREATE INDEX "report_material_bindings_workspace_idx" ON "public"."report_material_bindings" USING "btree" ("workspace_id", "status", "created_at");



CREATE INDEX "reports_account_idx" ON "public"."reports" USING "btree" ("account_id", "status");



CREATE INDEX "reports_profile_idx" ON "public"."reports" USING "btree" ("report_profile_id");



CREATE UNIQUE INDEX "section_regeneration_batches_one_started_idx" ON "public"."section_regeneration_batches" USING "btree" ("report_id", "section_key") WHERE ("status" = 'started'::"text");



CREATE INDEX "section_regeneration_batches_section_idx" ON "public"."section_regeneration_batches" USING "btree" ("report_id", "section_key", "started_at" DESC);



CREATE INDEX "lightweight_report_artifacts_report_idx" ON "public"."lightweight_report_artifacts" USING "btree" ("report_id", "created_at" DESC);



CREATE INDEX "lightweight_report_generation_events_run_idx" ON "public"."lightweight_report_generation_events" USING "btree" ("run_id", "id");



CREATE UNIQUE INDEX "lightweight_report_generation_runs_one_active_idx" ON "public"."lightweight_report_generation_runs" USING "btree" ("report_id") WHERE ("status" = ANY (ARRAY['queued'::"text", 'running'::"text"]));



CREATE INDEX "lightweight_report_generation_runs_queue_idx" ON "public"."lightweight_report_generation_runs" USING "btree" ("status", "created_at") WHERE ("status" = 'queued'::"text");



CREATE INDEX "lightweight_report_revisions_report_idx" ON "public"."lightweight_report_revisions" USING "btree" ("report_id", "revision" DESC);



CREATE INDEX "user_file_declaration_revisions_binding_idx" ON "public"."user_file_declaration_revisions" USING "btree" ("binding_id", "revision" DESC);



ALTER TABLE ONLY "public"."account_entitlement_grants"
    ADD CONSTRAINT "account_entitlement_grants_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."account_events"
    ADD CONSTRAINT "account_events_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."account_identities"
    ADD CONSTRAINT "account_identities_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."account_operator_permissions"
    ADD CONSTRAINT "account_operator_permissions_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."block_material_decision_materials"
    ADD CONSTRAINT "block_material_decision_materials_decision_fkey" FOREIGN KEY ("decision_id") REFERENCES "public"."block_material_decisions"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."block_material_decisions"
    ADD CONSTRAINT "block_material_decisions_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."block_material_decisions"
    ADD CONSTRAINT "block_material_decisions_run_fkey" FOREIGN KEY ("mapping_run_id") REFERENCES "public"."material_mapping_runs"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."block_material_decisions"
    ADD CONSTRAINT "block_material_decisions_snapshot_fkey" FOREIGN KEY ("snapshot_id") REFERENCES "public"."material_set_snapshots"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."evidence_assets"
    ADD CONSTRAINT "evidence_assets_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."evidence_assets"
    ADD CONSTRAINT "evidence_assets_duplicate_of_asset_id_fkey" FOREIGN KEY ("duplicate_of_asset_id") REFERENCES "public"."evidence_assets"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."evidence_assets"
    ADD CONSTRAINT "evidence_assets_report_id_account_id_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_binding_fkey" FOREIGN KEY ("binding_id") REFERENCES "public"."report_material_bindings"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_declaration_fkey" FOREIGN KEY ("declaration_revision_id") REFERENCES "public"."user_file_declaration_revisions"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_dossier_fkey" FOREIGN KEY ("dossier_id") REFERENCES "public"."file_dossiers"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_source_fkey" FOREIGN KEY ("source_id", "workspace_id") REFERENCES "public"."material_sources"("id", "workspace_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_agent_runs"
    ADD CONSTRAINT "file_agent_runs_workspace_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_binding_fkey" FOREIGN KEY ("binding_id") REFERENCES "public"."report_material_bindings"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_run_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."file_agent_runs"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_source_fkey" FOREIGN KEY ("source_id", "workspace_id") REFERENCES "public"."material_sources"("id", "workspace_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."file_dossiers"
    ADD CONSTRAINT "file_dossiers_workspace_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."generation_runs"
    ADD CONSTRAINT "generation_runs_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_binding_fkey" FOREIGN KEY ("binding_id") REFERENCES "public"."report_material_bindings"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_declaration_fkey" FOREIGN KEY ("declaration_revision_id") REFERENCES "public"."user_file_declaration_revisions"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_source_fkey" FOREIGN KEY ("source_id", "workspace_id") REFERENCES "public"."material_sources"("id", "workspace_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."image_agent_runs"
    ADD CONSTRAINT "image_agent_runs_workspace_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_events"
    ADD CONSTRAINT "material_events_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "public"."material_sources"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."material_events"
    ADD CONSTRAINT "material_events_workspace_id_fkey" FOREIGN KEY ("workspace_id") REFERENCES "public"."material_workspaces"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."material_mapping_runs"
    ADD CONSTRAINT "material_mapping_runs_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_mapping_runs"
    ADD CONSTRAINT "material_mapping_runs_snapshot_fkey" FOREIGN KEY ("snapshot_id") REFERENCES "public"."material_set_snapshots"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_mapping_runs"
    ADD CONSTRAINT "material_mapping_runs_workspace_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_set_snapshots"
    ADD CONSTRAINT "material_set_snapshots_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_set_snapshots"
    ADD CONSTRAINT "material_set_snapshots_workspace_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."material_sources"
    ADD CONSTRAINT "material_sources_workspace_id_account_id_fkey" FOREIGN KEY ("workspace_id", "account_id") REFERENCES "public"."material_workspaces"("id", "account_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."material_workspaces"
    ADD CONSTRAINT "material_workspaces_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."material_workspaces"
    ADD CONSTRAINT "material_workspaces_report_id_account_id_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_events"
    ADD CONSTRAINT "report_events_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_lineage_edges"
    ADD CONSTRAINT "report_lineage_edges_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_lineage_edges"
    ADD CONSTRAINT "report_lineage_edges_report_id_account_id_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_lineage_edges"
    ADD CONSTRAINT "report_lineage_edges_source_id_fkey" FOREIGN KEY ("source_id") REFERENCES "public"."material_sources"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."report_material_bindings"
    ADD CONSTRAINT "report_material_bindings_source_id_workspace_id_fkey" FOREIGN KEY ("source_id", "workspace_id") REFERENCES "public"."material_sources"("id", "workspace_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_material_bindings"
    ADD CONSTRAINT "report_material_bindings_workspace_id_fkey" FOREIGN KEY ("workspace_id") REFERENCES "public"."material_workspaces"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."report_states"
    ADD CONSTRAINT "report_states_report_id_fkey" FOREIGN KEY ("report_id") REFERENCES "public"."reports"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."reports"
    ADD CONSTRAINT "reports_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."section_regeneration_batches"
    ADD CONSTRAINT "section_regeneration_batches_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "public"."accounts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."section_regeneration_batches"
    ADD CONSTRAINT "section_regeneration_batches_report_id_account_id_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."lightweight_report_artifacts"
    ADD CONSTRAINT "lightweight_report_artifacts_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_artifacts"
    ADD CONSTRAINT "lightweight_report_artifacts_revision_fkey" FOREIGN KEY ("report_revision_id", "report_id", "account_id", "generation_run_id") REFERENCES "public"."lightweight_report_revisions"("id", "report_id", "account_id", "generation_run_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_generation_events"
    ADD CONSTRAINT "lightweight_report_generation_events_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_generation_events"
    ADD CONSTRAINT "lightweight_report_generation_events_run_fkey" FOREIGN KEY ("run_id") REFERENCES "public"."lightweight_report_generation_runs"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_revision_fkey" FOREIGN KEY ("result_revision_id", "report_id", "account_id", "id") REFERENCES "public"."lightweight_report_revisions"("id", "report_id", "account_id", "generation_run_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_generation_runs"
    ADD CONSTRAINT "lightweight_report_generation_runs_snapshot_fkey" FOREIGN KEY ("material_set_snapshot_id", "report_id", "account_id") REFERENCES "public"."material_set_snapshots"("id", "report_id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_generation_fkey" FOREIGN KEY ("generation_run_id", "report_id", "account_id") REFERENCES "public"."lightweight_report_generation_runs"("id", "report_id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."lightweight_report_revisions"
    ADD CONSTRAINT "lightweight_report_revisions_report_fkey" FOREIGN KEY ("report_id", "account_id") REFERENCES "public"."reports"("id", "account_id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."user_file_declaration_revisions"
    ADD CONSTRAINT "user_file_declaration_revisions_binding_id_fkey" FOREIGN KEY ("binding_id") REFERENCES "public"."report_material_bindings"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."user_file_declaration_revisions"
    ADD CONSTRAINT "user_file_declaration_revisions_workspace_id_fkey" FOREIGN KEY ("workspace_id") REFERENCES "public"."material_workspaces"("id") ON DELETE CASCADE;



ALTER TABLE "public"."account_entitlement_grants" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "account_entitlement_grants_owner_read" ON "public"."account_entitlement_grants" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."account_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "account_events_owner_read" ON "public"."account_events" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."account_identities" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "account_identities_owner_read" ON "public"."account_identities" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."account_operator_permissions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."accounts" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "accounts_owner_read" ON "public"."accounts" FOR SELECT TO "authenticated" USING (("id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."block_material_decision_materials" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."block_material_decisions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."evidence_assets" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "evidence_assets_owner_read" ON "public"."evidence_assets" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."file_agent_runs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."file_dossiers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."generation_runs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "generation_runs_owner_read" ON "public"."generation_runs" FOR SELECT TO "authenticated" USING ((( SELECT "r"."account_id"
   FROM "public"."reports" "r"
  WHERE ("r"."id" = "generation_runs"."report_id")) = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."image_agent_runs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."material_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "material_events_owner_read" ON "public"."material_events" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."material_workspaces" "workspace"
  WHERE (("workspace"."id" = "material_events"."workspace_id") AND ("workspace"."account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id"))))));



ALTER TABLE "public"."material_mapping_runs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."material_set_snapshots" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."material_sources" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "material_sources_owner_read" ON "public"."material_sources" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."material_workspaces" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "material_workspaces_owner_read" ON "public"."material_workspaces" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."report_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "report_events_owner_read" ON "public"."report_events" FOR SELECT TO "authenticated" USING ((( SELECT "r"."account_id"
   FROM "public"."reports" "r"
  WHERE ("r"."id" = "report_events"."report_id")) = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."report_lineage_edges" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "report_lineage_edges_owner_read" ON "public"."report_lineage_edges" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."report_material_bindings" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "report_material_bindings_owner_read" ON "public"."report_material_bindings" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."material_workspaces" "workspace"
  WHERE (("workspace"."id" = "report_material_bindings"."workspace_id") AND ("workspace"."account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id"))))));



ALTER TABLE "public"."report_states" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "report_states_owner_read" ON "public"."report_states" FOR SELECT TO "authenticated" USING ((( SELECT "r"."account_id"
   FROM "public"."reports" "r"
  WHERE ("r"."id" = "report_states"."report_id")) = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."reports" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "reports_owner_read" ON "public"."reports" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."section_regeneration_batches" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "section_regeneration_batches_owner_read" ON "public"."section_regeneration_batches" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."lightweight_report_artifacts" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "lightweight_report_artifacts_owner_read" ON "public"."lightweight_report_artifacts" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."lightweight_report_generation_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "lightweight_report_generation_events_owner_read" ON "public"."lightweight_report_generation_events" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."lightweight_report_generation_runs" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "lightweight_report_generation_runs_owner_read" ON "public"."lightweight_report_generation_runs" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."lightweight_report_revisions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "lightweight_report_revisions_owner_read" ON "public"."lightweight_report_revisions" FOR SELECT TO "authenticated" USING (("account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id")));



ALTER TABLE "public"."user_file_declaration_revisions" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "user_file_declaration_revisions_owner_read" ON "public"."user_file_declaration_revisions" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."material_workspaces" "workspace"
  WHERE (("workspace"."id" = "user_file_declaration_revisions"."workspace_id") AND ("workspace"."account_id" = ( SELECT "private"."current_account_id"() AS "current_account_id"))))));



GRANT USAGE ON SCHEMA "private" TO "authenticated";
GRANT USAGE ON SCHEMA "private" TO "service_role";



GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



REVOKE ALL ON FUNCTION "private"."current_account_id"() FROM PUBLIC;
GRANT ALL ON FUNCTION "private"."current_account_id"() TO "authenticated";
GRANT ALL ON FUNCTION "private"."current_account_id"() TO "service_role";



GRANT ALL ON TABLE "public"."account_entitlement_grants" TO "service_role";



GRANT ALL ON TABLE "public"."account_events" TO "service_role";



GRANT ALL ON SEQUENCE "public"."account_events_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."account_identities" TO "service_role";



GRANT ALL ON TABLE "public"."account_operator_permissions" TO "service_role";



GRANT ALL ON TABLE "public"."accounts" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."block_material_decision_materials" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."block_material_decisions" TO "service_role";



GRANT ALL ON TABLE "public"."evidence_assets" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."file_agent_runs" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."file_dossiers" TO "service_role";



GRANT ALL ON TABLE "public"."generation_runs" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."image_agent_runs" TO "service_role";



GRANT SELECT,INSERT ON TABLE "public"."material_events" TO "service_role";



GRANT SELECT,USAGE ON SEQUENCE "public"."material_events_id_seq" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."material_mapping_runs" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."material_set_snapshots" TO "service_role";



GRANT ALL ON TABLE "public"."material_sources" TO "service_role";



GRANT ALL ON TABLE "public"."material_workspaces" TO "service_role";



GRANT ALL ON TABLE "public"."report_events" TO "service_role";



GRANT ALL ON SEQUENCE "public"."report_events_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."report_lineage_edges" TO "service_role";



GRANT ALL ON TABLE "public"."report_material_bindings" TO "service_role";



GRANT ALL ON TABLE "public"."report_states" TO "service_role";



GRANT ALL ON TABLE "public"."reports" TO "service_role";



GRANT ALL ON TABLE "public"."section_regeneration_batches" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLE "public"."lightweight_report_artifacts" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLE "public"."lightweight_report_generation_events" TO "service_role";



GRANT UPDATE ON SEQUENCE "public"."lightweight_report_generation_events_id_seq" TO "anon";
GRANT UPDATE ON SEQUENCE "public"."lightweight_report_generation_events_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."lightweight_report_generation_events_id_seq" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "public"."lightweight_report_generation_runs" TO "service_role";



GRANT SELECT,INSERT,REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLE "public"."lightweight_report_revisions" TO "service_role";



GRANT ALL ON TABLE "public"."user_file_declaration_revisions" TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT UPDATE ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT UPDATE ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT UPDATE ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT REFERENCES,TRIGGER,TRUNCATE,MAINTAIN ON TABLES TO "service_role";

-- 浏览器角色（anon / authenticated）对业务表零授权：产品数据只经后端 service_role 访问；
-- service_role 只保留各表显式声明的 DML，默认授予的 REFERENCES/TRIGGER/TRUNCATE/MAINTAIN 一并收回。
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "public" FROM "anon", "authenticated";
REVOKE REFERENCES, TRIGGER, TRUNCATE, MAINTAIN ON ALL TABLES IN SCHEMA "public" FROM "service_role";

-- 私有存储桶：materials 存资料原件，exports 存工作台导出的 Word 存档；对象路径由后端生成，前端不直连 Storage。
INSERT INTO "storage"."buckets" ("id", "name", "public")
VALUES ('exports', 'exports', false)
ON CONFLICT ("id") DO UPDATE SET "public" = EXCLUDED."public";

INSERT INTO "storage"."buckets" ("id", "name", "public", "file_size_limit", "allowed_mime_types")
VALUES (
  'materials', 'materials', false, 20971520,
  ARRAY[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'image/png', 'image/jpeg', 'image/webp'
  ]
)
ON CONFLICT ("id") DO UPDATE
  SET "public" = EXCLUDED."public",
      "file_size_limit" = EXCLUDED."file_size_limit",
      "allowed_mime_types" = EXCLUDED."allowed_mime_types";

RESET ALL;
