# ABOUTME: 双重重要性矩阵图渲染测试——产出有效 PNG、空议题报错、阈值缺失回退、导出内联嵌入。
# ABOUTME: 视图级分类过滤（交互预览）与过滤参数解析同在此锁定；导出不传参路径不受影响。

import pytest
from docx import Document

from sustainability_desk.contract.loader import load_contract
from sustainability_desk.contract.models import AssessmentResult, MaterialityThreshold, ScoredAssessmentResult
from sustainability_desk.export.docx_renderer import render_docx
from sustainability_desk.export.matrix_chart import parse_visible_materialities, render_materiality_matrix
from knowledge_package_fixtures import SSE_PACKAGE

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_CONTRACT = SSE_PACKAGE.report_contract_path


def _topic(tid: str, name: str, dim: str, mat: str, fin: float, imp: float) -> ScoredAssessmentResult:
    return ScoredAssessmentResult(determination="scored",
        assessmentTopicId=tid, materiality=mat,
        financialScore=fin, impactScore=imp,
    )


def _assessment(topics: list[ScoredAssessmentResult], threshold: MaterialityThreshold | None = None) -> AssessmentResult:
    return AssessmentResult(reportingYear=2025, topics=topics, threshold=threshold)


_SAMPLE_TOPICS = [
    _topic("climate_change", "应对气候变化", "环境", "dual", 4.5, 4.6),
    _topic("risk_management", "风险管理", "治理", "financial", 4.3, 3.1),
    _topic("occupational_health_safety", "职业健康与安全", "社会", "impact", 3.2, 4.4),
    _topic("technology_ethics", "科技伦理", "治理", "non", 2.0, 2.1),
]


def test_render_returns_valid_png():
    png = render_materiality_matrix(_assessment(_SAMPLE_TOPICS, MaterialityThreshold(financial=4.0, impact=4.0)), package=SSE_PACKAGE)
    assert png[:8] == _PNG_MAGIC
    assert len(png) > 2000


def test_empty_topics_raises():
    with pytest.raises(ValueError):
        render_materiality_matrix(_assessment([]), package=SSE_PACKAGE)


def test_threshold_defaults_when_missing():
    png = render_materiality_matrix(_assessment([_topic("climate_change", "应对气候变化", "环境", "dual", 4.5, 4.6)]), package=SSE_PACKAGE)
    assert png[:8] == _PNG_MAGIC


def test_visible_filter_renders_png():
    png = render_materiality_matrix(
        _assessment(_SAMPLE_TOPICS, MaterialityThreshold(financial=4.0, impact=4.0)),
        visible_materialities={"dual", "non"}, package=SSE_PACKAGE,
    )
    assert png[:8] == _PNG_MAGIC
    assert len(png) > 2000


def test_visible_filter_excluding_all_renders_empty_chart():
    png = render_materiality_matrix(_assessment(_SAMPLE_TOPICS), visible_materialities=set(), package=SSE_PACKAGE)
    assert png[:8] == _PNG_MAGIC


def test_parse_visible_materialities():
    assert parse_visible_materialities("dual, non") == {"dual", "non"}
    assert parse_visible_materialities("") == set()
    with pytest.raises(ValueError):
        parse_visible_materialities("dual,unknown")


def test_matrix_embedded_as_inline_image(base_template, out_dir):
    """有评估时矩阵图块作为内联图片嵌入，比无评估（占位文字）恰好多一张内联图。"""
    report = load_contract(_CONTRACT)

    report.assessment = None
    out0 = render_docx(report.model_copy(deep=True), base_template, out_dir / "matrix_none.docx")
    n0 = len(Document(str(out0)).inline_shapes)

    report.assessment = _assessment(_SAMPLE_TOPICS, MaterialityThreshold(financial=4.0, impact=4.0))
    out1 = render_docx(report.model_copy(deep=True), base_template, out_dir / "matrix_embedded.docx")
    n1 = len(Document(str(out1)).inline_shapes)

    assert n1 == n0 + 1, "矩阵图未作为内联图片嵌入导出"
