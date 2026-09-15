# ABOUTME: 报告级生成提交校验的成功语义：ready 与带理由的受控表格省略可提交，段落省略与无理由省略不可。
# ABOUTME: 受控省略的判定口径由本用例锁定，避免整节成功的报告因单块省略被整体判为提交失败。
from __future__ import annotations

import pytest

from sustainability_desk.persistence.lightweight_report_generations import _validate_completion
from knowledge_package_fixtures import SSE_PACKAGE

_FINGERPRINT = "a" * 64


def _validate(*block_results: dict) -> None:
    _validate_completion(
        expected_block_ids=tuple(item["blockId"] for item in block_results),
        content_fingerprint=_FINGERPRINT,
        block_results=tuple(block_results),
        artifacts=(),
        export_blocked=True, package=SSE_PACKAGE,
    )


def test_controlled_table_omission_is_a_committable_result() -> None:
    _validate(
        {"blockId": "sm.gov_arch_overview", "kind": "paragraph", "status": "ready"},
        {"blockId": "x.table", "kind": "table", "status": "omitted", "reason": "无可披露资料"},
    )


def test_paragraph_omission_and_reasonless_omission_are_rejected() -> None:
    with pytest.raises(ValueError, match="受控表格省略"):
        _validate({"blockId": "p", "kind": "paragraph", "status": "omitted", "reason": "x"})
    with pytest.raises(ValueError, match="受控表格省略"):
        _validate({"blockId": "t", "kind": "table", "status": "omitted", "reason": "  "})
