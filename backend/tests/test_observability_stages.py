# ABOUTME: 校验 open_stage 的运行期不变量——registry 归属、同 trace 嵌套、执行范围与属性命名空间。
# ABOUTME: 每条以构造违例证明会当场失败；另覆盖根句柄的阶段事实收集（收束断言的事实基础）。
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sustainability_desk.observability.registry import (
    Stage,
    StageRegistrationError,
    register_stage,
)
from sustainability_desk.observability.stages import (
    StageError,
    StageScopeViolation,
    StageTraceMismatch,
    StageUnregistered,
    current_stage,
    open_stage,
    require_current_stage,
)
from sustainability_desk.lightweight_report_generation import (
    DELIVERY_RENDER_STAGE,
    DOCX_WORD_STAGE,
    MODULE_TITLES_STAGE,
    REPORT_GENERATION_STAGE,
)
from sustainability_desk.material.agent_pipeline import FILE_AGENT_STAGE

TRACE = "trace-fixture-0001"
REPORT = "report-fixture-0001"


@pytest.fixture(autouse=True)
def _isolate_stage_trace(tmp_path, monkeypatch):
    """把阶段轨迹写入隔离目录。

    open_stage 未指定 trace_root 时落到运行时观测根目录，测试会污染真实
    backend/out/observability/。这里改写默认根目录，使未显式传参的用例也隔离。
    """
    monkeypatch.setattr(
        "sustainability_desk.llm.ai_observability.DEFAULT_OBSERVABILITY_ROOT", tmp_path
    )
    monkeypatch.setattr(
        "sustainability_desk.runtime_environment.runtime_environment",
        lambda: SimpleNamespace(observability_root=tmp_path),
    )


def _open(stage, **overrides):
    kwargs = {
        "trace_id": TRACE,
        "report_id": REPORT,
        "scope": "full_simplified",
    }
    kwargs.update(overrides)
    return open_stage(stage, **kwargs)


def test_root_stage_opens_without_parent() -> None:
    with _open(REPORT_GENERATION_STAGE) as handle:
        assert handle.parent_span_id is None
        assert handle.trace_id == TRACE
        assert handle.report_id == REPORT
        assert handle.status == "running"
        assert handle.root is handle
    assert handle.status == "succeeded"
    assert handle.finished_at is not None


def test_nested_stage_inherits_parent_from_context() -> None:
    with _open(REPORT_GENERATION_STAGE) as parent_handle:
        with _open(DELIVERY_RENDER_STAGE) as child_handle:
            assert child_handle.parent_span_id == parent_handle.span_id
            assert child_handle.root is parent_handle
            assert current_stage() is child_handle
        assert current_stage() is parent_handle
    assert current_stage() is None


def test_root_collects_executed_stage_facts() -> None:
    """子 span 收束时把阶段事实记到根——收束断言据此比对，不回读文件。"""
    with _open(REPORT_GENERATION_STAGE) as root:
        with _open(DELIVERY_RENDER_STAGE):
            with _open(DOCX_WORD_STAGE, **{"sustainability_desk.artifact_count": 1}):
                pass
    executed = [stage_id for stage_id, _ in root.executed_stage_facts]
    assert executed == ["delivery.docx.word", "delivery.render", "report.generation"]
    docx_facts = dict(root.executed_stage_facts)["delivery.docx.word"]
    assert docx_facts["sustainability_desk.artifact_count"] == 1


def test_unregistered_stage_rejected() -> None:
    forged = Stage(id="forged.stage", kind="llm")
    with pytest.raises(StageUnregistered):
        with open_stage(forged, trace_id=TRACE, report_id=REPORT):
            pass


def test_stage_definition_conflict_rejected_at_registration() -> None:
    """同 id 不同定义即两处代码争夺同一词汇，导入期直接失败。"""
    conflicting = Stage(id="report.generation", kind="llm")
    with pytest.raises(StageRegistrationError):
        register_stage(conflicting)


def test_reregistering_identical_stage_is_idempotent() -> None:
    assert register_stage(REPORT_GENERATION_STAGE) is REPORT_GENERATION_STAGE


def test_cross_trace_parent_rejected() -> None:
    """跨工作单元不得伪造父子——父 span 属于另一条 trace 即失败。"""
    with _open(FILE_AGENT_STAGE, trace_id="other-trace") as foreign_root:
        pass
    with pytest.raises(StageTraceMismatch, match="不得伪造父子"):
        with _open(DELIVERY_RENDER_STAGE, parent=foreign_root):
            pass


def test_scoped_stage_requires_scope_and_report_id() -> None:
    with pytest.raises(StageScopeViolation, match="必须传入 scope"):
        with open_stage(REPORT_GENERATION_STAGE, trace_id=TRACE, report_id=REPORT):
            pass
    with pytest.raises(StageScopeViolation, match="report_id 不得为空"):
        with open_stage(
            REPORT_GENERATION_STAGE,
            trace_id=TRACE,
            report_id="",
            scope="full_simplified",
        ):
            pass


def test_attribute_namespace_enforced() -> None:
    with _open(REPORT_GENERATION_STAGE) as handle:
        handle.set_attribute("sustainability_desk.block_count", 3)
        handle.set_attribute("gen_ai.usage.input_tokens", 12)
        with pytest.raises(StageError, match="不在允许的命名空间"):
            handle.set_attribute("report_id", "r-1")


def test_failure_records_status_and_error_code() -> None:
    with pytest.raises(ValueError):
        with _open(REPORT_GENERATION_STAGE) as handle:
            raise ValueError("boom")
    assert handle.status == "failed"
    assert handle.error_code == "ValueError"
    assert handle.finished_at is not None


def test_context_restored_after_failure() -> None:
    """异常路径也必须还原上下文，否则后续阶段会挂到已结束的父上。"""
    with _open(REPORT_GENERATION_STAGE) as root:
        with pytest.raises(ValueError):
            with _open(DELIVERY_RENDER_STAGE):
                raise ValueError("boom")
        assert current_stage() is root
    assert current_stage() is None


def test_explicit_parent_overrides_context() -> None:
    """跨任务场景：父上下文可由调用方显式传入（如 synchronize 挂回触发它的根）。"""
    with _open(FILE_AGENT_STAGE) as root_handle:
        pass
    with _open(DELIVERY_RENDER_STAGE, parent=root_handle) as handle:
        assert handle.parent_span_id == root_handle.span_id
        assert handle.root is root_handle


def test_require_current_stage_fails_loud_outside_span() -> None:
    with pytest.raises(StageError, match="根 span"):
        require_current_stage("测试动作")


def test_agent_stage_projects_genai_semantics() -> None:
    """OTLP 后端 的 AI Agent 页靠 gen_ai.span.kind=AGENT + agent.name 成行。

    对照实测：缺 span.kind 时服务端只登记普通 XTRACE 服务，
    AI 应用与 Agent 列表全空。Agent 名沿用 registry 的 stage id，不另起一套。
    """
    from sustainability_desk.observability.stages import _genai_attributes

    attributes = _genai_attributes(FILE_AGENT_STAGE.id, FILE_AGENT_STAGE.kind)
    assert attributes["gen_ai.span.kind"] == "AGENT"
    assert attributes["gen_ai.agent.name"] == FILE_AGENT_STAGE.id
    assert attributes["gen_ai.operation.name"] == "invoke_agent"


def test_non_agent_stage_projects_as_chain_not_model_call() -> None:
    """非 agent/tool 阶段投影为 CHAIN：标 LLM 会重复计 Token，不标则 span 不进
    AI 应用视图、调用树缺编排骨架。"""
    from sustainability_desk.observability.stages import _genai_attributes

    for stage in (MODULE_TITLES_STAGE, DELIVERY_RENDER_STAGE, REPORT_GENERATION_STAGE):
        attributes = _genai_attributes(stage.id, stage.kind)
        assert attributes == {"gen_ai.span.kind": "CHAIN"}
        assert attributes["gen_ai.span.kind"] != "LLM"


def test_stage_mirror_span_carries_session_identity() -> None:
    """会话分析页靠 gen_ai.session.id 聚合；报告链路以 reportId 为会话。"""
    from sustainability_desk.observability.stage_trace import StageRecord
    from sustainability_desk.observability.stages import mirror_span_for_stage_record

    record = StageRecord(
        traceId=TRACE,
        spanId="00000000000000aa",
        parentSpanId=None,
        stageId=FILE_AGENT_STAGE.id,
        kind=FILE_AGENT_STAGE.kind,
        reportId=REPORT,
        scope="full_simplified",
        status="succeeded",
        errorCode="",
        durationMs=120,
        startedAt="2026-08-13T08:00:00+00:00",
        attributes={"sustainability_desk.attempt": 1},
    )
    span = mirror_span_for_stage_record(record)
    assert span.attributes["gen_ai.session.id"] == REPORT
    assert span.attributes["gen_ai.agent.name"] == FILE_AGENT_STAGE.id
    assert span.end_ns - span.start_ns == 120 * 1_000_000

    orphan = record.model_copy(update={"reportId": ""})
    assert mirror_span_for_stage_record(orphan).attributes["gen_ai.session.id"] == TRACE


def test_stage_mirror_span_name_and_io_carry_business_identity() -> None:
    """64 个同名 generation.block 在调用树里必须可区分：名称携带 block_id/行号，
    input.value 承载身份、output.value 承载状态与结果属性（不承载正文）。"""
    from sustainability_desk.observability.stage_trace import StageRecord
    from sustainability_desk.observability.stages import mirror_span_for_stage_record

    row = StageRecord(
        traceId=TRACE,
        spanId="00000000000000ab",
        parentSpanId="00000000000000aa",
        stageId="generation.row",
        kind="llm",
        reportId=REPORT,
        scope="full_simplified",
        status="succeeded",
        errorCode="",
        durationMs=90,
        startedAt="2026-08-13T08:00:00+00:00",
        attributes={
            "sustainability_desk.block_id": "sm.iro_table",
            "sustainability_desk.row_ordinal": 8,
            "sustainability_desk.attempts": 1,
        },
    )
    span = mirror_span_for_stage_record(row)
    assert span.name == "generation.row sm.iro_table r8"
    assert "block_id=sm.iro_table" in span.attributes["input.value"]
    assert span.attributes["output.value"].startswith("succeeded")
    assert "attempts=1" in span.attributes["output.value"]

    root = row.model_copy(
        update={
            "stageId": "report.generation",
            "kind": "orchestration",
            "parentSpanId": None,
            "attributes": {"sustainability_desk.block_count": 64},
        }
    )
    root_span = mirror_span_for_stage_record(root)
    assert root_span.name == "report.generation"
    assert f"report={REPORT[:8]}" in root_span.attributes["input.value"]
    assert "block_count=64" in root_span.attributes["output.value"]
