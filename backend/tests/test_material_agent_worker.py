# ABOUTME: 新资料 Agent worker 的有界并发与 File-first 调度测试。
# ABOUTME: 测试不调用真实模型、Storage 或数据库。
from uuid import uuid4

import pytest

from sustainability_desk.material.agent_worker import MaterialAgentWorker


@pytest.mark.asyncio
async def test_worker_prioritizes_file_agent(monkeypatch) -> None:
    calls: list[str] = []

    async def file_run(*_args, **_kwargs):
        calls.append("file")
        return True

    async def mapping_run(*_args, **_kwargs):
        calls.append("mapping")
        return True

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run",
        file_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_mapping_run",
        mapping_run,
    )
    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )

    assert await worker.run_once() is True
    assert calls == ["file"]


@pytest.mark.asyncio
async def test_worker_claims_image_agent_when_file_queue_is_empty(monkeypatch) -> None:
    calls: list[str] = []

    async def file_run(*_args, **_kwargs):
        calls.append("file")
        return False

    async def image_run(*_args, **_kwargs):
        calls.append("image")
        return True

    async def mapping_run(*_args, **_kwargs):
        calls.append("mapping")
        return True

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run",
        file_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_image_agent_run",
        image_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_mapping_run",
        mapping_run,
    )
    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )

    assert await worker.run_once() is True
    assert calls == ["file", "image"]


@pytest.mark.asyncio
async def test_worker_claims_mapping_when_file_and_image_queues_are_empty(monkeypatch) -> None:
    calls: list[str] = []

    async def file_run(*_args, **_kwargs):
        calls.append("file")
        return False

    async def image_run(*_args, **_kwargs):
        calls.append("image")
        return False

    async def mapping_run(*_args, **_kwargs):
        calls.append("mapping")
        return True

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run",
        file_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_image_agent_run",
        image_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_mapping_run",
        mapping_run,
    )
    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )

    assert await worker.run_once() is True
    assert calls == ["file", "image", "mapping"]


@pytest.mark.asyncio
async def test_worker_passes_local_report_and_mapping_scope_filters(monkeypatch) -> None:
    report_id = uuid4()
    calls: list[dict] = []

    async def file_run(*_args, **kwargs):
        calls.append(kwargs)
        return False

    async def image_run(*_args, **kwargs):
        calls.append(kwargs)
        return False

    async def mapping_run(*_args, **kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run",
        file_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_image_agent_run",
        image_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_mapping_run",
        mapping_run,
    )
    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="local-e2e-worker",
        report_id=report_id,
        mapping_scope_id="report-section:climate_change",
    )

    assert await worker.run_once() is True
    assert calls[0]["report_id"] == report_id
    assert calls[1]["report_id"] == report_id
    assert calls[2]["report_id"] == report_id
    assert calls[2]["scope_id"] == "report-section:climate_change"


@pytest.mark.asyncio
async def test_worker_mapping_mode_never_claims_file_or_report_generation(monkeypatch) -> None:
    calls: list[str] = []

    async def file_run(*_args, **_kwargs):
        calls.append("file")
        return True

    async def mapping_run(*_args, **_kwargs):
        calls.append("mapping")
        return True

    async def generation_run(*_args, **_kwargs):
        calls.append("generation")
        return True

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run",
        file_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_mapping_run",
        mapping_run,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_report_generation",
        generation_run,
    )
    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="local-e2e-mapping-worker",
        job_kind="mapping",
    )

    assert await worker.run_once() is True
    assert calls == ["mapping"]


@pytest.mark.asyncio
async def test_run_forever_consumes_concurrently(monkeypatch) -> None:
    """常驻循环须按环境并发数 fan-out 消费，不得串行单 run。"""
    import asyncio

    monkeypatch.setenv("SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY", "3")

    inflight = 0
    peak = 0
    handled = 0
    lock = asyncio.Lock()
    stop = asyncio.Event()

    async def file_run(*_args, **_kwargs):
        nonlocal inflight, peak, handled
        async with lock:
            inflight += 1
            peak = max(peak, inflight)
        await asyncio.sleep(0.02)
        async with lock:
            inflight -= 1
            handled += 1
            if handled >= 9:
                stop.set()
        return True

    async def noop_recover(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run", file_run
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.pipeline_dal.recover_expired_pipeline_runs",
        noop_recover,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.generation_dal.recover_expired_generation_runs",
        noop_recover,
    )

    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )
    await asyncio.wait_for(
        worker.run_forever(poll_interval=0.01, stop_event=stop), timeout=5
    )

    assert handled >= 9
    assert peak == 3


@pytest.mark.asyncio
async def test_lease_expiry_does_not_kill_worker(monkeypatch, caplog) -> None:
    """租约过期是可恢复分支，常驻消费必须继续。

    回归：File Agent 处理超过 lease_seconds 后写回失败，
    MaterialAgentPipelineLeaseError 若冒泡到 asyncio.gather 会使整个 worker 退出；
    进程重启后重新领取同一节点再次超时，形成崩溃循环，同批其余文件
    永远停在「正在理解」。
    """
    import asyncio

    from sustainability_desk.persistence.material_agent_pipeline import (
        MaterialAgentPipelineLeaseError,
    )

    monkeypatch.setenv("SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY", "1")
    calls = 0
    stop = asyncio.Event()

    async def file_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MaterialAgentPipelineLeaseError("expired-run-id")
        if calls >= 3:
            stop.set()
        return True

    async def noop_recover(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run", file_run
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.pipeline_dal.recover_expired_pipeline_runs",
        noop_recover,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.generation_dal.recover_expired_generation_runs",
        noop_recover,
    )

    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )
    await asyncio.wait_for(
        worker.run_forever(poll_interval=0.01, stop_event=stop), timeout=5
    )

    assert calls >= 3, "租约过期后 worker 必须继续消费后续节点"
    # 租约过期须走专属分支：它是可恢复的交还，不是未知故障。若被通用 except
    # 兜住，语义与日志级别都会错，故断言其被独立识别。
    assert any(
        "租约已过期" in record.getMessage() for record in caplog.records
    ), "租约过期须记为交还节点，而非未知故障"


@pytest.mark.asyncio
async def test_unexpected_node_failure_does_not_kill_worker(monkeypatch) -> None:
    """任意单节点异常同样不得终结常驻消费，否则一份坏文件拖垮整批。"""
    import asyncio

    monkeypatch.setenv("SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY", "1")
    calls = 0
    stop = asyncio.Event()

    async def file_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("解析器崩了")
        if calls >= 3:
            stop.set()
        return True

    async def noop_recover(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.process_one_file_agent_run", file_run
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.pipeline_dal.recover_expired_pipeline_runs",
        noop_recover,
    )
    monkeypatch.setattr(
        "sustainability_desk.material.agent_worker.generation_dal.recover_expired_generation_runs",
        noop_recover,
    )

    worker = MaterialAgentWorker(
        pool=object(),
        storage=object(),  # type: ignore[arg-type]
        worker_id="test-worker",
    )
    await asyncio.wait_for(
        worker.run_forever(poll_interval=0.01, stop_event=stop), timeout=5
    )

    assert calls >= 3, "单节点异常后 worker 必须继续消费"
