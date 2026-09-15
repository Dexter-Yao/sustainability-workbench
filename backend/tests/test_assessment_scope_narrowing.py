# ABOUTME: 议题适用范围收窄的写入边界与生成闸合同测试，覆盖「先评分、后改基本信息」顺序。
# ABOUTME: 守护：范围外评分不得静默落库、再到生成一步才抛裸 ValueError 成 500。
import pytest

from sustainability_desk.api.reports_router import _narrowed_to_applicable_assessment_scope
from sustainability_desk.contract.assessment_classify import (
    InapplicableScoredTopicsError,
    inapplicable_scored_topics,
)
from sustainability_desk.contract.models import (
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
)
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.topic_registry import (
    applicability_facts_from_values,
    applicable_scoring_topics,
)
from knowledge_package_fixtures import SSE_PACKAGE

TECHNOLOGY_ETHICS_FIELD = "has_technology_ethics_sensitive_activity"


def _facts(sensitive_activity: str):
    return applicability_facts_from_values(
        field_values={TECHNOLOGY_ETHICS_FIELD: sensitive_activity},
    )


def _fully_scored_state(sensitive_activity: str) -> StoredReportStateV4:
    """构造一份「在议题仍适用时完成全部评分」的报告状态。"""

    scored = applicable_scoring_topics(_facts("是"), package=SSE_PACKAGE)
    return StoredReportStateV4(
        version=4,
        fields={
            "company_registered_name": "测试公司",
            "industry_major_category": "制造业",
            "report_period_start": "2025-01-01",
            "report_period_end": "2025-12-31",
            TECHNOLOGY_ETHICS_FIELD: sensitive_activity,
        },
        assessmentInput=MaterialityAssessmentInput(
            reportingYear=2025,
            threshold=MaterialityThreshold(financial=4.0, impact=4.0),
            scores=[
                MaterialityScoreInput(
                    assessmentTopicId=topic.id,
                    financialScore=4.0,
                    impactScore=4.0,
                )
                for topic in scored
            ],
        ),
    )


def test_applicable_scope_narrows_when_technology_ethics_declared_inapplicable() -> None:
    """基本信息选「否」后，科技伦理退出评分范围；未作答时保持适用。"""

    assert any(topic.id == "technology_ethics" for topic in applicable_scoring_topics(_facts("是"), package=SSE_PACKAGE))
    assert all(
        topic.id != "technology_ethics" for topic in applicable_scoring_topics(_facts("否"), package=SSE_PACKAGE)
    )
    unanswered = applicability_facts_from_values(field_values={})
    assert any(topic.id == "technology_ethics" for topic in applicable_scoring_topics(unanswered, package=SSE_PACKAGE))


def test_put_state_narrows_scores_to_current_applicable_scope() -> None:
    """写入边界把已失效议题的评分剔除后落库，不打断用户编辑，也不留脏数据。"""

    state = _fully_scored_state("否")
    assert state.assessmentInput is not None
    assert any(
        score.assessmentTopicId == "technology_ethics"
        for score in state.assessmentInput.scores
    )

    narrowed = _narrowed_to_applicable_assessment_scope(state, package=SSE_PACKAGE)

    assert narrowed.assessmentInput is not None
    assert all(
        score.assessmentTopicId != "technology_ethics"
        for score in narrowed.assessmentInput.scores
    )
    expected_ids = {topic.id for topic in applicable_scoring_topics(_facts("否"), package=SSE_PACKAGE)}
    assert {
        score.assessmentTopicId for score in narrowed.assessmentInput.scores
    } == expected_ids
    # 收窄后正好构成完整覆盖，生成不再被范围问题阻断。
    assert not inapplicable_scored_topics(narrowed.assessmentInput, _facts("否"), package=SSE_PACKAGE)


def test_narrowing_applies_after_server_owned_merge_not_at_entry() -> None:
    """收窄必须作用于锁内权威覆盖之后的落库状态（403 死锁回归）。

    assessmentInput 是服务端拥有字段：请求体上的收窄会被 _preserve_server_owned
    用权威旧值覆盖丢弃；否则用户把科技伦理改为「否」的合法编辑会因权威旧评分
    含 technology_ethics 而被锁内范围校验拒绝，形成无法自救的 403。
    """
    from sustainability_desk.persistence.reports import _preserve_server_owned

    locked = _fully_scored_state("是")  # 权威旧状态：含 technology_ethics 评分
    requested = _fully_scored_state("否")  # 用户本次编辑：科技伦理改「否」
    requested = requested.model_copy(update={"assessmentInput": None})

    merged = _preserve_server_owned(requested, locked, writes=frozenset())
    assert merged.assessmentInput is not None
    assert any(
        score.assessmentTopicId == "technology_ethics"
        for score in merged.assessmentInput.scores
    ), "前提：权威旧评分在合并态中复活"

    narrowed = _narrowed_to_applicable_assessment_scope(merged, package=SSE_PACKAGE)
    assert narrowed.assessmentInput is not None
    assert all(
        score.assessmentTopicId != "technology_ethics"
        for score in narrowed.assessmentInput.scores
    )
    assert not inapplicable_scored_topics(narrowed.assessmentInput, _facts("否"), package=SSE_PACKAGE)


def test_put_state_leaves_applicable_scores_untouched() -> None:
    """议题仍适用时写入边界不得改动任何评分。"""

    state = _fully_scored_state("是")
    assert state.assessmentInput is not None

    narrowed = _narrowed_to_applicable_assessment_scope(state, package=SSE_PACKAGE)

    assert narrowed.assessmentInput is not None
    assert narrowed.assessmentInput.scores == state.assessmentInput.scores


def test_generation_path_fails_loud_on_inapplicable_scores() -> None:
    """范围外评分若绕过写入边界，生成路径必须以具名错误 fail-loud，不得穿透成 500。"""

    state = _fully_scored_state("否")

    with pytest.raises(InapplicableScoredTopicsError) as excinfo:
        build_report_revision(state, package=SSE_PACKAGE)

    assert "科技伦理" in excinfo.value.message
    # 面向用户的文案不得出现内部 id。
    assert "technology_ethics" not in excinfo.value.message


def test_narrowed_state_builds_report_without_error() -> None:
    """收窄后的状态可正常装配 Report——这是该故障场景修复后的期望终态。"""

    narrowed = _narrowed_to_applicable_assessment_scope(_fully_scored_state("否"), package=SSE_PACKAGE)

    report = build_report_revision(narrowed, package=SSE_PACKAGE)

    assert report.assessment is not None
    scored_ids = {
        topic.assessmentTopicId
        for topic in report.assessment.topics
        if getattr(topic, "financialScore", None) is not None
    }
    assert "technology_ethics" not in scored_ids
