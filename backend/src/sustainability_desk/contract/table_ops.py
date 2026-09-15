# ABOUTME: GsTable 节点树与「列键→值」字典视图的互转助手——填充/生成/校验共用，避免各处重复遍历 children。
# ABOUTME: 节点树（colDefs + tr/td/th + colSpan/rowSpan）是真相；字典视图仅为 LLM 输出与导出 gate 的临时投影。
# ABOUTME(en): Helpers converting GsTable node trees to and from column-key dict views, shared by fill and generation.
# ABOUTME(en): The node tree is the truth; the dict view is a transient projection for LLM output and the export gate.
from __future__ import annotations

from sustainability_desk.contract.models import (
    Block,
    FixedRowSeed,
    GsColDef,
    GsTableCell,
    GsTableRow,
    Report,
    RowExpansion,
    RowOrigin,
)


def resolve_preset_row_seeds(block: Block, report: Report) -> list[FixedRowSeed]:
    """按 GenerationSpec 的结构化选择合同解析本次可生成的 preset_catalog 行。"""
    generation = block.generation
    if generation is None:
        return []
    seeds = list(generation.fixedRowSeeds or [])
    selection = generation.presetRowSelection
    if selection is None:
        return seeds

    item = next((item for item in report.intakeItems if item.key == selection.intakeItemKey), None)
    selected = item.answer if item is not None and isinstance(item.answer, list) else []
    if not selected:
        return seeds if selection.unansweredBehavior == "show_all_rows" else []
    selected_names = set(selected)
    return [seed for seed in seeds if seed.theme in selected_names]

def row_values(row: GsTableRow) -> dict:
    """从数据行的单元格抽取 {colKey: value}（跳过无 colKey 的表头/合并占位格）。"""
    return {c.colKey: c.value for c in row.children if c.colKey}


def data_row(
    col_defs: list[GsColDef],
    values: dict,
    *,
    state=None,
    origin: RowOrigin | None = None,
) -> GsTableRow:
    """按 colDefs 顺序为一行均匀表数据组装单元格（每列一格，缺值留 None）。"""
    cells = [GsTableCell(type="td", colKey=c.key, value=values.get(c.key)) for c in col_defs]
    return GsTableRow(state=state, origin=origin, children=cells)


def build_expanded_rows(
    col_defs: list[GsColDef],
    expansion: RowExpansion,
    entries: list[dict],
    *,
    state=None,
    origin: RowOrigin | None = None,
) -> list[GsTableRow]:
    """按契约 rowExpansion 把每个业务行展开为多个披露子行（如 IRO 每议题＝影响行 + 风险机遇行）。

    共享列只在首个子行出格并 rowSpan=子行数，其余子行省略被合并的占位格；
    子行列按 unit.optionsNarrowing 写入单元格级 options（列级承载并集，子行据此收窄）。
    entries 每条形如 {共享列key: 值, unit.key: {子行列key: 值}}——与 expanded_row_model 的输出同形。
    """
    by_key = {col.key: col for col in col_defs}
    span = len(expansion.units)
    rows: list[GsTableRow] = []
    for entry in entries:
        for index, unit in enumerate(expansion.units):
            unit_values = entry.get(unit.key) or {}
            narrowing = unit.optionsNarrowing or {}
            cells: list[GsTableCell] = []
            for col in col_defs:
                if col.key in expansion.sharedColumnKeys:
                    if index == 0:
                        cells.append(
                            GsTableCell(
                                type="td", colKey=col.key, value=entry.get(col.key), rowSpan=span
                            )
                        )
                    continue  # 后续子行省略被合并的占位格
                if col.key in unit.columnKeys:
                    cells.append(
                        GsTableCell(
                            type="td",
                            colKey=col.key,
                            value=unit_values.get(col.key),
                            options=narrowing.get(col.key) or by_key[col.key].options,
                        )
                    )
            rows.append(GsTableRow(state=state, origin=origin, children=cells))
    return rows


def build_preset_catalog_rows(
    col_defs: list[GsColDef],
    groups: list[tuple[str, list[dict]]],
    *,
    state=None,
) -> list[GsTableRow]:
    """preset_catalog 表：按类型分组构建数据行，类型列首行 rowSpan 合并、续行省略被合并占位格。

    col_defs 顺序固定为 [type, name, <AI 列...>]；groups 为有序 (类型, [该组各行 {colKey: value}]) 清单，
    每行 dict 含 name 与各 AI 列的值（type 取自分组键）。origin 记 name/type 供导出 gate 与单行重生成还原。
    """
    type_key = col_defs[0].key
    name_key = col_defs[1].key
    rest_keys = [c.key for c in col_defs[1:]]
    rows: list[GsTableRow] = []
    for category, fills in groups:
        span = len(fills)
        for i, vals in enumerate(fills):
            cells: list[GsTableCell] = []
            if i == 0:
                cells.append(GsTableCell(type="td", colKey=type_key, value=category, rowSpan=span))
            cells.extend(GsTableCell(type="td", colKey=k, value=vals.get(k)) for k in rest_keys)
            origin = RowOrigin(theme=vals.get(name_key), category=category)
            rows.append(GsTableRow(state=state, origin=origin, children=cells))
    return rows


def harvest_table_rows(block: Block, entries: list[dict], *, state=None) -> list[GsTableRow]:
    """据 entries 组装数据行：契约声明 rowExpansion 的走子行展开，其余走均匀表。

    分派依据是块的生成契约，不从列名推断表型——契约是唯一真相源。
    """
    table = block.table
    expansion = block.generation.rowExpansion if block.generation else None
    if expansion is not None:
        return build_expanded_rows(table.colDefs, expansion, entries, state=state)
    return [data_row(table.colDefs, e, state=state) for e in entries]
