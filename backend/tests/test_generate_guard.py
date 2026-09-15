# ABOUTME: paragraph 生成入口以 typed EvidencePosture 区分企业事实与 context_only。
# ABOUTME: 缺少实质企业证据不再从 constrained blockType 推导省略。
from pathlib import Path
from types import SimpleNamespace

import pytest

from sustainability_desk.contract.models import Block, Field, Inline, IntakeItem, Report, Section
from sustainability_desk.llm.ai_observability import (
    GuardrailEvaluationEvent,
    ModelInvocationEvent,
    create_observation_run,
    observe_generation,
)
from sustainability_desk.llm.generate import GeneratedParagraphVariants, generate_variants
from sustainability_desk.llm.generation_guardrails import GuardrailViolation
from sustainability_desk.planner import load_topic_intake
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def observation(tmp_path: Path):
    run = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="test.generate",
        root=tmp_path,
    )
    with unit_span(run), observe_generation(run):
        yield run


def _blk(block_type: str, intake_items: list[str] | None) -> Block:
    generation = {"task": {"focus": "x"}}
    if intake_items is not None:
        generation["inputs"] = {
            "evidence": {"kind": "explicit", "intakeItems": intake_items}
        }
    return Block(
        id="x",
        type="paragraph",
        blockType=block_type,
        source="ai",
        generation=generation,
    )


def test_constrained_without_substantive_evidence_prepares_context_only() -> None:
    from sustainability_desk.llm.generate import _template, prepare_generation_context

    report = _template(SSE_PACKAGE)
    block, context = prepare_generation_context("company_intro.body", report)

    assert block.blockType == "constrained"
    assert context.evidence.substantive_input_present is False
    assert context.evidence_posture.level == "context_only"


async def test_single_block_generation_rejects_hidden_block_before_llm(
    monkeypatch, observation
) -> None:
    from sustainability_desk.llm.generate import _template

    report = _template(SSE_PACKAGE)
    intake = load_topic_intake(SSE_PACKAGE)
    climate_intake = []
    for item in intake:
        if item.contentScopeId != "climate_change":
            continue
        if item.key == "climate.q_training_activities":
            item = item.model_copy(update={"answer": "否"})
        climate_intake.append(item)
    report = report.model_copy(update={"intakeItems": climate_intake})

    def _unexpected_agent(*_args, **_kwargs):
        raise AssertionError("hidden block reached LLM")

    monkeypatch.setattr("sustainability_desk.llm.generate.build_agent", _unexpected_agent)
    with pytest.raises(ValueError, match="当前不可见"):
        await generate_variants(
            "climate.iro_training", report, n=1, observation=observation
        )


async def test_context_only_intake_backed_paragraph_still_uses_model_generation(
    monkeypatch, observation
) -> None:
    block = Block(
        id="topic.gov",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation={
            "task": {"focus": "topic.gov"},
            "inputs": {"evidence": {"kind": "explicit", "intakeItems": ["topic.q"]}},
        },
        content=[Inline(kind="text", text="治理职责：形成正文。")],
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_short_name": Field(
                key="company_short_name",
                label="公司简称",
                type="string",
                source="user_input",
                value="测试公司",
            )
        },
        intakeItems=[IntakeItem(key="topic.q", contentScopeId="topic", prompt="q", kind="text")],
        sections=[
            Section(
                key="topic",
                title="测试议题",
                headingLevel=2,
                reportSectionId="topic",
                children=[Section(key="topic.gov", title="治理", headingLevel=3, blocks=[block])],
            )
        ],
    )

    monkeypatch.setattr("sustainability_desk.llm.generate._template", lambda *_: report)
    agent = _VariantsAgent([
        [
            "相关治理工作通常可从职责边界、决策流程和监督机制等方面逐步完善。",
            "企业可结合业务特点识别相关治理要求，并将其作为后续管理能力建设的关注方向。",
            "相关议题可围绕治理架构、风险识别和持续改进等方面形成管理思路。",
        ]
    ])
    monkeypatch.setattr("sustainability_desk.llm.generate.build_agent", lambda *_args, **_kwargs: agent)
    variants = await generate_variants(
        "topic.gov",
        report,
        n=3,
        model_id="qwen3.7-plus",
        observation=observation,
        allow_synthetic_definition_fallback=True,
    )
    invocations = [
        event for event in observation.collectedEvents if isinstance(event, ModelInvocationEvent)
    ]

    assert len(variants) == 3
    assert all("测试公司" not in variant.content for variant in variants)
    assert len(invocations) == 1


class _VariantsAgent:
    """假 Pydantic AI Agent：每次 run 按调用序返回一组 variants（模拟多次尝试）。"""

    def __init__(self, variants: list[list[str]]):
        self._variants = variants
        self.calls = 0

    async def run(self, _user, **_kwargs):
        idx = min(self.calls, len(self._variants) - 1)
        self.calls += 1
        return SimpleNamespace(output=GeneratedParagraphVariants(
            variants=[{"content": content} for content in self._variants[idx]]
        ))


async def test_each_guardrail_retry_is_observed_as_a_model_invocation(monkeypatch, observation) -> None:
    block = Block(
        id="p.must",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "p.must"}},
        content=[Inline(kind="text", text="测试段落")],
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[block])])
    agent = _VariantsAgent([
        ["公司计划到2030年完成相关工作。"],
        ["相关工作可围绕治理职责、执行流程与持续改进形成完整的管理思路。"],
    ])

    monkeypatch.setattr("sustainability_desk.llm.generate._template", lambda *_: report)
    monkeypatch.setattr("sustainability_desk.llm.generate.build_agent", lambda *_args, **_kwargs: agent)
    out = await generate_variants(
        "p.must",
        report,
        n=1,
        model_id="qwen3.7-plus",
        observation=observation,
        allow_synthetic_definition_fallback=True,
    )
    invocations = [
        event for event in observation.collectedEvents if isinstance(event, ModelInvocationEvent)
    ]
    evaluations = [
        event
        for event in observation.collectedEvents
        if isinstance(event, GuardrailEvaluationEvent)
    ]

    assert [variant.content for variant in out] == [
        "相关工作可围绕治理职责、执行流程与持续改进形成完整的管理思路。"
    ]
    assert len(invocations) == 2
    assert [event.invocationOrdinal for event in invocations] == [1, 2]
    assert [event.status for event in evaluations] == ["rejected", "accepted"]
    assert evaluations[0].issues[0].key == "unsupported_numeric_claim"
    assert evaluations[0].issues[0].evidence == "2030年"
    assert "2030年" in evaluations[0].retryInstruction
    assert evaluations[1].retryInstruction == ""
    assert invocations[0].request.taskContext is not None
    assert invocations[0].result.structuredOutput == {
        "variants": [
            {"displayTitle": None, "content": "公司计划到2030年完成相关工作。"}
        ]
    }


async def test_exhausted_guardrail_retries_preserve_every_rejected_output(
    monkeypatch,
    observation,
) -> None:
    block = Block(
        id="p.failed",
        type="paragraph",
        blockType="generative",
        source="ai",
        generation={"task": {"focus": "p.failed"}},
        content=[Inline(kind="text", text="测试段落")],
    )
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[block])],
    )
    agent = _VariantsAgent(
        [
            ["公司计划到2030年完成第一项工作。"],
            ["公司计划到2031年完成第二项工作。"],
            ["公司计划到2032年完成第三项工作。"],
        ]
    )
    monkeypatch.setattr("sustainability_desk.llm.generate._template", lambda *_: report)
    monkeypatch.setattr(
        "sustainability_desk.llm.generate.build_agent", lambda *_args, **_kwargs: agent
    )

    with pytest.raises(GuardrailViolation):
        await generate_variants(
            "p.failed",
            report,
            n=1,
            model_id="qwen3.7-plus",
            observation=observation,
            allow_synthetic_definition_fallback=True,
        )

    invocations = [
        event
        for event in observation.collectedEvents
        if isinstance(event, ModelInvocationEvent)
    ]
    evaluations = [
        event
        for event in observation.collectedEvents
        if isinstance(event, GuardrailEvaluationEvent)
    ]
    assert len(invocations) == 3
    assert [
        event.result.structuredOutput["variants"][0]["content"]
        for event in invocations
    ] == [
        "公司计划到2030年完成第一项工作。",
        "公司计划到2031年完成第二项工作。",
        "公司计划到2032年完成第三项工作。",
    ]
    assert [event.status for event in evaluations] == [
        "rejected",
        "rejected",
        "rejected",
    ]
    assert evaluations[-1].retryInstruction == ""


def test_generated_variants_parse_stringified_array_at_contract_boundary() -> None:
    """Qwen 经工具调用把 variants 数组整体（或逐元素）序列化成 JSON 字符串时，合同边界先解析再校验。

    company_intro.body 会连续返回字符串化数组，输出重试无效，不解析即整次生成失败。
    """

    stringified_array = GeneratedParagraphVariants.model_validate(
        {"variants": '[{"displayTitle": null, "content": "公司成立于 2010 年。"}]'}
    )
    assert [variant.content for variant in stringified_array.variants] == ["公司成立于 2010 年。"]

    stringified_items = GeneratedParagraphVariants.model_validate(
        {"variants": ['{"content": "版本一"}', {"content": "版本二"}]}
    )
    assert [variant.content for variant in stringified_items.variants] == ["版本一", "版本二"]

    with pytest.raises(ValueError):
        GeneratedParagraphVariants.model_validate({"variants": "不是 JSON 的字符串"})
