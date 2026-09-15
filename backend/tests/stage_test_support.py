# ABOUTME: 测试专用的工作单元阶段与根 span 辅助——v3 起模型调用必须归属 span，测试同样不豁免。
# ABOUTME: 生产阶段常量声明在实现模块内；本模块只为测试提供一个通用 unit_root 词汇。
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import open_stage

TEST_UNIT_STAGE = register_stage(
    Stage(id="test.unit", kind="orchestration", unit_root=True)
)


@contextmanager
def unit_span(run: ObservationRun) -> Iterator[None]:
    """为测试中的观测任务开启与其 runId 对齐的根 span。"""
    with open_stage(
        TEST_UNIT_STAGE,
        trace_id=run.runId,
        report_id=run.reportId,
    ):
        yield
