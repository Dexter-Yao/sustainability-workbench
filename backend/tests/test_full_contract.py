# ABOUTME: 前四章契约（模板形态）加载与不变量测试——无具体值、块均分类、备注捕获、引用完整。

import pytest

from sustainability_desk.contract.loader import load_contract
from knowledge_package_fixtures import SSE_PACKAGE

CONTRACT = SSE_PACKAGE.report_contract_path


def test_template_form_has_no_field_values():
    """报告固定骨架不应含任何具体公司数据。"""
    report = load_contract(CONTRACT)
    assert all(f.value is None for f in report.fields.values()), "模板契约不应含字段值"


def test_blocks_typed():
    report = load_contract(CONTRACT)
    blocks = list(report.iter_blocks())
    assert len(blocks) >= 20
    assert all(b.blockType for b in blocks), "每块都应有 blockType"


def test_refs_resolve_to_defined_fields():
    """正文块与章节标题的 ref 必须指向已定义字段（引用完整性）。"""
    report = load_contract(CONTRACT)
    keys = set(report.fields)

    def valid_ref(ref: str) -> bool:
        return (
            ref in keys
            or ref in {
                "assessment.counts.dual",
                "assessment.counts.impact_only",
                "assessment.counts.financial_only",
                "assessment.counts.non_material",
                "assessment.applicableTopicCount",
            }
            or (ref.startswith("assessment.topics.") and ref.endswith(".materiality"))
            or ref in {
                "disclosureProfile.basisStatement",
                "disclosureProfile.selectedStandardNames",
                "appendixPackage.externalAssuranceReport.fileLabel",
                "appendixPackage.readerFeedbackContactInformation.address",
                "appendixPackage.readerFeedbackContactInformation.email",
                "appendixPackage.readerFeedbackContactInformation.phone",
            }
        )

    for b in report.iter_blocks():
        for inl in b.content or []:
            if inl.kind == "ref":
                assert valid_ref(inl.ref), f"{b.id} 引用未定义字段 {inl.ref}"
        # 脚注与正文同样进交付物，其 ref 必须一并可解析。
        for inl in b.footnote or []:
            if inl.kind == "ref":
                assert valid_ref(inl.ref), f"{b.id} 脚注引用未定义字段 {inl.ref}"

    # 章节标题（titleContent）的 ref 同样须解析（递归 Section 树新增）
    def walk(sections) -> None:
        for sec in sections:
            for inl in sec.titleContent or []:
                if inl.kind == "ref":
                    assert valid_ref(inl.ref), f"章节 {sec.key} 标题引用未定义字段 {inl.ref}"
            if sec.children:
                walk(sec.children)

    walk(report.sections)


def test_section_tree_heading_levels_valid():
    """加载即校验：章节树 headingLevel 顶层=1、逐层+1（loader 已校验，这里固化期望）。"""
    report = load_contract(CONTRACT)

    def walk(sections, parent_level) -> None:
        for sec in sections:
            assert sec.headingLevel == parent_level + 1, (
                f"章节 {sec.key} headingLevel={sec.headingLevel} 应为 {parent_level + 1}"
            )
            if sec.children:
                walk(sec.children, sec.headingLevel)

    walk(report.sections, 0)


# —— 子行展开（rowExpansion）加载期校验：非法声明必须 fail-loud，不留到运行时 ——


def _expansion_block(**expansion_kwargs):
    from sustainability_desk.contract.models import (
        Block,
        GenerationSpec,
        GenerationTask,
        GsColDef,
        GsTable,
        RowExpansion,
    )

    return Block(
        id="t.expand",
        type="table",
        blockType="constrained",
        source="ai",
        generation=GenerationSpec(
            task=GenerationTask(focus="f"),
            rowMode="expanded_rows",
            rowExpansion=RowExpansion(**expansion_kwargs),
        ),
        table=GsTable(
            colDefs=[
                GsColDef(key="topic", header="议题", cellType="text"),
                GsColDef(key="desc", header="描述", cellType="ai_text"),
                GsColDef(key="kind", header="分类", cellType="multi_select", options=["机遇", "风险"]),
            ]
        ),
    )


def _unit(key, label, column_keys, **kwargs):
    from sustainability_desk.contract.models import RowExpansionUnit

    return RowExpansionUnit(key=key, label=label, columnKeys=column_keys, **kwargs)


def test_row_expansion_accepts_well_formed_declaration():
    """共享列与子行列互斥、各子行列一致、并集覆盖全部列 → 通过。"""
    from sustainability_desk.contract.loader import validate_column_keys_in_blocks

    block = _expansion_block(
        sharedColumnKeys=["topic"],
        units=[
            _unit("impact", "影响描述", ["desc", "kind"], optionsNarrowing={"kind": ["风险"]}),
            _unit("risk_opportunity", "风险与机遇描述", ["desc", "kind"]),
        ],
    )
    validate_column_keys_in_blocks([block], where="测试")


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (
            {"sharedColumnKeys": ["topic", "desc"],
             "units": [_unit("a", "甲", ["desc", "kind"]), _unit("b", "乙", ["desc", "kind"])]},
            "既是共享列又归属子行",
        ),
        (
            {"sharedColumnKeys": ["topic"],
             "units": [_unit("a", "甲", ["desc", "kind"]), _unit("b", "乙", ["desc"])]},
            "各子行填写的列不一致",
        ),
        (
            {"sharedColumnKeys": [],
             "units": [_unit("a", "甲", ["desc", "kind"]), _unit("b", "乙", ["desc", "kind"])]},
            "未覆盖全部列",
        ),
        (
            {"sharedColumnKeys": ["topic"],
             "units": [
                 _unit("a", "甲", ["desc", "kind"], optionsNarrowing={"kind": ["不存在的候选"]}),
                 _unit("b", "乙", ["desc", "kind"]),
             ]},
            "不在列级 options 内",
        ),
        (
            {"sharedColumnKeys": ["topic"],
             "units": [_unit("a", "甲", ["desc", "kind"])]},
            "至少需两个子行",
        ),
    ],
)
def test_row_expansion_rejects_malformed_declarations(kwargs, expected):
    """归属重叠/子行列不一致/漏列/候选越界/子行不足，均在加载期拒绝。"""
    from sustainability_desk.contract.loader import validate_column_keys_in_blocks

    with pytest.raises(ValueError, match=expected):
        validate_column_keys_in_blocks([_expansion_block(**kwargs)], where="测试")


def test_row_expansion_and_row_mode_must_agree():
    """rowExpansion 与 rowMode=expanded_rows 必须同时出现，避免声明半生效。"""
    from sustainability_desk.contract.loader import validate_column_keys_in_blocks

    block = _expansion_block(
        sharedColumnKeys=["topic"],
        units=[_unit("a", "甲", ["desc", "kind"]), _unit("b", "乙", ["desc", "kind"])],
    )
    block.generation.rowMode = None
    with pytest.raises(ValueError, match="须同时出现"):
        validate_column_keys_in_blocks([block], where="测试")
