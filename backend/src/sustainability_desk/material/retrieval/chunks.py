# ABOUTME: 构建 whole-table/whole-sheet-first 结构化上下文合同。
# ABOUTME: 超大结构化数据只允许全列行分页传输，完整页集合形成前禁止任何 owner 级结论。
# ABOUTME(en): Builds a whole-table / whole-sheet-first structured context contract.
# ABOUTME(en): Oversized structured data pages by full-width rows; no owner-level conclusion before all pages exist.
from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sustainability_desk.material.intake.parsed_material import (
    ParsedMaterial,
    ParsedSheetNode,
    ParsedSheetRowNode,
    ParsedTableNode,
    ParsedTableRowNode,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RetrievalContractModel(BaseModel):
    """检索与模型上下文合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StructuredDataPaginationPolicy(RetrievalContractModel):
    """结构化 owner 的 whole-first 与传输分页阈值。"""

    policy_id: str = Field(min_length=1)
    whole_owner_max_rows: int = Field(default=200, ge=0)
    transport_page_max_rows: int = Field(default=100, ge=1)


class StructuredDataFullRange(RetrievalContractModel):
    """owner 的完整行列范围；分页只能引用该范围的连续行。"""

    range_fingerprint: str = Field(pattern=SHA256_PATTERN)
    row_node_ids: tuple[UUID, ...]
    header_row_node_ids: tuple[UUID, ...]
    column_count: int = Field(ge=0)
    source_cell_range: str | None = None

    @model_validator(mode="after")
    def _validate_refs(self) -> "StructuredDataFullRange":
        if len(self.row_node_ids) != len(set(self.row_node_ids)):
            raise ValueError("owner 完整范围的数据行引用不得重复")
        if len(self.header_row_node_ids) != len(set(self.header_row_node_ids)):
            raise ValueError("owner 表头行引用不得重复")
        if set(self.row_node_ids) & set(self.header_row_node_ids):
            raise ValueError("表头行不得同时进入数据行主范围")
        expected = structured_data_range_fingerprint(
            row_node_ids=self.row_node_ids,
            header_row_node_ids=self.header_row_node_ids,
            column_count=self.column_count,
            source_cell_range=self.source_cell_range,
        )
        if self.range_fingerprint != expected:
            raise ValueError("owner 完整范围指纹无效")
        return self


class StructuredDataOwner(RetrievalContractModel):
    """whole-table 或 whole-sheet 的唯一上下文 owner。"""

    owner_id: UUID
    owner_kind: Literal["table", "sheet"]
    owner_node_id: UUID
    parsed_material_fingerprint: str = Field(pattern=SHA256_PATTERN)
    owner_content_fingerprint: str = Field(pattern=SHA256_PATTERN)
    full_range: StructuredDataFullRange
    source_negative_evidence_allowed: bool

    @model_validator(mode="after")
    def _validate_stable_identity(self) -> "StructuredDataOwner":
        expected = stable_structured_data_owner_id(
            owner_kind=self.owner_kind,
            owner_node_id=self.owner_node_id,
            parsed_material_fingerprint=self.parsed_material_fingerprint,
        )
        if self.owner_id != expected:
            raise ValueError("结构化数据 owner 稳定身份无效")
        return self


class StructuredDataPageCoverage(RetrievalContractModel):
    """一个传输页在 owner 完整行范围中的连续覆盖。"""

    full_range_fingerprint: str = Field(pattern=SHA256_PATTERN)
    row_start_index: int = Field(ge=0)
    row_end_index: int = Field(ge=0)
    row_node_ids: tuple[UUID, ...]
    column_coverage: Literal["all_columns"] = "all_columns"

    @model_validator(mode="after")
    def _validate_indices(self) -> "StructuredDataPageCoverage":
        if not self.row_node_ids:
            if self.row_start_index != 0 or self.row_end_index != 0:
                raise ValueError("空 owner 页的行范围必须为 0..0")
            return self
        if self.row_start_index < 1 or self.row_end_index < self.row_start_index:
            raise ValueError("结构化数据页必须使用有效的一基连续行范围")
        expected_count = self.row_end_index - self.row_start_index + 1
        if expected_count != len(self.row_node_ids):
            raise ValueError("结构化数据页行范围与行引用数量不一致")
        return self


class StructuredDataTransportPage(RetrievalContractModel):
    """whole owner 或超大 owner 的传输页；页本身永远不可独立映射。"""

    page_id: UUID
    owner_id: UUID
    pagination_policy_id: str = Field(min_length=1)
    mode: Literal["whole_owner", "transport_page"]
    page_ordinal: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    full_range: StructuredDataFullRange
    coverage: StructuredDataPageCoverage
    allows_independent_mapping: Literal[False] = False
    allows_owner_level_conclusion: Literal[False] = False

    @model_validator(mode="after")
    def _validate_page(self) -> "StructuredDataTransportPage":
        if self.page_ordinal > self.total_pages:
            raise ValueError("结构化数据页序号不得超过总页数")
        if self.coverage.full_range_fingerprint != self.full_range.range_fingerprint:
            raise ValueError("结构化数据页 coverage 未绑定 owner 完整范围")
        expected_page_id = stable_structured_data_page_id(
            owner_id=self.owner_id,
            pagination_policy_id=self.pagination_policy_id,
            page_ordinal=self.page_ordinal,
            coverage=self.coverage,
        )
        if self.page_id != expected_page_id:
            raise ValueError("结构化数据传输页稳定身份无效")
        if self.mode == "whole_owner" and (
            self.page_ordinal != 1 or self.total_pages != 1
        ):
            raise ValueError("whole_owner 必须且只能由单页表达")
        if self.mode == "transport_page" and self.total_pages == 1:
            raise ValueError("单页结构化数据不得伪装为传输分页")
        return self


class StructuredDataContextBundle(RetrievalContractModel):
    """结构化 owner 的完整或部分传输集合及结论闸门。"""

    owner: StructuredDataOwner
    pages: tuple[StructuredDataTransportPage, ...] = Field(min_length=1)
    coverage_status: Literal["complete", "partial"]
    owner_conclusion_gate: Literal["open", "blocked"]

    @model_validator(mode="after")
    def _validate_bundle(self) -> "StructuredDataContextBundle":
        total_pages = {page.total_pages for page in self.pages}
        policy_ids = {page.pagination_policy_id for page in self.pages}
        ordinals = [page.page_ordinal for page in self.pages]
        if len(total_pages) != 1 or len(policy_ids) != 1:
            raise ValueError("结构化数据页必须共享总页数和分页策略")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("结构化数据页序号不得重复")
        for page in self.pages:
            if page.owner_id != self.owner.owner_id:
                raise ValueError("结构化数据页引用了其他 owner")
            if page.full_range != self.owner.full_range:
                raise ValueError("每个结构化数据页必须携带 owner 完整范围")
            start = page.coverage.row_start_index
            end = page.coverage.row_end_index
            expected_rows = (
                self.owner.full_range.row_node_ids[start - 1 : end]
                if start > 0
                else ()
            )
            if page.coverage.row_node_ids != expected_rows:
                raise ValueError("结构化数据页必须覆盖 owner 的连续完整行切片")

        expected_ordinals = list(range(1, next(iter(total_pages)) + 1))
        ordered_pages = sorted(self.pages, key=lambda page: page.page_ordinal)
        exact_complete = (
            sorted(ordinals) == expected_ordinals
            and tuple(
                row_id
                for page in ordered_pages
                for row_id in page.coverage.row_node_ids
            )
            == self.owner.full_range.row_node_ids
        )
        if exact_complete:
            if (
                self.coverage_status != "complete"
                or self.owner_conclusion_gate != "open"
            ):
                raise ValueError("完整页覆盖必须打开 owner 级结论闸门")
        elif (
            self.coverage_status != "partial"
            or self.owner_conclusion_gate != "blocked"
        ):
            raise ValueError("不完整页覆盖必须阻断 owner 级结论闸门")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def structured_data_range_fingerprint(
    *,
    row_node_ids: tuple[UUID, ...],
    header_row_node_ids: tuple[UUID, ...],
    column_count: int,
    source_cell_range: str | None,
) -> str:
    """生成结构化 owner 完整行列范围指纹。"""

    return _fingerprint(
        {
            "row_node_ids": [str(node_id) for node_id in row_node_ids],
            "header_row_node_ids": [
                str(node_id) for node_id in header_row_node_ids
            ],
            "column_count": column_count,
            "source_cell_range": source_cell_range,
        }
    )


def stable_structured_data_owner_id(
    *,
    owner_kind: Literal["table", "sheet"],
    owner_node_id: UUID,
    parsed_material_fingerprint: str,
) -> UUID:
    """按 ParsedMaterial 与 owner 节点生成稳定结构化上下文身份。"""

    identity = _canonical_json(
        {
            "owner_kind": owner_kind,
            "owner_node_id": str(owner_node_id),
            "parsed_material_fingerprint": parsed_material_fingerprint,
        }
    )
    return uuid5(NAMESPACE_URL, f"sustainability_desk.structured-data-owner:{identity}")


def stable_structured_data_page_id(
    *,
    owner_id: UUID,
    pagination_policy_id: str,
    page_ordinal: int,
    coverage: StructuredDataPageCoverage,
) -> UUID:
    """按 owner、策略和连续行覆盖生成稳定传输页身份。"""

    identity = _canonical_json(
        {
            "owner_id": str(owner_id),
            "pagination_policy_id": pagination_policy_id,
            "page_ordinal": page_ordinal,
            "coverage": coverage.model_dump(mode="json"),
        }
    )
    return uuid5(NAMESPACE_URL, f"sustainability_desk.structured-data-page:{identity}")


def _build_structured_bundle(
    *,
    owner_kind: Literal["table", "sheet"],
    owner_node_id: UUID,
    owner_content_fingerprint: str,
    row_node_ids: tuple[UUID, ...],
    header_row_node_ids: tuple[UUID, ...],
    column_count: int,
    source_cell_range: str | None,
    source_negative_evidence_allowed: bool,
    parsed_material_fingerprint: str,
    policy: StructuredDataPaginationPolicy,
) -> StructuredDataContextBundle:
    range_fingerprint = structured_data_range_fingerprint(
        row_node_ids=row_node_ids,
        header_row_node_ids=header_row_node_ids,
        column_count=column_count,
        source_cell_range=source_cell_range,
    )
    full_range = StructuredDataFullRange(
        range_fingerprint=range_fingerprint,
        row_node_ids=row_node_ids,
        header_row_node_ids=header_row_node_ids,
        column_count=column_count,
        source_cell_range=source_cell_range,
    )
    owner_id = stable_structured_data_owner_id(
        owner_kind=owner_kind,
        owner_node_id=owner_node_id,
        parsed_material_fingerprint=parsed_material_fingerprint,
    )
    owner = StructuredDataOwner(
        owner_id=owner_id,
        owner_kind=owner_kind,
        owner_node_id=owner_node_id,
        parsed_material_fingerprint=parsed_material_fingerprint,
        owner_content_fingerprint=owner_content_fingerprint,
        full_range=full_range,
        source_negative_evidence_allowed=source_negative_evidence_allowed,
    )
    if len(row_node_ids) <= policy.whole_owner_max_rows:
        groups = (row_node_ids,)
        mode: Literal["whole_owner", "transport_page"] = "whole_owner"
    else:
        groups = tuple(
            row_node_ids[offset : offset + policy.transport_page_max_rows]
            for offset in range(0, len(row_node_ids), policy.transport_page_max_rows)
        )
        mode = "transport_page"
    pages: list[StructuredDataTransportPage] = []
    row_start = 1
    for page_ordinal, group in enumerate(groups, start=1):
        if group:
            row_end = row_start + len(group) - 1
            coverage = StructuredDataPageCoverage(
                full_range_fingerprint=range_fingerprint,
                row_start_index=row_start,
                row_end_index=row_end,
                row_node_ids=group,
            )
            row_start = row_end + 1
        else:
            coverage = StructuredDataPageCoverage(
                full_range_fingerprint=range_fingerprint,
                row_start_index=0,
                row_end_index=0,
                row_node_ids=(),
            )
        pages.append(
            StructuredDataTransportPage(
                page_id=stable_structured_data_page_id(
                    owner_id=owner_id,
                    pagination_policy_id=policy.policy_id,
                    page_ordinal=page_ordinal,
                    coverage=coverage,
                ),
                owner_id=owner_id,
                pagination_policy_id=policy.policy_id,
                mode=mode,
                page_ordinal=page_ordinal,
                total_pages=len(groups),
                full_range=full_range,
                coverage=coverage,
            )
        )
    return StructuredDataContextBundle(
        owner=owner,
        pages=tuple(pages),
        coverage_status="complete",
        owner_conclusion_gate="open",
    )


def build_table_context_bundle(
    parsed_material: ParsedMaterial,
    *,
    table_node_id: UUID,
    policy: StructuredDataPaginationPolicy,
) -> StructuredDataContextBundle:
    """以整个表为 owner 构建上下文，行页只承担超大表传输。"""

    table = next(
        (
            node
            for node in parsed_material.nodes
            if node.node_id == table_node_id
            and isinstance(node, ParsedTableNode)
        ),
        None,
    )
    if table is None:
        raise ValueError("ParsedMaterial 不包含目标表格 owner")
    rows = tuple(
        node
        for node in parsed_material.nodes
        if isinstance(node, ParsedTableRowNode)
        and node.parent_node_id == table.node_id
    )
    ordered_rows = sorted(rows, key=lambda row: row.ordinal_path)
    declared_headers = set(table.header_row_node_ids)
    observed_headers = {row.node_id for row in ordered_rows if row.is_header}
    if declared_headers != observed_headers:
        raise ValueError("表格上下文必须提供全部且仅提供已声明表头行")
    data_rows = tuple(row.node_id for row in ordered_rows if not row.is_header)
    return _build_structured_bundle(
        owner_kind="table",
        owner_node_id=table.node_id,
        owner_content_fingerprint=table.content_fingerprint,
        row_node_ids=data_rows,
        header_row_node_ids=table.header_row_node_ids,
        column_count=table.column_count,
        source_cell_range=(
            table.locator.cell_range
            if table.locator.kind == "xlsx_table"
            else None
        ),
        source_negative_evidence_allowed=(
            parsed_material.coverage.allows_negative_evidence
        ),
        parsed_material_fingerprint=parsed_material.content_fingerprint,
        policy=policy,
    )


def build_sheet_context_bundle(
    parsed_material: ParsedMaterial,
    *,
    sheet_node_id: UUID,
    policy: StructuredDataPaginationPolicy,
) -> StructuredDataContextBundle:
    """以整个工作表为 owner 构建上下文，不猜测来源未声明的表头。"""

    sheet = next(
        (
            node
            for node in parsed_material.nodes
            if node.node_id == sheet_node_id
            and isinstance(node, ParsedSheetNode)
        ),
        None,
    )
    if sheet is None:
        raise ValueError("ParsedMaterial 不包含目标工作表 owner")
    rows = tuple(
        node
        for node in parsed_material.nodes
        if isinstance(node, ParsedSheetRowNode)
        and node.parent_node_id == sheet.node_id
    )
    ordered_rows = sorted(rows, key=lambda row: row.ordinal_path)
    observed_column_count = max(
        (
            cell.column_index
            for row in ordered_rows
            for cell in row.cells
        ),
        default=0,
    )
    observed_row_ids = tuple(row.node_id for row in ordered_rows)
    if observed_row_ids != sheet.row_node_ids:
        raise ValueError("工作表上下文必须提供 sheet owner 声明的完整有序行集合")
    if observed_column_count != sheet.column_count:
        raise ValueError("工作表上下文列数与 sheet owner 声明不一致")
    return _build_structured_bundle(
        owner_kind="sheet",
        owner_node_id=sheet.node_id,
        owner_content_fingerprint=sheet.content_fingerprint,
        row_node_ids=sheet.row_node_ids,
        header_row_node_ids=(),
        column_count=sheet.column_count,
        source_cell_range=sheet.cell_range,
        source_negative_evidence_allowed=(
            parsed_material.coverage.allows_negative_evidence
        ),
        parsed_material_fingerprint=parsed_material.content_fingerprint,
        policy=policy,
    )


def require_owner_level_conclusion(
    bundle: StructuredDataContextBundle,
    *,
    conclusion_kind: Literal["positive", "no_evidence"],
) -> None:
    """在表级事实或无证据结论前强制检查完整覆盖闸门。"""

    if (
        bundle.coverage_status != "complete"
        or bundle.owner_conclusion_gate != "open"
    ):
        raise ValueError(
            f"{conclusion_kind} owner 级结论需要全部传输页完整覆盖"
        )
    if (
        conclusion_kind == "no_evidence"
        and not bundle.owner.source_negative_evidence_allowed
    ):
        raise ValueError("no_evidence owner 级结论需要来源解析允许否定性证据")
