# ABOUTME: 报告级引用解析的空值边界测试。
# ABOUTME: 受限章节投影可移除附录状态，引用解析必须返回空值而非抛出运行时异常。
from __future__ import annotations

from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.contract.stored_report_state import empty_stored_report_state
from knowledge_package_fixtures import SSE_PACKAGE


def test_missing_appendix_reference_resolves_to_none() -> None:
    report = build_report_revision(empty_stored_report_state(), package=SSE_PACKAGE).model_copy(
        update={"appendixPackage": None}
    )

    assert (
        resolve_report_ref(
            "appendixPackage.externalAssuranceReport.isIncluded", report
        )
        is None
    )
