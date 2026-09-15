# ABOUTME: 资料工作区应用服务的纯投影与授权测试，锁定 stale、题型控件和内部字段隔离。
# ABOUTME: 不连接数据库、Storage 或模型；原子数据库路径由迁移与集成测试另行覆盖。
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from io import BytesIO

import asyncpg
import pytest
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter

import sustainability_desk.api.material_router as material_router
import sustainability_desk.material.workspace as material_workspace
from sustainability_desk.api.auth import AuthenticatedUser
from sustainability_desk.material.input_adapter import LightweightReportInputAdapter
from sustainability_desk.material.intake.parsers import MaterialParseError
from sustainability_desk.material.intake.models import (
    DocxParagraphLocator,
    EvidenceRef,
    InputProposal,
    MaterialFactClaim,
    MaterialFactClaimDraft,
    MaterialIngressDecision,
    MaterialProcessingError,
    MaterialSource,
    MaterialSourceDeletionTarget,
    MaterialSnapshot,
    MaterialWorkspace,
    NormalizedMaterial,
    ProcessingStep,
    MaterialSourceReviewDecision,
    ReportMaterialBinding,
    TextFragment,
    UserFileDeclaration,
    UserFileDeclarationRevision,
    ValidatedMaterialFile,
    WorkspaceState,
)
from sustainability_desk.material.workspace import (
    OUTSIDE_SCOPE_MATERIAL_NOTICE,
    MaterialWorkspaceService,
    REPORT_FILE_MAX_COUNT,
    active_binding_fingerprint,
    pending_file_description_count,
)
from sustainability_desk.material.workspace import MaterialAccessDeniedError
from sustainability_desk.material.workspace import MaterialConflictError
from sustainability_desk.material.workspace import MaterialRequestError
from sustainability_desk.material.workspace import MaterialServiceUnavailableError
from sustainability_desk.material.intake.storage import MaterialStorageError
from sustainability_desk.persistence import material_intake as material_dal
from knowledge_package_fixtures import SSE_PACKAGE


def _service() -> MaterialWorkspaceService:
    return MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset({"climate_change"}),
    )


class _PrimaryStorage:
    """资料主存储的内存替身，记录双副本生命周期而不暴露对象路径到投影。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def object_path(account_id, workspace_id, source_id, kind: str) -> str:
        return f"{account_id}/{workspace_id}/{source_id}.{kind}"

    async def upload(self, object_path: str, data: bytes, media_type: str) -> None:
        self.calls.append(("upload", object_path))

    async def delete(self, object_path: str) -> None:
        self.calls.append(("delete", object_path))


@pytest.mark.asyncio
async def test_report_file_remove_and_restore_only_mutate_binding(monkeypatch) -> None:
    """remove/restore 退化为纯状态变更；调度权全部收敛到 confirm，不再各自触发入队。"""

    primary = _PrimaryStorage()
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
        storage=primary,  # type: ignore[arg-type]
    )
    workspace_id = uuid4()
    binding_id = uuid4()
    operations: list[tuple[str, object]] = []

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def remove(*_args, **kwargs):
        operations.append(("remove", kwargs))

    async def restore(*_args, **kwargs):
        operations.append(("restore", kwargs))

    async def projection():
        return {"report_id": str(service.report_id), "active_file_count": 0}

    async def schedule_file_agent(**_kwargs):
        operations.append(("schedule_file_agent", _kwargs))

    async def synchronize_mapping():
        operations.append(("synchronize_mapping", None))

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_report_file_intake", projection)
    monkeypatch.setattr(service, "_enqueue_file_agent", schedule_file_agent)
    monkeypatch.setattr(service, "_synchronize_mapping_runs", synchronize_mapping)
    monkeypatch.setattr(material_dal, "remove_report_material_binding", remove)
    monkeypatch.setattr(material_dal, "restore_report_material_binding", restore)

    await service.remove_report_file(binding_id)
    await service.restore_report_file(binding_id)

    assert [name for name, _payload in operations] == ["remove", "restore"]
    assert operations[1][1]["max_files_per_report"] == REPORT_FILE_MAX_COUNT
    assert primary.calls == []


def _fact(
    *,
    fact_id=None,
    status: str = "confirmed",
    confirmation_method: str | None = "user",
) -> MaterialFactClaim:
    proposal = _proposal_fact_evidence()
    return MaterialFactClaim.from_draft(
        MaterialFactClaimDraft(
            semantic_key="climate.q_training_activities",
            value="是",
            supplement="开展了年度气候培训。",
            rationale="制度第 3 页明确记录培训。",
            evidence_refs=[proposal],
        ),
        status=status,
        confirmation_method=confirmation_method,
    ).model_copy(update={"fact_id": fact_id or uuid4()})


def _proposal_fact_evidence() -> EvidenceRef:
    return EvidenceRef(
        source_id=uuid4(),
        source_label="气候制度.docx",
        fragment_id="paragraph-3",
        locator=DocxParagraphLocator(paragraph_index=3),
    )


def _snapshot(proposal: InputProposal) -> MaterialSnapshot:
    service = _service()
    workspace = MaterialWorkspace(
        id=uuid4(),
        account_id=service.account_id,
        report_id=service.report_id,
        adapter_id=service.adapter.adapter_id,
        contract_version="contract-1",
        status="active",
        state=WorkspaceState(
            proposals=[proposal], facts=[_fact(fact_id=proposal.fact_claim_ids[0])]
        ),
        state_seq=4,
    )
    return MaterialSnapshot(workspace=workspace, sources=[])


def _attention_source(
    service: MaterialWorkspaceService,
    *,
    warnings: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> MaterialSource:
    source_id = uuid4()
    now = datetime.now(timezone.utc)
    return MaterialSource(
        id=source_id,
        workspace_id=uuid4(),
        account_id=service.account_id,
        source_label="复杂对象.docx",
        filename="复杂对象.docx",
        object_path="opaque/source.docx",
        kind="docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=10,
        sha256="a" * 64,
        status="needs_attention",
        normalized_material=NormalizedMaterial(
            source_id=source_id,
            source_label="复杂对象.docx",
            summary="已提取原生文本",
            fragments=[
                TextFragment(
                    fragment_id="paragraph-1",
                    text="相同文本",
                    locator=DocxParagraphLocator(paragraph_index=1),
                )
            ],
            processing_steps=[],
            warnings=warnings or [],
        ),
        processing_steps=[
            ProcessingStep(
                step="parsed",
                processor="deterministic",
                status="warning",
                parser="python-docx",
                input_fingerprint="a" * 64,
                output_fingerprint="b" * 64,
                quality_flags=quality_flags or [],
                started_at=now,
                completed_at=now,
            )
        ],
    )


def _workspace_for_service(service: MaterialWorkspaceService) -> MaterialWorkspace:
    return MaterialWorkspace(
        id=uuid4(),
        account_id=service.account_id,
        report_id=service.report_id,
        adapter_id=service.adapter.adapter_id,
        contract_version="contract-1",
        status="active",
        state=WorkspaceState(),
        state_seq=1,
    )


def _proposal(*, status: str = "accepted") -> InputProposal:
    adapter = LightweightReportInputAdapter(SSE_PACKAGE)
    target = "climate.q_training_activities"
    fact_id = uuid4()
    return InputProposal(
        target_handle=target,
        proposed_answer="是",
        supplement="开展了年度气候培训。",
        rationale="制度第 3 页明确记录培训。",
        evidence_refs=[_proposal_fact_evidence()],
        fact_claim_ids=[fact_id],
        status=status,
        target_fingerprint=adapter.target_fingerprint(target),
        current_value_fingerprint=adapter.fingerprint(None, None),
        proposed_value_fingerprint=adapter.fingerprint("是", "开展了年度气候培训。"),
    )


def test_snapshot_projects_typed_target_and_never_exposes_internal_paths() -> None:
    service = _service()
    projected = service._project_snapshot(_snapshot(_proposal()), {"intakeItems": {}})

    proposal = projected["proposals"][0]
    assert proposal["scope_id"] == "climate_change"
    assert proposal["target_kind"] == "single_select"
    assert proposal["target_options"] == ["是", "否", "不确定"]
    assert proposal["status"] == "accepted"
    assert proposal["basis"] == "material_evidence"
    assert proposal["evidence_refs"][0]["source_name"] == "气候制度.docx"
    assert proposal["fact_claim_ids"]
    assert projected["facts"][0]["status"] == "confirmed"
    assert projected["facts"][0]["basis"] == "material_evidence"
    serialized = str(projected)
    assert "object_path" not in serialized
    assert "service_key" not in serialized


@pytest.mark.asyncio
async def test_existing_scope_summaries_does_not_create_workspace(
    monkeypatch,
) -> None:
    service = _service()

    async def no_workspace(*_args, **_kwargs):
        return None

    monkeypatch.setattr(material_dal, "get_workspace_by_report", no_workspace)

    assert await service.get_existing_scope_summaries() == []


def test_source_snapshot_is_slim_and_content_projection_is_explicit() -> None:
    service = _service()
    source = MaterialSource(
        id=uuid4(),
        workspace_id=uuid4(),
        account_id=service.account_id,
        source_label="制度.docx",
        filename="制度.docx",
        object_path="private/source.docx",
        kind="docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=100,
        sha256="f" * 64,
        status="ready",
        normalized_material=NormalizedMaterial(
            source_id=uuid4(),
            source_label="制度.docx",
            summary="制度摘要",
            fragments=[
                TextFragment(
                    fragment_id="paragraph-1",
                    text="内部制度正文",
                    locator=DocxParagraphLocator(paragraph_index=1),
                )
            ],
            processing_steps=[],
        ),
    )

    assert service._project_source(source)["normalized_material"] is None
    projected = service._project_source(source, include_content=True)
    assert projected["normalized_material"]["segments"][0]["text"] == "内部制度正文"


def test_parse_failure_is_manually_retryable_after_runtime_repair() -> None:
    service = _service()
    source = MaterialSource(
        id=uuid4(),
        workspace_id=uuid4(),
        account_id=service.account_id,
        source_label="影印资料.pdf",
        filename="影印资料.pdf",
        object_path="private/source.pdf",
        kind="pdf",
        media_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        status="failed",
        error=MaterialProcessingError(
            code="document_unreadable",
            failure_stage="parse",
            reason="本地 PDF 渲染器不可用",
            next_action="请安装渲染器后重试。",
        ),
    )

    assert service._project_source(source)["can_retry"] is True


@pytest.mark.asyncio
async def test_topic_primary_input_mode_is_report_scoped_and_keeps_other_modes(
    monkeypatch,
) -> None:
    service = _service()
    proposal = _proposal()
    snapshot = _snapshot(proposal)
    snapshot.workspace.state.topic_primary_input_modes["water_resources"] = "questions"
    committed: list[WorkspaceState] = []

    async def typed_snapshot():
        return snapshot

    async def commit(**kwargs):
        committed.append(kwargs["state"])
        return snapshot.workspace.state_seq + 1

    async def projected_snapshot():
        return {"topic_primary_input_modes": committed[-1].topic_primary_input_modes}

    monkeypatch.setattr(service, "_typed_snapshot", typed_snapshot)
    monkeypatch.setattr(service, "_commit_workspace_mutation", commit)
    monkeypatch.setattr(service, "get_snapshot", projected_snapshot)

    result = await service.update_topic_primary_input_mode(
        "climate_change",
        primary_input_mode="materials",
        base_workspace_state_seq=4,
    )

    assert result["topic_primary_input_modes"] == {
        "water_resources": "questions",
        "climate_change": "materials",
    }
    with pytest.raises(MaterialAccessDeniedError):
        await service.update_topic_primary_input_mode(
            "not_allowed",
            primary_input_mode="questions",
            base_workspace_state_seq=4,
        )


@pytest.mark.asyncio
async def test_report_primary_input_mode_writes_report_state_not_workspace(
    monkeypatch,
) -> None:
    """报告级填报方式落报告状态：生成闸与导出闸必须读同一侧事实。

    落在资料工作区会让导出闸读不到它（诊断闸从不依赖资料工作区），
    进而出现"生成得了却导不出"。
    """
    from dataclasses import dataclass
    from sustainability_desk.contract.stored_report_state import StoredReportStateV4
    from sustainability_desk.persistence import reports as reports_dal

    service = _service()
    written: list[dict] = []

    @dataclass
    class _ReportState:
        state: dict
        state_seq: int

    async def get_state(_pool, _account_id, _report_id):
        return _ReportState(state={"version": 4, "fields": {}}, state_seq=4)

    async def put_state(_pool, _account_id, _report_id, state, base_seq, **_kwargs):
        assert base_seq == 4
        written.append(state)
        return base_seq + 1

    async def projected_snapshot():
        return {"report_primary_input_mode": written[-1]["meta"]["primaryInputMode"]}

    monkeypatch.setattr(reports_dal, "get_state", get_state)
    monkeypatch.setattr(reports_dal, "put_state", put_state)
    monkeypatch.setattr(service, "get_snapshot", projected_snapshot)

    result = await service.update_report_primary_input_mode(
        primary_input_mode="questions",
        base_report_state_seq=4,
    )

    assert result["report_primary_input_mode"] == "questions"
    # 只改编排状态，不触碰任何已填输入。
    assert StoredReportStateV4.model_validate(written[-1]).fields == {}

    with pytest.raises(MaterialConflictError):
        await service.update_report_primary_input_mode(
            primary_input_mode="materials",
            base_report_state_seq=3,
        )


def test_snapshot_marks_applied_proposal_stale_after_later_report_edit() -> None:
    service = _service()
    projected = service._project_snapshot(
        _snapshot(_proposal(status="applied")),
        {
            "intakeItems": {
                "climate.q_training_activities": {
                    "answer": "否",
                    "supplement": "用户后来直接修改。",
                }
            }
        },
    )

    proposal = projected["proposals"][0]
    assert proposal["status"] == "stale"
    assert proposal["stale_reason"] == "用户后续修改"


def test_processing_router_uses_only_deterministic_document_parsers() -> None:
    blank_pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(blank_pdf)

    local_step = MaterialWorkspaceService._route_source(
        "docx", "a" * 64, b"ignored"
    )
    deferred_step = MaterialWorkspaceService._route_source(
        "pdf", "b" * 64, blank_pdf.getvalue()
    )
    assert local_step.route == "native_docx"
    assert deferred_step.route == "native_pdf_text"
    with pytest.raises(MaterialParseError, match="排版素材"):
        MaterialWorkspaceService._route_source(
            "image", "c" * 64, b"ignored"
        )


@pytest.mark.asyncio
async def test_delete_can_retry_after_storage_succeeds_but_database_sync_fails(
    monkeypatch,
) -> None:
    service = _service()
    workspace_id = uuid4()
    source_id = uuid4()
    source = MaterialSource(
        id=source_id,
        workspace_id=workspace_id,
        account_id=service.account_id,
        source_label="待删除资料.docx",
        filename="待删除资料.docx",
        object_path="private/source.docx",
        kind="docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=100,
        sha256="d" * 64,
        status="ready",
    )

    class Storage:
        calls = 0

        async def delete(self, object_path: str) -> None:
            assert object_path == source.object_path
            self.calls += 1
            if self.calls > 1:
                raise MaterialStorageError("HTTP 404")

    storage = Storage()
    service._storage = storage  # type: ignore[assignment]

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def get_source_deletion_target(*_args, **_kwargs):
        return MaterialSourceDeletionTarget(
            object_path=source.object_path,
            status=source.status,
        )

    delete_attempts = 0

    async def delete(*_args, **_kwargs):
        nonlocal delete_attempts
        delete_attempts += 1
        if delete_attempts == 1:
            raise asyncpg.PostgresConnectionError("temporary database failure")

    async def snapshot():
        return {"id": str(workspace_id), "sources": []}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_snapshot", snapshot)
    monkeypatch.setattr(
        material_dal,
        "get_source_deletion_target",
        get_source_deletion_target,
    )
    monkeypatch.setattr(material_dal, "delete", delete)

    with pytest.raises(MaterialServiceUnavailableError, match="请再次删除"):
        await service.delete_source(source_id)

    assert await service.delete_source(source_id) == {
        "id": str(workspace_id),
        "sources": [],
    }
    assert storage.calls == 2
    assert delete_attempts == 2


@dataclass
class _Summary:
    report_profile_id: str = "sse_zh_hans@1"
    created_under_profile_id: str = "local_single_user@1"
    contract_version: str = "contract-1"
    data_classification: str = "synthetic"


class _Context:
    account_id = uuid4()
    profile_id = "local_single_user@1"


@pytest.mark.asyncio
async def test_authorized_service_denies_when_report_capability_is_disabled(
    monkeypatch,
) -> None:
    async def context(*_args):
        return _Context()

    async def summary(*_args):
        return _Summary()

    monkeypatch.setattr(material_router, "get_account_context", context)
    monkeypatch.setattr(material_router.reports_dal, "get_report_summary", summary)
    monkeypatch.setattr(
        material_router,
        "report_capabilities",
        lambda *_args, **_kwargs: {
            "material_agent_enabled": False,
            "allowed_report_section_ids": [],
        },
    )

    with pytest.raises(HTTPException) as raised:
        await material_router.authorized_material_service(
            uuid4(),
            AuthenticatedUser(subject=uuid4(), email=None),
            object(),  # type: ignore[arg-type]
        )
    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_batch_reuses_duplicate_source_and_audits_all_decisions(
    monkeypatch,
) -> None:
    primary = _PrimaryStorage()
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
        storage=primary,  # type: ignore[arg-type]
    )
    workspace_id = uuid4()
    reused_source_id = uuid4()
    recorded_decisions: list[MaterialIngressDecision] = []
    calls = 0

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    def validated(*_args, filename: str, **_kwargs):
        if filename == "rejected.docx":
            raise material_workspace.MaterialFileError("文件签名不匹配")
        digest = "a" * 64 if filename == "accepted.docx" else "b" * 64
        return ValidatedMaterialFile(
            filename=filename,
            kind="docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=4,
            sha256=digest,
        )

    async def reserve(*_args, **kwargs):
        nonlocal calls
        calls += 1
        if kwargs["file"].sha256 == "b" * 64:
            raise material_dal.MaterialDuplicateSourceError("b" * 64)
        return MaterialSource(
            id=uuid4(),
            workspace_id=workspace_id,
            account_id=service.account_id,
            source_label=kwargs["source_label"],
            filename=kwargs["file"].filename,
            object_path=kwargs["object_path"],
            kind="docx",
            media_type=kwargs["file"].media_type,
            size_bytes=4,
            sha256=kwargs["file"].sha256,
            status="uploading",
        )

    async def existing(*_args, **_kwargs):
        return MaterialSource(
            id=reused_source_id,
            workspace_id=workspace_id,
            account_id=service.account_id,
            source_label="既有资料",
            filename="existing.docx",
            object_path="opaque/existing.docx",
            kind="docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=4,
            sha256="b" * 64,
            status="ready",
            has_normalized_material=True,
            normalized_fragment_count=3,
        )

    async def finalized(*_args, **kwargs):
        recorded_decisions.append(kwargs["ingress_decision"])

    async def reuse(*_args, **kwargs):
        recorded_decisions.append(kwargs["decision"])
        return await existing()

    async def record(*_args, **kwargs):
        recorded_decisions.extend(kwargs["decisions"])

    async def snapshot():
        return {
            "sources": [],
            "ingress_receipts": [
                service._project_ingress_receipt(decision, {})
                for decision in recorded_decisions
            ],
        }

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_snapshot", snapshot)
    monkeypatch.setattr(material_workspace, "validate_material_file", validated)
    monkeypatch.setattr(material_dal, "reserve_source_upload", reserve)
    monkeypatch.setattr(material_dal, "get_active_source_by_sha256", existing)
    monkeypatch.setattr(material_dal, "reuse_source_and_record_ingress", reuse)
    monkeypatch.setattr(material_dal, "finalize_source_upload", finalized)
    monkeypatch.setattr(material_dal, "record_ingress_decisions", record)

    result = await service.upload_sources(
        [
            UploadFile(filename="accepted.docx", file=BytesIO(b"data")),
            UploadFile(filename="duplicate.docx", file=BytesIO(b"data")),
            UploadFile(filename="rejected.docx", file=BytesIO(b"data")),
        ],
        scope_kind="profile",
        report_section_ids=(),
    )

    assert calls == 2
    assert {item.status for item in recorded_decisions} == {
        "accepted",
        "reused",
        "rejected",
    }
    assert next(
        item for item in recorded_decisions if item.status == "reused"
    ).source_id == reused_source_id
    assert {item["status"] for item in result["ingress_receipts"]} == {
        "accepted",
        "reused",
        "rejected",
    }
    assert "upload_errors" not in result


@pytest.mark.asyncio
async def test_upload_batch_enforces_configured_max_in_flight(monkeypatch) -> None:
    service = _service()
    workspace_id = uuid4()
    active = 0
    max_active = 0

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def upload_one(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    async def snapshot():
        return {"sources": [], "ingress_receipts": []}

    monkeypatch.setenv("SUSTAINABILITY_DESK_MATERIAL_INGRESS_MAX_CONCURRENCY", "2")
    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "_upload_one", upload_one)
    monkeypatch.setattr(service, "get_snapshot", snapshot)

    await service.upload_sources(
        [
            UploadFile(filename=f"{index}.pdf", file=BytesIO(b"data"))
            for index in range(5)
        ],
        scope_kind="uncertain",
        report_section_ids=(),
    )

    assert max_active == 2


def test_ingress_decision_truncates_filename_and_never_persists_error_message() -> None:
    decision = MaterialWorkspaceService._ingress_decision(
        batch_id=uuid4(),
        filename=f"{'a' * 700}.pdf",
        status="rejected",
        reason_code="storage_failed",
        source_id=uuid4(),
        sha256="a" * 64,
    )

    assert len(decision.filename) == 500
    assert "message" not in decision.model_dump()
    assert "next_action" not in decision.model_dump()


@pytest.mark.asyncio
async def test_review_decision_binds_expected_normalized_material_fingerprint(
    monkeypatch,
) -> None:
    service = _service()
    workspace_id = uuid4()
    source_id = uuid4()
    now = datetime.now(timezone.utc)
    recorded = []
    source = MaterialSource(
        id=source_id,
        workspace_id=workspace_id,
        account_id=service.account_id,
        source_label="复杂对象.docx",
        filename="复杂对象.docx",
        object_path="opaque/source.docx",
        kind="docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=10,
        sha256="a" * 64,
        status="needs_attention",
        normalized_material=NormalizedMaterial(
            source_id=source_id,
            source_label="复杂对象.docx",
            summary="已提取原生文本",
            fragments=[],
            processing_steps=[],
        ),
        processing_steps=[
            ProcessingStep(
                step="parsed",
                processor="deterministic",
                status="warning",
                parser="python-docx",
                input_fingerprint="a" * 64,
                output_fingerprint="b" * 64,
                quality_flags=["embedded_objects_not_extracted"],
                started_at=now,
                completed_at=now,
            )
        ],
    )

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def record(*_args, **kwargs):
        recorded.append(kwargs["decision"])

    async def snapshot():
        return {"sources": []}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_snapshot", snapshot)
    monkeypatch.setattr(material_dal, "record_source_review_decision", record)

    expected_fingerprint = source.normalized_material_fingerprint
    assert expected_fingerprint is not None
    await service.record_source_review_decision(
        source_id,
        decision="reviewed_accepted",
        actor="operator",
        reason="已审查原生文本，内嵌对象不纳入本轮。",
        expected_normalized_material_fingerprint=expected_fingerprint,
    )

    assert recorded[0].source_id == source_id
    assert recorded[0].normalized_material_fingerprint == expected_fingerprint
    assert recorded[0].actor == "operator"


def test_review_decision_is_visible_after_refresh_and_stale_after_quality_change() -> None:
    service = _service()
    source = _attention_source(
        service,
        warnings=["内嵌对象未提取"],
        quality_flags=["embedded_objects_not_extracted"],
    )
    fingerprint = source.normalized_material_fingerprint
    assert fingerprint is not None
    resolution = MaterialSourceReviewDecision(
        source_id=source.id,
        normalized_material_fingerprint=fingerprint,
        decision="reviewed_accepted",
        actor="user",
        reason="已复核原生文本。",
    )
    snapshot = MaterialSnapshot(
        workspace=_workspace_for_service(service),
        sources=[source],
        review_decisions={source.id: resolution},
    )

    projected = service._project_snapshot(snapshot, {"intakeItems": {}})
    assert projected["sources"][0]["current_review_decision"] == {
        "decision": "reviewed_accepted",
        "reason": "已复核原生文本。",
    }
    assert projected["sources"][0]["normalized_material_fingerprint"] == fingerprint

    changed = _attention_source(
        service,
        warnings=["内嵌对象未提取", "表格样式发生变化"],
        quality_flags=["embedded_objects_not_extracted"],
    ).model_copy(
        update={
            "id": source.id,
            "workspace_id": source.workspace_id,
            "normalized_material": source.normalized_material.model_copy(
                update={"warnings": ["内嵌对象未提取", "表格样式发生变化"]}
            ),
        }
    )
    stale_snapshot = snapshot.model_copy(update={"sources": [changed]})
    stale_projected = service._project_snapshot(
        stale_snapshot,
        {"intakeItems": {}},
    )
    assert stale_projected["sources"][0]["current_review_decision"] is None
    assert changed.normalized_material_fingerprint != fingerprint


def test_operator_review_projection_hides_internal_identity_reason_and_fingerprint() -> None:
    service = _service()
    source = _attention_source(service, warnings=["内嵌对象未提取"])
    fingerprint = source.normalized_material_fingerprint
    assert fingerprint is not None
    decision = MaterialSourceReviewDecision(
        source_id=source.id,
        normalized_material_fingerprint=fingerprint,
        decision="reviewed_accepted",
        actor="operator",
        reason="内部验收备注不得返回客户。",
    )
    snapshot = MaterialSnapshot(
        workspace=_workspace_for_service(service),
        sources=[source],
        review_decisions={source.id: decision},
    )

    projected = service._project_snapshot(snapshot, {"intakeItems": {}})

    assert projected["sources"][0]["current_review_decision"] == {
        "decision": "reviewed_accepted",
        "reason": None,
    }
    assert not {
        "actor",
        "decision_id",
        "normalized_material_fingerprint",
    }.intersection(projected["sources"][0]["current_review_decision"])


def test_review_fingerprint_changes_when_only_quality_flag_changes() -> None:
    service = _service()
    first = _attention_source(service, quality_flags=["flag-a"])
    changed = first.model_copy(
        update={
            "processing_steps": [
                first.processing_steps[0].model_copy(
                    update={"quality_flags": ["flag-b"]}
                )
            ]
        }
    )

    assert first.normalized_material.render_text() == changed.normalized_material.render_text()
    assert first.normalized_material_fingerprint != changed.normalized_material_fingerprint


@pytest.mark.asyncio
async def test_review_decision_rejects_stale_ui_fingerprint(monkeypatch) -> None:
    service = _service()
    workspace_id = uuid4()
    stale_fingerprint = "a" * 64

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def stale(*_args, **_kwargs):
        raise material_dal.MaterialStateConflictError("资料解析结果已变化")

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(material_dal, "record_source_review_decision", stale)

    with pytest.raises(MaterialConflictError, match="资料状态已变化"):
        await service.record_source_review_decision(
            uuid4(),
            decision="reviewed_accepted",
            actor="user",
            reason="用户基于旧页面提交。",
            expected_normalized_material_fingerprint=stale_fingerprint,
        )


@pytest.mark.asyncio
async def test_operator_review_decision_is_persisted_as_human_event_actor() -> None:
    calls = []
    now = datetime.now(timezone.utc)
    source_id = uuid4()
    material = NormalizedMaterial(
        source_id=source_id,
        source_label="复杂对象.docx",
        summary="已提取",
        fragments=[],
        processing_steps=[],
    )
    step = ProcessingStep(
        step="parsed",
        processor="deterministic",
        status="warning",
        parser="python-docx",
        input_fingerprint="a" * 64,
        output_fingerprint="b" * 64,
        quality_flags=[],
        started_at=now,
        completed_at=now,
    )
    source = MaterialSource(
        id=source_id,
        workspace_id=uuid4(),
        account_id=uuid4(),
        source_label="复杂对象.docx",
        filename="复杂对象.docx",
        object_path="opaque/source.docx",
        kind="docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=10,
        sha256="a" * 64,
        status="needs_attention",
        normalized_material=material,
        processing_steps=[step],
    )
    expected_fingerprint = source.normalized_material_fingerprint
    assert expected_fingerprint is not None

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Connection:
        def transaction(self):
            return Transaction()

        async def fetchrow(self, *_args):
            return {
                "id": resolution.source_id,
                "workspace_id": workspace_id,
                "account_id": account_id,
                "source_label": "复杂对象.docx",
                "original_filename": "复杂对象.docx",
                "object_path": "opaque/source.docx",
                "kind": "docx",
                "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "size_bytes": 10,
                "sha256": "a" * 64,
                "status": "needs_attention",
                "scope_kind": "uncertain",
                "report_section_ids": [],
                "normalized_material": material.model_dump(mode="json"),
                "processing_steps": [step.model_dump(mode="json")],
                "error": None,
                "created_at": now,
                "updated_at": now,
            }

        async def execute(self, query, *args):
            calls.append((query, args))

    class Pool:
        def acquire(self):
            connection = Connection()

            class Acquire:
                async def __aenter__(self):
                    return connection

                async def __aexit__(self, *_args):
                    return False

            return Acquire()

    resolution = MaterialSourceReviewDecision(
        source_id=source_id,
        normalized_material_fingerprint=expected_fingerprint,
        decision="reviewed_accepted",
        actor="operator",
        reason="本地验收人工复核。",
    )
    workspace_id = uuid4()
    account_id = uuid4()

    await material_dal.record_source_review_decision(
        Pool(),  # type: ignore[arg-type]
        account_id=account_id,
        workspace_id=workspace_id,
        decision=resolution,
    )

    query, args = calls[0]
    assert "values ($1, $2, $3, 'source_review_decided', $4)" in query
    assert "insert into material_events" in query
    assert "update material_events" not in query and "delete from material_events" not in query
    assert args[-2] == "operator"
    assert "actor" not in args[-1]
    assert args[-1]["reason"] == "本地验收人工复核。"


@pytest.mark.asyncio
async def test_delete_mime_rejected_source_skips_nonexistent_storage_object(monkeypatch) -> None:
    primary = _PrimaryStorage()
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
        storage=primary,
    )
    workspace_id = uuid4()
    source_id = uuid4()
    deleted: list[bool] = []

    async def workspace():
        return SimpleNamespace(id=workspace_id)

    async def target(*_args, **_kwargs):
        return MaterialSourceDeletionTarget(
            object_path="account/workspace/source.docx",
            status="failed",
            error=MaterialProcessingError(
                code="source_upload_failed",
                failure_stage="storage",
                reason="Storage HTTP 400: invalid_mime_type",
                next_action="重新上传",
                retryable=False,
            ),
        )

    async def deleted_source(*_args, **_kwargs):
        deleted.append(True)

    async def snapshot():
        return {"sources": []}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_snapshot", snapshot)
    monkeypatch.setattr(material_dal, "get_source_deletion_target", target)
    monkeypatch.setattr(material_dal, "delete", deleted_source)

    assert await service.delete_source(source_id) == {"sources": []}
    assert primary.calls == []
    assert deleted == [True]


def _binding_row(
    *,
    binding_id,
    source_id,
    workspace_id,
    sha256_suffix: str,
    role: str = "semantic_material",
    description: str = "这是与 ESG 报告直接相关的文件说明。",
    asset_title: str | None = None,
    status: str = "active",
):
    now = datetime.now(timezone.utc)
    source = MaterialSource(
        id=source_id,
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
        source_id=source_id,
        status=status,
        created_at=now,
        updated_at=now,
        removed_at=now if status == "removed" else None,
    )
    declaration = UserFileDeclarationRevision(
        revision_id=uuid4(),
        binding_id=binding_id,
        revision=1,
        description=description,
        role=role,
        topic_tags=["climate_change"],
        asset_title=asset_title,
        declared_at=now,
    )
    return source, binding, declaration


def test_active_binding_fingerprint_ignores_removed_and_reacts_to_declaration_change() -> None:
    """确认指纹只覆盖 active binding；removed 不计入，declaration revision 变化会改变指纹。"""

    workspace_id = uuid4()
    active_binding_id, removed_binding_id = uuid4(), uuid4()
    active_source_id, removed_source_id = uuid4(), uuid4()

    active_row = _binding_row(
        binding_id=active_binding_id,
        source_id=active_source_id,
        workspace_id=workspace_id,
        sha256_suffix="a",
    )
    removed_row = _binding_row(
        binding_id=removed_binding_id,
        source_id=removed_source_id,
        workspace_id=workspace_id,
        sha256_suffix="b",
        status="removed",
    )

    baseline = active_binding_fingerprint([active_row, removed_row])
    only_active = active_binding_fingerprint([active_row])
    assert baseline == only_active, "removed binding 不参与指纹计算"

    changed_declaration_source, changed_declaration_binding, _old_declaration = active_row
    new_declaration = UserFileDeclarationRevision(
        revision_id=uuid4(),
        binding_id=active_binding_id,
        revision=2,
        description="修改后的说明，字数同样满足最少字数要求。",
        role="semantic_material",
        topic_tags=["climate_change"],
        asset_title=None,
        declared_at=datetime.now(timezone.utc),
    )
    changed_row = (changed_declaration_source, changed_declaration_binding, new_declaration)
    assert active_binding_fingerprint([changed_row]) != only_active, (
        "declaration revision 变化必须改变确认指纹"
    )
    assert active_binding_fingerprint([]) == active_binding_fingerprint([removed_row]), (
        "全部 removed 与空集合等价，指纹是固定值而非异常"
    )


@pytest.mark.asyncio
async def test_confirm_material_set_rejects_when_description_pending(monkeypatch) -> None:
    """说明未齐时确认必须 409，且不落指纹、不入队。"""

    workspace_id = uuid4()
    binding_id, source_id = uuid4(), uuid4()
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
    )
    row = _binding_row(
        binding_id=binding_id,
        source_id=source_id,
        workspace_id=workspace_id,
        sha256_suffix="c",
        description="",
    )
    recorded: list[object] = []

    async def workspace():
        return SimpleNamespace(
            id=workspace_id,
            material_set_confirmed_at=None,
            material_set_confirmed_fingerprint=None,
        )

    async def declarations(*_args, **_kwargs):
        return [row]

    async def record_confirmation(*_args, **_kwargs):
        recorded.append("recorded")

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(material_dal, "record_material_set_confirmation", record_confirmation)

    with pytest.raises(MaterialConflictError):
        await service.confirm_material_set()
    assert recorded == []


@pytest.mark.asyncio
async def test_confirm_material_set_enqueues_semantic_and_layout_bindings_then_synchronizes(
    monkeypatch,
) -> None:
    """确认落指纹后语义资料入 File Agent 队列、排版素材入 Image Agent 队列，removed 不入队，末尾统一同步 Mapping。"""

    workspace_id = uuid4()
    semantic_binding_id, layout_binding_id, removed_binding_id = (
        uuid4(),
        uuid4(),
        uuid4(),
    )
    semantic_source_id, layout_source_id, removed_source_id = (
        uuid4(),
        uuid4(),
        uuid4(),
    )
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
    )
    semantic_row = _binding_row(
        binding_id=semantic_binding_id,
        source_id=semantic_source_id,
        workspace_id=workspace_id,
        sha256_suffix="d",
        role="semantic_material",
    )
    layout_row = _binding_row(
        binding_id=layout_binding_id,
        source_id=layout_source_id,
        workspace_id=workspace_id,
        sha256_suffix="e",
        role="layout_asset",
        asset_title="企业获奖证书",
    )
    removed_row = _binding_row(
        binding_id=removed_binding_id,
        source_id=removed_source_id,
        workspace_id=workspace_id,
        sha256_suffix="f",
        status="removed",
    )
    operations: list[tuple[str, object]] = []

    async def workspace():
        return SimpleNamespace(
            id=workspace_id,
            material_set_confirmed_at=None,
            material_set_confirmed_fingerprint=None,
        )

    async def declarations(*_args, **_kwargs):
        return [semantic_row, layout_row, removed_row]

    async def record_confirmation(*_args, **kwargs):
        operations.append(("record_confirmation", kwargs["fingerprint"]))

    async def schedule_file_agent(**kwargs):
        operations.append(("enqueue_file_agent", kwargs["binding_id"]))

    async def schedule_image_agent(**kwargs):
        operations.append(("enqueue_image_agent", kwargs["binding_id"]))

    async def synchronize_mapping():
        operations.append(("synchronize_mapping", None))

    async def projection():
        return {"report_id": str(service.report_id)}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_report_file_intake", projection)
    monkeypatch.setattr(service, "_enqueue_file_agent", schedule_file_agent)
    monkeypatch.setattr(service, "_enqueue_image_agent", schedule_image_agent)
    monkeypatch.setattr(service, "_synchronize_mapping_runs", synchronize_mapping)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(material_dal, "record_material_set_confirmation", record_confirmation)

    await service.confirm_material_set()

    # 确认指纹必须在全部入队之后落库——它是"入队确实完成"的证据而非承诺。
    # 反序会在入队失败时留下不可自愈的脏状态。
    names = [name for name, _payload in operations]
    assert names == [
        "enqueue_file_agent",
        "enqueue_image_agent",
        "record_confirmation",
        "synchronize_mapping",
    ]
    assert operations[0][1] == semantic_binding_id
    assert operations[1][1] == layout_binding_id
    # 确认指纹只描述语义资料集：排版素材按单文件说明入队，不参与确认。
    expected_fingerprint = active_binding_fingerprint([semantic_row])
    assert operations[2][1] == expected_fingerprint
    assert active_binding_fingerprint([semantic_row, layout_row]) == expected_fingerprint


async def test_confirm_material_set_does_not_record_fingerprint_when_enqueue_fails(
    monkeypatch,
) -> None:
    """入队失败时不得落确认指纹——否则前端不再要求确认，报告永久卡在生成闸。

    回归：确认若先于入队落库，科技伦理范围违例让入队中途抛错，
    文件一份未入队却已标记确认，改回字段也无法自愈。
    """
    import pytest

    workspace_id = uuid4()
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
    )
    semantic_row = _binding_row(
        binding_id=uuid4(),
        source_id=uuid4(),
        workspace_id=workspace_id,
        sha256_suffix="d",
        role="semantic_material",
    )
    operations: list[tuple[str, object]] = []

    async def workspace():
        return SimpleNamespace(
            id=workspace_id,
            material_set_confirmed_at=None,
            material_set_confirmed_fingerprint=None,
        )

    async def declarations(*_args, **_kwargs):
        return [semantic_row]

    async def failing_enqueue_file_agent(**_kwargs):
        raise RuntimeError("装配报告失败")

    async def record_confirmation(*_args, **kwargs):
        operations.append(("record_confirmation", kwargs["fingerprint"]))

    async def synchronize_mapping():
        operations.append(("synchronize_mapping", None))

    async def projection():
        return {"report_id": str(service.report_id)}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "get_report_file_intake", projection)
    monkeypatch.setattr(service, "_enqueue_file_agent", failing_enqueue_file_agent)
    monkeypatch.setattr(service, "_synchronize_mapping_runs", synchronize_mapping)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(
        material_dal, "record_material_set_confirmation", record_confirmation
    )

    with pytest.raises(RuntimeError, match="装配报告失败"):
        await service.confirm_material_set()

    assert operations == []


def test_material_set_confirmation_status_recomputes_from_active_bindings_not_stored_flag() -> None:
    """确认状态由重算指纹与当前 active binding 集比对得出；已存储的确认列即使被直改也不被信任。

    等价于"数据库层直改确认列"的后门：workspace 行携带的 confirmed_fingerprint
    可以是任意值（包括被绕过服务层直接写入的陈旧值），状态机必须仍以当场重算为准。
    """

    workspace_id = uuid4()
    binding_id, source_id = uuid4(), uuid4()
    row = _binding_row(
        binding_id=binding_id,
        source_id=source_id,
        workspace_id=workspace_id,
        sha256_suffix="1",
    )
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
    )

    tampered_workspace = MaterialWorkspace(
        id=workspace_id,
        account_id=service.account_id,
        report_id=service.report_id,
        adapter_id="simplified-report-input@2",
        contract_version="contract-1",
        status="active",
        state=WorkspaceState(),
        state_seq=1,
        material_set_confirmed_at=datetime.now(timezone.utc),
        material_set_confirmed_fingerprint="0" * 64,  # 被后门直改的任意陈旧值
    )
    stale = service._material_set_confirmation_projection(
        workspace=tampered_workspace,
        sources=[row],
        pending_description_count=0,
    )
    assert stale["status"] == "required", "陈旧或被篡改的确认指纹必须判定为需要重新确认"

    matching_workspace = tampered_workspace.model_copy(
        update={"material_set_confirmed_fingerprint": active_binding_fingerprint([row])}
    )
    confirmed = service._material_set_confirmation_projection(
        workspace=matching_workspace,
        sources=[row],
        pending_description_count=0,
    )
    assert confirmed["status"] == "confirmed"


def test_pending_description_count_counts_semantic_and_layout_alike() -> None:
    """语义资料与排版素材缺说明同级计入生成门槛；removed 不计。"""

    workspace_id = uuid4()
    rows = [
        _binding_row(
            binding_id=uuid4(),
            source_id=uuid4(),
            workspace_id=workspace_id,
            sha256_suffix="a",
            description="",
        ),
        _binding_row(
            binding_id=uuid4(),
            source_id=uuid4(),
            workspace_id=workspace_id,
            sha256_suffix="b",
            role="layout_asset",
            description="",
            asset_title="",
        ),
        _binding_row(
            binding_id=uuid4(),
            source_id=uuid4(),
            workspace_id=workspace_id,
            sha256_suffix="c",
            description="这是一份完整的资料说明文本。",
        ),
        _binding_row(
            binding_id=uuid4(),
            source_id=uuid4(),
            workspace_id=workspace_id,
            sha256_suffix="d",
            description="",
            status="removed",
        ),
    ]
    assert pending_file_description_count(rows) == 2


def test_material_set_confirmation_not_required_when_only_layout_assets() -> None:
    """只有排版素材的报告不需要资料集确认：素材按单文件说明入队，不参与确认。"""

    service = _service()
    workspace_id = uuid4()
    layout_row = _binding_row(
        binding_id=uuid4(),
        source_id=uuid4(),
        workspace_id=workspace_id,
        sha256_suffix="e",
        role="layout_asset",
        asset_title="企业获奖证书",
    )
    workspace = MaterialWorkspace(
        id=workspace_id,
        account_id=service.account_id,
        report_id=service.report_id,
        adapter_id="simplified-report-input@2",
        contract_version="contract-1",
        status="active",
        state=WorkspaceState(),
        state_seq=1,
    )
    projection = service._material_set_confirmation_projection(
        workspace=workspace,
        sources=[layout_row],
        pending_description_count=0,
    )
    assert projection["status"] == "not_required"

    # 素材说明未填时仍停在 pending_description：缺说明先于"是否需要确认"判定。
    undescribed = service._material_set_confirmation_projection(
        workspace=workspace,
        sources=[layout_row],
        pending_description_count=1,
    )
    assert undescribed["status"] == "pending_description"


def _declaration_update_harness(
    monkeypatch,
    *,
    row,
) -> tuple[MaterialWorkspaceService, list[tuple[str, object]]]:
    """把 update_report_file_declaration 的持久化与入队替身接好，只留下分派逻辑。"""

    _source, binding, _declaration = row
    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
    )
    operations: list[tuple[str, object]] = []

    async def workspace():
        return SimpleNamespace(
            id=binding.workspace_id,
            material_set_confirmed_at=None,
            material_set_confirmed_fingerprint=None,
        )

    async def declarations(*_args, **_kwargs):
        return [row]

    async def persist(*_args, **kwargs):
        operations.append(("persist", kwargs["binding_id"]))

    async def enqueue_image_agent(**kwargs):
        operations.append(("enqueue_image_agent", kwargs["binding_id"]))

    async def autostart():
        operations.append(("autostart", None))
        return {"phase": "draft"}

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "_enqueue_image_agent", enqueue_image_agent)
    monkeypatch.setattr(service, "_autostart_material_processing", autostart)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(material_dal, "update_report_file_declaration", persist)
    return service, operations


@pytest.mark.asyncio
async def test_layout_description_save_enqueues_image_agent_before_autostart(
    monkeypatch,
) -> None:
    """素材说明保存成功即入队图片识别，且先于（不依赖）语义资料集的自动确认。"""

    binding_id = uuid4()
    row = _binding_row(
        binding_id=binding_id,
        source_id=uuid4(),
        workspace_id=uuid4(),
        sha256_suffix="f",
        role="layout_asset",
        description="",
        asset_title="",
    )
    service, operations = _declaration_update_harness(monkeypatch, row=row)

    result = await service.update_report_file_declaration(
        binding_id,
        declaration=UserFileDeclaration(
            description="这是用于报告展示的企业获奖证书图片资料。",
            role="layout_asset",
            topic_tags=["climate_change"],
            asset_title="企业获奖证书",
        ),
        expected_revision=1,
    )

    assert result == {"phase": "draft"}
    assert operations == [
        ("persist", binding_id),
        ("enqueue_image_agent", binding_id),
        ("autostart", None),
    ]


@pytest.mark.asyncio
async def test_layout_declaration_without_description_does_not_enqueue(
    monkeypatch,
) -> None:
    """说明仍为空的素材不具备入队条件：只保存声明，不触发图片识别。"""

    binding_id = uuid4()
    row = _binding_row(
        binding_id=binding_id,
        source_id=uuid4(),
        workspace_id=uuid4(),
        sha256_suffix="2",
        role="layout_asset",
        description="",
        asset_title="",
    )
    service, operations = _declaration_update_harness(monkeypatch, row=row)

    await service.update_report_file_declaration(
        binding_id,
        declaration=UserFileDeclaration(
            description="",
            role="layout_asset",
            topic_tags=["climate_change"],
            asset_title="企业获奖证书",
        ),
        expected_revision=1,
    )

    assert [name for name, _payload in operations] == ["persist", "autostart"]


@pytest.mark.asyncio
async def test_layout_image_enqueue_failure_keeps_saved_description(
    monkeypatch,
) -> None:
    """入队抛错只记日志；用户已保存的说明不得连带失败，仍返回当前投影。"""

    binding_id = uuid4()
    row = _binding_row(
        binding_id=binding_id,
        source_id=uuid4(),
        workspace_id=uuid4(),
        sha256_suffix="3",
        role="layout_asset",
        description="",
        asset_title="",
    )
    service, operations = _declaration_update_harness(monkeypatch, row=row)

    async def failing_enqueue(**_kwargs):
        raise RuntimeError("队列不可用")

    monkeypatch.setattr(service, "_enqueue_image_agent", failing_enqueue)

    result = await service.update_report_file_declaration(
        binding_id,
        declaration=UserFileDeclaration(
            description="这是用于报告展示的企业获奖证书图片资料。",
            role="layout_asset",
            topic_tags=["climate_change"],
            asset_title="企业获奖证书",
        ),
        expected_revision=1,
    )

    assert result == {"phase": "draft"}
    assert [name for name, _payload in operations] == ["persist", "autostart"]


@pytest.mark.asyncio
async def test_semantic_description_save_does_not_enqueue_image_agent(
    monkeypatch,
) -> None:
    """语义资料沿用自动确认路径，不直接入队图片识别。"""

    binding_id = uuid4()
    row = _binding_row(
        binding_id=binding_id,
        source_id=uuid4(),
        workspace_id=uuid4(),
        sha256_suffix="4",
        description="",
    )
    service, operations = _declaration_update_harness(monkeypatch, row=row)

    await service.update_report_file_declaration(
        binding_id,
        declaration=UserFileDeclaration(
            description="公司 2025 年能源管理制度及执行记录。",
            role="semantic_material",
            topic_tags=["climate_change"],
        ),
        expected_revision=1,
    )

    assert [name for name, _payload in operations] == ["persist", "autostart"]


@pytest.mark.asyncio
async def test_file_intake_phase_is_processing_while_only_layout_image_runs(
    monkeypatch,
) -> None:
    """零语义资料 + 一张素材识别中：无需确认（not_required）但阶段必须是 processing。"""

    from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
    from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal

    service = _service()
    workspace_id = uuid4()
    binding_id = uuid4()
    now = datetime.now(timezone.utc)
    source, binding, declaration = _binding_row(
        binding_id=binding_id,
        source_id=uuid4(),
        workspace_id=workspace_id,
        sha256_suffix="5",
        role="layout_asset",
        asset_title="企业获奖证书",
    )
    layout_row = (
        source.model_copy(update={"created_at": now, "updated_at": now}),
        binding,
        declaration,
    )

    async def workspace():
        return SimpleNamespace(
            id=workspace_id,
            material_set_confirmed_at=None,
            material_set_confirmed_fingerprint=None,
        )

    async def declarations(*_args, **_kwargs):
        return [layout_row]

    async def typed_snapshot(**_kwargs):
        return SimpleNamespace(sources=[], ingress_decisions=[])

    async def file_runs(*_args, **_kwargs):
        return ()

    async def image_runs(*_args, **_kwargs):
        return (
            SimpleNamespace(binding_id=binding_id, status="queued", updated_at=now),
        )

    async def layout_assets(*_args, **_kwargs):
        return ()

    async def no_snapshot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "_typed_snapshot", typed_snapshot)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(pipeline_dal, "list_current_file_agent_runs", file_runs)
    monkeypatch.setattr(pipeline_dal, "list_current_image_agent_runs", image_runs)
    monkeypatch.setattr(pipeline_dal, "latest_material_set_snapshot", no_snapshot)
    monkeypatch.setattr(layout_asset_dal, "list_layout_assets_for_report", layout_assets)

    file_intake = await service.get_report_file_intake()

    assert file_intake["material_set_confirmation"]["status"] == "not_required"
    assert file_intake["phase"] == "processing"

    async def finished_image_runs(*_args, **_kwargs):
        return (
            SimpleNamespace(binding_id=binding_id, status="succeeded", updated_at=now),
        )

    monkeypatch.setattr(pipeline_dal, "list_current_image_agent_runs", finished_image_runs)
    assert (await service.get_report_file_intake())["phase"] == "reviewed"


def _frozen_dossier(*, scope_id: str, relevance: str = "relevant"):
    from sustainability_desk.material.intake.file_agent_contract import (
        FileDossier,
        FileMaterial,
        FileSourceRevision,
        file_dossier_fingerprint,
    )

    source_revision = FileSourceRevision(source_id=uuid4(), source_sha256="c" * 64, declaration_revision=1)
    materials = (
        (FileMaterial(material_id=uuid4(), applicable_scope_ids=(scope_id,), content_markdown="资料内容。"),)
        if relevance == "relevant"
        else ()
    )
    return FileDossier(
        source_revision=source_revision,
        relevance=relevance,
        relevance_reason="理由。",
        materials=materials,
        dossier_fingerprint=file_dossier_fingerprint(
            source_revision=source_revision,
            relevance=relevance,
            relevance_reason="理由。",
            materials=materials,
            attention_items=(),
        ),
    )


@pytest.mark.asyncio
async def test_file_analysis_projects_report_scope_from_frozen_mapping_plan(monkeypatch) -> None:
    """相关资料是否进入本次报告以冻结 Mapping plan 为准：未路由到任何 scope 即范围外，附范围说明。"""

    from sustainability_desk.persistence import layout_evidence_assets as layout_asset_dal
    from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal

    service = _service()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)
    rows = {}
    dossiers = {
        "covered": _frozen_dossier(scope_id="report-section:climate_change"),
        "uncovered": _frozen_dossier(scope_id="report-section:water_resource_management"),
        "irrelevant": _frozen_dossier(scope_id="report-section:climate_change", relevance="not_relevant"),
    }
    for key in dossiers:
        binding_id = uuid4()
        source, binding, declaration = _binding_row(
            binding_id=binding_id, source_id=uuid4(), workspace_id=workspace_id, sha256_suffix="6",
        )
        rows[key] = (
            binding_id,
            (source.model_copy(update={"created_at": now, "updated_at": now}), binding, declaration),
        )

    async def workspace():
        return SimpleNamespace(
            id=workspace_id, material_set_confirmed_at=now, material_set_confirmed_fingerprint="x" * 64,
        )

    async def declarations(*_args, **_kwargs):
        return [row for _binding_id, row in rows.values()]

    async def typed_snapshot(**_kwargs):
        return SimpleNamespace(sources=[], ingress_decisions=[])

    async def file_runs(*_args, **_kwargs):
        return tuple(
            SimpleNamespace(binding_id=binding_id, status="succeeded", dossier=dossiers[key], updated_at=now)
            for key, (binding_id, _row) in rows.items()
        )

    async def image_runs(*_args, **_kwargs):
        return ()

    async def layout_assets(*_args, **_kwargs):
        return ()

    async def latest_snapshot(*_args, **_kwargs):
        return SimpleNamespace(snapshot=SimpleNamespace(
            members=[SimpleNamespace(dossier_id=dossier.dossier_id) for dossier in dossiers.values()],
            mapping_plan=SimpleNamespace(scopes=[
                SimpleNamespace(dossier_ids=(dossiers["covered"].dossier_id,)),
            ]),
        ))

    monkeypatch.setattr(service, "_workspace", workspace)
    monkeypatch.setattr(service, "_typed_snapshot", typed_snapshot)
    monkeypatch.setattr(material_dal, "list_report_file_declarations", declarations)
    monkeypatch.setattr(pipeline_dal, "list_current_file_agent_runs", file_runs)
    monkeypatch.setattr(pipeline_dal, "list_current_image_agent_runs", image_runs)
    monkeypatch.setattr(pipeline_dal, "latest_material_set_snapshot", latest_snapshot)
    monkeypatch.setattr(layout_asset_dal, "list_layout_assets_for_report", layout_assets)

    file_intake = await service.get_report_file_intake()
    projected = {
        key: next(
            item["file_analysis"]["dossier"]
            for item in file_intake["sources"]
            if item["binding_id"] == str(binding_id)
        )
        for key, (binding_id, _row) in rows.items()
    }

    assert projected["covered"]["report_scope"] == "within_report"
    assert projected["covered"]["report_scope_notice"] is None
    assert projected["uncovered"]["report_scope"] == "outside_report"
    assert projected["uncovered"]["report_scope_notice"] == OUTSIDE_SCOPE_MATERIAL_NOTICE
    assert projected["irrelevant"]["report_scope"] is None
    assert projected["irrelevant"]["report_scope_notice"] is None
    from sustainability_desk.material.intake.public_models import ReportFileIntakeProjection

    ReportFileIntakeProjection.model_validate(file_intake)


@pytest.mark.asyncio
async def test_update_source_label_validates_before_touching_persistence() -> None:
    """文件名边界校验先于任何持久化访问;空白与超长直接拒绝。"""

    service = _service()
    with pytest.raises(MaterialRequestError, match="1-140"):
        await service.update_report_file_source_label(uuid4(), source_label="   ")
    with pytest.raises(MaterialRequestError, match="1-140"):
        await service.update_report_file_source_label(
            uuid4(), source_label="名" * 141
        )


@pytest.mark.asyncio
async def test_update_layout_caption_validates_before_touching_persistence() -> None:
    """题注边界校验先于资产归属检查;空白与超长直接拒绝。"""

    service = _service()
    with pytest.raises(MaterialRequestError, match="1-50"):
        await service.update_layout_asset_caption(uuid4(), caption="  ")
    with pytest.raises(MaterialRequestError, match="1-50"):
        await service.update_layout_asset_caption(uuid4(), caption="注" * 51)


def test_report_update_available_judgment() -> None:
    """「报告可更新」只在输入真实变化时为真：状态推进或资料快照与生成所用不一致；
    从未有资料快照且状态未变时不得恒真（纯直填账户不应一直显示「更新报告」）。"""

    from sustainability_desk.material.workspace import (
        report_update_available_since_last_success,
    )

    snapshot_id = uuid4()
    success = SimpleNamespace(
        result_report_state_seq=5,
        material_set_snapshot_id=snapshot_id,
    )

    # 从未成功生成过：无所谓「更新」。
    assert report_update_available_since_last_success(
        report_state_seq=9, latest_success=None, latest_snapshot_id=None
    ) is False
    # 输入未变：状态未推进且快照一致。
    assert report_update_available_since_last_success(
        report_state_seq=5, latest_success=success, latest_snapshot_id=snapshot_id
    ) is False
    # 报告状态推进。
    assert report_update_available_since_last_success(
        report_state_seq=6, latest_success=success, latest_snapshot_id=snapshot_id
    ) is True
    # 资料快照更换。
    assert report_update_available_since_last_success(
        report_state_seq=5, latest_success=success, latest_snapshot_id=uuid4()
    ) is True
    # 生成后资料被清空（从有到无）也算变化。
    assert report_update_available_since_last_success(
        report_state_seq=5, latest_success=success, latest_snapshot_id=None
    ) is True


@pytest.mark.asyncio
async def test_autostart_enqueues_when_descriptions_complete() -> None:
    """说明补齐即自动入队解析，用户无需再点一次「开始处理」。"""

    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
        storage=_PrimaryStorage(),  # type: ignore[arg-type]
    )
    calls: list[str] = []

    async def confirm():
        calls.append("confirm")
        return {"phase": "processing"}

    service.confirm_material_set = confirm  # type: ignore[method-assign]

    assert await service._autostart_material_processing() == {"phase": "processing"}
    assert calls == ["confirm"]


@pytest.mark.asyncio
async def test_autostart_stays_in_draft_when_descriptions_missing() -> None:
    """说明未补齐是正常分支：保持 draft 形态，不把用户已保存的说明连带失败。"""

    service = MaterialWorkspaceService(knowledge_package=SSE_PACKAGE, 
        pool=object(),  # type: ignore[arg-type]
        account_id=uuid4(),
        report_id=uuid4(),
        report_contract_version="contract-1",
        allowed_report_section_ids=frozenset(),
        storage=_PrimaryStorage(),  # type: ignore[arg-type]
    )

    async def confirm():
        raise MaterialConflictError("还有 1 份文件待补充说明，无法确认资料集")

    async def projection():
        return {"phase": "draft"}

    service.confirm_material_set = confirm  # type: ignore[method-assign]
    service.get_report_file_intake = projection  # type: ignore[method-assign]

    # 不抛异常、不丢保存结果，返回当前投影。
    assert await service._autostart_material_processing() == {"phase": "draft"}


def test_workspace_state_drops_retired_report_primary_input_mode() -> None:
    """存量 state JSON 仍带 report_primary_input_mode，必须能解析而不是 500。

    该字段已迁到 StoredReportStateV4.meta.primaryInputMode。StrictModel
    禁止额外字段，若不在入口丢弃，所有既有工作区的准备投影都会解析失败成 500，
    且单测因构造全新 state 而看不到（本用例补上这条现实形态）。
    """
    state = WorkspaceState.model_validate(
        {
            "version": 1,
            "report_primary_input_mode": None,
            "topic_primary_input_modes": {"climate_change": "questions"},
        }
    )
    assert not hasattr(state, "report_primary_input_mode")
    assert state.topic_primary_input_modes == {"climate_change": "questions"}

    # 带值的存量行同样只丢弃、不报错（真相已在报告状态上）。
    assert WorkspaceState.model_validate(
        {"version": 1, "report_primary_input_mode": "materials"}
    ).topic_primary_input_modes == {}
