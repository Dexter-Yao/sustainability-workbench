# ABOUTME: 重要性评估解析器，将用户评分输入与 Registry 固定分类合成为唯一运行时结果。
# ABOUTME: 固定议题没有伪造分数；名称、维度、章节映射与计数均由权威合同即时投影。
# ABOUTME(en): Materiality resolver: merges user scores with the Registry's fixed determinations into one result.
# ABOUTME(en): Fixed topics get no fake scores; names, dimensions, section mapping and counts come from the contract.
from __future__ import annotations

from sustainability_desk.contract.models import (
    AssessmentCounts,
    AssessmentResult,
    FixedAssessmentResult,
    Materiality,
    MaterialityAssessmentInput,
    MaterialityThreshold,
    Report,
    ScoredAssessmentResult,
)
from sustainability_desk.contract.knowledge_packages import KnowledgePackage, knowledge_package_of
from sustainability_desk.contract.topic_registry import (
    _package_for,
    AssessmentTopicRef,
    TopicScopeBasis,
    all_assessment_topics,
    applicable_materiality_topics,
    applicable_scoring_topics,
)

DEFAULT_THRESHOLD = MaterialityThreshold(financial=4.0, impact=4.0)


class InapplicableScoredTopicsError(ValueError):
    """评分包含当前不适用议题——数据与适用范围不一致，需用户重新提交评分。

    与「填不全」不同，这不是编辑期草稿而是脏数据，任何路径都 fail-loud。
    带类型是为了让 HTTP 边界统一投影为可读 422，而不是各自 except ValueError
    或任其穿透成无信息 500。
    """

    def __init__(self, topics: tuple[AssessmentTopicRef, ...]) -> None:
        self.topics = topics
        self.topic_names = tuple(topic.name for topic in topics)
        listed = "、".join(self.topic_names)
        self.message = (
            f"{listed} 已不在本报告的适用议题范围内，其评分无法使用。"
            "请重新打开重要性评分页提交一次评分，"
            "或在基本信息中将该议题改回适用。"
        )
        super().__init__(self.message)


def classify_materiality(
    financial: float, impact: float, threshold: MaterialityThreshold
) -> Materiality:
    financial_material = financial >= threshold.financial
    impact_material = impact >= threshold.impact
    if financial_material and impact_material:
        return "dual"
    if financial_material:
        return "financial"
    if impact_material:
        return "impact"
    return "non"


def inapplicable_scored_topics(
    assessment_input: MaterialityAssessmentInput | None,
    basis: TopicScopeBasis,
    *,
    package: KnowledgePackage | None = None,
) -> tuple[AssessmentTopicRef, ...]:
    """评分输入中已不属于当前适用范围的议题，按 Registry 顺序返回。

    唯一的「范围外评分」判据：适用性由基本信息决定，评分只能是其子集。
    写入边界据此拒绝脏数据，投影据此收窄，二者不各自判断。
    未在 Registry 中登记的 id 不由本函数裁决——那是合同违例，由 resolver fail-loud。
    """
    if assessment_input is None:
        return ()
    resolved = _package_for(basis, package)
    expected_ids = {topic.id for topic in applicable_scoring_topics(basis, package=resolved)}
    scored_ids = {score.assessmentTopicId for score in assessment_input.scores}
    extra_ids = scored_ids - expected_ids
    if not extra_ids:
        return ()
    return tuple(
        topic for topic in all_assessment_topics(resolved) if topic.id in extra_ids
    )


def resolve_materiality_assessment(
    assessment_input: MaterialityAssessmentInput,
    report: Report | None,
) -> AssessmentResult:
    """校验完整评分范围并按 Registry 顺序合成 scored/fixed 结果。"""
    package = knowledge_package_of(report)
    scoring_scope = applicable_scoring_topics(report, package=package)
    full_scope = applicable_materiality_topics(report, package=package)
    expected_ids = {topic.id for topic in scoring_scope}
    by_id = {score.assessmentTopicId: score for score in assessment_input.scores}
    if len(by_id) != len(assessment_input.scores):
        raise ValueError("重要性评分输入包含重复 assessmentTopicId")
    missing = [topic.name for topic in scoring_scope if topic.id not in by_id]
    # 面向用户的文案只出现官方议题名称；无法解析的 id 保留原值以便定位合同违例。
    known_names = {topic.id: topic.name for topic in all_assessment_topics(package)}
    extra = [
        known_names.get(topic_id, topic_id)
        for topic_id in sorted(set(by_id) - expected_ids)
    ]
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"缺少适用评分议题：{'、'.join(missing)}")
        if extra:
            parts.append(f"包含无需评分或不适用议题：{'、'.join(extra)}")
        raise ValueError("；".join(parts))

    results = []
    for topic in full_scope:
        determination = topic.materialityDetermination
        if determination.kind == "fixed":
            results.append(
                FixedAssessmentResult(
                    assessmentTopicId=topic.id,
                    materiality=determination.materiality,
                )
            )
            continue
        score = by_id[topic.id]
        results.append(
            ScoredAssessmentResult(
                assessmentTopicId=topic.id,
                financialScore=score.financialScore,
                impactScore=score.impactScore,
                materiality=classify_materiality(
                    score.financialScore,
                    score.impactScore,
                    assessment_input.threshold,
                ),
                iroItems=score.iroItems,
            )
        )
    return AssessmentResult(
        reportingYear=assessment_input.reportingYear,
        topics=results,
        threshold=assessment_input.threshold,
    )


def assessment_counts(assessment: AssessmentResult) -> AssessmentCounts:
    """从唯一结果现算分类数量。"""
    return AssessmentCounts(
        dual=sum(topic.materiality == "dual" for topic in assessment.topics),
        impact_only=sum(topic.materiality == "impact" for topic in assessment.topics),
        financial_only=sum(topic.materiality == "financial" for topic in assessment.topics),
        non_material=sum(topic.materiality == "non" for topic in assessment.topics),
        total=len(assessment.topics),
    )


def industry_display(major: str, division: str) -> str:
    return " / ".join(part.strip() for part in (major, division) if part and part.strip())
