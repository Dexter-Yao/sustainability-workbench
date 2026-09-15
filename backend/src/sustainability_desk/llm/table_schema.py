# ABOUTME: 表格 AI 生成 SOP——行 schema 从 GsColDef 动态推导（create_model）+ 定行 RowSeed 受控模型。
# ABOUTME: select 列约束为 Literal/合法选项；multi_select 去重 + 最大项数；列 key 须合法标识符（loader 已校验）。
# ABOUTME(en): Table generation SOP: the row schema derives dynamically from GsColDef plus a controlled RowSeed model.
# ABOUTME(en): select columns become Literals; multi_select is deduplicated and capped; column keys must be identifiers.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, create_model, field_validator

from sustainability_desk.contract.models import GsColDef, RowExpansion
from sustainability_desk.llm.provider_output import parse_stringified_json

MAX_MULTI_SELECT = 4  # multi_select 单元格最大项数（MVP 宽松上限，配置可调）


class RowSeed(BaseModel):
    """AI 定行的受控条目：行级生成的白名单输入（绝不混入 facts/brief）。"""

    theme: str                          # 该行主题（如风险/机遇名称大类）
    category: str | None = None         # 可选归类（如「政策法律」「急性物理风险」）
    driver_hint: str | None = None      # 可选驱动因素提示（行业路径据 TCFD 标杆给）


class RowSeedList(BaseModel):
    """定行结构化输出容器。"""

    rows: list[RowSeed]


def row_model_from_columns(
    columns: list[GsColDef],
    *,
    model_name: str = "DynamicRow",
    options_narrowing: dict[str, list[str]] | None = None,
) -> type[BaseModel]:
    """据 columns 动态推导该表的行 Pydantic 模型（结构化输出 schema）。

    single_select → Literal[*options]；multi_select → list[Literal[*options]]（去重 + 最大项数）；
    text/ai_text → str。列 key 合法性由 loader.validate_column_keys 在加载期保证。
    options_narrowing 按列收窄候选（子行展开用），其为列级 options 子集由 loader 在加载期保证。
    """
    fields: dict[str, tuple] = {}
    multi_keys: list[str] = []
    narrowing = options_narrowing or {}

    for col in columns:
        options = narrowing.get(col.key, col.options)
        if col.cellType == "single_select" and options:
            typ = Literal[tuple(options)]  # type: ignore[valid-type]
        elif col.cellType == "multi_select" and options:
            typ = list[Literal[tuple(options)]]  # type: ignore[valid-type]
            multi_keys.append(col.key)
        else:
            typ = str
        fields[col.key] = (typ, ...)

    def _dedupe(cls, v):  # cls 为 pydantic 校验时传入的模型类
        if isinstance(v, list):
            seen: list = []
            for x in v:
                if x not in seen:
                    seen.append(x)
            if len(seen) > MAX_MULTI_SELECT:
                raise ValueError(f"多选项数超上限 {MAX_MULTI_SELECT}")
            return seen
        return v

    validators = (
        {
            "_dedupe_multi": field_validator(*multi_keys, mode="after")(_dedupe)
        }
        if multi_keys
        else {}
    )

    return create_model(model_name, __validators__=validators, **fields)


def expanded_row_model(
    columns: list[GsColDef], expansion: RowExpansion
) -> type[BaseModel]:
    """据 rowExpansion 推导「一个业务行」的嵌套输出模型：共享列在外层，每个子行一个嵌套对象。

    模型一次产出该业务行的全部披露子行，因而能在同一次判断中区分影响与风险机遇；
    rowSpan、占位格与表格行序均不进入 schema，由 table_ops 确定性展开。
    """
    by_key = {col.key: col for col in columns}
    shared_model = row_model_from_columns(
        [by_key[key] for key in expansion.sharedColumnKeys],
        model_name="ExpandedRowShared",
    )
    fields: dict[str, tuple] = {}
    for unit in expansion.units:
        fields[unit.key] = (
            row_model_from_columns(
                [by_key[key] for key in unit.columnKeys],
                model_name=f"ExpandedUnit_{unit.key}",
                options_narrowing=unit.optionsNarrowing,
            ),
            ...,
        )

    def _parse_stringified_unit(cls, value: object) -> object:  # noqa: N805
        # 与 image agent 同一条 ToolOutput 路径上的同一个模型行为，故共用
        # generate.parse_stringified_json，不再各自维护一份还原逻辑。
        return parse_stringified_json(value)

    unit_keys = [unit.key for unit in expansion.units]
    return create_model(
        "ExpandedRow",
        __base__=shared_model,
        __validators__={
            "_parse_stringified_units": field_validator(*unit_keys, mode="before")(
                classmethod(_parse_stringified_unit)
            )
        },
        **fields,
    )
