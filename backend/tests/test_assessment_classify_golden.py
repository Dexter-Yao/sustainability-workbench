# ABOUTME: 双重重要性分类跨端 golden 一致性测试（后端侧）——读共享 fixture 跑 classify_assessment，断言 materiality/counts == expected。
# ABOUTME: 同一 fixture 前端 vitest 亦消费（assessment-classify.test.ts），两端各自对 golden 成立即防分类双写漂移。
import json
from pathlib import Path

from sustainability_desk.contract.assessment_classify import assessment_counts, classify_materiality
from sustainability_desk.contract.models import AssessmentResult, MaterialityThreshold, ScoredAssessmentResult

FIXTURE = Path(__file__).parent / "fixtures" / "assessment_classify_golden.json"


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_assessment_classify_golden_backend():
    """分类与派生计数保持 golden；前端不再复制分类算法。"""
    failures = []
    for case in _cases():
        threshold = MaterialityThreshold(**case["threshold"])
        topics = [
            ScoredAssessmentResult(
                assessmentTopicId=item["id"],
                financialScore=item["financialScore"],
                impactScore=item["impactScore"],
                materiality=classify_materiality(
                    item["financialScore"], item["impactScore"], threshold
                ),
            )
            for item in case["scored"]
        ]
        result = AssessmentResult(
            reportingYear=case["reportingYear"], topics=topics, threshold=threshold
        )
        got = {
            "materiality": {t.assessmentTopicId: t.materiality for t in result.topics},
            "counts": assessment_counts(result).model_dump(),
        }
        if got != case["expected"]:
            failures.append(f"{case['name']}: got {got}, expected {case['expected']}")
    assert not failures, "后端 classify 与 golden 不符：\n" + "\n".join(failures)
