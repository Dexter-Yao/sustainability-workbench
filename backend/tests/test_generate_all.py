# ABOUTME: 生成编排总控单测——收集可生成块、并发分派、空表省略、合同失败隔离与汇总。
# ABOUTME: 用假生成函数（monkeypatch generate_variants/generate_table），只验证编排逻辑，不打真实 LLM。
import logging

import sustainability_desk.llm.generate_all as GA
from sustainability_desk.contract.models import Block, GsColDef, GsTable, Report, Section
from sustainability_desk.llm.ai_observability import create_observation_run
from sustainability_desk.llm.generate import GeneratedParagraphVariant
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE


def _observation():
    return create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="test.generate_all",
    )


async def _generate_all(*args, observation=None, **kwargs):
    """v3 起模型调用必须归属工作单元 span；测试统一在此开根 span。"""
    obs = observation if observation is not None else _observation()
    with unit_span(obs):
        return await GA.generate_all(*args, observation=obs, **kwargs)


def _report() -> Report:
    cols = [GsColDef(key="name", header="名称", cellType="text")]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="p.gen", type="paragraph", blockType="generative", source="ai",
              generation={"task": {"focus": "x"}}),
        Block(id="p.con", type="paragraph", blockType="constrained", source="ai",
              generation={"task": {"focus": "y"}, "inputs": {"evidence": {"kind": "explicit", "intakeItems": ["foo"]}}}),
        Block(id="t.tbl", type="table", blockType="generative", source="ai",
              generation={"task": {"focus": "z"}}, table=GsTable(colDefs=cols)),
        Block(id="p.fixed", type="paragraph", blockType="fixed", source="template", content=[]),
        Block(id="p.slot", type="paragraph", blockType="slot", source="user_input", content=[]),
    ])])


def _patch_ok(monkeypatch):
    async def _variants(block_id, report, n=3, **_kwargs):
        return [GeneratedParagraphVariant(content=f"{block_id}-v{i}") for i in range(n)]

    async def _table(block_id, report, **_kwargs):
        return [{"type": "tr", "state": "ready",
                 "children": [{"type": "td", "colKey": "name", "value": block_id}]}]

    monkeypatch.setattr(GA, "generate_variants", _variants)
    monkeypatch.setattr(GA, "generate_table", _table)


def _by_id(results):
    return {r["blockId"]: r for r in results}


async def test_generates_every_generable_block_and_skips_others(monkeypatch):
    """只对 constrained/generative 且有 generation 的块生成；fixed/slot 不纳入。"""
    _patch_ok(monkeypatch)
    ids = {
        r["blockId"]
        for r in await _generate_all(_report(), observation=_observation())
    }
    assert ids == {"p.gen", "p.con", "t.tbl"}


async def test_explicit_block_plan_only_dispatches_authorized_model_tasks(monkeypatch):
    """自动建报只调度冻结计划明确授权的 Block。"""
    _patch_ok(monkeypatch)

    ids = {
        result["blockId"]
        for result in await _generate_all(
            _report(),
            block_ids=frozenset({"p.gen", "t.tbl"}),
            observation=_observation(),
        )
    }

    assert ids == {"p.gen", "t.tbl"}


async def test_hidden_block_not_generated(monkeypatch):
    """appears_when 不满足的块隐身即不生成（不进结果）——隐身块进 LLM 既浪费又有泄漏风险。"""
    from sustainability_desk.contract.models import Condition, ConditionRule, IntakeItem

    _patch_ok(monkeypatch)
    rep = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        intakeItems=[IntakeItem(key="k", contentScopeId="t", prompt="q", kind="single_select",
                                options=["开展过", "未开展"], answer="未开展")],
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[
            Block(id="p.shown", type="paragraph", blockType="generative", source="ai",
                  generation={"task": {"focus": "x"}}),
            Block(id="p.hidden", type="paragraph", blockType="generative", source="ai",
                  appears_when=Condition(all=[ConditionRule(path="intakeItems.k", op="eq", value="开展过")]),
                  generation={"task": {"focus": "y"}}),
        ])],
    )
    ids = {
        r["blockId"] for r in await _generate_all(rep, observation=_observation())
    }
    assert "p.shown" in ids
    assert "p.hidden" not in ids, "隐身块不应进入生成"


async def test_metric_source_condition_excludes_narrative_when_any_value_exists(monkeypatch):
    """指标有值时，编译后的可见性合同直接排除正文任务；Prompt 不承担条件分支。"""
    _patch_ok(monkeypatch)
    report = Report.model_validate(
        {
            "title": "t",
            "meta": {
                "quantitativeMetrics": {
                    "metrics": {
                        "economic_environment_r11": {"value": "123.45"},
                        "economic_environment_r17": {"value": None},
                    }
                }
            },
            "sections": [
                {
                    "key": "energy.metrics",
                    "title": "指标与目标",
                    "headingLevel": 1,
                    "blocks": [
                        {
                            "id": "energy.metrics.image",
                            "type": "image",
                            "blockType": "fixed",
                            "source": "derived",
                            "image": {
                                "derivedVisualization": {
                                    "kind": "quantitative_metric_summary",
                                    "metricKeys": ["economic_environment_r11", "economic_environment_r17"],
                                }
                            },
                        },
                        {
                            "id": "energy.metrics.body",
                            "type": "paragraph",
                            "blockType": "constrained",
                            "source": "ai",
                            "generation": {
                                "task": {"mode": "metric_narrative", "focus": "energy.metrics.body"},
                                "inputs": {
                                    "evidence": {
                                        "kind": "explicit",
                                        "quantitativeMetrics": ["economic_environment_r11", "economic_environment_r17"],
                                    }
                                },
                            },
                            "appears_when": {
                                "all": [
                                    {"path": "quantitativeMetrics.economic_environment_r11", "op": "not_exists"},
                                    {"path": "quantitativeMetrics.economic_environment_r17", "op": "not_exists"},
                                ]
                            },
                        },
                    ],
                }
            ],
        }
    )

    results = await _generate_all(report, observation=_observation())

    assert results == []


async def test_blocks_under_hidden_section_not_generated(monkeypatch):
    """section 级隐藏时整棵子树不进入生成；隐藏事实只由 visible 统一判断。"""
    from sustainability_desk.contract.models import Condition, ConditionRule, Field

    _patch_ok(monkeypatch)
    rep = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={"flag": Field(key="flag", label="flag", type="string", source="user_input", value=None)},
        sections=[
            Section(
                key="hidden",
                title="Hidden",
                headingLevel=1,
                appears_when=Condition(all=[ConditionRule(path="fields.flag.value", op="exists")]),
                blocks=[
                    Block(id="p.hidden.child", type="paragraph", blockType="generative", source="ai",
                          generation={"task": {"focus": "x"}}),
                ],
            ),
            Section(
                key="shown",
                title="Shown",
                headingLevel=1,
                blocks=[
                    Block(id="p.shown.child", type="paragraph", blockType="generative", source="ai",
                          generation={"task": {"focus": "y"}}),
                ],
            ),
        ],
    )

    ids = {
        r["blockId"] for r in await _generate_all(rep, observation=_observation())
    }
    assert ids == {"p.shown.child"}


async def test_paragraph_yields_variants_table_yields_rows(monkeypatch):
    """段落块产 typed variants、表块产 rows，kind 标注正确，状态 ready。"""
    _patch_ok(monkeypatch)
    by = _by_id(
        await _generate_all(_report(), n=2, observation=_observation())
    )
    assert by["p.gen"]["kind"] == "paragraph"
    assert by["p.gen"]["variants"] == [
        {"displayTitle": None, "content": "p.gen-v0"},
        {"displayTitle": None, "content": "p.gen-v1"},
    ]
    assert by["p.gen"]["status"] == "ready"
    assert by["t.tbl"]["kind"] == "table"
    assert by["t.tbl"]["rows"][0]["children"][0]["value"] == "t.tbl"
    assert by["t.tbl"]["status"] == "ready"


async def test_empty_table_can_be_explicitly_omitted_for_automatic_report_runs(monkeypatch):
    """自动建报把零数据行表格记录为合同省略，不伪装为 ready。"""

    async def empty_table(*_args, **_kwargs):
        return []

    async def variants(block_id, report, n=3, **_kwargs):
        return [GeneratedParagraphVariant(content=f"{block_id}-v0")]

    monkeypatch.setattr(GA, "generate_table", empty_table)
    monkeypatch.setattr(GA, "generate_variants", variants)

    result = _by_id(
        await _generate_all(
            _report(),
            observation=_observation(),
            empty_table_policy="omit",
        )
    )["t.tbl"]

    assert result == {
        "blockId": "t.tbl",
        "kind": "table",
        "fileRoutingDisposition": "no_applicable_file_dossier",
        "status": "omitted",
        "reason": "当前表格缺少可披露的用户资料，已按报告合同省略。",
        "rows": [],
    }


async def test_paragraph_contract_error_is_blocked_and_isolated(monkeypatch):
    """单个 paragraph 合同错误归 blocked；不影响其他独立 Block。"""
    async def fake_variants(block_id, report, n=3, **_kwargs):
        if block_id == "p.con":
            raise ValueError(f"块 {block_id} 不满足当前可见性合同")
        return [GeneratedParagraphVariant(content=f"{block_id}-v0")]

    async def fake_table(block_id, report, **_kwargs):
        return [{"type": "tr", "state": "ready", "children": []}]

    monkeypatch.setattr(GA, "generate_variants", fake_variants)
    monkeypatch.setattr(GA, "generate_table", fake_table)
    by = _by_id(await _generate_all(_report(), observation=_observation()))
    assert by["p.con"]["status"] == "blocked"
    assert "可见性合同" in by["p.con"]["reason"]
    assert by["p.gen"]["status"] == "ready"


async def test_block_callbacks_follow_each_fan_out_task_and_keep_result_order(monkeypatch):
    """运行收据回调必须覆盖所有已调度 Block，不允许并发生成变成无进度的黑盒。"""
    _patch_ok(monkeypatch)
    started: list[str] = []
    completed: list[tuple[str, str]] = []

    async def on_started(block_id: str) -> None:
        started.append(block_id)

    async def on_completed(block_id: str, result: dict) -> None:
        completed.append((block_id, result["status"]))

    results = await _generate_all(
        _report(),
        observation=_observation(),
        max_concurrency=3,
        on_block_started=on_started,
        on_block_completed=on_completed,
    )

    result_ids = [item["blockId"] for item in results]
    assert set(started) == set(result_ids)
    assert {item[0] for item in completed} == set(result_ids)
    assert all(status == "ready" for _, status in completed)


async def test_generation_failure_isolated_as_failed(monkeypatch):
    """某块生成抛非 ValueError 异常 → status=failed 隔离；其余块成功。"""
    async def fake_table(block_id, report, **_kwargs):
        raise RuntimeError("LLM 超时")

    async def fake_variants(block_id, report, n=3, **_kwargs):
        return [GeneratedParagraphVariant(content=f"{block_id}-v0")]

    monkeypatch.setattr(GA, "generate_variants", fake_variants)
    monkeypatch.setattr(GA, "generate_table", fake_table)
    by = _by_id(await _generate_all(_report(), observation=_observation()))
    assert by["t.tbl"]["status"] == "failed"
    assert by["p.gen"]["status"] == "ready"
    assert by["p.con"]["status"] == "ready"


async def test_generate_all_logs_warning_on_failure(monkeypatch, caplog):
    """生成失败隔离时记 warning（含 block_id），不静默。"""
    async def boom(block_id, report, n=3, **_kwargs):
        raise RuntimeError("boom")

    async def _table(block_id, report, **_kwargs):
        return []

    monkeypatch.setattr(GA, "generate_variants", boom)
    monkeypatch.setattr(GA, "generate_table", _table)
    with caplog.at_level(logging.WARNING, logger="sustainability_desk.llm.generate_all"):
        await _generate_all(_report(), observation=_observation())
    assert any("p.gen" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_api_generate_all_route_is_removed():
    """公开 /api/generate-all 已删除；离线 eval 继续直接调用 generate_all。"""
    import sustainability_desk.api.app as APP

    paths = {route.path for route in APP.app.routes if hasattr(route, "path")}
    assert "/api/generate-all" not in paths


# —— IRO 阶段：先于其余块生成，其结论供议题章节参照；缺失不阻断 ——


def _iro_stage_report() -> Report:
    """含 IRO 表与一个普通段落块的报告（IRO 表按契约声明子行展开）。"""
    from sustainability_desk.contract.models import (
        AssessmentResult,
        GenerationSpec,
        GenerationTask,
        RowExpansion,
        RowExpansionUnit,
        ScoredAssessmentResult,
    )

    cols = [
        GsColDef(key="iro_topic", header="议题", cellType="text"),
        GsColDef(key="iro_desc", header="描述", cellType="ai_text"),
    ]
    iro_block = Block(
        id="sm.iro_table",
        type="table",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task=GenerationTask(focus="IRO"),
            producesConclusion="topic_iro",
            rowMode="expanded_rows",
            rowExpansion=RowExpansion(
                sharedColumnKeys=["iro_topic"],
                units=[
                    RowExpansionUnit(key="impact", label="影响描述", columnKeys=["iro_desc"]),
                    RowExpansionUnit(
                        key="risk_opportunity", label="风险与机遇描述", columnKeys=["iro_desc"]
                    ),
                ],
            ),
        ),
        table=GsTable(rowSource="assessment_iro", colDefs=cols),
    )
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        assessment=AssessmentResult(
            reportingYear=2025,
            topics=[
                ScoredAssessmentResult(
                    determination="scored",
                    assessmentTopicId="climate_change",
                    materiality="dual",
                    financialScore=4.6,
                    impactScore=4.5,
                )
            ],
        ),
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[
            iro_block,
            Block(id="p.topic", type="paragraph", blockType="generative", source="ai",
                  generation={"task": {"focus": "议题正文"}}),
        ])],
    )


async def test_iro_table_generates_before_other_blocks(monkeypatch):
    """IRO 表先于其余块生成——其结论是议题章节的方向参照，必须先落定。"""
    order: list[str] = []

    async def _variants(block_id, report, n=3, **_kwargs):
        order.append(block_id)
        return [GeneratedParagraphVariant(content="正文")]

    async def _table(block_id, report, **_kwargs):
        order.append(block_id)
        return [
            {"type": "tr", "state": "ready", "children": [
                {"type": "td", "colKey": "iro_topic", "value": "应对气候变化", "rowSpan": 2},
                {"type": "td", "colKey": "iro_desc", "value": "对外部环境的影响。"}]},
            {"type": "tr", "state": "ready", "children": [
                {"type": "td", "colKey": "iro_desc", "value": "对公司的风险与机遇。"}]},
        ]

    monkeypatch.setattr(GA, "generate_variants", _variants)
    monkeypatch.setattr(GA, "generate_table", _table)

    results = await _generate_all(_iro_stage_report(), n=1, observation=_observation())

    assert order == ["sm.iro_table", "p.topic"]
    assert all(res["status"] == "ready" for res in results)


async def test_generated_iro_conclusions_reach_downstream_blocks(monkeypatch):
    """阶段二的块能从在途 Report 解析出本次 IRO 结论（否则方向参照永远为空）。"""
    from sustainability_desk.contract.iro_conclusions import iro_conclusions_by_topic

    seen: dict[str, dict] = {}

    async def _variants(block_id, report, n=3, **_kwargs):
        seen[block_id] = iro_conclusions_by_topic(report)
        return [GeneratedParagraphVariant(content="正文")]

    async def _table(block_id, report, **_kwargs):
        return [
            {"type": "tr", "state": "ready", "children": [
                {"type": "td", "colKey": "iro_topic", "value": "应对气候变化", "rowSpan": 2},
                {"type": "td", "colKey": "iro_desc", "value": "对外部环境的影响。"}]},
            {"type": "tr", "state": "ready", "children": [
                {"type": "td", "colKey": "iro_desc", "value": "对公司的风险与机遇。"}]},
        ]

    monkeypatch.setattr(GA, "generate_variants", _variants)
    monkeypatch.setattr(GA, "generate_table", _table)

    await _generate_all(_iro_stage_report(), n=1, observation=_observation())

    conclusion = seen["p.topic"]["应对气候变化"]
    assert conclusion.impact_summary == "对外部环境的影响。"
    assert conclusion.risk_opportunity_summary == "对公司的风险与机遇。"


async def test_failed_iro_table_does_not_block_other_blocks(monkeypatch):
    """IRO 表失败只是少一层方向校准；议题章节有自身资料与合同，照常生成。"""
    async def _variants(block_id, report, n=3, **_kwargs):
        return [GeneratedParagraphVariant(content="正文")]

    async def _table(block_id, report, **_kwargs):
        raise RuntimeError("IRO 生成失败")

    monkeypatch.setattr(GA, "generate_variants", _variants)
    monkeypatch.setattr(GA, "generate_table", _table)

    results = await _generate_all(_iro_stage_report(), n=1, observation=_observation())
    by_id = {res["blockId"]: res for res in results}

    assert by_id["sm.iro_table"]["status"] == "failed"
    assert by_id["p.topic"]["status"] == "ready"


async def test_stage_order_follows_contract_declaration_not_block_id(monkeypatch):
    """阶段划分只读契约 producesConclusion；编排器不认识任何具体 block id。

    这里让一个与 IRO 无关的块声明产出结论，它同样应先跑——证明机制是通用的。
    """
    from sustainability_desk.contract.models import GenerationSpec, GenerationTask

    order: list[str] = []

    async def _variants(block_id, report, n=3, **_kwargs):
        order.append(block_id)
        return [GeneratedParagraphVariant(content="正文")]

    monkeypatch.setattr(GA, "generate_variants", _variants)

    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="p.downstream", type="paragraph", blockType="generative", source="ai",
              generation={"task": {"focus": "下游"}}),
        Block(id="p.upstream", type="paragraph", blockType="generative", source="ai",
              generation=GenerationSpec(
                  task=GenerationTask(focus="上游结论"),
                  producesConclusion="topic_iro",
              )),
    ])])

    await _generate_all(report, n=1, observation=_observation())

    # 声明在后、id 靠后，但因契约声明而先跑。
    assert order == ["p.upstream", "p.downstream"]


def test_duplicate_conclusion_producer_is_rejected_at_compile_time():
    """同一结论有两个产出方会让阶段划分产生歧义，编译期 fail-closed。"""
    import pytest

    from sustainability_desk.contract.compiled_definition import (
        CompiledGenerationContract,
        ContractCompileError,
        _validate_conclusion_wiring,
    )

    def _contract(block_id: str, produces=None):
        return CompiledGenerationContract(
            node_id=f"block/{block_id}",
            block_id=block_id,
            block_type="constrained",
            absence_behavior="generate_context_only",
            semantic_task="t",
            produces_conclusion=produces,
        )

    # 单一产出方：通过。
    _validate_conclusion_wiring({
        "a": _contract("a", "topic_iro"),
        "b": _contract("b"),
    })

    with pytest.raises(ContractCompileError, match="有多个产出方"):
        _validate_conclusion_wiring({
            "a": _contract("a", "topic_iro"),
            "b": _contract("b", "topic_iro"),
        })


async def test_earlier_pillar_text_reaches_later_pillar_context(monkeypatch):
    """议题内按支柱分阶段：治理支柱落定的正文必须出现在 IRO 块的生成上下文里。

    去重指令存在于 IRO 块写作口径，但若各支柱并发生成，
    「治理支柱已披露的事实」在生成时尚不存在，去重指令随即失效。
    """
    from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
    from sustainability_desk.llm.generate import _template
    from sustainability_desk.llm.prompts import build_model_context

    template = _template(SSE_PACKAGE)
    report = template.model_copy(deep=True)
    definition = load_compiled_report_definition(SSE_PACKAGE)
    gov_id = "anti_bribery_anti_corruption.gov_structure_responsibilities"
    iro_id = "anti_bribery_anti_corruption.iro_management_framework"
    seen: dict[str, tuple[str, ...]] = {}

    async def fake_variants(block_id, instance_report, **kwargs):
        seen[block_id] = tuple(
            item.text
            for item in build_model_context(
                instance_report.find_block(block_id),
                template,
                instance_report,
                definition=definition,
            ).prior_disclosures
        )
        return [GeneratedParagraphVariant(content=f"{block_id} 正文")]

    monkeypatch.setattr(GA, "generate_variants", fake_variants)
    await _generate_all(report, block_ids=frozenset({gov_id, iro_id}))

    assert seen[gov_id] == ()
    assert any(gov_id in text for text in seen[iro_id])
