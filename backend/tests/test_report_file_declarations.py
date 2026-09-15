# ABOUTME: 报告文件用户声明与准入策略的领域合同测试。
# ABOUTME: 标签、角色和文件格式由服务端裁决，前端只能投影同一规则。
from __future__ import annotations

import pytest
from pydantic import ValidationError

from datetime import datetime, timezone
from uuid import uuid4

from sustainability_desk.material.intake.models import (
    UserFileDeclaration,
    UserFileDeclarationRevision,
    ValidatedMaterialFile,
)
from sustainability_desk.material.workspace import MaterialRequestError, MaterialWorkspaceService
from sustainability_desk.persistence import material_intake as material_dal
from knowledge_package_fixtures import SSE_PACKAGE


def _file(kind: str, *, pdf_page_count: int | None = None) -> ValidatedMaterialFile:
    return ValidatedMaterialFile(
        filename=f"material.{kind}",
        kind=kind,  # type: ignore[arg-type]
        media_type="application/octet-stream",
        size_bytes=1,
        sha256="a" * 64,
        pdf_page_count=pdf_page_count,
    )


def test_layout_asset_allows_pending_title_and_never_accepts_docx_or_xlsx_formats() -> None:
    """排版素材允许上传时缺标题（待补充）；非空标题仍受最大长度约束；DOCX/XLSX 等语义格式不被接受。"""

    pending = UserFileDeclaration(
        description="",
        role="layout_asset",
        topic_tags=["uncertain"],
    )
    assert pending.asset_title is None

    declaration = UserFileDeclaration(
        description="这是用于报告展示的企业获奖证书图片资料。",
        role="layout_asset",
        topic_tags=["uncertain"],
        asset_title="企业获奖证书",
    )
    with pytest.raises(MaterialRequestError, match="不支持 DOCX"):
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            declaration,
            _file("docx"),
            MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE),
        )


def test_layout_asset_accepts_single_page_pdf_but_rejects_multi_page() -> None:
    """排版素材接受单页 PDF；多页 PDF 须提示改走语义资料，报错含实际页数。"""

    declaration = UserFileDeclaration(
        description="这是用于报告展示的企业获奖证书扫描件。",
        role="layout_asset",
        topic_tags=["uncertain"],
        asset_title="企业获奖证书",
    )
    policy = MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE)
    MaterialWorkspaceService.validate_report_file_declaration_for_policy(
        declaration, _file("pdf", pdf_page_count=1), policy,
    )
    with pytest.raises(MaterialRequestError, match="仅接受单页 PDF（当前 3 页）"):
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            declaration, _file("pdf", pdf_page_count=3), policy,
        )


def test_description_allows_empty_but_rejects_short_non_empty() -> None:
    """空说明表示待补充；非空但短于下限的半成品说明应被拒绝。"""

    pending = UserFileDeclaration(
        description="",
        role="semantic_material",
        topic_tags=["uncertain"],
    )
    assert pending.description == ""

    with pytest.raises(ValidationError, match="至少 10 字"):
        UserFileDeclaration(
            description="太短",
            role="semantic_material",
            topic_tags=["uncertain"],
        )


def test_semantic_material_uses_topic_registry_tags_and_disallows_uncertain_mix() -> None:
    declaration = UserFileDeclaration(
        description="公司 2025 年能源管理制度及执行记录，用于气候议题说明。",
        role="semantic_material",
        topic_tags=["climate_change"],
    )
    MaterialWorkspaceService.validate_report_file_declaration_for_policy(
        declaration,
        _file("docx"),
        MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE),
    )

    mixed = UserFileDeclaration(
        description="公司 2025 年能源管理制度及执行记录，用于气候议题说明。",
        role="semantic_material",
        topic_tags=["uncertain", "climate_change"],
    )
    with pytest.raises(MaterialRequestError, match="不能与其他资料标签同时选择"):
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            mixed,
            _file("docx"),
            MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE),
        )


def test_report_file_policy_is_single_source_for_limits_and_topic_tags() -> None:
    policy = MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE)

    assert policy.max_files_per_report == 30
    assert policy.max_file_bytes == 10 * 1024 * 1024
    assert policy.max_pdf_pages == 40
    assert {"png", "jpeg", "webp", "pdf"} == set(policy.layout_asset_kinds)
    assert policy.description_min_chars == 10
    assert policy.description_max_chars == 140
    assert policy.asset_title_max_chars == 100
    assert set(policy.semantic_material_extensions) == {
        ".pdf", ".docx", ".xlsx", ".pptx",
    }
    assert set(policy.layout_asset_extensions) == {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pdf",
    }
    assert any(tag.id == "climate_change" for tag in policy.topic_tags)


def test_declaration_revision_owns_persistent_revision_identity() -> None:
    declaration = UserFileDeclaration(
        description="公司 2025 年能源管理制度及执行记录，用于气候议题说明。",
        role="semantic_material",
        topic_tags=["climate_change"],
    )
    assert "revision" not in declaration.model_dump()

    revision = UserFileDeclarationRevision(
        **declaration.model_dump(),
        revision_id=uuid4(),
        binding_id=uuid4(),
        revision=2,
        declared_at=datetime.now(timezone.utc),
    )
    assert revision.revision == 2
    assert revision.matches(declaration)
    assert not revision.matches(
        declaration.model_copy(update={"description": "另一条至少十个字符的权威文件说明。"})
    )


@pytest.mark.asyncio
async def test_failed_sources_do_not_count_toward_report_file_capacity() -> None:
    captured: list[str] = []

    class _Connection:
        async def fetchval(self, sql: str, _workspace_id):
            captured.append(sql)
            return 29

    assert await material_dal.active_report_file_count(
        _Connection(),  # type: ignore[arg-type]
        uuid4(),
    ) == 29
    assert "binding.status = 'active'" in captured[0]
    assert "source.status not in ('failed', 'deleted')" in captured[0]


@pytest.mark.asyncio
async def test_declaration_update_appends_revision_instead_of_overwriting() -> None:
    workspace_id = uuid4()
    account_id = uuid4()
    binding_id = uuid4()
    source_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(timezone.utc)
    statements: list[str] = []

    class _Transaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return None

    class _Connection:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql: str, *_args):
            statements.append(sql)
            if "select binding.id" in sql:
                return {"id": binding_id, "status": "active", "source_id": source_id}
            return {
                "declaration_revision_id": revision_id,
                "binding_id": binding_id,
                "revision": 2,
                "description": "公司 2025 年能源管理制度及执行记录，用于气候议题说明。",
                "role": "semantic_material",
                "topic_tags": ["climate_change"],
                "asset_title": None,
                "declared_at": now,
            }

        async def fetchval(self, sql: str, *_args):
            statements.append(sql)
            return 1

        async def execute(self, sql: str, *_args):
            statements.append(sql)
            return "INSERT 0 1"

    connection = _Connection()

    class _Acquire:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *_args):
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

    revision = await material_dal.update_report_file_declaration(
        _Pool(),  # type: ignore[arg-type]
        account_id=account_id,
        workspace_id=workspace_id,
        binding_id=binding_id,
        declaration=UserFileDeclaration(
            description="公司 2025 年能源管理制度及执行记录，用于气候议题说明。",
            role="semantic_material",
            topic_tags=["climate_change"],
        ),
        expected_revision=1,
    )

    assert revision.revision_id == revision_id
    assert revision.revision == 2
    assert any(
        "insert into user_file_declaration_revisions" in statement
        for statement in statements
    )
    assert not any(
        "update user_file_declaration_revisions" in statement
        for statement in statements
    )
