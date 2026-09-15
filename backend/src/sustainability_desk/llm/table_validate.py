# ABOUTME: 表格 AI 生成的确定性校验——定行去重/行数边界 + 导出 gate；非 LLM，是「合法≠正确」的兜网。
# ABOUTME: 主题边界由各表块 GenerationTask 与 typed row contract 约束；定行校验不承担开放语义判定。
# ABOUTME(en): Deterministic table generation checks: row deduplication, row-count bounds and the export gate; no LLM.
# ABOUTME(en): Topic boundaries stay with each block's GenerationTask and typed row contract; no semantic judgement.
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sustainability_desk.contract.models import Block, Report
from sustainability_desk.contract.table_ops import row_values
from sustainability_desk.contract.visibility import visible
from sustainability_desk.llm.table_schema import RowSeed

#: 导出 gate 能产出的全部行级问题种类。这是闭合值域：新增一种必须同时在
#: diagnostics 的级别表登记，否则加载期即失败——见 diagnostics._TABLE_LEVEL。
TableIssueKind = Literal[
    "required_empty",
    "ai_text_empty",
    "row_failed",
    "fixed_row_missing",
    "fixed_row_duplicate",
]


@dataclass(frozen=True)
class TableExportIssue:
    """导出 gate 的行级问题。

    级别与用户文案不在此处决定——本类型只陈述「哪个块的哪一行的哪一列出了哪类问题」，
    严重程度由 diagnostics 按块的版式 profile 解释。
    """

    blockId: str
    kind: TableIssueKind
    rowId: str | None = None
    col: str | None = None
    colHeader: str | None = None
    rowLabel: str | None = None


def validate_seeds(
    seeds: list[RowSeed], *, count_min: int, count_max: int
) -> tuple[list[RowSeed], list[str]]:
    """定行校验：按 theme 去重（保序）、裁剪到上限、不足下限记提示。返回 (保留条目, 提示)。"""
    seen: set[str] = set()
    uniq: list[RowSeed] = []
    for s in seeds:
        if s.theme not in seen:
            seen.add(s.theme)
            uniq.append(s)
    issues: list[str] = []
    if len(uniq) > count_max:
        issues.append(f"定行 {len(uniq)} 超上限 {count_max}，已截断")
    kept = uniq[:count_max]
    if len(kept) < count_min:
        issues.append(f"定行 {len(kept)} 不足下限 {count_min}")
    return kept, issues


def _row_visible(row, report: Report | None) -> bool:
    if row.appears_when is None:
        return True
    if report is None:
        return False  # fail-closed：无 report 上下文时隐藏行不导出
    return visible(row, report)


def _nonempty(v) -> bool:
    """单元格值非空判定：多选非空列表为真，标量去空白后非空为真。"""
    if isinstance(v, list):
        return len(v) > 0
    return bool(str(v if v is not None else "").strip())


def _row_values_with_spans(rows) -> dict[int, dict]:
    """按行展开 rowSpan 合并格；仅用于语义校验，表格节点树仍是真相源。"""
    expanded: dict[int, dict] = {}
    active_row_spans: dict[str, tuple[object, int]] = {}
    for idx, row in enumerate(rows):
        vals: dict = {}
        next_row_spans: dict[str, tuple[object, int]] = {}
        for col_key, (value, remaining_rows) in active_row_spans.items():
            vals[col_key] = value
            if remaining_rows > 1:
                next_row_spans[col_key] = (value, remaining_rows - 1)
        for cell in row.children:
            if not cell.colKey:
                continue
            vals[cell.colKey] = cell.value
            if cell.rowSpan > 1:
                next_row_spans[cell.colKey] = (cell.value, cell.rowSpan - 1)
        active_row_spans = next_row_spans
        expanded[idx] = vals
    return expanded


def _col_header(block: Block, key: str) -> str:
    tm = block.table
    if tm is None:
        return key
    return next((c.header for c in tm.colDefs if c.key == key), key)


def _fixed_row_label(row, vals: dict) -> str:
    if row.origin and row.origin.theme:
        return row.origin.theme
    for key in ("risk_name", "risk_type"):
        value = vals.get(key)
        if _nonempty(value):
            return str(value)
    for value in vals.values():
        if _nonempty(value):
            return str(value)
    return ""


def table_export_issues(block: Block, report: Report | None = None) -> list[TableExportIssue]:
    """导出 gate：可见数据行的必填列空、ai_text 空或生成未就绪时返回 issue。

    表头行跳过；rowId 用 children 下标（节点暂不持久 id，前端据下标定位）。
    必填/ai_text 列即使本行缺该格也报（缺格 = 空，杜绝坏 payload 删格后空白进 Word）；
    rowSpan 合并格按上方单元格展开，避免把版式占位误判为缺失。
    """
    issues: list[TableExportIssue] = []
    tm = block.table
    if tm is None:
        return issues
    required_keys = [c.key for c in tm.colDefs if c.required]
    ai_keys = [c.key for c in tm.colDefs if c.cellType == "ai_text"]
    visible_row_labels: dict[str, list[str]] = {}
    expanded_values = _row_values_with_spans(tm.children)
    for idx, row in enumerate(tm.children):
        if row.headerRow or not _row_visible(row, report):
            continue
        vals = expanded_values.get(idx) or row_values(row)
        row_id = str(idx)
        row_label = _fixed_row_label(row, vals)
        if row_label:
            visible_row_labels.setdefault(row_label, []).append(row_id)
        for k in required_keys:
            if not _nonempty(vals.get(k)):
                issues.append(TableExportIssue(
                    blockId=block.id, rowId=row_id, kind="required_empty",
                    col=k, colHeader=_col_header(block, k), rowLabel=row_label,
                ))
        for k in ai_keys:
            if not _nonempty(vals.get(k)):
                issues.append(TableExportIssue(
                    blockId=block.id, rowId=row_id, kind="ai_text_empty",
                    col=k, colHeader=_col_header(block, k), rowLabel=row_label,
                ))
        if row.state in ("failed", "pending", "generating"):
            issues.append(TableExportIssue(
                blockId=block.id, rowId=row_id, kind="row_failed", rowLabel=row_label,
            ))
    fixed_seeds = block.generation.fixedRowSeeds if block.generation and block.generation.fixedRowSeeds else []
    for seed in fixed_seeds:
        row_ids = visible_row_labels.get(seed.theme, [])
        if not row_ids:
            issues.append(TableExportIssue(
                blockId=block.id, kind="fixed_row_missing", rowLabel=seed.theme,
            ))
        elif len(row_ids) > 1:
            for row_id in row_ids[1:]:
                issues.append(TableExportIssue(
                    blockId=block.id, rowId=row_id, kind="fixed_row_duplicate", rowLabel=seed.theme,
                ))
    return issues
