# ABOUTME: 唯一模型调用出口的观测测试，覆盖完整请求、消息历史、结构化结果与失败详情。
# ABOUTME: 不调用真实模型；验证每次 run_agent 恰好直接写出一条 model_invocation。
import json
import hashlib
from pathlib import Path

import httpx
import pytest
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from sustainability_desk.llm.ai_observability import ModelInvocationEvent, create_observation_run, observe_generation
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.provider_transport import record_provider_http_send
from stage_test_support import TEST_UNIT_STAGE, unit_span


class _Result:
    output = "ok"
    usage = RunUsage(requests=1, input_tokens=9, output_tokens=3)

    def all_messages_json(self) -> bytes:
        return json.dumps(
            [{"role": "assistant", "content": "provider 原始返回"}],
            ensure_ascii=False,
        ).encode()


class _Agent:
    _sustainability_desk_observability_context = {
        "instructions": "system",
        "modelSettings": {"temperature": 0.2},
        "outputSchema": {"type": "string"},
    }

    async def run(self, _prompt: str) -> _Result:
        return _Result()


def _run(root: Path):
    return create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="test.block",
        root=root,
    )


async def test_run_agent_records_property_usage_once(tmp_path: Path) -> None:
    observation = _run(tmp_path)
    with unit_span(observation), observe_generation(observation):
        result = await run_agent(
            _Agent(),
            "用户输入原文",
            observation.invocation(task_context={"answer": "用户输入原文"}),
        )

    invocations = [
        event for event in observation.collectedEvents if isinstance(event, ModelInvocationEvent)
    ]
    assert result.output == "ok"
    assert len(invocations) == 1
    assert invocations[0].inputTokens == 9
    assert invocations[0].outputTokens == 3
    assert invocations[0].transportAttempts == 1
    assert invocations[0].request.systemPrompt == "system"
    assert invocations[0].request.userPrompt == "用户输入原文"
    assert invocations[0].request.taskContext == {"answer": "用户输入原文"}
    assert invocations[0].result.structuredOutput == "ok"
    assert invocations[0].result.messageHistory == [
        {"role": "assistant", "content": "provider 原始返回"}
    ]


async def test_run_agent_preserves_pydantic_ai_deps_and_history(tmp_path: Path) -> None:
    class ToolAgent(_Agent):
        def __init__(self) -> None:
            self.kwargs = {}

        async def run(self, _prompt: str, **kwargs) -> _Result:
            self.kwargs = kwargs
            return _Result()

    agent = ToolAgent()
    observation = _run(tmp_path)
    deps = object()
    with unit_span(observation), observe_generation(observation):
        await run_agent(
            agent,
            "使用领域工具",
            observation.invocation(),
            deps=deps,
            message_history=["previous"],
        )

    assert agent.kwargs == {
        "deps": deps,
        "message_history": ["previous"],
    }


async def test_run_agent_redacts_ephemeral_value_from_trace(tmp_path: Path) -> None:
    signed_url = "https://storage.example/private.pdf?token=secret"

    class SignedUrlResult(_Result):
        def all_messages_json(self) -> bytes:
            return json.dumps([{"content": signed_url}]).encode()

    class SignedUrlAgent(_Agent):
        async def run(self, _prompt, **_kwargs) -> SignedUrlResult:
            return SignedUrlResult()

    observation = _run(tmp_path)
    with unit_span(observation), observe_generation(observation):
        await run_agent(
            SignedUrlAgent(),
            [{"url": signed_url}],
            observation.invocation(),
            sensitive_values=(signed_url,),
        )

    invocation = next(
        event for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    )
    assert signed_url not in invocation.request.userPrompt
    assert signed_url not in json.dumps(invocation.result.messageHistory)
    assert "[REDACTED_EPHEMERAL_VALUE]" in invocation.request.userPrompt


async def test_run_agent_excludes_model_reasoning_but_preserves_tool_history(
    tmp_path: Path,
) -> None:
    class ReasoningResult(_Result):
        def all_messages_json(self) -> bytes:
            return json.dumps([
                {
                    "role": "assistant",
                    "parts": [
                        {"part_kind": "thinking", "content": "private chain of thought"},
                        {"part_kind": "tool-call", "tool_name": "view_sources", "args": {}},
                        {"part_kind": "text", "content": "已整理。", "reasoning_content": "private"},
                    ],
                }
            ]).encode()

    class ReasoningAgent(_Agent):
        async def run(self, _prompt, **_kwargs) -> ReasoningResult:
            return ReasoningResult()

    observation = _run(tmp_path)
    with unit_span(observation), observe_generation(observation):
        await run_agent(
            ReasoningAgent(),
            "整理资料",
            observation.invocation(),
        )

    invocation = next(
        event for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    )
    history = json.dumps(invocation.result.messageHistory, ensure_ascii=False)
    assert "private chain of thought" not in history
    assert '"reasoning_content"' not in history
    assert "view_sources" in history
    assert "已整理。" in history


async def test_run_agent_replaces_binary_prompt_and_history_with_descriptors(
    tmp_path: Path,
) -> None:
    image_bytes = b"RAW_IMAGE_SENTINEL"
    opaque_bytes = b"RAW_BYTES_SENTINEL"

    class BinaryResult(_Result):
        def all_messages_json(self) -> bytes:
            return ModelMessagesTypeAdapter.dump_json([
                ModelRequest(parts=[
                    UserPromptPart(content=[
                        BinaryContent(data=image_bytes, media_type="image/png")
                    ])
                ])
            ])

    class BinaryAgent(_Agent):
        async def run(self, _prompt, **_kwargs) -> BinaryResult:
            return BinaryResult()

    observation = _run(tmp_path)
    with unit_span(observation), observe_generation(observation):
        await run_agent(
            BinaryAgent(),
            [
                BinaryContent(data=image_bytes, media_type="image/png"),
                opaque_bytes,
            ],
            observation.invocation(),
        )

    invocation = next(
        event
        for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    )
    trace_text = json.dumps(invocation.model_dump(mode="json"), ensure_ascii=False)
    assert "RAW_IMAGE_SENTINEL" not in trace_text
    assert "RAW_BYTES_SENTINEL" not in trace_text

    prompt = json.loads(invocation.request.userPrompt)
    assert prompt == [
        {
            "kind": "binary_descriptor",
            "mediaType": "image/png",
            "byteLength": len(image_bytes),
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
        },
        {
            "kind": "binary_descriptor",
            "mediaType": "application/octet-stream",
            "byteLength": len(opaque_bytes),
            "sha256": hashlib.sha256(opaque_bytes).hexdigest(),
        },
    ]
    history_descriptor = invocation.result.messageHistory[0]["parts"][0]["content"][0]
    assert history_descriptor == prompt[0]


class _FailingAgent:
    _sustainability_desk_observability_context = {"instructions": "system", "modelSettings": {}}

    async def run(self, _prompt: str) -> _Result:
        raise RuntimeError("内部错误 /Users/dexter/private")


async def test_run_agent_records_non_http_failure_with_complete_request(tmp_path: Path) -> None:
    observation = _run(tmp_path)
    with pytest.raises(RuntimeError):
        with unit_span(observation), observe_generation(observation):
            await run_agent(
                _FailingAgent(),
                "password=TopSecret123",
                observation.invocation(),
            )

    invocation = next(
        event for event in observation.collectedEvents if isinstance(event, ModelInvocationEvent)
    )
    assert invocation.errorCode == "RuntimeError"
    assert invocation.request.userPrompt == "password=TopSecret123"
    assert invocation.request.systemPrompt == "system"
    assert invocation.result.error is not None
    assert invocation.result.error.type == "RuntimeError"
    assert invocation.result.error.message == "内部错误 /Users/dexter/private"


async def test_run_agent_records_partial_messages_cause_chain_and_http_sends_on_failure(
    tmp_path: Path,
) -> None:
    def call_failing_tool(_messages, _info) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(
            "fail_transport",
            {"value": "probe-value"},
            tool_call_id="transport-probe",
        )])

    agent = Agent(FunctionModel(call_failing_tool), output_type=str)
    setattr(
        agent,
        "_sustainability_desk_observability_context",
        {"instructions": "system", "modelSettings": {}},
    )

    @agent.tool_plain
    async def fail_transport(value: str) -> str:
        request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
        await record_provider_http_send(request)
        await record_provider_http_send(request)
        try:
            raise httpx.ConnectTimeout("TLS handshake timed out")
        except httpx.ConnectTimeout as cause:
            raise ModelAPIError("qwen3.7-plus", "Connection error.") from cause

    observation = _run(tmp_path)
    with pytest.raises(ModelAPIError):
        with unit_span(observation), observe_generation(observation):
            await run_agent(agent, "触发连接探针", observation.invocation())

    invocation = next(
        event for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    )
    history = json.dumps(invocation.result.messageHistory, ensure_ascii=False)
    assert "fail_transport" in history
    assert "probe-value" in history
    assert invocation.httpSendAttempts == 2
    assert invocation.result.error is not None
    assert [cause.type for cause in invocation.result.error.causes] == [
        "ConnectTimeout"
    ]
    assert invocation.result.error.causes[0].message == "TLS handshake timed out"


class _TransientAgent(_Agent):
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _prompt: str) -> _Result:
        self.calls += 1
        if self.calls == 1:
            raise ModelHTTPError(429, "qwen3.7-plus", {"requestId": "provider-req-1"})
        return _Result()


async def test_run_agent_preserves_transient_provider_error_before_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("sustainability_desk.llm.concurrency.asyncio.sleep", _no_sleep)
    observation = _run(tmp_path)
    with unit_span(observation), observe_generation(observation):
        await run_agent(_TransientAgent(), "用户输入原文", observation.invocation())

    invocation = next(
        event
        for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    )
    assert invocation.transportAttempts == 2
    assert invocation.result.transportErrors[0].statusCode == 429
    assert invocation.result.transportErrors[0].body == {"requestId": "provider-req-1"}
