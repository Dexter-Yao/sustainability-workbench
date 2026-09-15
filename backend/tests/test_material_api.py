# ABOUTME: 资料工作区 HTTP 合同测试，锁定完整受保护端点与请求到服务层的类型化映射。
# ABOUTME: 所有用例使用内存服务替身，不连接数据库、Storage 或真实模型。
from __future__ import annotations

import json
from io import BytesIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from sustainability_desk.api.app import app
from sustainability_desk.api.material_router import authorized_material_service


class _MaterialService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.snapshot = {
            "id": str(uuid4()),
            "report_id": str(uuid4()),
            "adapter_id": "simplified-report-input@2",
            "contract_version": "test-contract",
            "state_seq": 1,
            "projection_seq": 1,
            "report_state_seq": 1,
            "sources": [],
            "messages": [],
            "clarifications": [],
            "proposals": [],
            "facts": [],
            "gaps": [],
            "topic_primary_input_modes": {},
            "scope_summaries": [],
        }
        self.file_intake = {
            "report_id": str(uuid4()),
            "projection_seq": 1,
            "policy": {
                "max_files_per_report": 30,
                "max_file_bytes": 10 * 1024 * 1024,
                "max_pdf_pages": 10,
                "description_min_chars": 10,
                "description_max_chars": 100,
                "asset_title_max_chars": 100,
                "semantic_material_kinds": ["pdf", "docx", "xlsx"],
                "layout_asset_kinds": ["png", "jpeg", "webp"],
                "semantic_material_extensions": [".pdf", ".docx", ".xlsx"],
                "layout_asset_extensions": [".png", ".jpg", ".jpeg", ".webp"],
                "topic_tags": [
                    {
                        "id": "comprehensive",
                        "label": "综合",
                        "kind": "auxiliary",
                    },
                    {
                        "id": "uncertain",
                        "label": "暂不确定",
                        "kind": "auxiliary",
                    },
                    {
                        "id": "climate_change",
                        "label": "气候变化",
                        "kind": "report_section",
                    },
                ],
            },
            "active_file_count": 0,
            "sources": [],
            "ingress_receipts": [],
            "material_set_confirmation": {
                "status": "not_required",
                "confirmed_at": None,
                "pending_description_count": 0,
            },
        }
        self.preparation = {
            "contract": "sustainability_desk.report_preparation.v1",
            "report_id": str(uuid4()),
            "report_state_seq": 1,
            "generation_eligible": False,
            "generation_blockers": [
                {
                    "target_handle": "field.company_registered_name",
                    "label": "公司注册名称",
                    "message": "请填写公司注册名称。",
                    "href": "/intake/info",
                }
            ],
            "areas": [
                {
                    "id": "report_identity",
                    "title": "企业及报告基本信息",
                    "href": "/intake/info",
                    "required_for_generation": True,
                    "status": "needs_input",
                    "summary": "还有 1 项最低信息需要填写。",
                    "action_label": "填写基本信息",
                },
                {
                    "id": "materiality",
                    "title": "议题重要性评分",
                    "href": "/intake/scoring",
                    "required_for_generation": False,
                    "status": "optional_empty",
                    "summary": "尚未填写；不会阻断轻量版生成。",
                    "action_label": "填写或导入",
                },
                {
                    "id": "quantitative_metrics",
                    "title": "ESG 定量信息",
                    "href": "/intake/metrics",
                    "required_for_generation": False,
                    "status": "optional_empty",
                    "summary": "尚未填写；不会阻断轻量版生成。",
                    "action_label": "填写或导入",
                },
                {
                    "id": "materials",
                    "title": "上传资料",
                    "href": "/materials",
                    "required_for_generation": False,
                    "status": "optional_empty",
                    "summary": "尚未上传文件；轻量版仍可继续生成。",
                    "action_label": "管理文件",
                },
            ],
            "report_update_available": False,
            "workbench_enabled": True,
        }

    async def get_report_preparation(self) -> dict:
        self.calls.append(("get_report_preparation", None))
        return self.preparation

    async def get_report_file_intake(self) -> dict:
        self.calls.append(("get_report_file_intake", None))
        return self.file_intake

    async def upload_report_files(self, files, *, declarations) -> dict:
        self.calls.append(
            (
                "upload_report_files",
                ([item.filename for item in files], declarations),
            )
        )
        return self.file_intake

    async def update_report_file_declaration(
        self, binding_id: UUID, *, declaration, expected_revision: int
    ) -> dict:
        self.calls.append(
            (
                "update_report_file_declaration",
                (binding_id, declaration, expected_revision),
            )
        )
        return self.file_intake

    async def remove_report_file(self, binding_id: UUID) -> dict:
        self.calls.append(("remove_report_file", binding_id))
        return self.file_intake

    async def restore_report_file(self, binding_id: UUID) -> dict:
        self.calls.append(("restore_report_file", binding_id))
        return self.file_intake

    async def confirm_material_set(self) -> dict:
        self.calls.append(("confirm_material_set", None))
        return self.file_intake

    async def get_snapshot(self) -> dict:
        self.calls.append(("get_snapshot", None))
        return self.snapshot

    async def get_source_content(self, source_id: UUID) -> dict:
        self.calls.append(("get_source_content", source_id))
        return {"source_id": str(source_id), "normalized_material": None}

    async def upload_sources(
        self,
        files,
        *,
        scope_kind: str,
        report_section_ids: tuple[str, ...],
    ) -> dict:
        self.calls.append(
            (
                "upload_sources",
                (
                    [item.filename for item in files],
                    scope_kind,
                    report_section_ids,
                ),
            )
        )
        return self.snapshot

    async def update_source_metadata(
        self,
        source_id: UUID,
        *,
        scope_kind: str,
        report_section_ids: tuple[str, ...],
    ) -> dict:
        self.calls.append(
            (
                "update_source_metadata",
                (source_id, scope_kind, report_section_ids),
            )
        )
        return self.snapshot

    async def delete_source(self, source_id: UUID) -> dict:
        self.calls.append(("delete_source", source_id))
        return self.snapshot

    async def retry_source(self, source_id: UUID) -> dict:
        self.calls.append(("retry_source", source_id))
        return self.snapshot

    async def extract_source(self, source_id: UUID) -> dict:
        self.calls.append(("extract_source", source_id))
        return self.snapshot

    async def submit_turn(
        self, *, message: str, scope_kind: str, report_section_ids: tuple[str, ...]
    ) -> dict:
        self.calls.append(("submit_turn", (message, scope_kind, report_section_ids)))
        return self.snapshot

    async def collect_scope(
        self, *, scope_kind: str, report_section_ids: tuple[str, ...]
    ) -> dict:
        self.calls.append(("collect_scope", (scope_kind, report_section_ids)))
        return self.snapshot

    async def answer_clarification(
        self, clarification_id: UUID, *, answer: str
    ) -> dict:
        self.calls.append(("answer_clarification", (clarification_id, answer)))
        return self.snapshot

    async def dismiss_clarification(self, clarification_id: UUID) -> dict:
        self.calls.append(("dismiss_clarification", clarification_id))
        return self.snapshot

    async def update_topic_primary_input_mode(
        self,
        report_section_id: str,
        *,
        primary_input_mode: str,
        base_workspace_state_seq: int,
    ) -> dict:
        self.calls.append(
            (
                "update_topic_primary_input_mode",
                (
                    report_section_id,
                    primary_input_mode,
                    base_workspace_state_seq,
                ),
            )
        )
        return self.snapshot

    async def update_report_primary_input_mode(
        self,
        *,
        primary_input_mode: str,
        base_report_state_seq: int,
    ) -> dict:
        self.calls.append(
            (
                "update_report_primary_input_mode",
                (primary_input_mode, base_report_state_seq),
            )
        )
        return self.snapshot


def _client(service: _MaterialService) -> TestClient:
    app.dependency_overrides[authorized_material_service] = lambda: service
    return TestClient(app)


def test_material_routes_cover_complete_mlp_control_surface() -> None:
    paths = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    expected = {
        ("/api/reports/{report_id}/material-workspace", "GET"),
        ("/api/reports/{report_id}/file-intake", "GET"),
        ("/api/reports/{report_id}/preparation", "GET"),
        ("/api/reports/{report_id}/file-intake/files", "POST"),
        ("/api/reports/{report_id}/file-intake/files/{binding_id}", "PATCH"),
        (
            "/api/reports/{report_id}/file-intake/files/{binding_id}/remove",
            "POST",
        ),
        (
            "/api/reports/{report_id}/file-intake/files/{binding_id}/restore",
            "POST",
        ),
        ("/api/reports/{report_id}/file-intake/confirm", "POST"),
        ("/api/reports/{report_id}/material-sources", "POST"),
        (
            "/api/reports/{report_id}/material-sources/{source_id}/content",
            "GET",
        ),
        ("/api/reports/{report_id}/material-sources/{source_id}", "PATCH"),
        ("/api/reports/{report_id}/material-sources/{source_id}", "DELETE"),
        (
            "/api/reports/{report_id}/material-topics/{report_section_id}/primary-input-mode",
            "PATCH",
        ),
        ("/api/reports/{report_id}/primary-input-mode", "PATCH"),
    }
    retired = {
        ("/api/reports/{report_id}/material-proposals/{proposal_id}", "PATCH"),
        ("/api/reports/{report_id}/material-facts/{fact_id}", "PATCH"),
        ("/api/reports/{report_id}/material-gaps/{gap_id}/dismiss", "POST"),
        ("/api/reports/{report_id}/material-scopes/{scope_id}/apply", "POST"),
    }
    assert expected <= paths
    assert not retired & paths


def test_report_file_intake_routes_map_typed_declarations() -> None:
    service = _MaterialService()
    binding_id = uuid4()
    declaration = {
        "description": "2025 年度温室气体核算台账及边界说明",
        "role": "semantic_material",
        "topic_tags": ["climate_change"],
    }
    try:
        client = _client(service)
        report_id = uuid4()
        assert client.get(f"/api/reports/{report_id}/file-intake").status_code == 200
        uploaded = client.post(
            f"/api/reports/{report_id}/file-intake/files",
            files=[
                (
                    "files",
                    (
                        "emissions.docx",
                        BytesIO(b"not parsed in router test"),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
            data={"declarations": json.dumps([declaration])},
        )
        assert uploaded.status_code == 201
        assert (
            client.patch(
                f"/api/reports/{report_id}/file-intake/files/{binding_id}",
                json={"declaration": declaration, "expected_revision": 1},
            ).status_code
            == 200
        )
        assert client.post(
            f"/api/reports/{report_id}/file-intake/files/{binding_id}/remove"
        ).status_code == 200
        assert client.post(
            f"/api/reports/{report_id}/file-intake/files/{binding_id}/restore"
        ).status_code == 200
        assert client.post(
            f"/api/reports/{report_id}/file-intake/confirm"
        ).status_code == 200
        malformed = client.post(
            f"/api/reports/{report_id}/file-intake/files",
            files=[("files", ("bad.docx", BytesIO(b"x"), "application/octet-stream"))],
            data={"declarations": "not-json"},
        )
        assert malformed.status_code == 422
    finally:
        app.dependency_overrides.clear()

    assert [name for name, _ in service.calls] == [
        "get_report_file_intake",
        "upload_report_files",
        "update_report_file_declaration",
        "remove_report_file",
        "restore_report_file",
        "confirm_material_set",
    ]
    uploaded_declaration = service.calls[1][1][1][0]
    assert uploaded_declaration.description == declaration["description"]
    assert uploaded_declaration.topic_tags == ["climate_change"]


def test_report_preparation_route_returns_server_owned_eligibility() -> None:
    service = _MaterialService()
    try:
        client = _client(service)
        response = client.get(
            f"/api/reports/{uuid4()}/preparation"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["generation_eligible"] is False
    assert response.json()["areas"][3]["status"] == "optional_empty"
    assert service.calls == [("get_report_preparation", None)]


def test_material_router_maps_upload_scope_and_all_mutations() -> None:
    service = _MaterialService()
    source_id = uuid4()
    try:
        client = _client(service)
        report_id = uuid4()
        response = client.post(
            f"/api/reports/{report_id}/material-sources",
            files=[
                (
                    "files",
                    ("evidence.pdf", BytesIO(b"%PDF-1.4\n%%EOF"), "application/pdf"),
                )
            ],
            data={
                "scope_kind": "topics",
                "report_section_ids": '["climate_change"]',
            },
        )
        assert response.status_code == 201
        assert service.calls[-1] == (
            "upload_sources",
            (["evidence.pdf"], "topics", ("climate_change",)),
        )

        assert (
            client.patch(
                f"/api/reports/{report_id}/material-sources/{source_id}",
                json={
                    "scope_kind": "profile",
                    "report_section_ids": [],
                },
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/reports/{report_id}/material-sources/{source_id}/content"
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/reports/{report_id}/material-topics/climate_change/primary-input-mode",
                json={"primary_input_mode": "materials", "base_workspace_state_seq": 1},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/reports/{report_id}/primary-input-mode",
                json={"primary_input_mode": "questions", "base_report_state_seq": 1},
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/reports/{report_id}/material-sources/{source_id}"
            ).status_code
            == 200
        )
    finally:
        app.dependency_overrides.clear()

    assert [name for name, _ in service.calls] == [
        "upload_sources",
        "update_source_metadata",
        "get_source_content",
        "update_topic_primary_input_mode",
        "update_report_primary_input_mode",
        "delete_source",
    ]
    assert (
        "update_report_primary_input_mode",
        ("questions", 1),
    ) in service.calls


def test_material_router_rejects_invalid_batch_and_scope_payloads_before_service() -> (
    None
):
    service = _MaterialService()
    try:
        client = _client(service)
        report_id = uuid4()
        too_many = [
            ("files", (f"{index}.png", BytesIO(b"x"), "image/png"))
            for index in range(11)
        ]
        response = client.post(
            f"/api/reports/{report_id}/material-sources",
            files=too_many,
            data={
                "scope_kind": "uncertain",
                "report_section_ids": "[]",
            },
        )
        assert response.status_code == 422

        malformed = client.post(
            f"/api/reports/{report_id}/material-sources",
            files=[("files", ("a.png", BytesIO(b"x"), "image/png"))],
            data={
                "scope_kind": "topics",
                "report_section_ids": "not-json",
            },
        )
        assert malformed.status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert service.calls == []


