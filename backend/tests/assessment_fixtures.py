# ABOUTME: 测试专用的完整重要性结果构造器，避免单议题单测绕过 Planner 严格范围合同。
# ABOUTME: 它只从权威 Registry 构造结果；不在产品代码中恢复部分装配或兼容入口。
from sustainability_desk.contract.models import (
    AssessmentResult,
    FixedAssessmentResult,
    Report,
    ScoredAssessmentResult,
)
from sustainability_desk.contract.topic_registry import applicable_materiality_topics
from knowledge_package_fixtures import SSE_PACKAGE


def complete_assessment(
    report: Report,
    *,
    materialities: dict[str, str] | None = None,
) -> AssessmentResult:
    overrides = materialities or {}
    topics = []
    for topic in applicable_materiality_topics(report, package=SSE_PACKAGE):
        determination = topic.materialityDetermination
        materiality = overrides.get(topic.id, determination.materiality or "dual")
        if determination.kind == "fixed":
            topics.append(FixedAssessmentResult(
                assessmentTopicId=topic.id,
                determination="fixed",
                materiality=materiality,
            ))
        else:
            topics.append(ScoredAssessmentResult(
                assessmentTopicId=topic.id,
                determination="scored",
                materiality=materiality,
                financialScore=4.5,
                impactScore=4.5,
            ))
    return AssessmentResult(reportingYear=2025, topics=topics)
