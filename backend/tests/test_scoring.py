# ABOUTME: 评分表解析测试，锁定官方议题名称、完整适用清单和条件排除校验。
from io import BytesIO
from uuid import UUID

import openpyxl
import pytest

from sustainability_desk.assets.scoring import parse_scoring
from sustainability_desk.assets.scoring_template import create_scoring_template
from sustainability_desk.contract.models import DisclosureProfile, Field, Report
from sustainability_desk.contract.structured_inputs import StructuredInputContext
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from knowledge_package_fixtures import SSE_PACKAGE

CONTEXT = StructuredInputContext(
    reportId=UUID("00000000-0000-0000-0000-000000000001"),
    contractVersion="cv-test",
    compiledSemanticsVersion="semantics-test",
)


def _report(*, technology_ethics: str = "否") -> Report:
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        fields={
            "has_technology_ethics_sensitive_activity": Field(
                key="has_technology_ethics_sensitive_activity",
                label="科技伦理适用性",
                type="enum",
                source="user_input",
                value=technology_ethics,
                options=["是", "否"],
            )
        },
        disclosureProfile=DisclosureProfile(),
    )


def _xlsx(report: Report, rows: list[tuple[str, float, float]]) -> bytes:
    wb = openpyxl.load_workbook(
        BytesIO(create_scoring_template(report, context=CONTEXT))
    )
    ws = wb["重要性评分表"]
    ws.delete_rows(9, ws.max_row - 8)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _complete_rows(report: Report) -> list[tuple[str, float, float]]:
    return [(topic.name, 4.0, 4.0) for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)]


def test_parse_scoring_requires_complete_applicable_official_topics():
    report = _report(technology_ethics="否")
    result = parse_scoring(
        _xlsx(report, _complete_rows(report)),
        report=report,
        context=CONTEXT,
    )
    ids = [topic.assessmentTopicId for topic in result.scored]
    assert len(ids) == 22
    assert "technology_ethics" not in ids
    assert "risk_management" in ids
    assert "rural_revitalization" in ids
    assert "social_contribution" in ids
    assert "stakeholder_communication" not in ids


def test_parse_scoring_rejects_fixed_stakeholder_communication_topic():
    report = _report()
    rows = [*_complete_rows(report), ("利益相关方沟通", 4.0, 4.0)]
    with pytest.raises(ValueError, match="固定分类，无需评分"):
        parse_scoring(_xlsx(report, rows), report=report, context=CONTEXT)


def test_parse_scoring_rejects_old_topic_names():
    report = _report()
    rows = _complete_rows(report)
    rows[0] = ("产品安全与质量", 4.0, 4.0)
    with pytest.raises(ValueError, match="非官方议题名称"):
        parse_scoring(_xlsx(report, rows), report=report, context=CONTEXT)


def test_parse_scoring_rejects_missing_applicable_topic():
    report = _report()
    rows = [row for row in _complete_rows(report) if row[0] != "社会贡献"]
    with pytest.raises(ValueError, match="评分表缺少适用议题：社会贡献"):
        parse_scoring(_xlsx(report, rows), report=report, context=CONTEXT)


def test_parse_scoring_rejects_excluded_topic():
    report = _report(technology_ethics="否")
    rows = [*_complete_rows(report), ("科技伦理", 4.0, 4.0)]
    with pytest.raises(ValueError, match="当前报告配置不适用"):
        parse_scoring(_xlsx(report, rows), report=report, context=CONTEXT)


@pytest.mark.parametrize("financial, impact", [(0, 4.0), (-0.5, 4.0), (5.1, 4.0), (3.55, 4.0), (3.50001, 4.0)])
def test_parse_scoring_rejects_values_outside_template_score_scale(financial: float, impact: float):
    report = _report()
    rows = _complete_rows(report)
    name, _, _ = rows[0]
    rows[0] = (name, financial, impact)

    with pytest.raises(ValueError, match="不符合评分尺度"):
        parse_scoring(_xlsx(report, rows), report=report, context=CONTEXT)
