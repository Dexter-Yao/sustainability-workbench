# ABOUTME: 验证轻量版报告级生成 API 的异步合同、公共投影与客户交付物下载边界。
# ABOUTME: 内部审计 artifact 即使已经持久化，也不能出现在状态响应或客户下载路径中。
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sustainability_desk.api.app import app
from sustainability_desk.api.report_generation_router import (
    authorized_report_projection,
)
from sustainability_desk.contract.block_provenance import (
    BlockProvenanceEntry,
    ReportBlockProvenanceProjection,
)
from sustainability_desk.contract.report_generation import (
    CreateReportGenerationRequest,
    ReportArtifactProjection,
    ReportGenerationProjection,
)
from sustainability_desk.persistence import lightweight_report_generations as generations_dal
from sustainability_desk.report_projection import (
    ReportArtifactDownload,
    ReportGenerationArtifactNotFoundError,
    ReportGenerationNotFoundError,
    LightweightReportGenerationService,
)

REPORT_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000002")
WORD_ID = UUID("30000000-0000-0000-0000-000000000003")
CUSTOMER_REVIEW_ID = UUID("40000000-0000-0000-0000-000000000004")
INTERNAL_AUDIT_ID = UUID("50000000-0000-0000-0000-000000000005")
ACCOUNT_ID = UUID("60000000-0000-0000-0000-000000000006")
NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


class _UnusedEnqueuePort:
    async def enqueue(self, **_kwargs) -> UUID:
        raise AssertionError("测试不应调用生成命令端口")


class _ArtifactReader:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[str] = []

    async def read(self, storage_ref: str) -> bytes:
        self.calls.append(storage_ref)
        return self.content


def _run(
    *,
    status: str = "succeeded",
) -> generations_dal.ReportGenerationRunRecord:
    return generations_dal.ReportGenerationRunRecord(
        run_id=RUN_ID,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        material_set_snapshot_id=uuid4(),
        base_report_state_seq=1,
        input_fingerprint="a" * 64,
        idempotency_key=uuid4(),
        model_id="luna",
        status=status,
        expected_block_ids=("profile.overview", "climate.strategy"),
        block_results=({"blockId": "profile.overview"},),
        result_report_state_seq=2 if status == "succeeded" else None,
        result_revision_id=uuid4() if status == "succeeded" else None,
        failure_code=None,
        started_at=NOW,
    )


def _event() -> dict[str, object]:
    return {
        "event_type": "artifacts_ready",
        "user_message": "Word 报告和审阅说明已准备完成。",
        "current_object": None,
        "action_required": False,
        "created_at": NOW,
        "payload": None,
    }


def _block_event(
    *,
    block_id: str,
    display_label: str,
    completed: bool,
) -> dict[str, object]:
    return {
        "event_type": "block_completed" if completed else "block_started",
        "user_message": (
            f"已完成：{display_label}" if completed else f"正在生成：{display_label}"
        ),
        "current_object": display_label,
        "action_required": False,
        "created_at": NOW,
        "payload": {"blockId": block_id},
    }


def _artifact(
    *,
    artifact_id: UUID,
    kind: str,
    filename: str,
    content: bytes,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "kind": kind,
        "filename": filename,
        "media_type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
            if kind == "word"
            else "text/markdown"
        ),
        "content_fingerprint": sha256(content).hexdigest(),
        "storage_ref": f"private/{artifact_id}",
    }


def _service(reader: _ArtifactReader) -> LightweightReportGenerationService:
    return LightweightReportGenerationService(
        pool=object(),
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        workbench_enabled=True,
        enqueue_port=_UnusedEnqueuePort(),
        artifact_reader=reader,
    )


def test_public_artifact_contract_structurally_rejects_internal_audit() -> None:
    with pytest.raises(ValidationError):
        ReportArtifactProjection(
            artifact_id=INTERNAL_AUDIT_ID,
            kind="internal_audit",
            filename="internal.md",
            media_type="text/markdown",
            download_href=(
                f"/api/reports/{REPORT_ID}/generations/{RUN_ID}/artifacts/"
                f"{INTERNAL_AUDIT_ID}/download"
            ),
        )


async def test_status_projection_excludes_internal_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"artifact"
    artifacts = (
        _artifact(
            artifact_id=WORD_ID,
            kind="word",
            filename="report.docx",
            content=content,
        ),
        _artifact(
            artifact_id=CUSTOMER_REVIEW_ID,
            kind="review",
            filename="review.md",
            content=content,
        ),
        _artifact(
            artifact_id=INTERNAL_AUDIT_ID,
            kind="internal_audit",
            filename="internal.md",
            content=content,
        ),
    )

    async def get_generation(*_args, **_kwargs):
        return _run(), (_event(),), artifacts

    monkeypatch.setattr(generations_dal, "get_generation", get_generation)
    projection = await _service(_ArtifactReader(content)).get_generation(RUN_ID)

    assert [artifact.kind for artifact in projection.artifacts] == [
        "word",
        "review",
    ]
    assert "internal" not in projection.model_dump_json()


async def test_internal_audit_direct_download_is_not_found_without_storage_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"internal"

    async def get_generation(*_args, **_kwargs):
        return (
            _run(),
            (),
            (
                _artifact(
                    artifact_id=INTERNAL_AUDIT_ID,
                    kind="internal_audit",
                    filename="internal.md",
                    content=content,
                ),
            ),
        )

    monkeypatch.setattr(generations_dal, "get_generation", get_generation)
    reader = _ArtifactReader(content)

    with pytest.raises(
        ReportGenerationArtifactNotFoundError,
        match="报告交付物不存在",
    ):
        await _service(reader).download_artifact(
            run_id=RUN_ID,
            artifact_id=INTERNAL_AUDIT_ID,
        )

    assert reader.calls == []


class _ApiService:
    def __init__(self) -> None:
        self.requests: list[CreateReportGenerationRequest] = []

    async def create_generation(
        self,
        request: CreateReportGenerationRequest,
    ) -> ReportGenerationProjection:
        self.requests.append(request)
        return self._projection("queued")

    async def get_generation(
        self,
        run_id: UUID,
    ) -> ReportGenerationProjection:
        assert run_id == RUN_ID
        return self._projection("succeeded")

    async def get_block_provenance(self) -> ReportBlockProvenanceProjection:
        return ReportBlockProvenanceProjection(
            report_id=REPORT_ID,
            revision=1,
            generated_report_state_seq=2,
            generated_at=NOW,
            trace_availability="unavailable",
            blocks=(
                BlockProvenanceEntry(
                    block_id="profile.overview",
                    basis=("structured_input", "industry_disclosure_context"),
                    generation_outcome="ready",
                    material_disposition="no_decision",
                ),
            ),
        )

    async def download_artifact(
        self,
        *,
        run_id: UUID,
        artifact_id: UUID,
    ) -> ReportArtifactDownload:
        assert run_id == RUN_ID
        if artifact_id == INTERNAL_AUDIT_ID:
            raise ReportGenerationArtifactNotFoundError("报告交付物不存在")
        assert artifact_id == WORD_ID
        return ReportArtifactDownload(
            kind="word",
            filename="../企业报告\r\nX-Evil: yes.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=b"docx",
        )

    @staticmethod
    def _projection(status: str) -> ReportGenerationProjection:
        return ReportGenerationProjection(
            run_id=RUN_ID,
            report_id=REPORT_ID,
            status=status,
            base_report_state_seq=1,
            result_report_state_seq=2 if status == "succeeded" else None,
            completed_block_count=1 if status == "succeeded" else 0,
            total_block_count=1,
            summary="报告生成请求已接收。",
            events=(),
            artifacts=(),
            workbench_enabled=True,
        )


@pytest.fixture
def api_client() -> tuple[TestClient, _ApiService]:
    service = _ApiService()
    app.dependency_overrides[authorized_report_projection] = (
        lambda: service
    )
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.pop(
            authorized_report_projection,
            None,
        )


def test_report_generation_routes_create_poll_and_download(
    api_client: tuple[TestClient, _ApiService],
) -> None:
    client, service = api_client
    idempotency_key = uuid4()

    created = client.post(
        f"/api/reports/{REPORT_ID}/generations",
        json={
            "idempotency_key": str(idempotency_key),
            "base_report_state_seq": 1,
        },
    )
    polled = client.get(
        f"/api/reports/{REPORT_ID}/generations/{RUN_ID}"
    )
    downloaded = client.get(
        f"/api/reports/{REPORT_ID}/generations/{RUN_ID}"
        f"/artifacts/{WORD_ID}/download"
    )

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert service.requests[0].idempotency_key == idempotency_key
    assert polled.status_code == 200
    assert polled.json()["status"] == "succeeded"
    assert downloaded.status_code == 200
    assert downloaded.content == b"docx"
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    disposition = downloaded.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "../" not in disposition


def test_block_provenance_route_returns_latest_revision_projection(
    api_client: tuple[TestClient, _ApiService],
) -> None:
    client, _service = api_client
    response = client.get(
        f"/api/reports/{REPORT_ID}/generations/latest/block-provenance"
    )
    assert response.status_code == 200
    projection = ReportBlockProvenanceProjection.model_validate(response.json())
    assert projection.trace_availability == "unavailable"
    assert projection.blocks[0].block_id == "profile.overview"


def test_block_provenance_route_reports_not_generated_as_not_found(
    api_client: tuple[TestClient, _ApiService],
) -> None:
    client, service = api_client

    async def not_generated() -> ReportBlockProvenanceProjection:
        raise ReportGenerationNotFoundError("报告尚未成功生成")

    service.get_block_provenance = not_generated  # type: ignore[method-assign]
    response = client.get(
        f"/api/reports/{REPORT_ID}/generations/latest/block-provenance"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "报告尚未成功生成"}


def test_internal_audit_download_route_returns_not_found(
    api_client: tuple[TestClient, _ApiService],
) -> None:
    client, _service = api_client
    response = client.get(
        f"/api/reports/{REPORT_ID}/generations/{RUN_ID}"
        f"/artifacts/{INTERNAL_AUDIT_ID}/download"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "报告交付物不存在"}


def test_openapi_contains_report_generation_control_surface() -> None:
    paths = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert (
        "/api/reports/{report_id}/generations",
        "POST",
    ) in paths
    assert (
        "/api/reports/{report_id}/generations/{run_id}",
        "GET",
    ) in paths
    assert (
        "/api/reports/{report_id}/generations/latest/block-provenance",
        "GET",
    ) in paths
    assert (
        "/api/reports/{report_id}/generations/{run_id}/artifacts/"
        "{artifact_id}/download",
        "GET",
    ) in paths


@pytest.mark.asyncio
async def test_projection_passes_through_section_titles_and_counts_by_block_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归:current_object 曾被当 block_id 查表致全部置空;完成计数曾按标题去重,
    祖先回退致多块同名而系统性偏低、进度条卡住。"""
    events = (
        _block_event(block_id="profile.overview", display_label="公司介绍", completed=False),
        _block_event(block_id="profile.overview", display_label="公司介绍", completed=True),
        # 两个不同块共享同一祖先标题——须按 blockId 计 2,不按标题计 1。
        _block_event(block_id="climate.strategy", display_label="应对气候变化", completed=True),
        _block_event(block_id="climate.strategy_table", display_label="应对气候变化", completed=True),
    )

    async def get_generation(*_args, **_kwargs):
        return _run(), events, ()

    monkeypatch.setattr(generations_dal, "get_generation", get_generation)
    projection = await _service(_ArtifactReader(b"x")).get_generation(RUN_ID)

    assert projection.completed_block_count == 3
    assert projection.started_at == NOW
    assert [event.current_object for event in projection.events] == [
        "公司介绍",
        "公司介绍",
        "应对气候变化",
        "应对气候变化",
    ]
    assert projection.events[0].message == "正在生成：公司介绍"
    assert projection.events[1].message == "已完成：公司介绍"
