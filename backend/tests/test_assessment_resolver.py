# ABOUTME: 验证用户评分输入与固定重要性策略在单一后端 resolver 中合成。
# ABOUTME: 固定议题没有伪造分数，计数包含固定结果而矩阵可识别 scored 子集。
from sustainability_desk.contract.assessment_classify import assessment_counts, resolve_materiality_assessment
from sustainability_desk.contract.models import Field, MaterialityAssessmentInput, MaterialityScoreInput, Report
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from knowledge_package_fixtures import SSE_PACKAGE


def _report():
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        fields={
            "has_technology_ethics_sensitive_activity": Field(
                key="has_technology_ethics_sensitive_activity",
                label="科技伦理适用性",
                type="enum",
                source="user_input",
                value="否",
                options=["是", "否"],
            )
        },
    )


def _input(report):
    return MaterialityAssessmentInput(
        reportingYear=2025,
        threshold={"financial": 4.0, "impact": 4.0},
        scores=[
            MaterialityScoreInput(
                assessmentTopicId=topic.id,
                financialScore=3.0,
                impactScore=5.0,
            )
            for topic in applicable_scoring_topics(report, package=SSE_PACKAGE)
        ],
    )


def test_resolver_injects_fixed_stakeholder_without_scores():
    report = _report()
    resolved = resolve_materiality_assessment(_input(report), report)
    stakeholder = next(
        topic
        for topic in resolved.topics
        if topic.assessmentTopicId == "stakeholder_communication"
    )
    assert stakeholder.determination == "fixed"
    assert stakeholder.materiality == "impact"
    assert not hasattr(stakeholder, "financialScore")
    counts = assessment_counts(resolved)
    assert counts.total == 23
    assert counts.impact_only == 23


def test_resolver_rejects_fixed_topic_score():
    report = _report()
    assessment_input = _input(report)
    assessment_input.scores.append(
        MaterialityScoreInput(
            assessmentTopicId="stakeholder_communication",
            financialScore=4.0,
            impactScore=4.0,
        )
    )
    try:
        resolve_materiality_assessment(assessment_input, report)
    except ValueError as error:
        assert "无需评分" in str(error)
    else:
        raise AssertionError("固定议题评分必须被拒绝")
