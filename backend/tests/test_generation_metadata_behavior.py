# ABOUTME: 生成元数据行为测试——表格行数区间取自 block.generation.rowCount；段落字数区间为软校验（warn 不阻断）。
# ABOUTME: 守护「rowCount/targetChars 是 GenerationSpec 一等字段」与「字数越界软提示、不硬阻断生成」。
from sustainability_desk.contract.models import Block, GenerationSpec, GsColDef, GsTable
from sustainability_desk.llm import table_gen as TG
from sustainability_desk.llm.generate import _length_warnings


def _table_block(row_count):
    return Block(
        id="t.x", type="table", blockType="generative", source="ai",
        generation=GenerationSpec(task={"focus": "x"}, rowCount=row_count),
        table=GsTable(colDefs=[GsColDef(key="name", header="名")]),
    )


def test_row_count_from_block_generation():
    assert TG._row_count(_table_block((2, 5))) == (2, 5)


def test_row_count_defaults_when_absent():
    assert TG._row_count(_table_block(None)) == (3, TG.DEFAULT_MAX_ROWS)


def test_length_softcheck_flags_only_out_of_range():
    """字数软校验：越界版本返回提示，区间内不提示；目标缺省则全不提示。"""
    warns = _length_warnings(["字" * 100, "字" * 200], (150, 320), "zh-Hans")
    assert len(warns) == 1 and "100" in warns[0]
    assert _length_warnings(["字" * 200], None, "zh-Hans") == []
