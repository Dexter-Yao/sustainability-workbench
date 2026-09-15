# ABOUTME: fill_report 表格填充测试——按列 key 取值（列驱动、不依赖列序）+ sample_values 表键与 schema 列一致。
from pathlib import Path

import pytest
import yaml

from sustainability_desk.contract.fill import ReportContent, apply_report_content, fill_report
from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import Block, GsColDef, GsTable, Report, Section
from sustainability_desk.contract.table_ops import row_values
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.planner import load_topic_templates_from
from sustainability_desk.contract.company_inputs import parse_company_inputs

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = SSE_PACKAGE.report_contract_path
TOPIC_DIR = SSE_PACKAGE.topic_sections_dir
SAMPLE_VALUES = SSE_PACKAGE.sample_values_path


def _table_report() -> Report:
    cols = [
        GsColDef(key="name", header="名称", cellType="text"),
        GsColDef(key="tags", header="标签", cellType="multi_select", options=["A", "B"]),
    ]
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(id="b.tbl", type="table", blockType="slot", source="user_input",
              table=GsTable(colDefs=cols)),
    ])])


def test_fill_report_table_rows_keyed_by_column_key():
    """表格值以 {列key: 值} 字典提供，按列 key 填入 cells；与字典书写顺序无关。"""
    report = _table_report()
    # 字典键序故意与列序相反，验证按 key 匹配而非位置
    values = {"tables": {"b.tbl": [{"tags": ["A", "B"], "name": "行1"}]}}
    children = fill_report(report, values).find_block("b.tbl").table.children
    assert len(children) == 1
    assert row_values(children[0]) == {"name": "行1", "tags": ["A", "B"]}


def test_fill_report_rejects_non_dict_table_row():
    """表格行非 dict（如误传旧 list[list] 格式）应 fail-loud，而非静默产生空 cells。"""
    report = _table_report()
    with pytest.raises(ValueError):
        fill_report(report, {"tables": {"b.tbl": [["奖项", "机构"]]}})


def test_generated_text_only_overwrites_generation_paragraphs():
    """generated 正文只写入可生成段落；fixed/slot 文案以模板为准。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(
            id="p.gen",
            type="paragraph",
            blockType="constrained",
            source="ai",
            generation={"task": {"focus": "p.gen"}},
            content=[{"kind": "text", "text": "生成占位"}],
        ),
        Block(
            id="p.fixed",
            type="paragraph",
            blockType="fixed",
            source="template",
            content=[{"kind": "text", "text": "固定文案"}],
        ),
    ])])

    filled = apply_report_content(
        report,
        ReportContent(generated={"p.gen": "生成正文", "p.fixed": "不应覆盖"}),
    )

    assert filled.find_block("p.gen").content[0].text == "生成正文"
    assert filled.find_block("p.fixed").content[0].text == "固定文案"


def test_generated_text_writeback_does_not_require_generation_spec():
    """generated 是已生成内容写回，不依赖该块当前是否仍有 generation 配置。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", sections=[Section(key="s", title="S", headingLevel=1, blocks=[
        Block(
            id="p.gen",
            type="paragraph",
            blockType="generative",
            source="ai",
            content=[{"kind": "text", "text": "生成占位"}],
        ),
    ])])

    filled = fill_report(report, {"generated": {"p.gen": "生成正文"}})

    assert report.find_block("p.gen").content[0].text == "生成占位"
    assert filled.find_block("p.gen").content[0].text == "生成正文"


def _walk_blocks(sec):
    yield from sec.blocks
    for child in (sec.children or []):
        yield from _walk_blocks(child)


def _all_table_columns() -> dict[str, list[str]]:
    cols: dict[str, list[str]] = {}
    for blk in load_contract(CONTRACT).iter_blocks():
        if blk.table is not None:
            cols[blk.id] = blk
    for sec in load_topic_templates_from(TOPIC_DIR, package=SSE_PACKAGE).values():
        for blk in _walk_blocks(sec):
            if blk.table is not None:
                cols[blk.id] = blk
    return cols


def _expected_row_keys(blk: Block) -> set[str]:
    """样例值行的期望键集：普通表＝列键；声明 rowExpansion 的表＝共享列 + 各子行 key。"""
    expansion = blk.generation.rowExpansion if blk.generation else None
    if expansion is None:
        return {c.key for c in blk.table.colDefs}
    return set(expansion.sharedColumnKeys) | {u.key for u in expansion.units}


def test_sample_values_table_keys_match_schema_columns():
    """sample_values.yaml 每个表的每行均为 dict，且列键与对应 block 的 schema 列键完全一致（防列名漂移 / 缺列）。

    期望键集由块的生成契约决定（rowExpansion 声明子行时按子行形态），不从列名推断表型。
    """
    tables = (yaml.safe_load(SAMPLE_VALUES.read_text(encoding="utf-8")).get("content") or {}).get("tables", {})
    blocks = _all_table_columns()
    assert tables, "sample_values.yaml 应含 tables"
    for block_id, rows in tables.items():
        assert block_id in blocks, f"未知表块: {block_id}"
        blk = blocks[block_id]
        allowed = _expected_row_keys(blk)
        expansion = blk.generation.rowExpansion if blk.generation else None
        for i, row in enumerate(rows):
            assert isinstance(row, dict), f"{block_id} 第 {i} 行应为 dict（列键→值），实为 {type(row).__name__}"
            assert set(row) == allowed, (
                f"{block_id} 第 {i} 行列键 {sorted(row)} 与期望列 {sorted(allowed)} 不完全一致"
            )
            for unit in expansion.units if expansion else []:
                unit_row = row[unit.key]
                assert isinstance(unit_row, dict), f"{block_id} 第 {i} 行子行「{unit.label}」应为 dict"
                assert set(unit_row) == set(unit.columnKeys), (
                    f"{block_id} 第 {i} 行子行「{unit.label}」列键 {sorted(unit_row)} "
                    f"与期望 {sorted(unit.columnKeys)} 不一致"
                )


def test_sample_values_generated_keys_target_generation_blocks():
    """sample_values.yaml 的 generated 正文只能指向当前装配后的可生成段落。"""
    from sustainability_desk.contract.build_report import build_report

    raw = yaml.safe_load(SAMPLE_VALUES.read_text(encoding="utf-8"))
    report = build_report(parse_company_inputs(package=SSE_PACKAGE, raw=raw["inputs"]))
    generated = (raw.get("content") or {}).get("generated", {})

    assert generated, "sample_values.yaml 应含 generated"
    for block_id in generated:
        block = report.find_block(block_id)
        assert block is not None, f"未知生成块: {block_id}"
        assert block.type == "paragraph", f"{block_id} 不是段落块"
        assert block.blockType in {"generative", "constrained"}, f"{block_id} 不是可生成块"
        assert block.generation is not None, f"{block_id} 缺少 generation 配置"
