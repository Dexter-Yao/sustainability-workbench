# ABOUTME: 持续消费轻量版 File Agent、章节 Mapping 与显式报告生成节点。
# ABOUTME: worker 不运行旧 extraction/collection 链；报告正文只由报告级原子提交替换。
# ABOUTME(en): Continuously drains lightweight File Agent, section Mapping and report generation nodes.
# ABOUTME(en): Runs no legacy extraction chain; report body text is replaced only by report-scoped atomic commits.
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from typing import Literal
from uuid import UUID

from sustainability_desk.material.agent_pipeline import (
    process_one_file_agent_run,
    process_one_image_agent_run,
    process_one_mapping_run,
)
from sustainability_desk.material.intake.storage import MaterialStorageClient
from sustainability_desk.persistence import material_agent_pipeline as pipeline_dal
from sustainability_desk.persistence import lightweight_report_generations as generation_dal
from sustainability_desk.persistence.db import create_pool
from sustainability_desk.persistence.settings import persistence_settings
from sustainability_desk.runtime_environment import assert_environment_boundary, runtime_environment
from sustainability_desk.persistence.material_agent_pipeline import (
    MaterialAgentPipelineLeaseError,
)
from sustainability_desk.lightweight_report_generation import (
    process_one_report_generation,
)

logger = logging.getLogger(__name__)


def material_agent_worker_concurrency() -> int:
    """读取同一进程的有界任务并发；模型请求仍受统一 LLM 信号量限制。"""

    raw = os.getenv("SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY", "4")
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError("资料 Agent worker 并发必须是整数") from error
    if value < 1:
        raise RuntimeError("资料 Agent worker 并发必须为正整数")
    return value


class MaterialAgentWorker:
    """File Agent 优先、Mapping 随后的单一可恢复 worker。"""

    def __init__(
        self,
        *,
        pool,
        storage: MaterialStorageClient,
        worker_id: str,
        report_id: UUID | None = None,
        mapping_scope_id: str | None = None,
        job_kind: Literal[
            "all", "file_agent", "image_agent", "mapping", "report_generation"
        ] = "all",
    ) -> None:
        self._pool = pool
        self._storage = storage
        self._worker_id = worker_id
        self._report_id = report_id
        self._mapping_scope_id = mapping_scope_id
        self._job_kind = job_kind

    async def run_once(self) -> bool:
        """领取至多一个节点；优先让并行单文件调查尽快形成完整 snapshot。"""

        if self._job_kind in {"all", "file_agent"}:
            if await process_one_file_agent_run(
                self._pool,
                storage=self._storage,
                worker_id=self._worker_id,
                report_id=self._report_id,
            ):
                return True
        if self._job_kind in {"all", "image_agent"}:
            if await process_one_image_agent_run(
                self._pool,
                storage=self._storage,
                worker_id=self._worker_id,
                report_id=self._report_id,
            ):
                return True
        if self._job_kind in {"all", "mapping"}:
            if await process_one_mapping_run(
                self._pool,
                storage=self._storage,
                worker_id=self._worker_id,
                report_id=self._report_id,
                scope_id=self._mapping_scope_id,
            ):
                return True
        if self._job_kind in {"all", "report_generation"}:
            return await process_one_report_generation(
                self._pool,
                worker_id=self._worker_id,
                report_id=self._report_id,
                storage=self._storage,
            )
        return False

    async def drain(
        self,
        *,
        max_jobs: int = 1_000,
        max_concurrency: int | None = None,
    ) -> int:
        """用固定 worker 数排空当前队列，供本地 E2E 与恢复检查使用。"""

        concurrency = max_concurrency or material_agent_worker_concurrency()
        if max_jobs < 1:
            raise ValueError("max_jobs 必须为正数")
        handled = 0
        reserved = 0
        lock = asyncio.Lock()

        async def consume(index: int) -> None:
            nonlocal handled, reserved
            while True:
                async with lock:
                    if handled + reserved >= max_jobs:
                        return
                    reserved += 1
                processed = await MaterialAgentWorker(
                    pool=self._pool,
                    storage=self._storage,
                    worker_id=f"{self._worker_id}-{index}",
                    report_id=self._report_id,
                    mapping_scope_id=self._mapping_scope_id,
                    job_kind=self._job_kind,
                ).run_once()
                async with lock:
                    reserved -= 1
                    if processed:
                        handled += 1
                if not processed:
                    return

        await pipeline_dal.recover_expired_pipeline_runs(self._pool)
        await generation_dal.recover_expired_generation_runs(self._pool)
        await asyncio.gather(*(consume(index) for index in range(concurrency)))
        return handled

    async def run_forever(
        self,
        *,
        poll_interval: float = 0.5,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """持续并发轮询；停止信号后不再领取新节点。

        消费协程数由 SUSTAINABILITY_DESK_MATERIAL_AGENT_WORKER_CONCURRENCY 决定（默认 4，
        与 drain 同源）；领取互斥由 DAL 的 for update skip locked 保证。过期租约
        恢复独立成低频协程，不随消费轮询次数放大。
        """

        stop = stop_event or asyncio.Event()
        concurrency = material_agent_worker_concurrency()

        async def recover_loop() -> None:
            while not stop.is_set():
                try:
                    await pipeline_dal.recover_expired_pipeline_runs(self._pool)
                    await generation_dal.recover_expired_generation_runs(self._pool)
                except Exception:  # noqa: BLE001 — 一次 DB 抖动不得终结整个 worker gather
                    logger.exception("过期租约恢复本轮失败，下一轮重试")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2.0)
                except TimeoutError:
                    continue

        async def consume(index: int) -> None:
            worker = MaterialAgentWorker(
                pool=self._pool,
                storage=self._storage,
                worker_id=f"{self._worker_id}-{index}",
                report_id=self._report_id,
                mapping_scope_id=self._mapping_scope_id,
                job_kind=self._job_kind,
            )
            while not stop.is_set():
                try:
                    claimed = await worker.run_once()
                except MaterialAgentPipelineLeaseError as error:
                    # 租约在处理期间过期（本节点耗时超过 lease_seconds）：另一 worker
                    # 已可重新领取，本次结果无处写回。这是可恢复分支，不得让整个进程
                    # 退出——否则一份慢文件会拖垮同批其余文件，且 systemd 重启后重新
                    # 领取同一节点，形成崩溃循环。
                    logger.warning("File Agent 租约已过期，交还该节点：%s", error)
                    continue
                except Exception:  # noqa: BLE001 — 单节点失败不得终结常驻消费
                    logger.exception("资料 Agent 节点处理失败，继续消费下一个节点")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                    except TimeoutError:
                        pass
                    continue
                if claimed:
                    continue
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                except TimeoutError:
                    continue

        await asyncio.gather(
            recover_loop(),
            *(consume(index) for index in range(concurrency)),
        )


def _parser() -> argparse.ArgumentParser:
    """解析常驻 worker 与受控本地 E2E 排空两种运行方式。"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--drain",
        action="store_true",
        help="排空当前 File Agent、Mapping 与报告生成队列后退出。",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=1_000,
        help="--drain 最多领取的队列节点数。",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="--drain 的 worker 并发；省略时使用环境配置。",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="可观测日志中的 worker 身份；省略时由当前进程 PID 派生。",
    )
    parser.add_argument(
        "--report-id",
        type=UUID,
        default=None,
        help="仅处理该报告的队列节点；本地 E2E 必填，常驻 worker 省略。",
    )
    parser.add_argument(
        "--mapping-scope-id",
        default=None,
        help="仅处理指定 Mapping scope；必须与 --report-id 一起使用。",
    )
    parser.add_argument(
        "--job-kind",
        choices=("all", "file_agent", "image_agent", "mapping", "report_generation"),
        default="all",
        help="仅领取指定种类的节点；本地 E2E 用于防止阶段越界。",
    )
    return parser


async def _main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.max_jobs < 1:
        parser.error("--max-jobs 必须为正整数")
    if args.max_concurrency is not None and args.max_concurrency < 1:
        parser.error("--max-concurrency 必须为正整数")
    if args.mapping_scope_id is not None and args.report_id is None:
        parser.error("--mapping-scope-id 必须与 --report-id 一起使用")
    if args.mapping_scope_id is not None and args.job_kind != "mapping":
        parser.error("--mapping-scope-id 仅可与 --job-kind mapping 一起使用")
    settings = persistence_settings()
    if not settings.database_url:
        raise RuntimeError(
            "SUSTAINABILITY_DESK_DATABASE_URL 未配置，material agent worker 无法启动"
        )
    assert_environment_boundary(
        runtime_environment(),
        persistence_configured=settings.configured,
        supabase_url=settings.supabase_url,
    )
    pool = await create_pool(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    try:
        worker = MaterialAgentWorker(
            pool=pool,
            storage=MaterialStorageClient(settings),
            worker_id=args.worker_id or f"material-agent-worker-{os.getpid()}",
            report_id=args.report_id,
            mapping_scope_id=args.mapping_scope_id,
            job_kind=args.job_kind,
        )
        if args.drain:
            handled = await worker.drain(
                max_jobs=args.max_jobs,
                max_concurrency=args.max_concurrency,
            )
            print(f"已排空 {handled} 个轻量版 Agent 队列节点。")
            return
        await worker.run_forever(stop_event=stop)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
