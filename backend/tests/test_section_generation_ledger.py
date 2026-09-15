# ABOUTME: 整节生成账本纯函数测试——完整页面补丁、缺块失败和非目标页面保持不变。
# ABOUTME: 数据库竞态与租约由本地 Supabase 集成测试覆盖；本文件不触发真实模型调用。
from __future__ import annotations

import pytest

from sustainability_desk.persistence.section_generations import apply_generation_results
from knowledge_package_fixtures import SSE_PACKAGE


def _state() -> dict:
    return {
        "version": 4,
        "fields": {"company_name": "测试企业"},
        "intakeItems": {},
        "generatedBlocks": {
            "other.paragraph": {
                "content": [{"kind": "text", "text": "其他页面正文"}],
                "state": "ready",
            }
        },
        "tableBlocks": {},
    }


def test_apply_generation_results_only_patches_expected_blocks():
    result = apply_generation_results(
        _state(),
        ("climate.paragraph", "climate.table"),
        [
            {
                "blockId": "climate.paragraph",
                "kind": "paragraph",
                "status": "ready",
                "variants": [{"displayTitle": None, "content": "新正文"}],
            },
            {
                "blockId": "climate.table",
                "kind": "table",
                "status": "ready",
                "rows": [{"children": []}],
            },
        ],
        company_business_summary="主营业务摘要", package=SSE_PACKAGE,
    )
    assert result["generatedBlocks"]["other.paragraph"]["state"] == "ready"
    assert result["generatedBlocks"]["climate.paragraph"] == {
        "content": [{"kind": "text", "text": "新正文"}],
        "state": "ready",
    }
    assert result["tableBlocks"]["climate.table"]["children"] == [
        {"type": "tr", "headerRow": False, "state": None, "origin": None, "children": []}
    ]
    assert result["tableBlocks"]["climate.table"]["state"] == "ready"
    assert result["fields"]["company_business_summary"] == "主营业务摘要"


def test_apply_generation_results_projects_runtime_table_rows_to_stored_state():
    """运行时 Plate 骨架和行级模板规则不得进入 V4，但企业值与来源必须保留。"""
    result = apply_generation_results(
        _state(),
        ("climate.table",),
        [
            {
                "blockId": "climate.table",
                "kind": "table",
                "status": "ready",
                "rows": [
                    {
                        "type": "tr",
                        "state": "ready",
                        "origin": {"from": "ai", "theme": "气候风险"},
                        "generation": None,
                        "appears_when": None,
                        "children": [
                            {
                                "type": "td",
                                "colKey": "risk",
                                "value": "气候风险",
                                "children": [{"type": "p", "children": [{"text": ""}]}],
                            }
                        ],
                    }
                ],
            }
        ], package=SSE_PACKAGE,
    )

    row = result["tableBlocks"]["climate.table"]["children"][0]
    assert row == {
        "type": "tr",
        "headerRow": False,
        "state": "ready",
        "origin": {"from": "ai", "theme": "气候风险", "category": None, "driver_hint": None},
        "children": [
            {
                "type": "td",
                "colKey": "risk",
                "value": "气候风险",
                "options": None,
                "colSpan": 1,
                "rowSpan": 1,
                "cellState": None,
            }
        ],
    }


def test_apply_generation_results_persists_automatic_empty_table_as_omitted():
    """空表格不是 ready 空壳；仅自动建报明确允许的省略分支可以写入该终态。"""

    result = apply_generation_results(
        _state(),
        ("climate.table",),
        [{
            "blockId": "climate.table",
            "kind": "table",
            "status": "omitted",
            "reason": "当前表格缺少可披露的用户资料，已按报告合同省略。",
            "rows": [],
        }],
        allow_contract_omissions=True, package=SSE_PACKAGE,
    )

    assert result["tableBlocks"]["climate.table"] == {
        "children": [],
        "state": "omitted",
    }

    with pytest.raises(ValueError, match="未成功生成"):
        apply_generation_results(
            _state(),
            ("climate.table",),
            [{
                "blockId": "climate.table",
                "kind": "table",
                "status": "omitted",
                "reason": "当前表格缺少可披露的用户资料，已按报告合同省略。",
                "rows": [],
            }], package=SSE_PACKAGE,
        )


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"blockId": "climate.paragraph", "kind": "paragraph", "status": "failed"}],
        [
            {
                "blockId": "forged.block",
                "kind": "paragraph",
                "status": "ready",
                "variants": [{"displayTitle": None, "content": "伪造"}],
            }
        ],
    ],
)
def test_apply_generation_results_fails_closed(results):
    with pytest.raises(ValueError):
        apply_generation_results(_state(), ("climate.paragraph",), results, package=SSE_PACKAGE)


def test_apply_generation_results_writes_paired_h4_title_and_body_atomically():
    result = apply_generation_results(
        _state(),
        ("climate.paragraph",),
        [{
            "blockId": "climate.paragraph",
            "kind": "paragraph",
            "status": "ready",
            "titleSectionKey": "climate.gov.practice",
            "variants": [{
                "displayTitle": "治理协同与实践",
                "content": "与标题同步生成的正文。",
            }],
        }], package=SSE_PACKAGE,
    )

    assert result["generatedBlocks"]["climate.paragraph"]["content"][0]["text"] == "与标题同步生成的正文。"
    assert result["sectionTitles"]["climate.gov.practice"]["text"] == "治理协同与实践"


def test_apply_generation_results_rejects_title_task_without_paired_title():
    original = _state()
    with pytest.raises(ValueError, match="缺少配对标题"):
        apply_generation_results(
            original,
            ("climate.paragraph",),
            [{
                "blockId": "climate.paragraph",
                "kind": "paragraph",
                "status": "ready",
                "titleSectionKey": "climate.gov.practice",
                "variants": [{"displayTitle": None, "content": "正文"}],
            }], package=SSE_PACKAGE,
        )
    assert "climate.paragraph" not in original["generatedBlocks"]


def test_unsuccessful_generation_results_shares_success_semantics_with_apply():
    from sustainability_desk.persistence.section_generations import (
        unsuccessful_generation_results,
    )

    results = [
        {"blockId": "a", "status": "ready", "kind": "paragraph"},
        {"blockId": "b", "status": "blocked", "kind": "paragraph",
         "reason": "生成结果未通过确定性检查",
         "guardrailIssueKeys": ["missing_or_negative_statement"]},
        {"blockId": "c", "status": "omitted", "kind": "table", "reason": "无数据行"},
    ]
    # 不允许合同省略：blocked 与 omitted 都算未成功。
    failed = unsuccessful_generation_results(results, allow_contract_omissions=False, package=SSE_PACKAGE)
    assert [item["blockId"] for item in failed] == ["b", "c"]
    # 允许合同省略：带理由的表格省略是成功语义，blocked 仍是失败。
    failed = unsuccessful_generation_results(results, allow_contract_omissions=True, package=SSE_PACKAGE)
    assert [item["blockId"] for item in failed] == ["b"]


def test_incomplete_generation_user_message_is_actionable_without_internal_mechanics():
    from sustainability_desk.contract.fill import fill_report
    from sustainability_desk.contract.loader import load_contract
    from sustainability_desk.lightweight_report_generation import (
        _incomplete_generation_user_message,
    )

    contract = SSE_PACKAGE.report_contract_path
    report = fill_report(load_contract(contract), {"fields": {}, "intake": {}})
    block_id = next(
        block.id for section in report.sections for block in (section.blocks or [])
    )
    failed = [{
        "blockId": block_id,
        "status": "blocked",
        "reason": "生成结果未通过确定性检查：输出包含缺失、未做或未披露类负面表述。",
        "guardrailIssueKeys": ["missing_or_negative_statement"],
    }]
    message = _incomplete_generation_user_message(report, failed)
    # 指出未完成的内容与可行动建议。
    assert "未能完整生成" in message and "「" in message
    assert "暂未建立相关制度" in message and "重新生成" in message
    assert "既有报告和交付物未被覆盖" in message
    # 不泄露内部机制：守卫、断言、重试次数、块 id 都不出现。
    for leaked in ("L1", "守卫", "断言", "Guardrail", block_id, "重试"):
        assert leaked not in message

    # 非负面表述类失败给通用建议，不误导用户改填写。
    generic = _incomplete_generation_user_message(
        report,
        [{"blockId": block_id, "status": "failed", "reason": "生成失败：TimeoutError"}],
    )
    assert "填写" not in generic and "重新生成" in generic
