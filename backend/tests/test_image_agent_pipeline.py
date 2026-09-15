# ABOUTME: 排版素材图片识别链的确定性预处理、Harness 冻结、DAL 幂等与编排接线测试。
# ABOUTME: 不连接真实数据库或 VLM；DAL 用内存假 pool，Agent 用 pydantic_ai FunctionModel 注入。
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pypdf import PdfWriter

from sustainability_desk.llm.ai_observability import create_observation_run, observe_generation
from sustainability_desk.material.intake.file_agent_contract import FileMaterialScope, FileSourceRevision
from sustainability_desk.material.intake.image_agent_ai import (
    ImageUnderstandingAgentAdapter,
    build_image_understanding_agent,
    model_image_pixel_size,
    prepare_model_image,
)
from sustainability_desk.material.intake.image_agent_contract import (
    CertificateFact,
    ImageAgentContext,
    ImageAgentProductTask,
    ImageDossierDraft,
)
from sustainability_desk.material.intake.image_agent_ai import freeze_image_dossier
from sustainability_desk.material.intake.models import UserFileDeclaration
from sustainability_desk.material.workspace import (
    LAYOUT_ASSET_PDF_MAX_PAGES,
    MaterialWorkspaceService,
    MaterialRequestError,
)
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.llm.prompt_profiles import load_prompt_profile


# ---------------------------------------------------------------------------
# 确定性送模预处理
# ---------------------------------------------------------------------------

IMAGE_TEXTS = load_prompt_profile(SSE_PACKAGE).agent_instructions.image_agent


def _png_bytes(size: tuple[int, int], color=(10, 20, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes(size: tuple[int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(1, 2, 3)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _single_page_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _multi_page_pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_prepare_model_image_passes_through_small_png_unchanged() -> None:
    data = _png_bytes((64, 64))
    result = prepare_model_image(data, media_type="image/png")
    assert isinstance(result, BinaryContent)
    assert result.media_type == "image/png"
    assert result.data == data


def test_prepare_model_image_downscales_oversized_png() -> None:
    data = _png_bytes((3000, 100))
    result = prepare_model_image(data, media_type="image/png")
    assert result.media_type == "image/png"
    with Image.open(BytesIO(result.data)) as resized:
        assert max(resized.width, resized.height) <= 2048


def test_prepare_model_image_converts_webp_to_jpeg() -> None:
    data = _webp_bytes((64, 64))
    result = prepare_model_image(data, media_type="image/webp")
    assert result.media_type == "image/jpeg"
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.format == "JPEG"


def test_prepare_model_image_renders_single_page_pdf_to_png() -> None:
    data = _single_page_pdf_bytes()
    result = prepare_model_image(data, media_type="application/pdf")
    assert result.media_type == "image/png"
    with Image.open(BytesIO(result.data)) as decoded:
        assert decoded.format == "PNG"


def test_model_image_pixel_size_reads_pdf_first_page_size() -> None:
    data = _single_page_pdf_bytes()
    width, height = model_image_pixel_size(data, media_type="application/pdf")
    assert width > 0 and height > 0


def test_model_image_pixel_size_reads_raw_image_size() -> None:
    data = _png_bytes((123, 45))
    width, height = model_image_pixel_size(data, media_type="image/png")
    assert (width, height) == (123, 45)


# ---------------------------------------------------------------------------
# Harness 冻结：scope alias -> scope_id、内容指纹
# ---------------------------------------------------------------------------


def _context(*, scopes: tuple[FileMaterialScope, ...] | None = None) -> ImageAgentContext:
    return ImageAgentContext(
        source_revision=FileSourceRevision(
            source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1
        ),
        filename="certificate.png",
        material_kind="png",
        size_bytes=1024,
        declaration=UserFileDeclaration(
            description="", role="layout_asset", topic_tags=["comprehensive"],
            asset_title="ISO 14001 认证证书",
        ),
        product_task=ImageAgentProductTask(
            report_id=uuid4(),
            material_scopes=scopes or (
                FileMaterialScope(
                    alias="scope_1", scope_id="report-area:company_intro",
                    title="关于公司", kind="report_area",
                ),
            ),
        ),
    )


def test_freeze_image_dossier_maps_alias_to_scope_id_and_derives_fingerprint() -> None:
    context = _context()
    draft = ImageDossierDraft(
        summary="公司获得的 ISO 14001 环境管理体系认证证书。",
        category="certificate_or_award",
        caption="ISO 14001 环境管理体系认证证书",
        alt_text="一张印有 ISO 14001 认证字样的证书图片。",
        scope_alias="scope_1",
        placement_reason="证书与公司资质介绍直接相关。",
        certificate_fact=CertificateFact(
            certificate_name="ISO 14001 环境管理体系认证证书",
        ),
    )
    dossier = freeze_image_dossier(
        draft, context=context, scope_alias_to_id={"scope_1": "report-area:company_intro"},
    )
    assert dossier.scope_id == "report-area:company_intro"
    assert dossier.dossier_fingerprint


def test_freeze_image_dossier_rejects_unmapped_alias() -> None:
    context = _context()
    draft = ImageDossierDraft(
        summary="摘要", category="other", caption="题注", alt_text="替代文本",
        scope_alias="scope_unknown", placement_reason="理由",
    )
    with pytest.raises(ValueError, match="无法映射到报告范围"):
        freeze_image_dossier(draft, context=context, scope_alias_to_id={})


# ---------------------------------------------------------------------------
# Agent 适配器：真实工具调用协议经 FunctionModel 校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_run_retries_when_scope_alias_is_not_allowed(monkeypatch) -> None:
    """output_validator 必须在 scope_alias 越权时触发 ModelRetry 并最终收敛到合法值。"""

    context = _context()
    attempts: list[str] = []

    def respond(_messages, info: AgentInfo) -> ModelResponse:
        output_tool = info.output_tools[0]
        if not attempts:
            attempts.append("invalid")
            payload = {
                "summary": "摘要", "category": "other", "caption": "题注",
                "alt_text": "替代文本", "scope_alias": "scope_not_allowed",
                "placement_reason": "理由",
            }
        else:
            attempts.append("valid")
            payload = {
                "summary": "摘要", "category": "other", "caption": "题注",
                "alt_text": "替代文本", "scope_alias": "scope_1",
                "placement_reason": "理由",
            }
        return ModelResponse(parts=[ToolCallPart(output_tool.name, payload, tool_call_id=str(len(attempts)))])

    def fake_build_agent(_model_id, *, output_type, instructions, deps_type, **_):
        return Agent(FunctionModel(respond), output_type=output_type, deps_type=deps_type, instructions=instructions)

    monkeypatch.setattr("sustainability_desk.material.intake.image_agent_ai.build_agent", fake_build_agent)
    agent = build_image_understanding_agent("qwen3.7-plus", texts=IMAGE_TEXTS)
    adapter = ImageUnderstandingAgentAdapter(agent=agent, texts=IMAGE_TEXTS)
    image = BinaryContent(data=_png_bytes((16, 16)), media_type="image/png")
    observation = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test", model_id="qwen3.7-plus", workload_kind="product_generation",
        report_id=str(context.product_task.report_id), block_id="file:test",
    )
    with unit_span(observation), observe_generation(observation):
        draft = await adapter.run(context, image, observation=observation)
    assert attempts == ["invalid", "valid"]
    assert draft.scope_alias == "scope_1"


# ---------------------------------------------------------------------------
# DAL：内存假 pool（同构 test_material_agent_pipeline_persistence.py）
# ---------------------------------------------------------------------------


class _Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def __init__(self, rows=(), *, execute_result: str = "UPDATE 1"):
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self._execute_result = execute_result
        self.fetchval_result = 0

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql, *args):
        self.statements.append((sql, args))
        if not self.rows:
            return None
        return self.rows.pop(0)

    async def execute(self, sql, *args):
        self.statements.append((sql, args))
        return self._execute_result

    async def fetch(self, sql, *args):
        self.statements.append((sql, args))
        return self.rows

    async def fetchval(self, sql, *args):
        self.statements.append((sql, args))
        return self.fetchval_result


class _Pool:
    def __init__(self, connection: _Connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def fetchrow(self, sql, *args):
        return await self.connection.fetchrow(sql, *args)

    async def execute(self, sql, *args):
        return await self.connection.execute(sql, *args)

    async def fetch(self, sql, *args):
        return await self.connection.fetch(sql, *args)

    async def fetchval(self, sql, *args):
        return await self.connection.fetchval(sql, *args)


def _image_run_row(*, context: ImageAgentContext, **overrides):
    row = {
        "id": uuid4(), "account_id": uuid4(), "report_id": context.product_task.report_id,
        "workspace_id": uuid4(), "binding_id": uuid4(),
        "source_id": context.source_revision.source_id, "declaration_revision_id": uuid4(),
        "input_fingerprint": "b" * 64, "idempotency_key": "image-agent:test",
        "harness_version": "image-agent@1", "status": "queued", "attempt": 0, "max_attempts": 3,
        "input_payload": context.model_dump(mode="json"),
        "updated_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_enqueue_image_agent_run_is_idempotent_on_same_input_fingerprint() -> None:
    context = _context()
    row = _image_run_row(context=context)
    connection = _Connection([row])
    stored = await pipeline_dal.enqueue_image_agent_run(
        _Pool(connection), run_id=row["id"], account_id=row["account_id"],
        report_id=row["report_id"], workspace_id=row["workspace_id"],
        binding_id=row["binding_id"], declaration_revision_id=row["declaration_revision_id"],
        context=context, input_fingerprint=row["input_fingerprint"],
        idempotency_key=row["idempotency_key"], harness_version=row["harness_version"],
    )
    assert "insert into image_agent_runs" in connection.statements[0][0]
    assert "on conflict (report_id, idempotency_key) do update" in connection.statements[0][0]
    assert stored.context == context
    assert stored.status == "queued"


@pytest.mark.asyncio
async def test_finish_image_agent_run_requires_output_payload_on_success() -> None:
    from sustainability_desk.material.intake.image_agent_ai import build_run_receipt

    context = _context()
    receipt = build_run_receipt(
        run_id=uuid4(), observation_run_id="trace-1", attempt=1, context=context,
        started_at=datetime.now(timezone.utc), dossier_fingerprint="c" * 64,
    )
    connection = _Connection()
    with pytest.raises(ValueError, match="output_payload"):
        await pipeline_dal.finish_image_agent_run(
            _Pool(connection), run_id=uuid4(), lease_token=uuid4(),
            status="succeeded", output_payload=None, receipt=receipt,
        )


@pytest.mark.asyncio
async def test_finish_image_agent_run_writes_failure_code_on_failure() -> None:
    from sustainability_desk.material.intake.image_agent_ai import build_run_receipt

    context = _context()
    receipt = build_run_receipt(
        run_id=uuid4(), observation_run_id=None, attempt=1, context=context,
        started_at=datetime.now(timezone.utc), failure_code="RuntimeError",
    )
    connection = _Connection()
    await pipeline_dal.finish_image_agent_run(
        _Pool(connection), run_id=uuid4(), lease_token=uuid4(),
        status="failed", output_payload=None, receipt=receipt,
    )
    sql, args = connection.statements[0]
    assert "update image_agent_runs" in sql
    assert "RuntimeError" in args


@pytest.mark.asyncio
async def test_finish_image_agent_run_requeues_retryable_failure_by_attempt_budget() -> None:
    from sustainability_desk.material.intake.image_agent_ai import build_run_receipt

    context = _context()
    receipt = build_run_receipt(
        run_id=uuid4(), observation_run_id=None, attempt=1, context=context,
        started_at=datetime.now(timezone.utc), failure_code="UnexpectedModelBehavior",
    )
    connection = _Connection()
    await pipeline_dal.finish_image_agent_run(
        _Pool(connection), run_id=uuid4(), lease_token=uuid4(),
        status="failed", output_payload=None, receipt=receipt,
        retryable_failure=True,
    )
    sql, args = connection.statements[0]
    assert "case when $6::boolean and attempt < max_attempts" in sql
    assert "then 'queued' else 'failed'" in sql
    assert "then null else now()" in sql
    assert args[-1] is True


@pytest.mark.asyncio
async def test_finish_image_agent_run_rejects_retryable_flag_on_success() -> None:
    from sustainability_desk.material.intake.image_agent_ai import build_run_receipt

    context = _context()
    receipt = build_run_receipt(
        run_id=uuid4(), observation_run_id="trace-1", attempt=1, context=context,
        started_at=datetime.now(timezone.utc), dossier_fingerprint="c" * 64,
    )
    with pytest.raises(ValueError, match="retryable_failure"):
        await pipeline_dal.finish_image_agent_run(
            _Pool(_Connection()), run_id=uuid4(), lease_token=uuid4(),
            status="succeeded", output_payload={"schema": "sustainability_desk.image_dossier.v1"},
            receipt=receipt, retryable_failure=True,
        )


@pytest.mark.asyncio
async def test_unfinished_image_agent_run_count_only_counts_queued_or_running() -> None:
    connection = _Connection()
    connection.fetchval_result = 2
    count = await pipeline_dal.unfinished_image_agent_run_count(
        _Pool(connection), account_id=uuid4(), report_id=uuid4(),
    )
    assert count == 2
    sql = connection.statements[0][0]
    assert "'queued', 'running'" in sql
    assert "layout_asset" in sql


@pytest.mark.asyncio
async def test_never_enqueued_image_agent_binding_ids_requires_description_and_no_live_run() -> None:
    """只找说明已填、且没有有效运行（无 run 或 superseded）的活跃排版素材。"""

    binding_id = uuid4()
    connection = _Connection([{"binding_id": binding_id}])
    result = await pipeline_dal.never_enqueued_image_agent_binding_ids(
        _Pool(connection), account_id=uuid4(), report_id=uuid4(),
    )
    assert result == (binding_id,)
    sql = connection.statements[0][0]
    assert "layout_asset" in sql
    assert "btrim(declaration.description) <> ''" in sql
    assert "current.status is null or current.status = 'superseded'" in sql


@pytest.mark.asyncio
async def test_material_pipeline_status_counts_image_runs_in_flight() -> None:
    connection = _Connection(
        [
            {
                "file_queued_or_running": 0,
                "image_queued_or_running": 1,
                "mapping_queued_or_running": 0,
                "file_needs_attention": 0,
                "mapping_needs_attention": 0,
                "file_failed": 0,
                "mapping_failed": 0,
            }
        ]
    )
    status = await pipeline_dal.material_pipeline_status(
        _Pool(connection), account_id=uuid4(), report_id=uuid4(),
    )
    assert status.image_queued_or_running == 1
    assert "from image_agent_runs" in connection.statements[0][0]


@pytest.mark.asyncio
async def test_promote_layout_asset_upserts_and_preserves_user_caption() -> None:
    connection = _Connection([{"id": uuid4()}])
    asset_id = await layout_asset_dal.promote_layout_asset(
        _Pool(connection), report_id=uuid4(), account_id=uuid4(),
        material_source_id=uuid4(), caption="ISO 14001 认证证书", alt_text="证书图片",
        width_px=800, height_px=600, category="certificate_or_award",
        placement_scope_id="report-area:company_intro", fingerprint="d" * 64,
    )
    assert asset_id is not None
    sql, args = connection.statements[0]
    assert "insert into evidence_assets" in sql
    assert "on conflict (report_id, material_source_id) do update" in sql
    assert "caption_source = 'agent'" in sql
    assert "intended_use" not in sql or "'layout_asset'" in sql
    # 识别类别随每次重跑覆盖写入,只用于素材归档与人工核对,不驱动生成分支。
    assert "category = excluded.category" in sql
    assert "certificate_or_award" in args
    assert "structured_chart" not in sql
    assert "render_preference" not in sql


def _layout_asset_row(**overrides):
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid4(), "material_source_id": uuid4(),
        "placement_scope_id": "report-area:governance", "category": "other",
        "caption": "组织架构图", "caption_source": "agent", "alt_text": "组织架构图替代文本",
        "certificate_fact": None,
        "version": 2, "fingerprint": "e" * 64, "width_px": 1200, "height_px": 800,
        "created_at": now, "updated_at": now, "binding_created_at": now,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_current_layout_asset_records_project_category() -> None:
    connection = _Connection([_layout_asset_row(), _layout_asset_row(category=None)])
    records = await layout_asset_dal.current_layout_asset_records(
        _Pool(connection), uuid4(),
    )
    assert [record.category for record in records] == ["other", None]
    sql = connection.statements[0][0]
    assert "asset.category" in sql
    assert "render_preference" not in sql
    assert "structured_chart" not in sql


@pytest.mark.asyncio
async def test_list_layout_assets_for_report_projects_category() -> None:
    connection = _Connection([_layout_asset_row(category="photo")])
    records = await layout_asset_dal.list_layout_assets_for_report(
        _Pool(connection), uuid4(),
    )
    assert records[0].category == "photo"
    assert "category" in connection.statements[0][0]


@pytest.mark.asyncio
async def test_update_layout_asset_caption_marks_source_as_user() -> None:
    connection = _Connection()
    await layout_asset_dal.update_layout_asset_caption(
        _Pool(connection), report_id=uuid4(), asset_id=uuid4(), caption="用户改写的题注",
    )
    sql, args = connection.statements[0]
    assert "caption_source = 'user'" in sql
    assert "用户改写的题注" in args


# ---------------------------------------------------------------------------
# 单页 PDF 准入
# ---------------------------------------------------------------------------


def _layout_asset_policy():
    return MaterialWorkspaceService.report_file_ingress_policy(SSE_PACKAGE)


def test_single_page_pdf_layout_asset_is_admitted() -> None:
    from sustainability_desk.material.intake.files import validate_material_file

    validated = validate_material_file(
        filename="poster.pdf", content_type="application/pdf", data=_single_page_pdf_bytes(),
    )
    declaration = UserFileDeclaration(
        description="", role="layout_asset", topic_tags=["comprehensive"], asset_title="海报",
    )
    MaterialWorkspaceService.validate_report_file_declaration_for_policy(
        declaration, validated, _layout_asset_policy(),
    )


def test_multi_page_pdf_layout_asset_is_rejected_with_page_count_in_message() -> None:
    from sustainability_desk.material.intake.files import validate_material_file

    validated = validate_material_file(
        filename="deck.pdf", content_type="application/pdf", data=_multi_page_pdf_bytes(2),
    )
    declaration = UserFileDeclaration(
        description="", role="layout_asset", topic_tags=["comprehensive"], asset_title="画册",
    )
    with pytest.raises(MaterialRequestError, match="仅接受单页 PDF（当前 2 页）"):
        MaterialWorkspaceService.validate_report_file_declaration_for_policy(
            declaration, validated, _layout_asset_policy(),
        )


def test_layout_asset_pdf_max_pages_constant_is_one() -> None:
    assert LAYOUT_ASSET_PDF_MAX_PAGES == 1
