# ABOUTME: 验证报告生成只消费冻结 FileMaterial 的选择结果，未路由 Block 固定走 context_only。
# ABOUTME: Mapping 缺覆盖、重复决定或快照外材料必须在模型调用前失败。
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sustainability_desk.material.intake.file_agent_contract import (
    FileDossier,
    FileMaterial,
    FileSourceRevision,
    file_dossier_fingerprint,
)
from sustainability_desk.material.intake.models import (
    MaterialSource,
    MaterialWorkspace,
    ReportMaterialBinding,
    UserFileDeclarationRevision,
    WorkspaceState,
)
from sustainability_desk.material.mapping.decisions import BlockMaterialDecision, ValidatedMappingResult
from sustainability_desk.material.mapping.snapshot import FrozenMappingPlan, MappingPlanScope
from sustainability_desk.contract.report_generation import delivery_docx_filename
from sustainability_desk.accounts.report_execution_scope import execution_scope_for_profile
from sustainability_desk.persistence import material_intake as material_dal
import sustainability_desk.material.agent_pipeline as material_agent_pipeline_service
import sustainability_desk.lightweight_report_generation as generation_service
from sustainability_desk.contract.report_generation import CreateReportGenerationRequest
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import reports as reports_dal
from sustainability_desk.lightweight_report_generation import (
    ReportGenerationInputNotReadyError,
    ReportGenerationMappingError,
    ReportGenerationServiceError,
    _ensure_generation_workspace,
    _mapping_evidence,
    _material_set_requires_confirmation,
    _reenqueue_missing_image_agent_runs,
    enqueue_report_generation,
    report_artifact_root,
)
from sustainability_desk.material.workspace import active_binding_fingerprint
from knowledge_package_fixtures import SSE_PACKAGE


def _dossier() -> FileDossier:
    revision = FileSourceRevision(source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1)
    material = FileMaterial(
        material_id=uuid4(),
        applicable_scope_ids=("report-section:climate",),
        content_markdown="董事会每年审议气候相关风险。",
    )
    return FileDossier(
        source_revision=revision,
        relevance="relevant",
        relevance_reason="气候治理资料。",
        materials=(material,),
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=revision,
            relevance="relevant",
            relevance_reason="气候治理资料。",
            materials=(material,),
            attention_items=(),
        ),
    )


def _plan(dossier: FileDossier, *block_ids: str) -> FrozenMappingPlan:
    return FrozenMappingPlan(
        candidate_dossier_ids=(dossier.dossier_id,),
        scopes=(
            MappingPlanScope(
                scope_id="report-section:climate",
                dossier_ids=(dossier.dossier_id,),
                block_ids=block_ids,
            ),
        ),
    )


def test_report_artifact_root_uses_private_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT", "/var/tmp/report-artifacts")
    assert report_artifact_root() == Path("/var/tmp/report-artifacts")
    monkeypatch.setenv("SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT", "artifacts")
    with pytest.raises(ReportGenerationServiceError, match="绝对路径"):
        report_artifact_root()


def test_delivery_docx_filename_uses_report_variants_and_china_date() -> None:
    generated_at = datetime(2026, 8, 1, 16, 30, tzinfo=timezone.utc)

    assert delivery_docx_filename(
        company_registered_name="晟原/精密电子股份有限公司",
        variant="正式稿",
        generated_at=generated_at,
    ) == "晟原 精密电子股份有限公司_正式稿_2026-08-02.docx"
    assert delivery_docx_filename(
        company_registered_name="晟原精密电子股份有限公司",
        variant="审阅稿",
        generated_at=generated_at,
    ) == "晟原精密电子股份有限公司_审阅稿_2026-08-02.docx"


def test_delivery_filename_variants_resolve_from_execution_scope_package() -> None:
    """交付文件名变体取自执行范围的知识包，不取自 StoredReportState。

    存储态不带 knowledgePackageId，误传即 AttributeError——且失败发生在全部块
    生成之后的 delivery.render，一整轮生成作废。三包各有自己的语言变体。
    """

    from sustainability_desk.contract.knowledge_packages import load_knowledge_package
    from sustainability_desk.export.format_profile import load_format_profile

    expected = {
        "sse_zh_hans": ("正式稿", "审阅稿"),
        "hkex_zh_hant": ("正式稿", "審閱稿"),
        "hkex_en": ("Final", "Review"),
    }
    for package_id, (word, review) in expected.items():
        package = load_knowledge_package(package_id)
        scope = execution_scope_for_profile(
            "local_single_user@1", knowledge_package=package
        )
        variants = load_format_profile(
            scope.knowledge_package
        ).labels.delivery_filename_variants
        assert (variants.word, variants.review) == (word, review), package_id




def test_mapping_evidence_exposes_only_selected_file_material() -> None:
    dossier = _dossier()
    material_id = dossier.materials[0].material_id
    result = ValidatedMappingResult(
        scope_id="report-section:climate",
        block_decisions=(
            BlockMaterialDecision(
                scope_id="report-section:climate",
                block_id="climate.governance",
                disposition="supported",
                material_ids=(material_id,),
                reason="资料直接支持。",
            ),
            BlockMaterialDecision(
                scope_id="report-section:climate",
                block_id="climate.training",
                disposition="context_only",
                material_ids=(),
                reason="资料未说明培训。",
            ),
        ),
    )

    mapped, selected, decisions = _mapping_evidence(
        expected_block_ids=("climate.governance", "climate.training", "other.block"),
        results=(result,),
        mapping_plan=_plan(dossier, "climate.governance", "climate.training"),
        dossiers=(dossier,),
    )

    assert mapped["climate.governance"].materials == dossier.materials
    assert mapped["climate.training"].materials == ()
    assert mapped["other.block"].file_routing_disposition == "no_applicable_file_dossier"
    assert selected == dossier.materials
    assert decisions == result.block_decisions


def test_mapping_evidence_rejects_missing_or_snapshot_external_material() -> None:
    dossier = _dossier()
    incomplete = ValidatedMappingResult(
        scope_id="report-section:climate",
        block_decisions=(
            BlockMaterialDecision(
                scope_id="report-section:climate",
                block_id="climate.governance",
                disposition="context_only",
                material_ids=(),
                reason="无资料。",
            ),
        ),
    )
    with pytest.raises(ReportGenerationMappingError, match="尚未完整覆盖"):
        _mapping_evidence(
            expected_block_ids=("climate.governance", "climate.training"),
            results=(incomplete,),
            mapping_plan=_plan(dossier, "climate.governance", "climate.training"),
            dossiers=(dossier,),
        )

    invalid = incomplete.model_copy(
        update={
            "block_decisions": (
                BlockMaterialDecision(
                    scope_id="report-section:climate",
                    block_id="climate.governance",
                    disposition="supported",
                    material_ids=(uuid4(),),
                    reason="错误材料。",
                ),
            )
        }
    )
    with pytest.raises(ReportGenerationMappingError, match="快照外 FileMaterial"):
        _mapping_evidence(
            expected_block_ids=("climate.governance",),
            results=(invalid,),
            mapping_plan=_plan(dossier, "climate.governance"),
            dossiers=(dossier,),
        )


def _material_binding_row(
    *,
    binding_id,
    sha256_suffix: str,
    status: str = "active",
    role: str = "semantic_material",
):
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    source = MaterialSource(
        id=uuid4(),
        workspace_id=workspace_id,
        account_id=uuid4(),
        source_label="policy.pdf",
        filename="policy.pdf",
        object_path="account/workspace/source.pdf",
        kind="pdf",
        media_type="application/pdf",
        size_bytes=10,
        sha256=(sha256_suffix * 64)[:64],
        status="ready",
    )
    binding = ReportMaterialBinding(
        binding_id=binding_id,
        workspace_id=workspace_id,
        source_id=source.id,
        status=status,
        created_at=now,
        updated_at=now,
        removed_at=now if status == "removed" else None,
    )
    declaration = UserFileDeclarationRevision(
        revision_id=uuid4(),
        binding_id=binding_id,
        revision=1,
        description="这是与 ESG 报告直接相关的文件说明。",
        role=role,
        topic_tags=["climate_change"],
        asset_title="企业获奖证书" if role == "layout_asset" else None,
        declared_at=now,
    )
    return source, binding, declaration


def _workspace(fingerprint: str | None) -> MaterialWorkspace:
    return MaterialWorkspace(
        id=uuid4(),
        account_id=uuid4(),
        report_id=uuid4(),
        adapter_id="simplified-report-input@2",
        contract_version="contract-1",
        status="active",
        state=WorkspaceState(),
        state_seq=1,
        material_set_confirmed_at=datetime.now(timezone.utc) if fingerprint else None,
        material_set_confirmed_fingerprint=fingerprint,
    )


def test_material_set_requires_confirmation_is_false_for_zero_files_and_pending_description() -> None:
    """零文件报告与说明未齐都不需要确认 blocker——前者是 optional，后者由缺说明 blocker 单独指出。"""

    row = _material_binding_row(binding_id=uuid4(), sha256_suffix="a")

    assert _material_set_requires_confirmation(
        existing_workspace=None,
        file_declarations=[],
        pending_file_description_count=0,
    ) is False

    assert _material_set_requires_confirmation(
        existing_workspace=_workspace(None),
        file_declarations=[row],
        pending_file_description_count=1,
    ) is False


def test_material_set_requires_confirmation_true_until_fingerprint_matches() -> None:
    """说明齐但确认指纹不匹配（含从未确认过）时需要确认；指纹匹配当前 active 集合后不再需要。"""

    row = _material_binding_row(binding_id=uuid4(), sha256_suffix="b")

    never_confirmed = _workspace(None)
    assert _material_set_requires_confirmation(
        existing_workspace=never_confirmed,
        file_declarations=[row],
        pending_file_description_count=0,
    ) is True

    stale_confirmation = _workspace("0" * 64)
    assert _material_set_requires_confirmation(
        existing_workspace=stale_confirmation,
        file_declarations=[row],
        pending_file_description_count=0,
    ) is True

    matching_confirmation = _workspace(active_binding_fingerprint([row]))
    assert _material_set_requires_confirmation(
        existing_workspace=matching_confirmation,
        file_declarations=[row],
        pending_file_description_count=0,
    ) is False


def test_material_set_requires_confirmation_is_false_when_only_layout_assets() -> None:
    """只有排版素材的报告不需要确认：素材按单文件说明入队，不参与资料集确认。"""

    layout_row = _material_binding_row(
        binding_id=uuid4(), sha256_suffix="c", role="layout_asset"
    )
    assert _material_set_requires_confirmation(
        existing_workspace=_workspace(None),
        file_declarations=[layout_row],
        pending_file_description_count=0,
    ) is False


def _state_without_topic_answers(primary_input_mode: str):
    from local_e2e_fixture import (
        load_local_e2e_fixture_recipe,
        synthesize_stored_report_state,
    )

    state = synthesize_stored_report_state(load_local_e2e_fixture_recipe())
    assert state.meta is not None
    return state.model_copy(
        update={
            "intakeItems": {
                key: value
                for key, value in state.intakeItems.items()
                if not key.startswith("climate.")
            },
            "meta": state.meta.model_copy(
                update={"primaryInputMode": primary_input_mode}
            ),
        }
    )


class _PassedPreparationGate(Exception):
    """哨兵：入队流程已越过准备门槛，进入工作区建立一步。"""


def _enqueue_generation_harness(
    monkeypatch: pytest.MonkeyPatch, *, state
) -> CreateReportGenerationRequest:
    """把入队流程到准备门槛为止的持久化读取替换掉，其后一步抛哨兵。"""

    async def current_scope(_pool, **_kwargs):
        return execution_scope_for_profile("local_single_user@1", knowledge_package=SSE_PACKAGE)

    async def snapshot(_pool, _account_id, _report_id):
        return SimpleNamespace(
            state_seq=1,
            state=state,
            report_profile_id="sse_zh_hans@1",
            contract_version="lightweight-report@4",
        )

    async def no_workspace(_pool, **_kwargs):
        return None

    async def passed_gate(_pool, **_kwargs):
        raise _PassedPreparationGate()

    monkeypatch.setattr(generation_service, "_current_generation_scope", current_scope)
    monkeypatch.setattr(reports_dal, "get_lightweight_v4_snapshot", snapshot)
    monkeypatch.setattr(material_dal, "get_workspace_by_report", no_workspace)
    monkeypatch.setattr(generation_service, "_ensure_generation_workspace", passed_gate)
    return CreateReportGenerationRequest(idempotency_key=uuid4(), base_report_state_seq=1)


@pytest.mark.asyncio
async def test_enqueue_never_blocks_on_unanswered_topic_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """入队门禁与准备中心、导出闸同一裁定：议题引导问题在任一填报路径都不阻断。"""

    for primary_input_mode in ("questions", "materials"):
        request = _enqueue_generation_harness(
            monkeypatch, state=_state_without_topic_answers(primary_input_mode)
        )
        with pytest.raises(_PassedPreparationGate):
            await enqueue_report_generation(
                object(), account_id=uuid4(), report_id=uuid4(), request=request
            )


@pytest.mark.asyncio
async def test_enqueue_reenqueues_never_enqueued_images_before_image_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """说明已填却从未入队的素材在图片软门禁之前补入队，再按进行中运行决定等待。"""

    request = _enqueue_generation_harness(
        monkeypatch, state=_state_without_topic_answers("materials")
    )
    binding_id = uuid4()
    calls: list[str] = []

    async def workspace_ready(_pool, **_kwargs):
        return uuid4()

    async def no_unfinished_files(_pool, **_kwargs):
        return pipeline_dal.UnfinishedFileAgentWork()

    async def never_enqueued(_pool, **_kwargs):
        calls.append("never_enqueued")
        return (binding_id,)

    async def reenqueue(_pool, **kwargs):
        calls.append("reenqueue")
        assert kwargs["binding_ids"] == (binding_id,)

    async def one_in_flight(_pool, **_kwargs):
        calls.append("image_gate")
        return 1

    monkeypatch.setattr(generation_service, "_ensure_generation_workspace", workspace_ready)
    monkeypatch.setattr(pipeline_dal, "unfinished_file_agent_work", no_unfinished_files)
    monkeypatch.setattr(
        pipeline_dal, "never_enqueued_image_agent_binding_ids", never_enqueued
    )
    monkeypatch.setattr(generation_service, "_reenqueue_missing_image_agent_runs", reenqueue)
    monkeypatch.setattr(pipeline_dal, "unfinished_image_agent_run_count", one_in_flight)

    with pytest.raises(ReportGenerationInputNotReadyError, match="素材图片识别仍在进行"):
        await enqueue_report_generation(
            object(), account_id=uuid4(), report_id=uuid4(), request=request
        )
    assert calls == ["never_enqueued", "reenqueue", "image_gate"]


@pytest.mark.asyncio
async def test_reenqueue_missing_image_agent_runs_is_idempotent_and_tolerates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补入队逐个 binding 进行；单个失败只记日志，不打断其余 binding。"""

    workspace_id = uuid4()
    failing, healthy = uuid4(), uuid4()
    enqueued: list[object] = []

    async def workspace(_pool, **_kwargs):
        return SimpleNamespace(id=workspace_id)

    async def enqueue(_pool, **kwargs):
        if kwargs["binding_id"] == failing:
            raise RuntimeError("队列不可用")
        enqueued.append(kwargs["binding_id"])
        assert kwargs["workspace_id"] == workspace_id

    monkeypatch.setattr(material_dal, "get_workspace_by_report", workspace)
    monkeypatch.setattr(
        material_agent_pipeline_service, "enqueue_image_agent_for_binding", enqueue
    )

    await _reenqueue_missing_image_agent_runs(
        object(),
        account_id=uuid4(),
        report_id=uuid4(),
        binding_ids=(failing, healthy),
    )
    assert enqueued == [healthy]


@pytest.mark.asyncio
async def test_generation_ensures_empty_report_material_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    account_id = uuid4()
    report_id = uuid4()
    workspace_id = uuid4()
    recorded: dict[str, object] = {}

    async def get_or_create_workspace(_pool, **kwargs):
        recorded.update(kwargs)
        return SimpleNamespace(id=workspace_id)

    monkeypatch.setattr(material_dal, "get_or_create_workspace", get_or_create_workspace)
    assert await _ensure_generation_workspace(
        object(), account_id=account_id, report_id=report_id, report_contract_version="lightweight-report@4"
    ) == workspace_id
    assert recorded["account_id"] == account_id
    assert recorded["report_id"] == report_id
