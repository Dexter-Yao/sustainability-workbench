# ABOUTME: 验证 whole-table/whole-sheet-first 结构化上下文闸门。
# ABOUTME: 行分页只能传输全列连续范围，单页或不完整页集合不得独立映射或形成无证据结论。
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from sustainability_desk.material.intake.parsed_material import (
    ParsedCell,
    ParsedDocumentNode,
    ParsedMaterial,
    ParsedSheetNode,
    ParsedSheetRowNode,
    ParsedTableNode,
    ParsedTableRowNode,
    build_parsed_material,
    build_parsed_node,
)
from sustainability_desk.material.intake.parse_coverage import ParseCoverage, ParseGap
from sustainability_desk.material.intake.parsed_material_locators import (
    DocumentRootLocator,
    DocxTableLocator,
    DocxTableRowLocator,
    XlsxRowLocator,
    XlsxSheetLocator,
)
from sustainability_desk.material.retrieval.chunks import (
    StructuredDataContextBundle,
    StructuredDataPageCoverage,
    StructuredDataPaginationPolicy,
    StructuredDataTransportPage,
    build_sheet_context_bundle,
    build_table_context_bundle,
    require_owner_level_conclusion,
)
from sustainability_desk.material.retrieval.structured_markdown import (
    build_structured_markdown_projection,
)

SOURCE_SHA = "3" * 64
MATERIAL_FINGERPRINT = "4" * 64
PARSER_PROFILE_ID = "docx-structural@1"


def _table_fixture() -> tuple[
    ParsedMaterial,
    ParsedTableNode,
    tuple[ParsedTableRowNode, ...],
    ParsedTableRowNode,
]:
    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label="表格测试",
    )
    table = build_parsed_node(
        ParsedTableNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxTableLocator(
            part="body",
            block_index=2,
            table_index=1,
        ),
        parent_node_id=root.node_id,
        ordinal_path=(1, 2),
        column_count=2,
        header_row_node_ids=(),
    )

    def build_row(row_index: int, *, is_header: bool) -> ParsedTableRowNode:
        return build_parsed_node(
            ParsedTableRowNode,
            source_sha256=SOURCE_SHA,
            parser_profile_id=PARSER_PROFILE_ID,
            locator=DocxTableRowLocator(
                part="body",
                table_index=1,
                row_index=row_index,
            ),
            parent_node_id=table.node_id,
            ordinal_path=(1, 2, row_index),
            is_header=is_header,
            cells=(
                ParsedCell(column_index=1, text=f"指标 {row_index}"),
                ParsedCell(column_index=2, text=str(row_index)),
            ),
        )

    header = build_row(1, is_header=True)
    data_rows = tuple(
        build_row(index, is_header=False) for index in range(2, 9)
    )
    table = build_parsed_node(
        ParsedTableNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=table.locator,
        parent_node_id=root.node_id,
        ordinal_path=(1, 2),
        column_count=2,
        header_row_node_ids=(header.node_id,),
    )
    nodes = (root, table, header, *data_rows)
    parsed = build_parsed_material(
        source_id=uuid4(),
        source_sha256=SOURCE_SHA,
        document_kind="docx",
        parser_profile_id=PARSER_PROFILE_ID,
        parser_fingerprint="5" * 64,
        normalization_profile_id="test@1",
        root_node_id=root.node_id,
        nodes=nodes,
        coverage=ParseCoverage(
            disposition="complete_for_declared_capabilities",
            source_units_total=len(nodes),
            source_units_parsed=len(nodes),
            text_characters_parsed=0,
            table_cells_parsed=16,
            capabilities=(),
        ),
    )
    return parsed, table, (header, *data_rows), header


def _sheet_fixture() -> tuple[
    ParsedMaterial,
    ParsedSheetNode,
    tuple[ParsedSheetRowNode, ...],
]:
    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label="工作表测试",
    )
    sheet = build_parsed_node(
        ParsedSheetNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=XlsxSheetLocator(sheet_name="定量数据", sheet_index=1),
        parent_node_id=root.node_id,
        ordinal_path=(1, 1),
        label="定量数据",
        sheet_state="visible",
        cell_range=None,
        row_count=0,
        column_count=0,
        cell_count=0,
        row_node_ids=(),
    )
    rows = tuple(
        build_parsed_node(
            ParsedSheetRowNode,
            source_sha256=SOURCE_SHA,
            parser_profile_id="xlsx-structural@1",
            locator=XlsxRowLocator(sheet_name="定量数据", row_index=index),
            parent_node_id=sheet.node_id,
            ordinal_path=(1, 1, index),
            row_index=index,
            hidden=index == 4,
            cells=(
                ParsedCell(
                    column_index=1,
                    cell_reference=f"A{index}",
                    text=f"字段 {index}",
                    hidden_row=index == 4,
                ),
                ParsedCell(
                    column_index=2,
                    cell_reference=f"B{index}",
                    text=str(index),
                    value_kind="formula" if index == 3 else "text",
                    formula="=SUM(B1:B2)" if index == 3 else None,
                    cached_value=3 if index == 3 else None,
                    native_data_type="f" if index == 3 else "s",
                    number_format="0.00" if index == 3 else None,
                    hidden_row=index == 4,
                    hidden_column=True,
                ),
            ),
        )
        for index in range(1, 6)
    )
    sheet = build_parsed_node(
        ParsedSheetNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id="xlsx-structural@1",
        locator=sheet.locator,
        parent_node_id=root.node_id,
        ordinal_path=(1, 1),
        label="定量数据",
        sheet_state="visible",
        cell_range="A1:B5",
        row_count=5,
        column_count=2,
        cell_count=10,
        row_node_ids=tuple(row.node_id for row in rows),
    )
    nodes = (root, sheet, *rows)
    parsed = build_parsed_material(
        source_id=uuid4(),
        source_sha256=SOURCE_SHA,
        document_kind="xlsx",
        parser_profile_id="xlsx-structural@1",
        parser_fingerprint="6" * 64,
        normalization_profile_id="test@1",
        root_node_id=root.node_id,
        nodes=nodes,
        coverage=ParseCoverage(
            disposition="complete_for_declared_capabilities",
            source_units_total=len(nodes),
            source_units_parsed=len(nodes),
            text_characters_parsed=0,
            table_cells_parsed=10,
            capabilities=(),
        ),
    )
    return parsed, sheet, rows


def test_small_table_is_one_whole_owner_context_not_independent_rows() -> None:
    parsed, table, rows, header = _table_fixture()
    policy = StructuredDataPaginationPolicy(
        policy_id="structured-context@1",
        whole_owner_max_rows=10,
        transport_page_max_rows=3,
    )

    first = build_table_context_bundle(
        parsed,
        table_node_id=table.node_id,
        policy=policy,
    )
    second = build_table_context_bundle(
        parsed,
        table_node_id=table.node_id,
        policy=policy,
    )

    assert first.owner.owner_id == second.owner.owner_id
    assert len(first.pages) == 1
    page = first.pages[0]
    assert page.mode == "whole_owner"
    assert page.coverage.row_node_ids == tuple(
        row.node_id for row in rows if not row.is_header
    )
    assert page.full_range.header_row_node_ids == (header.node_id,)
    assert page.coverage.column_coverage == "all_columns"
    assert page.allows_independent_mapping is False
    assert page.allows_owner_level_conclusion is False
    assert first.owner_conclusion_gate == "open"
    require_owner_level_conclusion(first, conclusion_kind="positive")


def test_large_table_pages_repeat_owner_range_and_only_bundle_can_conclude() -> None:
    parsed, table, rows, header = _table_fixture()
    policy = StructuredDataPaginationPolicy(
        policy_id="structured-context@1",
        whole_owner_max_rows=3,
        transport_page_max_rows=3,
    )

    bundle = build_table_context_bundle(
        parsed,
        table_node_id=table.node_id,
        policy=policy,
    )

    assert len(bundle.pages) == 3
    assert all(page.mode == "transport_page" for page in bundle.pages)
    assert all(page.owner_id == bundle.owner.owner_id for page in bundle.pages)
    assert all(page.full_range == bundle.owner.full_range for page in bundle.pages)
    assert all(
        page.full_range.header_row_node_ids == (header.node_id,)
        for page in bundle.pages
    )
    assert all(
        page.coverage.column_coverage == "all_columns"
        for page in bundle.pages
    )
    assert tuple(
        row_id
        for page in bundle.pages
        for row_id in page.coverage.row_node_ids
    ) == bundle.owner.full_range.row_node_ids
    require_owner_level_conclusion(bundle, conclusion_kind="no_evidence")


def test_whole_markdown_is_default_even_when_table_transport_is_paginated() -> None:
    parsed, table, _, _ = _table_fixture()
    policy = StructuredDataPaginationPolicy(
        policy_id="structured-context@1",
        whole_owner_max_rows=2,
        transport_page_max_rows=2,
    )

    first = build_structured_markdown_projection(
        parsed,
        owner_node_id=table.node_id,
        pagination_policy=policy,
    )
    second = build_structured_markdown_projection(
        parsed,
        owner_node_id=table.node_id,
        pagination_policy=policy,
    )

    assert first.projection_id == second.projection_id
    assert first.markdown == second.markdown
    assert first.contract == "sustainability_desk.structured_owner_markdown.v2"
    assert first.projection_profile_id == "structured-owner-markdown@2"
    assert first.render_mode == "pipe_table"
    assert first.default_model_delivery == "whole_markdown"
    assert first.pagination_role == "oversized_transport_only"
    assert len(first.transport_bundle.pages) == 4
    assert "指标 2" in first.markdown
    assert "指标 8" in first.markdown
    assert str(first.owner.owner_id) in first.markdown
    assert first.owner.owner_content_fingerprint in first.markdown
    assert first.owner.full_range.range_fingerprint in first.markdown
    assert "R1C1" in first.markdown
    body = first.markdown.split("## 完整结构化内容\n\n", maxsplit=1)[1]
    assert body.count("&quot;coordinate&quot;") == 16
    assert "&quot;formula&quot;:null" not in body
    assert "&quot;cached_value&quot;:null" not in body
    assert "&quot;hidden_row&quot;:false" not in body
    assert "&quot;hidden_column&quot;:false" not in body
    assert "&quot;row_span&quot;:1" not in body
    assert "&quot;column_span&quot;:1" not in body
    assert '"omitted_fields_equal_defaults"' in first.markdown
    assert {
        gap.code for gap in first.coverage.gaps
    }.issuperset(
        {
            "visual_colors_not_modeled",
            "visual_icons_not_modeled",
            "conditional_formatting_not_modeled",
        }
    )
    assert first.coverage.overall_no_evidence_conclusion_allowed is False


def test_sheet_markdown_preserves_coordinates_formula_and_hidden_markers() -> None:
    parsed, sheet, _ = _sheet_fixture()

    projection = build_structured_markdown_projection(
        parsed,
        owner_node_id=sheet.node_id,
        pagination_policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
            whole_owner_max_rows=20,
            transport_page_max_rows=10,
        ),
    )

    assert projection.render_mode == "pipe_table"
    assert projection.owner.full_range.source_cell_range == "A1:B5"
    assert "derived_navigation_header=true" in projection.markdown
    assert "=SUM(B1:B2)" in projection.markdown
    assert "B3" in projection.markdown
    assert "cached_value&quot;:3" in projection.markdown
    assert "native_data_type&quot;:&quot;f&quot;" in projection.markdown
    assert "number_format&quot;:&quot;0.00&quot;" in projection.markdown
    assert "hidden_row&quot;:true" in projection.markdown
    assert "hidden_column&quot;:true" in projection.markdown
    body = projection.markdown.split("## 完整结构化内容\n\n", maxsplit=1)[1]
    assert "&quot;formula&quot;:null" not in body
    assert "&quot;cached_value&quot;:null" not in body
    assert "&quot;number_format&quot;:null" not in body


def test_merged_table_uses_html_with_rowspan_colspan_and_merge_markers() -> None:
    root = build_parsed_node(
        ParsedDocumentNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocumentRootLocator(),
        parent_node_id=None,
        ordinal_path=(1,),
        label="合并表测试",
    )
    table = build_parsed_node(
        ParsedTableNode,
        source_sha256=SOURCE_SHA,
        parser_profile_id=PARSER_PROFILE_ID,
        locator=DocxTableLocator(
            part="body",
            block_index=1,
            table_index=1,
        ),
        parent_node_id=root.node_id,
        ordinal_path=(1, 1),
        column_count=2,
        header_row_node_ids=(),
    )
    rows: list[ParsedTableRowNode] = []
    for row_index in (1, 2):
        cells = tuple(
            ParsedCell(
                column_index=column_index,
                text="合并事实" if (row_index, column_index) == (1, 1) else "",
                merged_anchor="R1C1",
                merged_range="R1C1:R2C2",
                row_span=2 if (row_index, column_index) == (1, 1) else 1,
                column_span=2 if (row_index, column_index) == (1, 1) else 1,
                hidden_column=(row_index, column_index) == (2, 2),
            )
            for column_index in (1, 2)
        )
        rows.append(
            build_parsed_node(
                ParsedTableRowNode,
                source_sha256=SOURCE_SHA,
                parser_profile_id=PARSER_PROFILE_ID,
                locator=DocxTableRowLocator(
                    part="body",
                    table_index=1,
                    row_index=row_index,
                ),
                parent_node_id=table.node_id,
                ordinal_path=(1, 1, row_index),
                is_header=False,
                cells=cells,
            )
        )
    nodes = (root, table, *rows)
    parsed = build_parsed_material(
        source_id=uuid4(),
        source_sha256=SOURCE_SHA,
        document_kind="docx",
        parser_profile_id=PARSER_PROFILE_ID,
        parser_fingerprint="7" * 64,
        normalization_profile_id="test@1",
        root_node_id=root.node_id,
        nodes=nodes,
        coverage=ParseCoverage(
            disposition="complete_for_declared_capabilities",
            source_units_total=len(nodes),
            source_units_parsed=len(nodes),
            text_characters_parsed=4,
            table_cells_parsed=4,
            capabilities=(),
        ),
    )

    projection = build_structured_markdown_projection(
        parsed,
        owner_node_id=table.node_id,
        pagination_policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
        ),
    )

    assert projection.render_mode == "html_table"
    assert "<table " in projection.markdown
    assert 'rowspan="2"' in projection.markdown
    assert 'colspan="2"' in projection.markdown
    assert projection.markdown.count("&quot;coordinate&quot;") == 4
    assert "merged-covered" in projection.markdown
    assert "merged_range&quot;:&quot;R1C1:R2C2&quot;" in projection.markdown
    assert (
        "coordinate&quot;:&quot;R2C2&quot;,&quot;hidden_column&quot;:true"
        in projection.markdown
    )
    assert "合并事实" in projection.markdown


def test_source_parse_gap_blocks_owner_no_evidence_and_is_visible_in_markdown() -> None:
    complete, table, _, _ = _table_fixture()
    nodes = complete.nodes
    incomplete = build_parsed_material(
        source_id=complete.source_id,
        source_sha256=complete.source_sha256,
        document_kind=complete.document_kind,
        parser_profile_id=complete.parser_profile_id,
        parser_fingerprint=complete.parser_fingerprint,
        normalization_profile_id=complete.normalization_profile_id,
        root_node_id=complete.root_node_id,
        nodes=nodes,
        coverage=ParseCoverage(
            disposition="incomplete_usable",
            source_units_total=len(nodes),
            source_units_parsed=len(nodes) - 1,
            text_characters_parsed=0,
            table_cells_parsed=16,
            capabilities=(),
            gaps=(
                ParseGap(
                    code="unparsed_object",
                    message="存在未解析对象",
                    effect="negative_evidence_blocked",
                ),
                ParseGap(
                    code="unparsed_object",
                    message="存在未解析对象",
                    effect="negative_evidence_blocked",
                ),
            ),
        ),
    )
    projection = build_structured_markdown_projection(
        incomplete,
        owner_node_id=table.node_id,
        pagination_policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
        ),
    )

    with pytest.raises(ValueError, match="否定性证据"):
        require_owner_level_conclusion(
            projection.transport_bundle,
            conclusion_kind="no_evidence",
        )
    assert "source_parse_gap:unparsed_object" in projection.markdown
    assert (
        [
            gap.code
            for gap in projection.coverage.gaps
        ].count("source_parse_gap:unparsed_object")
        == 1
    )


def test_partial_page_set_blocks_positive_and_no_evidence_conclusions() -> None:
    parsed, table, rows, _ = _table_fixture()
    complete = build_table_context_bundle(
        parsed,
        table_node_id=table.node_id,
        policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
            whole_owner_max_rows=2,
            transport_page_max_rows=2,
        ),
    )
    partial = StructuredDataContextBundle(
        owner=complete.owner,
        pages=complete.pages[:-1],
        coverage_status="partial",
        owner_conclusion_gate="blocked",
    )

    for conclusion_kind in ("positive", "no_evidence"):
        with pytest.raises(ValueError, match="全部传输页"):
            require_owner_level_conclusion(
                partial,
                conclusion_kind=conclusion_kind,
            )
    with pytest.raises(ValidationError, match="阻断"):
        StructuredDataContextBundle(
            owner=complete.owner,
            pages=complete.pages[:-1],
            coverage_status="partial",
            owner_conclusion_gate="open",
        )


def test_contract_forbids_column_slices_and_independent_page_mapping() -> None:
    parsed, table, rows, _ = _table_fixture()
    bundle = build_table_context_bundle(
        parsed,
        table_node_id=table.node_id,
        policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
            whole_owner_max_rows=2,
            transport_page_max_rows=2,
        ),
    )
    page = bundle.pages[0]

    with pytest.raises(ValidationError, match="Extra inputs"):
        StructuredDataPageCoverage.model_validate(
            {
                **page.coverage.model_dump(mode="json"),
                "column_start": 1,
                "column_end": 1,
            }
        )
    with pytest.raises(ValidationError):
        StructuredDataTransportPage.model_validate(
            {
                **page.model_dump(mode="json"),
                "allows_independent_mapping": True,
            }
        )


def test_whole_sheet_owner_keeps_all_rows_and_does_not_guess_headers() -> None:
    parsed, sheet, rows = _sheet_fixture()
    bundle = build_sheet_context_bundle(
        parsed,
        sheet_node_id=sheet.node_id,
        policy=StructuredDataPaginationPolicy(
            policy_id="structured-context@1",
            whole_owner_max_rows=2,
            transport_page_max_rows=2,
        ),
    )

    assert bundle.owner.owner_kind == "sheet"
    assert bundle.owner.full_range.row_node_ids == tuple(
        row.node_id for row in rows
    )
    assert bundle.owner.full_range.header_row_node_ids == ()
    assert bundle.owner.full_range.column_count == 2
    assert bundle.owner.full_range.source_cell_range == "A1:B5"
    assert len(bundle.pages) == 3
    assert all(page.full_range == bundle.owner.full_range for page in bundle.pages)
    assert all(
        page.coverage.column_coverage == "all_columns"
        for page in bundle.pages
    )
