# ABOUTME: AI 观测合同测试——完整保存模型请求、结构化结果与业务守卫判定。
# ABOUTME: JSONL 文件保持仅所有者可读写；历史无正文合同明确不兼容。
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.observability.observability_analysis import summarize_observability_file
from sustainability_desk.llm.ai_observability import (
    GuardrailEvaluationEvent,
    GuardrailIssueTrace,
    ModelInvocationEvent,
    ModelTraceRequest,
    ModelTraceResult,
    create_observation_run,
    observe_generation,
    parse_observability_event,
    record_guardrail_evaluation,
    record_model_invocation,
)
from stage_test_support import TEST_UNIT_STAGE, unit_span


def _run(root: Path):
    return create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="p.x",
        root=root,
        request_id="req-test",
        environment="test",
        release_id="release-test",
        git_sha="abc123",
    )


def test_observability_persists_complete_model_exchange_and_guardrail_result(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    with unit_span(run), observe_generation(run):
        invocation = run.invocation(
            evidence_selector_kind="report_section",
            intake_fact_count=3,
            metric_evidence_count=4,
            evidence_level="block_facts",
            context_fingerprint="sha256:context-test",
            task_context={"evidence": {"intakeFacts": [{"answer": "用户事实原文"}]}},
        )
        record_model_invocation(
            invocation,
            request=ModelTraceRequest(
                taskContext=invocation.taskContext,
                systemPrompt="完整系统提示词",
                userPrompt="完整用户提示词：用户事实原文",
                modelSettings={"temperature": 0.2},
                outputSchema={"type": "object"},
            ),
            result=ModelTraceResult(
                messageHistory=[{"role": "assistant", "content": "模型原始消息"}],
                structuredOutput={"variants": [{"content": "生成正文"}]},
                transportErrors=[
                    {"type": "ModelHTTPError", "message": "HTTP 429", "statusCode": 429}
                ],
            ),
            usage={"requests": 1, "input_tokens": 12, "output_tokens": 4},
            duration_ms=125,
            transport_attempts=1,
            prompt_hash="sha256:test",
        )
        record_guardrail_evaluation(
            invocation,
            issues=[
                GuardrailIssueTrace(
                    key="unsupported_formal_name",
                    message="正式名称无证据。",
                    evidence="创新委员会",
                    location="variant[0]",
                )
            ],
            retry_instruction="请删除创新委员会。",
        )

    events = [parse_observability_event(line) for line in run.path.read_text().splitlines()]
    assert [event.eventType for event in events] == [
        "generation_started",
        "model_invocation",
        "guardrail_evaluation",
        "generation_finished",
    ]
    invocation = next(event for event in events if isinstance(event, ModelInvocationEvent))
    assert invocation.inputTokens == 12
    assert invocation.outputTokens == 4
    assert invocation.invocationOrdinal == 1
    assert invocation.evidenceSelectorKind == "report_section"
    assert invocation.intakeFactCount == 3
    assert invocation.metricEvidenceCount == 4
    assert invocation.evidenceLevel == "block_facts"
    assert invocation.contextFingerprint == "sha256:context-test"
    serialized = invocation.model_dump_json()
    assert "用户事实原文" in serialized
    assert "完整系统提示词" in serialized
    assert "完整用户提示词" in serialized
    assert "模型原始消息" in serialized
    assert "生成正文" in serialized
    assert invocation.result.transportErrors[0].statusCode == 429
    guardrail = next(event for event in events if isinstance(event, GuardrailEvaluationEvent))
    assert guardrail.status == "rejected"
    assert guardrail.issues[0].evidence == "创新委员会"
    assert guardrail.retryInstruction == "请删除创新委员会。"
    assert run.path.parent.stat().st_mode & 0o777 == 0o700
    assert run.path.stat().st_mode & 0o777 == 0o600


def test_invocation_mirror_span_renders_genai_standard_keys(tmp_path: Path) -> None:
    """OTLP 后端 链路追踪页只按 GenAI 标准键渲染内容与归属；sustainability_desk.* 大属性
    是完整事实镜像，控制台不认识——两套键必须同时在场。"""
    import json

    from sustainability_desk.llm.ai_observability import mirror_span_for_invocation

    run = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="p.x",
        root=tmp_path,
        request_id="req-test",
        environment="test",
        release_id="release-test",
        git_sha="abc123",
        report_id="report-1",
        user_id="account-1",
    )
    with unit_span(run), observe_generation(run):
        invocation = run.invocation()
        assert invocation.userId == "account-1"
        record_model_invocation(
            invocation,
            request=ModelTraceRequest(systemPrompt="系统提示", userPrompt="用户提示"),
            result=ModelTraceResult(structuredOutput={"content": "生成正文"}),
            usage={"input_tokens": 10, "output_tokens": 3},
            duration_ms=50,
            transport_attempts=1,
            prompt_hash="sha256:t",
        )
    event = next(
        item for item in run.collectedEvents if isinstance(item, ModelInvocationEvent)
    )
    span = mirror_span_for_invocation(event, user_id=invocation.userId)
    assert span.name == "llm p.x #1"
    attributes = span.attributes
    assert attributes["gen_ai.agent.name"] == TEST_UNIT_STAGE.id
    assert attributes["gen_ai.session.id"] == "report-1"
    assert attributes["gen_ai.user.id"] == "account-1"
    assert json.loads(attributes["gen_ai.system_instructions"]) == [
        {"type": "text", "content": "系统提示"}
    ]
    assert json.loads(attributes["gen_ai.input.messages"]) == [
        {"role": "system", "parts": [{"type": "text", "content": "系统提示"}]},
        {"role": "user", "parts": [{"type": "text", "content": "用户提示"}]},
    ]
    output_messages = json.loads(attributes["gen_ai.output.messages"])
    assert output_messages[0]["role"] == "assistant"
    assert "生成正文" in output_messages[0]["parts"][0]["content"]
    assert attributes["input.value"] == "用户提示"
    assert "生成正文" in attributes["output.value"]
    assert "sustainability_desk.request" in attributes
    assert "sustainability_desk.result" in attributes
    assert span.end_ns - span.start_ns == 50 * 1_000_000


def test_invocation_mirror_session_falls_back_to_run_without_report(
    tmp_path: Path,
) -> None:
    """无报告归属的工作单元（eval 等）以 run 自身为一次会话，不留空。"""
    from sustainability_desk.llm.ai_observability import mirror_span_for_invocation

    run = _run(tmp_path)
    with unit_span(run), observe_generation(run):
        record_model_invocation(
            run.invocation(),
            request=ModelTraceRequest(systemPrompt="s", userPrompt="u"),
            result=ModelTraceResult(structuredOutput={"content": "x"}),
            usage=None,
            duration_ms=1,
            transport_attempts=1,
            prompt_hash="sha256:t",
        )
    event = next(
        item for item in run.collectedEvents if isinstance(item, ModelInvocationEvent)
    )
    span = mirror_span_for_invocation(event)
    assert span.attributes["gen_ai.session.id"] == run.runId
    assert "gen_ai.user.id" not in span.attributes


def test_observability_records_failed_task_and_invocation(tmp_path: Path) -> None:
    run = _run(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        with unit_span(run), observe_generation(run):
            record_model_invocation(
                run.invocation(),
                request=ModelTraceRequest(systemPrompt="system", userPrompt="user"),
                result=ModelTraceResult(
                    error={"type": "RuntimeError", "message": "boom"}
                ),
                usage=None,
                duration_ms=5,
                transport_attempts=2,
                error_code="RuntimeError",
                prompt_hash="sha256:secret-is-not-stored",
            )
            raise RuntimeError("boom")

    summary = summarize_observability_file(run.path)
    assert run.status == "failed"
    assert summary.failedRuns == 1
    assert summary.failedInvocations == 1
    assert summary.transportAttempts == 2


def test_observability_rejects_historical_contract() -> None:
    old = (
        '{"schemaVersion":"sustainability_desk.ai_observability.v1",'
        '"eventType":"model_invocation","runId":"old"}'
    )
    with pytest.raises(ValidationError):
        parse_observability_event(old)


def test_observation_tasks_are_independent_without_implicit_context(tmp_path: Path) -> None:
    outer = _run(tmp_path / "outer")
    inner = _run(tmp_path / "inner")
    with unit_span(outer), observe_generation(outer):
        pass
    # 两个工作单元各有独立 trace；v3 禁止跨 trace 嵌套 span，独立性由
    # 显式传递的 run 保证，而非隐式上下文。
    with unit_span(inner), observe_generation(inner):
        record_model_invocation(
            inner.invocation(),
            request=ModelTraceRequest(systemPrompt="system", userPrompt="user"),
            result=ModelTraceResult(structuredOutput="ok"),
            usage={"requests": 1},
            duration_ms=1,
            transport_attempts=1,
            prompt_hash="sha256:inner",
        )

    assert not any(
        isinstance(event, ModelInvocationEvent) for event in outer.collectedEvents
    )
    assert sum(
        isinstance(event, ModelInvocationEvent) for event in inner.collectedEvents
    ) == 1


def test_successful_unit_asserts_its_trace_landed(tmp_path) -> None:
    """成功收尾必须留下可被 locate_observation_trace 找到的轨迹文件。

    下游把 observationRunId 写进 receipt，交付期据此解析轨迹。缺失若不在工作单元边界
    拦下，就会很晚才以 FileNotFoundError 暴露：全部块生成成功、Word 已落盘的报告
    会因此整体判 failed。
    """

    from sustainability_desk.llm.ai_observability import (
        ObservationTraceMissingError,
        create_observation_run,
        observe_generation,
    )

    run = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="test-model",
        workload_kind="evaluation",
        report_id=str(uuid4()),
        block_id="report-section:test",
        root=tmp_path,
    )

    # 正常路径：轨迹落盘，收尾不报错。
    with observe_generation(run):
        pass
    assert run.path.is_file()

    # 断言确实由「文件是否存在」驱动：收尾后删掉文件再走一次收尾即触发。
    replay = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="test-model",
        workload_kind="evaluation",
        report_id=str(uuid4()),
        block_id="report-section:test",
        root=tmp_path,
    )
    original_write = Path.write_bytes

    with pytest.raises(ObservationTraceMissingError, match="观测轨迹未落盘"):
        with observe_generation(replay):
            # 模拟收尾写入后轨迹被外部移除（轮转、清理、根被改写）。
            replay.path.parent.mkdir(parents=True, exist_ok=True)
            replay.path.write_text("", encoding="utf-8")
            _unlink_after_finish(replay)

    assert original_write is Path.write_bytes


def _unlink_after_finish(run) -> None:
    """把轨迹文件替换成一个收尾写入后立即消失的路径。"""

    import sustainability_desk.llm.ai_observability as observability

    original = observability._write_event

    def _write_then_remove(target_run, event):
        original(target_run, event)
        if target_run is run and event.eventType == "generation_finished":
            target_run.path.unlink(missing_ok=True)
            observability._write_event = original

    observability._write_event = _write_then_remove
