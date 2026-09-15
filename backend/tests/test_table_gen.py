# ABOUTME: 表格生成编排单测——定行/补全/并发隔离/单行重生成；用假 Pydantic AI Agent，不打真实 LLM。
import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

import sustainability_desk.llm.prompts as P
import sustainability_desk.llm.table_gen as TG
from sustainability_desk.contract.models import (
    Block,
    AssessmentResult,
    FixedRowSeed,
    GenerationSpec,
    GenerationTask,
    GsColDef,
    GsTable,
    IntakeItem,
    PresetRowSelection,
    Report,
    RowExpansion,
    RowExpansionUnit,
    ScoredAssessmentResult,
    Section,
)
from sustainability_desk.contract.table_ops import resolve_preset_row_seeds
from sustainability_desk.llm.ai_observability import ModelInvocationEvent, create_observation_run, observe_generation
from sustainability_desk.llm.table_schema import RowSeed, RowSeedList
from stage_test_support import TEST_UNIT_STAGE, unit_span
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.llm.prompt_profiles import prompt_labels

_CURRENT_OBSERVATION = None


@pytest.fixture(autouse=True)
def observation(tmp_path):
    global _CURRENT_OBSERVATION
    run = create_observation_run(TEST_UNIT_STAGE, contract_version="cv-test",
        model_id="qwen3.7-plus",
        workload_kind="evaluation",
        block_id="test.table",
        root=tmp_path,
    )
    with unit_span(run), observe_generation(run):
        _CURRENT_OBSERVATION = run
        yield run
        _CURRENT_OBSERVATION = None


def _observation():
    assert _CURRENT_OBSERVATION is not None
    return _CURRENT_OBSERVATION


def _cells(row: dict) -> dict:
    """从 GsTableRow payload（model_dump）抽取 {colKey: value}，供断言。"""
    return {c["colKey"]: c["value"] for c in row["children"] if c.get("colKey")}


class FakeAgent:
    """假 Pydantic AI Agent：按 output_type 分派定行/补全，run(user) 返回 .output；fail_themes 命中则抛。"""

    def __init__(self, output_type, *, propose, row, table, fail_themes):
        self.output_type = output_type
        self.propose = propose
        self.row = row
        self.table = table
        self.fail_themes = fail_themes

    async def run(self, user, **_kwargs):
        if self.output_type is RowSeedList:
            return SimpleNamespace(output=self.propose)
        for t in self.fail_themes:
            if t in user:
                raise RuntimeError("structured output 失败")
        if "rows" in getattr(self.output_type, "model_fields", {}):
            return SimpleNamespace(output=self.table(self.output_type, user))
        return SimpleNamespace(output=self.row(self.output_type, user))


def _row_factory(schema, user):
    """据动态行 schema 造一个合法实例：select 取首个允许值，str 取含字段名文本。

    嵌套子行模型（rowExpansion）递归构造，使假 Agent 与真实结构化输出同形。
    """
    data = {}
    for name, fld in schema.model_fields.items():
        ann = fld.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):  # 子行嵌套对象
            data[name] = _row_factory(ann, user)
        elif getattr(ann, "__origin__", None) is list:  # multi_select: list[Literal[...]]
            inner = ann.__args__[0]
            data[name] = [inner.__args__[0]]
        elif getattr(ann, "__args__", None):  # single_select: Literal[...]
            data[name] = ann.__args__[0]
        else:
            data[name] = f"文本-{name}"
    return schema(**data)


def _phys_report(*_: object) -> Report:
    cols = [
        GsColDef(key="name", header="名称", cellType="text"),
        GsColDef(key="response", header="应对", cellType="ai_text", genHint="覆盖四类"),
        GsColDef(
            key="value_chain",
            presetFullCoverage=True,
            header="价值链",
            cellType="multi_select",
            options=["上游价值链", "公司运营", "下游价值链"],
            genHint="默认覆盖上游价值链、公司运营、下游价值链，确有明显不适用时再删减",
        ),
    ]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.phys", type="table", blockType="generative", source="ai",
              generation={"task": {"focus": "phys"}, "rowCount": [2, 5]}, table=GsTable(colDefs=cols)),
    ])])


def _fixed_seed_report() -> Report:
    cols = [
        GsColDef(key="risk_type", header="风险类型", cellType="text"),
        GsColDef(key="response", header="应对", cellType="ai_text"),
    ]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.fixed", type="table", blockType="generative", source="ai",
              generation={
                  "task": {"focus": "fixed"},
                  "rowCount": [2, 2],
                  "fixedRowSeeds": [
                      {"theme": "合规与监管风险", "category": "风险"},
                      {"theme": "人员廉洁意识风险", "category": "风险"},
                  ],
              }, table=GsTable(colDefs=cols)),
    ])])


def _assessment_iro_report() -> Report:
    cols = [
        GsColDef(key="iro_topic", header="议题", cellType="text"),
        GsColDef(key="iro_desc", header="影响、风险与机遇描述", cellType="ai_text"),
        GsColDef(
            key="iro_class",
            header="分类",
            cellType="multi_select",
            options=["实际正面影响", "潜在负面影响", "机遇", "风险"],
        ),
        GsColDef(
            key="iro_value_chain",
            header="影响范围",
            cellType="multi_select",
            options=["上游价值链", "公司运营", "下游价值链"],
        ),
        GsColDef(
            key="iro_time_horizon",
            header="影响周期",
            cellType="multi_select",
            options=["短期", "中期", "长期"],
        ),
    ]
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
                ),
                ScoredAssessmentResult(
                    determination="scored",
                    assessmentTopicId="waste_management",
                    materiality="impact",
                    financialScore=3.2,
                    impactScore=4.3,
                ),
                ScoredAssessmentResult(
                    determination="scored",
                    assessmentTopicId="energy_management",
                    materiality="financial",
                    financialScore=4.2,
                    impactScore=3.7,
                ),
            ],
        ),
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[
            Block(
                id="sm.iro_table",
                type="table",
                blockType="constrained",
                source="ai",
                generation={"task": {"focus": "IRO"}},
                table=GsTable(rowSource="assessment_iro", colDefs=cols),
            ),
        ])],
    )


def test_assessment_iro_rows_are_fixed_by_materiality_not_model_proposal() -> None:
    report = _assessment_iro_report()
    block = report.find_block("sm.iro_table")
    assert block is not None

    seeds = TG._assessment_iro_row_seeds(block, report)

    assert [(seed.theme, seed.category) for seed in seeds or []] == [
        ("应对气候变化", "双重重要性"),
        ("能源管理", "财务重要性"),
    ]
    cells = TG._apply_fixed_seed_cells(
        block,
        (seeds or [])[0],
        {"iro_topic": "模型擅自改名", "iro_desc": "行业相关的潜在转型影响"},
    )
    assert cells["iro_topic"] == "应对气候变化"


def _catalog_report() -> Report:
    cols = [
        GsColDef(key="risk_type", header="风险类型", cellType="text"),
        GsColDef(key="risk_name", header="风险名称", cellType="text"),
        GsColDef(key="response", header="应对", cellType="ai_text"),
    ]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.catalog", type="table", blockType="generative", source="ai",
              generation={
                  "task": {"focus": "catalog"},
                  "rowMode": "preset_catalog",
                  "inputs": {"evidence": {"kind": "explicit", "intakeItems": ["t.risk_choices"]}},
                  "fixedRowSeeds": [
                      {"theme": "合规与监管风险", "category": "风险", "referenceImpact": "监管趋严影响合规成本"},
                      {"theme": "人员廉洁意识风险", "category": "风险", "referenceImpact": "员工意识不足带来舞弊风险"},
                  ],
              }, table=GsTable(colDefs=cols, iroKind="risk")),
    ])])


def _selected_catalog_report(answer: list[str] | None, *, unanswered_behavior: str = "hide_all_rows") -> Report:
    report = _catalog_report()
    block = report.find_block("t.catalog")
    assert block and block.generation
    block.generation.presetRowSelection = PresetRowSelection(
        intakeItemKey="t.risk_choices",
        selectionMode="selected_only",
        unansweredBehavior=unanswered_behavior,
    )
    report.intakeItems = [
        IntakeItem(
            key="t.risk_choices",
            contentScopeId="t",
            prompt="请选择风险",
            kind="multi_select",
            options=["合规与监管风险", "人员廉洁意识风险"],
            answer=answer,
        )
    ]
    return report


def test_resolve_preset_row_seeds_uses_structured_selection() -> None:
    report = _selected_catalog_report(["人员廉洁意识风险"])
    block = report.find_block("t.catalog")
    assert block
    assert [seed.theme for seed in resolve_preset_row_seeds(block, report)] == ["人员廉洁意识风险"]


def test_resolve_preset_row_seeds_has_explicit_unanswered_branches() -> None:
    hidden = _selected_catalog_report(None)
    visible = _selected_catalog_report(None, unanswered_behavior="show_all_rows")
    hidden_block = hidden.find_block("t.catalog")
    visible_block = visible.find_block("t.catalog")
    assert hidden_block and visible_block
    assert resolve_preset_row_seeds(hidden_block, hidden) == []
    assert len(resolve_preset_row_seeds(visible_block, visible)) == 2


def _adaptive_catalog_report() -> Report:
    cols = [
        GsColDef(key="risk_category", header="风险与机遇类型", cellType="text"),
        GsColDef(key="risk_name", header="风险与机遇名称", cellType="text"),
        GsColDef(key="impact", header="潜在影响", cellType="ai_text"),
    ]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.adaptive", type="table", blockType="generative", source="ai",
              generation={
                  "task": {"focus": "adaptive"},
                  "rowMode": "adaptive_catalog",
                  "inputs": {"evidence": {"kind": "explicit", "intakeItems": ["t.strategy"]}},
                  "rowCount": [2, 3],
                  "referenceCatalog": [
                      {"category": "风险", "name": "法规政策风险", "reference": "监管趋严影响合规成本"},
                      {"category": "风险", "name": "声誉风险", "reference": "环境事件影响利益相关方评价"},
                      {"category": "机遇", "name": "市场机遇", "reference": "绿色治理能力带来市场认可"},
                  ],
              }, table=GsTable(colDefs=cols, iroKind="risk")),
    ])])


def _catalog_factory(schema, _user):
    row_model = schema.model_fields["rows"].annotation.__args__[0]
    return schema(rows=[
        row_model(risk_type="风险", risk_name="合规与监管风险", response="关注法规变化并完善基础管理"),
        row_model(risk_type="风险", risk_name="人员廉洁意识风险", response="开展廉洁提醒并规范业务行为"),
    ])


def _patch(monkeypatch, *, propose=None, row=None, table=None, fail_themes=()):
    monkeypatch.setattr(
        TG, "build_agent",
        lambda *a, **k: FakeAgent(k["output_type"], propose=propose, row=row, table=table, fail_themes=fail_themes),
    )
    monkeypatch.setattr(TG, "_template_report", _phys_report)


async def test_propose_rows_dedupes_and_bounds(monkeypatch):
    """定行：结构化输出 RowSeedList 经定行校验（去重）。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[
        RowSeed(theme="极端高温"), RowSeed(theme="极端高温"), RowSeed(theme="海平面上升"),
    ]))
    seeds = await TG.propose_rows(
        "t.phys", _phys_report(), observation=_observation()
    )
    assert [s.theme for s in seeds] == ["极端高温", "海平面上升"]


async def test_complete_row_returns_cells_and_drafted(monkeypatch):
    """单行补全返回 cells + state=ready；multi_select 为 list。"""
    _patch(monkeypatch, row=_row_factory)
    out = await TG.complete_row(
        "t.phys", RowSeed(theme="极端高温"), _phys_report(), observation=_observation()
    )
    assert out["state"] == "ready"
    assert out["cells"]["name"] == "文本-name"
    assert out["cells"]["value_chain"] == ["上游价值链", "公司运营", "下游价值链"]


async def test_complete_row_retries_l1_assertion_failure(monkeypatch, observation):
    """单行补全命中 L1 缺失表述后重试，返回第二次合格结果。"""
    calls = {"n": 0}

    def row(schema, user):
        calls["n"] += 1
        data = {}
        for name, fld in schema.model_fields.items():
            ann = fld.annotation
            if getattr(ann, "__origin__", None) is list:
                inner = ann.__args__[0]
                data[name] = [inner.__args__[0]]
            elif getattr(ann, "__args__", None):
                data[name] = ann.__args__[0]
            elif name == "response" and calls["n"] == 1:
                data[name] = "暂未披露具体措施。"
            else:
                data[name] = f"文本-{name}"
        return schema(**data)

    _patch(monkeypatch, row=row)
    out = await TG.complete_row(
        "t.phys", RowSeed(theme="极端高温"), _phys_report(), observation=observation
    )
    invocations = [
        event for event in observation.collectedEvents if isinstance(event, ModelInvocationEvent)
    ]

    assert calls["n"] == 2
    assert out["cells"]["response"] == "文本-response"
    assert len(invocations) == 2


async def test_fill_table_rows_isolates_failures(monkeypatch):
    """行级并发：某行结构化失败 → 标 failed 隔离、其余成功、顺序对应、保留 seed。"""
    _patch(monkeypatch, row=_row_factory, fail_themes=["海平面上升"])
    seeds = [RowSeed(theme="极端高温"), RowSeed(theme="海平面上升"), RowSeed(theme="台风")]
    rows = await TG.fill_table_rows(
        "t.phys", seeds, _phys_report(), max_concurrency=4, observation=_observation()
    )
    assert [r["state"] for r in rows] == ["ready", "failed", "ready"]
    assert all(c["value"] is None for c in rows[1]["children"])  # 失败行各格空
    assert rows[1]["origin"]["theme"] == "海平面上升"  # 失败行保留 seed 供重生成


async def test_propose_rows_truncates_over_max(monkeypatch):
    """propose_rows 端到端：LLM 返回超 max 时经 validate_seeds 截断（_patch 配置 max=5）。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[RowSeed(theme=f"t{i}") for i in range(10)]))
    seeds = await TG.propose_rows(
        "t.phys", _phys_report(), observation=_observation()
    )
    assert len(seeds) == 5


async def test_propose_rows_blocks_under_min(monkeypatch):
    """propose_rows 低于最小行数时阻断，不静默进入人工审阅。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[RowSeed(theme="极端高温")]))
    with pytest.raises(ValueError, match="不足下限"):
        await TG.propose_rows("t.phys", _phys_report(), observation=_observation())


async def test_propose_rows_rejects_non_table_block(monkeypatch):
    """_ensure_generative_table：对非表块抛 ValueError。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[]))
    rep = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="p", type="paragraph", blockType="fixed", source="template", content=[]),
    ])])
    monkeypatch.setattr(TG, "_template_report", lambda *_: rep)
    with pytest.raises(ValueError):
        await TG.propose_rows("p", rep, observation=_observation())


async def test_table_generation_uses_server_template_block(monkeypatch):
    """表格生成以服务端模板表结构为准，客户端实例只证明当前块存在。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[RowSeed(theme="极端高温"), RowSeed(theme="台风")]))
    poisoned = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="t.phys", type="paragraph", blockType="fixed", source="template", content=[]),
    ])])
    seeds = await TG.propose_rows("t.phys", poisoned, observation=_observation())
    assert [s.theme for s in seeds] == ["极端高温", "台风"]


async def test_generate_table_is_propose_plus_fill(monkeypatch):
    """整表 = 定行 + 行级并发补全。"""
    _patch(monkeypatch, propose=RowSeedList(rows=[RowSeed(theme="极端高温"), RowSeed(theme="台风")]),
           row=_row_factory)
    rows = await TG.generate_table(
        "t.phys", _phys_report(), observation=_observation()
    )
    assert len(rows) == 2 and all(r["state"] == "ready" for r in rows)
    assert rows[0]["origin"]["theme"] == "极端高温"


async def test_generate_table_uses_fixed_row_seeds_without_ai_propose(monkeypatch):
    """固定行表直接使用契约声明的 row seeds，不调用 AI 定行。"""
    report = _fixed_seed_report()
    _patch(monkeypatch, row=_row_factory, propose=RowSeedList(rows=[RowSeed(theme="不应使用")]))
    monkeypatch.setattr(TG, "_template_report", lambda *_: report)

    rows = await TG.generate_table("t.fixed", report, observation=_observation())

    assert [row["origin"]["theme"] for row in rows] == ["合规与监管风险", "人员廉洁意识风险"]
    assert [_cells(row)["risk_type"] for row in rows] == ["合规与监管风险", "人员廉洁意识风险"]


async def test_generate_catalog_table_fills_whole_table_once(monkeypatch):
    """目录表初始生成：固定锚点后整表一次填充，不走 AI 定行。"""
    report = _catalog_report()
    _patch(monkeypatch, table=_catalog_factory, propose=RowSeedList(rows=[RowSeed(theme="不应使用")]))
    monkeypatch.setattr(TG, "_template_report", lambda *_: report)

    rows = await TG.generate_table("t.catalog", report, observation=_observation())

    assert [row["origin"]["theme"] for row in rows] == ["合规与监管风险", "人员廉洁意识风险"]
    assert [_cells(row)["response"] for row in rows] == [
        "关注法规变化并完善基础管理",
        "开展廉洁提醒并规范业务行为",
    ]


def test_catalog_row_support_is_parse_first_from_bound_intake_items():
    """固定目录行支持状态来自本表绑定问卷答案，不从生成内容或块名推断。"""
    report = _catalog_report()
    report.intakeItems = [
        IntakeItem(
            key="t.risk_choices",
            contentScopeId="t",
            prompt="风险选择",
            kind="multi_select",
            options=["合规与监管风险", "人员廉洁意识风险"],
            answer=["合规与监管风险"],
            supplement="报告期内重点关注监管要求变化。",
        )
    ]
    block = report.find_block("t.catalog")
    materials = TG._catalog_support_materials(block, report)

    supported = TG._catalog_row_support(FixedRowSeed(theme="合规与监管风险"), materials, prompt_labels(SSE_PACKAGE))
    unsupported = TG._catalog_row_support(FixedRowSeed(theme="人员廉洁意识风险"), materials, prompt_labels(SSE_PACKAGE))

    assert supported[P.CATALOG_ROW_SUPPORT_STATUS_KEY] == "user_supported_anchor"
    assert "用户在本表绑定的问题中选择或补充了「合规与监管风险」" in supported[P.CATALOG_ROW_SUPPORT_EVIDENCE_KEY]
    assert unsupported[P.CATALOG_ROW_SUPPORT_STATUS_KEY] == "framework_anchor"
    assert "不代表公司已识别或已开展对应管理" in unsupported[P.CATALOG_ROW_SUPPORT_EVIDENCE_KEY]


def test_adaptive_catalog_projection_prefers_reference_catalog_and_filters_unsupported_custom_rows():
    """adaptive_catalog 锚点按 referenceCatalog 与本表绑定输入投影，不保留无输入支撑的自定义名称。"""
    report = _adaptive_catalog_report()
    block = report.find_block("t.adaptive")
    anchors, _ = TG._anchor_ai_split(block.table.colDefs)

    rows = TG._project_adaptive_catalog_rows(
        block,
        anchors,
        [
            {"risk_category": "风险", "risk_name": "法规政策风险"},
            {"risk_category": "风险", "risk_name": "供应链合规风险"},
        ],
        support_materials={},
        count_min=2,
        count_max=3,
        labels=prompt_labels(SSE_PACKAGE),
    )

    assert [row["risk_name"] for row in rows] == ["法规政策风险", "声誉风险"]
    assert rows[0]["referenceImpact"] == "监管趋严影响合规成本"
    assert all(row["risk_name"] != "供应链合规风险" for row in rows)


def test_adaptive_catalog_projection_keeps_user_supported_custom_rows():
    """用户在本表绑定输入中直接给出的自定义锚点可保留，但带有用户支持边界。"""
    report = _adaptive_catalog_report()
    block = report.find_block("t.adaptive")
    anchors, _ = TG._anchor_ai_split(block.table.colDefs)

    rows = TG._project_adaptive_catalog_rows(
        block,
        anchors,
        [{"risk_category": "风险", "risk_name": "园区排放管控风险"}],
        support_materials={"t.strategy": "公司重点关注园区排放管控风险。"},
        count_min=1,
        count_max=3,
        labels=prompt_labels(SSE_PACKAGE),
    )

    assert rows[0]["risk_name"] == "园区排放管控风险"
    assert rows[0][P.CATALOG_ROW_SUPPORT_STATUS_KEY] == "user_supported_anchor"


async def test_complete_row_propagates_structured_failure(monkeypatch):
    """结构化解析失败（Pydantic AI 内置重试耗尽后）由 complete_row 上抛，交由上层隔离。"""
    _patch(monkeypatch, row=_row_factory, fail_themes=["极端高温"])
    with pytest.raises(RuntimeError):
        await TG.complete_row(
            "t.phys", RowSeed(theme="极端高温"), _phys_report(), observation=_observation()
        )


async def test_fill_table_rows_logs_warning_on_failed_row(monkeypatch, caplog):
    """fill_table_rows 某行失败隔离为 failed 时记 warning（含 block_id、theme），不再静默。"""
    _patch(monkeypatch, row=_row_factory, fail_themes=["海平面上升"])
    seeds = [RowSeed(theme="极端高温"), RowSeed(theme="海平面上升")]
    with caplog.at_level(logging.WARNING, logger="sustainability_desk.llm.table_gen"):
        rows = await TG.fill_table_rows(
            "t.phys", seeds, _phys_report(), max_concurrency=2, observation=_observation()
        )
    assert rows[1]["state"] == "failed"
    assert any(
        r.levelno == logging.WARNING and "海平面上升" in r.getMessage()
        for r in caplog.records
    )


# —— 子行展开（rowExpansion）：契约声明 → schema/展开/校验的确定性链路 ——


def _expansion_block() -> Block:
    """两子行展开的合成表块：共享列 + 每子行独占描述与收窄候选。"""
    return Block(
        id="t.expand",
        type="table",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task=GenerationTask(focus="补全两段披露。"),
            rowMode="expanded_rows",
            rowExpansion=RowExpansion(
                sharedColumnKeys=["topic", "scope"],
                units=[
                    RowExpansionUnit(
                        key="impact",
                        label="影响描述",
                        columnKeys=["desc", "kind"],
                        optionsNarrowing={"kind": ["正面影响", "负面影响"]},
                        genHintOverride={"desc": "只写对外部的影响。"},
                    ),
                    RowExpansionUnit(
                        key="risk_opportunity",
                        label="风险与机遇描述",
                        columnKeys=["desc", "kind"],
                        optionsNarrowing={"kind": ["机遇", "风险"]},
                    ),
                ],
            ),
        ),
        table=GsTable(
            colDefs=[
                GsColDef(key="topic", header="议题", cellType="text"),
                GsColDef(key="scope", header="范围", cellType="multi_select", options=["上游", "运营"]),
                GsColDef(key="desc", header="描述", cellType="ai_text"),
                GsColDef(
                    key="kind",
                    header="分类",
                    cellType="multi_select",
                    options=["正面影响", "负面影响", "机遇", "风险"],
                ),
            ],
        ),
    )


def test_expanded_row_schema_narrows_options_per_unit() -> None:
    """结构化输出 schema 逐子行收窄候选：模型在 schema 层就无法跨子行串用分类。"""
    from sustainability_desk.llm.table_schema import expanded_row_model

    block = _expansion_block()
    schema = expanded_row_model(block.table.colDefs, block.generation.rowExpansion).model_json_schema()

    assert set(schema["properties"]) == {"topic", "scope", "impact", "risk_opportunity"}
    defs = schema["$defs"]
    assert defs["ExpandedUnit_impact"]["properties"]["kind"]["items"]["enum"] == ["正面影响", "负面影响"]
    assert defs["ExpandedUnit_risk_opportunity"]["properties"]["kind"]["items"]["enum"] == ["机遇", "风险"]


def test_expanded_row_parses_stringified_units() -> None:
    """Qwen 经工具调用会把嵌套对象序列化成 JSON 字符串，合同边界须解析后再校验。

    回归依据：image agent 实测该行为，且重试不改变它。
    生成模型 qwen3.7-plus 未启用 native_structured_output，走的是同一条
    ToolOutput 路径；无此防护时整个 IRO 表所有行会被判为 failed。
    """
    import json as _json

    from sustainability_desk.llm.table_schema import expanded_row_model

    block = _expansion_block()
    model = expanded_row_model(block.table.colDefs, block.generation.rowExpansion)

    row = model.model_validate(
        {
            "topic": "气候变化",
            "scope": ["运营"],
            "impact": _json.dumps(
                {"desc": "影响描述", "kind": ["负面影响"]}, ensure_ascii=False
            ),
            "risk_opportunity": _json.dumps(
                {"desc": "风险描述", "kind": ["风险"]}, ensure_ascii=False
            ),
        }
    )

    assert row.impact.desc == "影响描述"
    assert row.risk_opportunity.kind == ["风险"]
    # 解析后仍走同一结构校验：子行候选收窄依然生效。
    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "topic": "气候变化",
                "scope": ["运营"],
                "impact": _json.dumps({"desc": "x", "kind": ["机遇"]}, ensure_ascii=False),
                "risk_opportunity": {"desc": "y", "kind": ["风险"]},
            }
        )


def test_build_expanded_rows_merges_shared_columns_and_narrows_cell_options() -> None:
    """一个业务行确定性展开为多子行：共享列首行 rowSpan、续行省略占位格，子行候选各自收窄。"""
    from sustainability_desk.contract.table_ops import harvest_table_rows

    block = _expansion_block()
    rows = harvest_table_rows(
        block,
        [{
            "topic": "应对气候变化",
            "scope": ["运营"],
            "impact": {"desc": "影响段", "kind": ["负面影响"]},
            "risk_opportunity": {"desc": "风险机遇段", "kind": ["机遇", "风险"]},
        }],
    )

    assert len(rows) == 2
    first = {c.colKey: c for c in rows[0].children}
    assert first["topic"].rowSpan == 2 and first["scope"].rowSpan == 2
    assert first["desc"].value == "影响段"
    assert first["kind"].options == ["正面影响", "负面影响"]
    # 续行只出子行列，被合并的共享列不留占位格（导出按 rowSpan 网格还原）。
    assert [c.colKey for c in rows[1].children] == ["desc", "kind"]
    assert rows[1].children[0].value == "风险机遇段"
    assert rows[1].children[1].options == ["机遇", "风险"]


async def test_expanded_row_generation_expands_each_seed_into_its_units(monkeypatch) -> None:
    """生成链路按契约把每个 seed 展开为全部子行；共享列合并、子行各自成行。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[_expansion_block()])],
    )
    _patch(monkeypatch, row=_row_factory)
    monkeypatch.setattr(TG, "_template_report", lambda *_: report)

    rows = await TG.fill_table_rows(
        "t.expand",
        [RowSeed(theme="应对气候变化")],
        report,
        observation=_observation(),
    )

    assert len(rows) == 2  # 一个 seed → 两个披露子行
    assert _cells(rows[0])["topic"] == "文本-topic"
    assert [c["colKey"] for c in rows[1]["children"]] == ["desc", "kind"]
