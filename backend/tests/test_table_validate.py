# ABOUTME: 表格确定性校验单测——定行去重/行数边界 + 导出 gate（合法≠正确的兜网）。
from sustainability_desk.contract.models import Block, Condition, ConditionRule, GsColDef, GsTable, Report
from sustainability_desk.contract.table_ops import data_row, row_values
from sustainability_desk.llm.table_schema import RowSeed
from sustainability_desk.llm.table_validate import table_export_issues, validate_seeds
from knowledge_package_fixtures import SSE_PACKAGE

COLS = [
    GsColDef(key="name", header="名称", cellType="text", required=True),
    GsColDef(key="response", header="应对", cellType="ai_text"),
]


def _drow(cells, *, state=None, appears_when=None):
    row = data_row(COLS, cells, state=state)
    if appears_when is not None:
        row.appears_when = appears_when
    return row


def _table_block(rows):
    return Block(id="t.x", type="table", blockType="generative", source="ai",
                 table=GsTable(colDefs=COLS, children=rows))


def test_validate_seeds_dedupes_by_theme():
    """按 theme 去重（保序）。"""
    seeds = [RowSeed(theme="极端高温"), RowSeed(theme="极端高温"), RowSeed(theme="海平面上升")]
    kept, issues = validate_seeds(seeds, count_min=1, count_max=8)
    assert [s.theme for s in kept] == ["极端高温", "海平面上升"]


def test_validate_seeds_truncates_over_max():
    """超上限截断并记提示。"""
    seeds = [RowSeed(theme=f"t{i}") for i in range(10)]
    kept, issues = validate_seeds(seeds, count_min=2, count_max=6)
    assert len(kept) == 6 and any("超上限" in m for m in issues)


def test_validate_seeds_warns_under_min():
    """不足下限记提示（不阻断）。"""
    seeds = [RowSeed(theme="t0")]
    kept, issues = validate_seeds(seeds, count_min=3, count_max=8)
    assert len(kept) == 1 and any("不足下限" in m for m in issues)


def test_export_gate_flags_empty_required_and_ai_text():
    """必填列空 + ai_text 空 → 各记 issue。"""
    blk = _table_block([_drow({"name": "", "response": ""}, state="ready")])
    kinds = {i.kind for i in table_export_issues(blk)}
    assert "required_empty" in kinds and "ai_text_empty" in kinds


def test_export_gate_flags_only_failed_lifecycle_rows():
    """failed 行阻断；ready 行直接是当前有效版本。rowId 为 children 下标。"""
    blk = _table_block([
        _drow({"name": "风险A", "response": "措施A"}, state="failed"),
        _drow({"name": "风险B", "response": "措施B"}, state="ready"),
        _drow({"name": "风险C", "response": "措施C"}, state="ready"),
    ])
    rids = {i.rowId for i in table_export_issues(blk)}
    assert "0" in rids and "1" not in rids and "2" not in rids


def test_export_gate_skips_hidden_rows():
    """appears_when=false 的行被过滤、不报（report=None 时隐藏行 fail-closed 跳过）。"""
    hidden = _drow({"name": "", "response": ""}, state="ready",
                   appears_when=Condition(all=[ConditionRule(path="fields.nope.value", op="exists")]))
    assert table_export_issues(_table_block([hidden]), report=None) == []


def test_render_rows_filters_hidden():
    """_render_table 与诊断同源：仅导出可见行（appears_when=false 行被过滤，Codex P2）。"""
    from sustainability_desk.export.docx_renderer import _render_rows

    rows = [
        _drow({"name": "A"}),
        _drow({"name": "B"},
              appears_when=Condition(all=[ConditionRule(path="fields.nope.value", op="exists")])),
    ]
    table = GsTable(colDefs=COLS, children=rows)
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", fields={}, sections=[])
    visible = _render_rows(table, report)
    assert len(visible) == 1 and row_values(visible[0])["name"] == "A"


def test_export_gate_skips_header_rows():
    """表头行（headerRow）不参与必填/ai_text/state 校验。"""
    from sustainability_desk.contract.models import GsTableCell, GsTableRow

    header = GsTableRow(headerRow=True, children=[
        GsTableCell(type="th", value="名称"), GsTableCell(type="th", value="应对"),
    ])
    blk = _table_block([header, _drow({"name": "风险A", "response": "措施A"}, state="ready")])
    assert table_export_issues(blk) == []


def test_export_gate_flags_missing_required_cell():
    """普通数据行整格缺失（非 rowSpan 合并占位）→ 必填/ai_text 列仍报，杜绝坏 payload 删格放行。"""
    from sustainability_desk.contract.models import GsTableCell, GsTableRow

    row = GsTableRow(state="ready", children=[GsTableCell(type="td", colKey="response", value="措施A")])
    kinds = {(i.kind, i.col) for i in table_export_issues(_table_block([row]))}
    assert ("required_empty", "name") in kinds


def test_export_gate_expands_row_span_required_cells():
    """rowSpan 续行省略的是版式占位，不应被导出 gate 当作必填列缺失。"""
    from sustainability_desk.contract.models import GsTableCell, GsTableRow

    rows = [
        GsTableRow(
            state="ready",
            children=[
                GsTableCell(type="td", colKey="name", value="风险", rowSpan=2),
                GsTableCell(type="td", colKey="response", value="措施A"),
            ],
        ),
        GsTableRow(
            state="ready",
            children=[
                GsTableCell(type="td", colKey="response", value="措施B"),
            ],
        ),
    ]

    assert table_export_issues(_table_block(rows)) == []


def test_export_gate_locked_row_not_flagged():
    """locked 行已经定稿，不产生生成生命周期问题。"""
    blk = _table_block([_drow({"name": "风险A", "response": "措施A"}, state="locked")])
    assert table_export_issues(blk) == []


def test_every_table_issue_kind_has_an_explicit_diagnostics_level() -> None:
    """每种表行问题都必须有显式级别，不得落到默认值。

    `_TABLE_LEVEL.get(kind, "warn")` 的默认分支意味着：新增一种 kind 而忘了登记级别，
    一类本该阻断导出的问题会静默降级成 warn 放行。Word 导出保真是一级风险，这条不能
    靠人记得，必须由测试固化。
    """
    from typing import get_args

    from sustainability_desk.diagnostics import _TABLE_LEVEL, _TABLE_MSG
    from sustainability_desk.llm.table_validate import TableIssueKind

    kinds = set(get_args(TableIssueKind))
    # 固定行两类的级别依版式而定（见 _table_issue_level），其余必须在级别表里
    version_dependent = {"fixed_row_missing", "fixed_row_duplicate"}
    assert kinds - version_dependent <= set(_TABLE_LEVEL), (
        f"这些 kind 没有显式级别，会静默降级为 warn：{sorted(kinds - version_dependent - set(_TABLE_LEVEL))}"
    )
    assert kinds <= set(_TABLE_MSG), (
        f"这些 kind 没有用户文案：{sorted(kinds - set(_TABLE_MSG))}"
    )
