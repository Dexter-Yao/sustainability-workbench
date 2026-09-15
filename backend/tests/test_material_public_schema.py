# ABOUTME: 资料 HTTP 公共 schema 的回归测试，锁定后端 SSOT 与浏览器 parse-first 所需字段。
# ABOUTME: 导出合同不得携带只适用于 OpenAPI 的 discriminator 扩展。

from sustainability_desk.material.intake.schema_export import build_schema


def test_material_public_schema_requires_projection_sequence_and_retry_contract() -> None:
    schema = build_schema()
    workspace = schema["$defs"]["MaterialWorkspaceProjection"]
    source = schema["$defs"]["MaterialSourceProjection"]

    assert "projection_seq" in workspace["required"]
    assert "report_state_seq" in workspace["required"]
    assert "can_retry" in source["required"]
    assert "kind" in schema["$defs"]["PdfPageLocator"]["required"]
    file_intake = schema["$defs"]["ReportFileIntakeProjection"]
    declaration = schema["$defs"]["UserFileDeclaration"]
    assert {
        "report_id",
        "projection_seq",
        "policy",
        "sources",
        "material_set_confirmation",
    }.issubset(file_intake["required"])
    confirmation = schema["$defs"]["MaterialSetConfirmationProjection"]
    assert {"status", "pending_description_count"}.issubset(confirmation["required"])
    assert set(confirmation["properties"]["status"]["enum"]) == {
        "not_required",
        "pending_description",
        "required",
        "confirmed",
    }
    assert {"description", "role", "topic_tags"}.issubset(declaration["required"])
    policy = schema["$defs"]["ReportFileIngressPolicy"]
    assert {
        "description_min_chars",
        "description_max_chars",
        "asset_title_max_chars",
        "semantic_material_extensions",
        "layout_asset_extensions",
    }.issubset(policy["required"])
    source = schema["$defs"]["ReportFileSourceProjection"]
    assert {
        "binding_id",
        "source_id",
        "binding_status",
        "declaration",
    }.issubset(source["required"])
    assert "file_analysis" in source["properties"]
    analysis = schema["$defs"]["ReportFileAnalysisProjection"]
    dossier = schema["$defs"]["ReportFileDossierProjection"]
    assert "status" in analysis["required"]
    assert {
        "relevance",
        "relevance_reason",
        "applicable_scope_count",
    }.issubset(dossier["required"])
    assert "attention_items" in dossier["properties"]
    assert {"report_scope", "report_scope_notice"}.issubset(dossier["properties"])
    assert "receipt" not in str(analysis)
    declaration_revision = schema["$defs"]["UserFileDeclarationRevision"]
    assert {"revision_id", "revision", "declared_at"}.issubset(
        declaration_revision["required"]
    )
    assert "discriminator" not in str(schema)
