# ABOUTME: 交付级渲染引用回归——render_final_docx 前置扫描对无值且无回退的可见引用 fail-loud，
# ABOUTME: 决不交付静默空洞；_inline_text 保持宽渲染供局部文档复用且回退文案生效。
import pytest

from sustainability_desk.contract.models import Block, Field, Inline, Report, Section
from sustainability_desk.export.docx_renderer import (
    UnresolvedReportReferenceError,
    _assert_final_references_resolved,
    _inline_text,
)
from knowledge_package_fixtures import SSE_PACKAGE


def _report(value: str, *, fallback: str | None = None) -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "company_short_name": Field(
                key="company_short_name",
                label="公司简称",
                type="string",
                source="user_input",
                value=value,
            )
        },
        sections=[
            Section(
                key="s",
                title="S",
                headingLevel=1,
                blocks=[
                    Block(
                        id="b.ref",
                        type="paragraph",
                        blockType="fixed",
                        source="template",
                        content=[
                            Inline(kind="text", text="由"),
                            Inline(kind="ref", ref="company_short_name", fallback=fallback),
                            Inline(kind="text", text="编制"),
                        ],
                    )
                ],
            )
        ],
    )


def test_inline_text_resolves_value_and_fallback():
    content = _report("示例公司").sections[0].blocks[0].content
    assert _inline_text(content, _report("示例公司")) == "由示例公司编制"
    fallback_content = _report("", fallback="本公司").sections[0].blocks[0].content
    assert _inline_text(fallback_content, _report("", fallback="本公司")) == "由本公司编制"


def test_final_reference_scan_fails_loud_on_unresolved_ref_without_fallback():
    """两条出文档路径都有 diagnose 闸；漏检时交付级渲染终止而非静默留空。"""
    with pytest.raises(UnresolvedReportReferenceError) as exc:
        _assert_final_references_resolved(_report(""))
    assert exc.value.ref == "company_short_name"


def test_final_reference_scan_accepts_value_or_fallback():
    _assert_final_references_resolved(_report("示例公司"))
    _assert_final_references_resolved(_report("", fallback="本公司"))
