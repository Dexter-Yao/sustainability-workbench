# ABOUTME: Mapping worker 的报告范围再装配测试。
# ABOUTME: worker 不以冻结 scope 或 scope_id 持续授权；必须与当前 Report revision 的任务装配完全一致。
from __future__ import annotations

import pytest



def test_worker_error_retryability_denylists_deterministic_failures() -> None:
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from sustainability_desk.accounts.service import AccountEntitlementError
    from sustainability_desk.material.agent_pipeline import is_retryable_worker_error
    from sustainability_desk.persistence.material_agent_pipeline import (
        MaterialAgentPipelinePersistenceError,
    )

    assert is_retryable_worker_error(UnexpectedModelBehavior("模型输出异常"))
    assert is_retryable_worker_error(TimeoutError("上游超时"))
    assert is_retryable_worker_error(RuntimeError("存储瞬时错误"))
    assert not is_retryable_worker_error(AccountEntitlementError("资料 Agent 权益已失效"))
    assert not is_retryable_worker_error(
        MaterialAgentPipelinePersistenceError("冻结输入不完整")
    )
    assert not is_retryable_worker_error(ValueError("冻结 Mapping scope 已不属于当前报告范围"))


def _file_agent_lease(report_id):
    from uuid import uuid4

    from sustainability_desk.material.intake.file_agent_contract import (
        FileAgentContext,
        FileAgentProductTask,
        FileMaterialScope,
        FileSourceRevision,
    )
    from sustainability_desk.material.intake.models import UserFileDeclaration
    from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal

    context = FileAgentContext(
        source_revision=FileSourceRevision(source_id=uuid4(), source_sha256="a" * 64, declaration_revision=1),
        filename="气候制度.docx", material_kind="docx", size_bytes=1024,
        declaration=UserFileDeclaration(description="公司提交的气候治理制度资料。", role="semantic_material", topic_tags=["气候变化"]),
        product_task=FileAgentProductTask(
            report_id=report_id,
            material_scopes=(FileMaterialScope(alias="scope_climate", scope_id="report-section:climate", title="气候", kind="esg_topic"),),
        ),
        available_tools=("convert_file", "read_file"),
    )
    return pipeline_dal.FileAgentRunLease(
        run_id=uuid4(), lease_token=uuid4(), attempt=1, account_id=uuid4(),
        report_id=report_id, workspace_id=uuid4(), binding_id=uuid4(),
        input_fingerprint="b" * 64, context=context, checkpoint=None,
    )


@pytest.mark.asyncio
async def test_file_worker_requeues_transient_error_and_terminates_entitlement_error(monkeypatch) -> None:
    from uuid import uuid4

    import sustainability_desk.material.agent_pipeline as service
    from sustainability_desk.accounts.service import AccountEntitlementError

    lease = _file_agent_lease(uuid4())
    captured: dict[str, object] = {}

    async def fake_claim(pool, **kwargs):
        return lease

    async def fake_finish(pool, **kwargs):
        captured.update(kwargs)

    async def fake_unfinished(pool, **kwargs):
        return service.pipeline_dal.UnfinishedFileAgentWork(in_flight_count=1)

    monkeypatch.setattr(service.pipeline_dal, "claim_file_agent_run", fake_claim)
    monkeypatch.setattr(service.pipeline_dal, "finish_file_agent_run", fake_finish)
    monkeypatch.setattr(
        service.pipeline_dal, "unfinished_file_agent_work", fake_unfinished
    )

    async def scope_ok(pool, **kwargs):
        return None

    async def transient_get_source(pool, **kwargs):
        raise TimeoutError("对象存储瞬时超时")

    monkeypatch.setattr(service, "_assert_pipeline_scope", scope_ok)
    monkeypatch.setattr(service.material_dal, "get_source", transient_get_source)
    assert await service.process_one_file_agent_run(None, storage=object(), worker_id="w1")
    assert captured["retryable_failure"] is True
    assert captured["result"].status == "failed"
    assert captured["result"].receipt.failure_code == "TimeoutError"

    async def scope_denied(pool, **kwargs):
        raise AccountEntitlementError("资料 Agent 权益已失效")

    captured.clear()
    monkeypatch.setattr(service, "_assert_pipeline_scope", scope_denied)
    assert await service.process_one_file_agent_run(None, storage=object(), worker_id="w1")
    assert captured["retryable_failure"] is False
    assert captured["result"].receipt.failure_code == "AccountEntitlementError"
