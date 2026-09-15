# ABOUTME: 「本报告披露议题数量」跨端 golden 后端侧——与 frontend/lib/report-values.test.ts 消费同一 fixture。
# ABOUTME: 该数由 topic_registry 的议题清单与适用性规则现算；前端镜像结论，本文件防两端漂移。
import json
from pathlib import Path

from sustainability_desk.contract.models import Field, Report
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from knowledge_package_fixtures import SSE_PACKAGE

FIXTURE = Path(__file__).parent / "fixtures" / "applicable_scoring_topic_count_golden.json"


def _report(technology_ethics: str | None) -> Report:
    fields = {}
    if technology_ethics is not None:
        fields["has_technology_ethics_sensitive_activity"] = Field(
            key="has_technology_ethics_sensitive_activity",
            label="科技伦理敏感业务",
            type="string",
            source="user_input",
            value=technology_ethics,
        )
    return Report(knowledgePackageId=SSE_PACKAGE.id, title="t", fields=fields, sections=[])


def test_applicable_scoring_topic_count_matches_golden():
    cases = json.loads(FIXTURE.read_text())["cases"]
    for case in cases:
        report = _report(case["has_technology_ethics_sensitive_activity"])
        assert len(applicable_scoring_topics(report, package=SSE_PACKAGE)) == case["expected"], case["name"]


def test_topic_count_ref_resolves_to_the_same_number():
    """契约里的 {kind: ref} 与注册表现算必须同值——正文写出的就是这个数。"""

    cases = json.loads(FIXTURE.read_text())["cases"]
    for case in cases:
        report = _report(case["has_technology_ethics_sensitive_activity"])
        assert resolve_report_ref("assessment.applicableTopicCount", report) == case["expected"], case["name"]


def test_scoring_scope_excludes_fixed_materiality_topics():
    """取评分范围而非重要性范围：后者多含 stakeholder_communication（固定归类，不进议题章节）。"""

    from sustainability_desk.contract.topic_registry import applicable_materiality_topics

    report = _report("否")
    scoring = {topic.id for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)}
    materiality = {topic.id for topic in applicable_materiality_topics(report, package=SSE_PACKAGE)}
    assert materiality - scoring == {"stakeholder_communication"}
