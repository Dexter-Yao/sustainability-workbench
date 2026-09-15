# ABOUTME: 从完整 ParsedMaterial owner 构建可重建的整表或整工作表 Markdown 文件投影。
# ABOUTME: Markdown 不是 SSOT；视觉颜色、图标和条件格式未建模并必须作为显式能力缺口公开。
# ABOUTME(en): Builds reconstructible whole-table or whole-sheet Markdown projections from a ParsedMaterial owner.
# ABOUTME(en): Markdown is not the source of truth; colors, icons and conditional formats are declared as gaps.
from __future__ import annotations

from hashlib import sha256
from html import escape
import json
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.parsed_material import (
    ParsedCell,
    ParsedMaterial,
    ParsedSheetNode,
    ParsedSheetRowNode,
    ParsedTableNode,
    ParsedTableRowNode,
)
from sustainability_desk.material.retrieval.chunks import (
    StructuredDataContextBundle,
    StructuredDataOwner,
    StructuredDataPaginationPolicy,
    build_sheet_context_bundle,
    build_table_context_bundle,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
PROJECTION_PROFILE_ID = "structured-owner-markdown@2"
CELL_MARKER_DEFAULTS: dict[str, object] = {
    "value_kind": "text",
    "formula": None,
    "cached_value": None,
    "native_data_type": None,
    "number_format": None,
    "hidden_row": False,
    "hidden_column": False,
    "merged_anchor": None,
    "merged_range": None,
    "row_span": 1,
    "column_span": 1,
}


class StructuredMarkdownModel(BaseModel):
    """结构化 Markdown 投影的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StructuredMarkdownGap(StructuredMarkdownModel):
    """Markdown 文件无法表达或来源解析尚未覆盖的能力。"""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    basis: Literal["capability_not_modeled", "source_parse_gap"]


class StructuredMarkdownCoverage(StructuredMarkdownModel):
    """Markdown 投影自身的结构与能力覆盖声明。"""

    owner_rows_complete: Literal[True] = True
    owner_columns_complete: Literal[True] = True
    cell_text_markers_complete: Literal[True] = True
    formula_markers_complete: Literal[True] = True
    merge_markers_complete: Literal[True] = True
    visual_semantics: Literal["not_modeled"] = "not_modeled"
    overall_no_evidence_conclusion_allowed: Literal[False] = False
    gaps: tuple[StructuredMarkdownGap, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def _visual_gaps_are_explicit(self) -> "StructuredMarkdownCoverage":
        codes = {gap.code for gap in self.gaps}
        required = {
            "visual_colors_not_modeled",
            "visual_icons_not_modeled",
            "conditional_formatting_not_modeled",
        }
        if not required.issubset(codes):
            raise ValueError("结构化 Markdown 必须显式声明全部未建模视觉能力")
        return self


class StructuredMarkdownProjection(StructuredMarkdownModel):
    """默认整份入模的完整 owner Markdown 文件。"""

    contract: Literal["sustainability_desk.structured_owner_markdown.v2"]
    projection_id: UUID
    projection_profile_id: Literal["structured-owner-markdown@2"]
    owner: StructuredDataOwner
    transport_bundle: StructuredDataContextBundle
    render_mode: Literal["pipe_table", "html_table"]
    filename: str = Field(pattern=r"^[0-9a-f-]{36}\.md$")
    media_type: Literal["text/markdown; charset=utf-8"] = (
        "text/markdown; charset=utf-8"
    )
    markdown: str = Field(min_length=1)
    markdown_sha256: str = Field(pattern=SHA256_PATTERN)
    default_model_delivery: Literal["whole_markdown"] = "whole_markdown"
    pagination_role: Literal["oversized_transport_only"] = (
        "oversized_transport_only"
    )
    coverage: StructuredMarkdownCoverage

    @model_validator(mode="after")
    def _validate_projection(self) -> "StructuredMarkdownProjection":
        if self.transport_bundle.owner != self.owner:
            raise ValueError("Markdown 与传输 bundle 必须引用同一 owner")
        if (
            self.transport_bundle.coverage_status != "complete"
            or self.transport_bundle.owner_conclusion_gate != "open"
        ):
            raise ValueError("Markdown 只能从完整 owner bundle 构建")
        expected_id = stable_structured_markdown_projection_id(
            owner=self.owner,
            projection_profile_id=self.projection_profile_id,
        )
        if self.projection_id != expected_id:
            raise ValueError("结构化 Markdown projection_id 无效")
        if self.filename != f"{self.projection_id}.md":
            raise ValueError("结构化 Markdown 文件名必须由 projection_id 派生")
        if self.markdown_sha256 != sha256(self.markdown.encode("utf-8")).hexdigest():
            raise ValueError("结构化 Markdown 内容指纹无效")
        return self


def stable_structured_markdown_projection_id(
    *,
    owner: StructuredDataOwner,
    projection_profile_id: str,
) -> UUID:
    """按 owner 完整身份和投影版本生成稳定 Markdown 文件身份。"""

    identity = json.dumps(
        {
            "owner_id": str(owner.owner_id),
            "owner_content_fingerprint": owner.owner_content_fingerprint,
            "full_range_fingerprint": owner.full_range.range_fingerprint,
            "projection_profile_id": projection_profile_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, f"sustainability_desk.structured-markdown:{identity}")


def _coordinate(
    cell: ParsedCell,
    *,
    row_position: int,
) -> str:
    return cell.cell_reference or f"R{row_position}C{cell.column_index}"


def _cell_marker(
    cell: ParsedCell,
    *,
    row_position: int,
    row_hidden: bool,
) -> dict[str, object]:
    complete_marker = {
        "coordinate": _coordinate(cell, row_position=row_position),
        "value_kind": cell.value_kind,
        "formula": cell.formula,
        "cached_value": cell.cached_value,
        "native_data_type": cell.native_data_type,
        "number_format": cell.number_format,
        "hidden_row": cell.hidden_row or row_hidden,
        "hidden_column": cell.hidden_column,
        "merged_anchor": cell.merged_anchor,
        "merged_range": cell.merged_range,
        "row_span": cell.row_span,
        "column_span": cell.column_span,
    }
    return {
        key: value
        for key, value in complete_marker.items()
        if key == "coordinate" or CELL_MARKER_DEFAULTS[key] != value
    }


def _visible_cell(
    cell: ParsedCell,
    *,
    row_position: int,
    row_hidden: bool,
) -> str:
    marker = json.dumps(
        _cell_marker(
            cell,
            row_position=row_position,
            row_hidden=row_hidden,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    text = escape(cell.text).replace("|", "&#124;").replace("\n", "<br>")
    return f"{text}<br><sub>⟦{escape(marker)}⟧</sub>"


def _requires_html(
    rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...],
    *,
    header_row_ids: tuple[UUID, ...],
) -> bool:
    if len(header_row_ids) > 1:
        return True
    return any(
        cell.merged_anchor is not None
        or cell.merged_range is not None
        or cell.row_span > 1
        or cell.column_span > 1
        for row in rows
        for cell in row.cells
    )


def _render_pipe_table(
    rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...],
    *,
    header_row_ids: tuple[UUID, ...],
    column_count: int,
) -> str:
    header_set = set(header_row_ids)
    source_headers = [row for row in rows if row.node_id in header_set]
    if source_headers:
        header_cells = source_headers[0].cells
        body_rows = [row for row in rows if row.node_id not in header_set]
        header_position = rows.index(source_headers[0]) + 1
        header_hidden = bool(getattr(source_headers[0], "hidden", False))
        rendered_header = [
            _visible_cell(
                cell,
                row_position=header_position,
                row_hidden=header_hidden,
            )
            for cell in header_cells
        ]
    else:
        rendered_header = [
            f"列 {column_index}<br><sub>⟦derived_navigation_header=true⟧</sub>"
            for column_index in range(1, column_count + 1)
        ]
        body_rows = list(rows)
    lines = [
        f"| {' | '.join(rendered_header)} |",
        f"| {' | '.join('---' for _ in range(column_count))} |",
    ]
    for row in body_rows:
        row_position = rows.index(row) + 1
        row_hidden = bool(getattr(row, "hidden", False))
        lines.append(
            f"| {' | '.join(_visible_cell(cell, row_position=row_position, row_hidden=row_hidden) for cell in row.cells)} |"
        )
    return "\n".join(lines)


def _render_marker(marker: dict[str, object]) -> str:
    return escape(
        json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _render_merged_covered_cell(
    cell: ParsedCell,
    *,
    marker: dict[str, object],
) -> str:
    payload = escape(
        json.dumps(
            {
                "marker": marker,
                "text": cell.text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    ).replace("--", "&#45;&#45;")
    return f"<!-- merged-covered ⟦{payload}⟧ -->"


def _render_html_rows(
    rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...],
    *,
    header_row_ids: tuple[UUID, ...],
) -> tuple[str, str]:
    header_set = set(header_row_ids)
    header_lines: list[str] = []
    body_lines: list[str] = []
    for row_position, row in enumerate(rows, start=1):
        cells: list[str] = []
        is_header = row.node_id in header_set
        tag = "th" if is_header else "td"
        row_hidden = bool(getattr(row, "hidden", False)) or any(
            cell.hidden_row for cell in row.cells
        )
        for cell in row.cells:
            marker = _cell_marker(
                cell,
                row_position=row_position,
                row_hidden=row_hidden,
            )
            coordinate = str(marker["coordinate"])
            if cell.merged_anchor is not None and cell.merged_anchor != coordinate:
                cells.append(
                    _render_merged_covered_cell(
                        cell,
                        marker=marker,
                    )
                )
                continue
            span_attributes = (
                f' rowspan="{cell.row_span}"' if cell.row_span > 1 else ""
            ) + (
                f' colspan="{cell.column_span}"'
                if cell.column_span > 1
                else ""
            )
            cells.append(
                f"<{tag}{span_attributes}>"
                f"{escape(cell.text)}<br><small>⟦{_render_marker(marker)}⟧</small>"
                f"</{tag}>"
            )
        row_hidden_attribute = (
            ' data-hidden-row="true"' if row_hidden else ""
        )
        rendered = (
            f"<tr{row_hidden_attribute}>"
            f"{''.join(cells)}</tr>"
        )
        (header_lines if is_header else body_lines).append(rendered)
    return "\n".join(header_lines), "\n".join(body_lines)


def _render_html_table(
    rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...],
    *,
    header_row_ids: tuple[UUID, ...],
    column_count: int,
) -> str:
    header_html, body_html = _render_html_rows(
        rows,
        header_row_ids=header_row_ids,
    )
    if not header_html:
        header_html = (
            '<tr data-derived-navigation-header="true">'
            + "".join(
                f"<th>列 {column_index}</th>"
                for column_index in range(1, column_count + 1)
            )
            + "</tr>"
        )
    return (
        '<table data-sustainability-desk-projection="structured-owner-markdown@2">\n'
        f"<thead>\n{header_html}\n</thead>\n"
        f"<tbody>\n{body_html}\n</tbody>\n</table>"
    )


def _validate_complete_grid(
    rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...],
    *,
    column_count: int,
) -> None:
    expected_columns = tuple(range(1, column_count + 1))
    for row in rows:
        actual_columns = tuple(cell.column_index for cell in row.cells)
        if actual_columns != expected_columns:
            raise ValueError(
                f"结构化 Markdown 不接受缺列行：{row.node_id}"
            )


def _projection_gaps(parsed_material: ParsedMaterial) -> tuple[StructuredMarkdownGap, ...]:
    gaps = [
        StructuredMarkdownGap(
            code="visual_colors_not_modeled",
            message="单元格颜色与字体颜色未进入 ParsedMaterial，Markdown 不表达该视觉语义",
            basis="capability_not_modeled",
        ),
        StructuredMarkdownGap(
            code="visual_icons_not_modeled",
            message="图标与图标集未进入 ParsedMaterial，Markdown 不表达该视觉语义",
            basis="capability_not_modeled",
        ),
        StructuredMarkdownGap(
            code="conditional_formatting_not_modeled",
            message="条件格式规则未进入 ParsedMaterial，Markdown 不表达该视觉语义",
            basis="capability_not_modeled",
        ),
    ]
    source_gaps = {
        (gap.code, gap.message)
        for gap in parsed_material.coverage.gaps
    }
    gaps.extend(
        StructuredMarkdownGap(
            code=f"source_parse_gap:{code}",
            message=message,
            basis="source_parse_gap",
        )
        for code, message in sorted(source_gaps)
    )
    return tuple(gaps)


def _markdown_preamble(
    *,
    owner: StructuredDataOwner,
    title: str,
    gaps: tuple[StructuredMarkdownGap, ...],
) -> str:
    metadata = {
        "projection_role": "derived_rebuildable_not_ssot",
        "owner_id": str(owner.owner_id),
        "owner_kind": owner.owner_kind,
        "owner_node_id": str(owner.owner_node_id),
        "parsed_material_fingerprint": owner.parsed_material_fingerprint,
        "owner_content_fingerprint": owner.owner_content_fingerprint,
        "full_range_fingerprint": owner.full_range.range_fingerprint,
        "source_cell_range": owner.full_range.source_cell_range,
        "row_count": len(owner.full_range.row_node_ids),
        "column_count": owner.full_range.column_count,
        "header_row_node_ids": [
            str(node_id) for node_id in owner.full_range.header_row_node_ids
        ],
        "default_model_delivery": "whole_markdown",
        "pagination_role": "oversized_transport_only",
        "visual_semantics": "not_modeled",
        "cell_marker_rule": {
            "always_present": ["coordinate"],
            "omitted_fields_equal_defaults": CELL_MARKER_DEFAULTS,
        },
        "gap_codes": [gap.code for gap in gaps],
    }
    return (
        f"# {escape(title)}\n\n"
        "> 此文件由 ParsedMaterial 确定性重建，不是业务真相源；"
        "默认整份进入模型上下文，分页仅用于超大文件传输。\n\n"
        "```json\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)}\n"
        "```\n\n"
        "## 完整结构化内容\n\n"
    )


def build_structured_markdown_projection(
    parsed_material: ParsedMaterial,
    *,
    owner_node_id: UUID,
    pagination_policy: StructuredDataPaginationPolicy,
) -> StructuredMarkdownProjection:
    """从完整 ParsedMaterial owner 构建全量 Markdown 文件投影。"""

    owner_node = next(
        (
            node
            for node in parsed_material.nodes
            if node.node_id == owner_node_id
            and isinstance(node, (ParsedTableNode, ParsedSheetNode))
        ),
        None,
    )
    if owner_node is None:
        raise ValueError("ParsedMaterial 不包含目标 table/sheet owner")
    if isinstance(owner_node, ParsedTableNode):
        bundle = build_table_context_bundle(
            parsed_material,
            table_node_id=owner_node.node_id,
            policy=pagination_policy,
        )
        rows: tuple[ParsedTableRowNode | ParsedSheetRowNode, ...] = tuple(
            sorted(
                (
                    node
                    for node in parsed_material.nodes
                    if isinstance(node, ParsedTableRowNode)
                    and node.parent_node_id == owner_node.node_id
                ),
                key=lambda row: row.ordinal_path,
            )
        )
        title = owner_node.title or "完整表格"
    else:
        bundle = build_sheet_context_bundle(
            parsed_material,
            sheet_node_id=owner_node.node_id,
            policy=pagination_policy,
        )
        rows = tuple(
            sorted(
                (
                    node
                    for node in parsed_material.nodes
                    if isinstance(node, ParsedSheetRowNode)
                    and node.parent_node_id == owner_node.node_id
                ),
                key=lambda row: row.ordinal_path,
            )
        )
        title = owner_node.label or "完整工作表"
    owner = bundle.owner
    gaps = _projection_gaps(parsed_material)
    _validate_complete_grid(
        rows,
        column_count=owner.full_range.column_count,
    )
    use_html = _requires_html(
        rows,
        header_row_ids=owner.full_range.header_row_node_ids,
    )
    if use_html:
        render_mode: Literal["pipe_table", "html_table"] = "html_table"
        body = _render_html_table(
            rows,
            header_row_ids=owner.full_range.header_row_node_ids,
            column_count=owner.full_range.column_count,
        )
    else:
        render_mode = "pipe_table"
        body = _render_pipe_table(
            rows,
            header_row_ids=owner.full_range.header_row_node_ids,
            column_count=owner.full_range.column_count,
        )
    markdown = _markdown_preamble(
        owner=owner,
        title=title,
        gaps=gaps,
    ) + body + "\n"
    projection_id = stable_structured_markdown_projection_id(
        owner=owner,
        projection_profile_id=PROJECTION_PROFILE_ID,
    )
    return StructuredMarkdownProjection(
        contract="sustainability_desk.structured_owner_markdown.v2",
        projection_id=projection_id,
        projection_profile_id=PROJECTION_PROFILE_ID,
        owner=owner,
        transport_bundle=bundle,
        render_mode=render_mode,
        filename=f"{projection_id}.md",
        markdown=markdown,
        markdown_sha256=sha256(markdown.encode("utf-8")).hexdigest(),
        coverage=StructuredMarkdownCoverage(gaps=gaps),
    )
