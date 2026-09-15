# ABOUTME: 表格 AI 生成 SOP 后端单测——行模型动态推导、列 key 校验、GsColDef.genHint。
import pytest

from sustainability_desk.contract.loader import validate_column_keys
from sustainability_desk.contract.models import Block, GsColDef, GsTable, Report, Section
from sustainability_desk.llm.table_schema import row_model_from_columns
from knowledge_package_fixtures import SSE_PACKAGE


def test_column_def_accepts_gen_hint():
    """GsColDef 支持 genHint（列级生成指引，来源限受控 YAML）。"""
    col = GsColDef(key="response", header="应对措施", cellType="ai_text", genHint="覆盖缓解/转移/承受/控制四类")
    assert col.genHint == "覆盖缓解/转移/承受/控制四类"


def test_column_def_gen_hint_defaults_none():
    """未传入 genHint 时默认为 None，既有 YAML 不受该字段影响。"""
    col = GsColDef(key="name", header="名称")
    assert col.genHint is None


def test_column_def_gen_hint_rejects_non_str():
    """genHint 仅接受 str 或 None，其他类型应被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GsColDef(key="x", header="x", genHint={"injected": "payload"})


def _report_with_col_key(key: str) -> Report:
    """构造含单张表（单列、key 为指定值）的最小 Report，供列 key 校验测试复用。"""
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[Section(key="s", title="S", headingLevel=1, blocks=[
            Block(id="b", type="table", blockType="generative", source="ai",
                  table=GsTable(colDefs=[GsColDef(key=key, header="H")])),
        ])],
    )


@pytest.mark.parametrize("good", ["value_chain", "x", "col2"])
def test_legal_column_key_passes(good):
    """合法 ASCII 标识符列 key（含下划线、单字符、数字结尾）通过校验。"""
    validate_column_keys(_report_with_col_key(good))  # 不抛


@pytest.mark.parametrize("bad", ["影响价值链", "value-chain", "value.chain", "1col"])
def test_illegal_column_key_fails_loud(bad):
    """非法列 key（中文/短横线/点号/数字开头）fail-loud。"""
    with pytest.raises(ValueError, match="列 key"):
        validate_column_keys(_report_with_col_key(bad))


def _cols():
    return [
        GsColDef(key="name", header="名称", cellType="text"),
        GsColDef(key="response", header="应对", cellType="ai_text"),
        GsColDef(key="magnitude", header="程度", cellType="single_select", options=["一般重要", "重要", "非常重要"]),
        GsColDef(key="value_chain", header="价值链", cellType="multi_select", options=["上游价值链", "公司运营", "下游价值链"]),
    ]


def test_row_model_text_and_ai_text_are_str():
    """text/ai_text 列推导为 str 字段。"""
    M = row_model_from_columns(_cols())
    inst = M(name="市场风险", response="加强监测", magnitude="重要", value_chain=["公司运营"])
    assert inst.name == "市场风险" and inst.response == "加强监测"


def test_single_select_rejects_illegal_option():
    """single_select 推导为 Literal，非法选项被拒。"""
    M = row_model_from_columns(_cols())
    with pytest.raises(Exception):
        M(name="x", response="y", magnitude="不存在的选项", value_chain=["公司运营"])


def test_multi_select_rejects_illegal_and_is_list():
    """multi_select 推导为 list[Literal]，非法元素被拒、合法为 list。"""
    M = row_model_from_columns(_cols())
    with pytest.raises(Exception):
        M(name="x", response="y", magnitude="重要", value_chain=["不存在"])
    inst = M(name="x", response="y", magnitude="重要", value_chain=["公司运营", "下游价值链"])
    assert inst.value_chain == ["公司运营", "下游价值链"]


def test_multi_select_dedupes():
    """multi_select 去重（保序）。"""
    M = row_model_from_columns(_cols())
    inst = M(name="x", response="y", magnitude="重要", value_chain=["公司运营", "公司运营"])
    assert inst.value_chain == ["公司运营"]


def test_multi_select_rejects_over_limit():
    """multi_select 去重后超过 MAX_MULTI_SELECT 应被拒。"""
    cols = [GsColDef(key="vc", header="价值链", cellType="multi_select",
                      options=["a", "b", "c", "d", "e"])]
    M = row_model_from_columns(cols)
    with pytest.raises(Exception):
        M(vc=["a", "b", "c", "d", "e"])  # 去重后 5 项 > MAX_MULTI_SELECT(4)
