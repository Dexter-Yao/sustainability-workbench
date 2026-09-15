# ABOUTME: 评估→values 投影 golden 回归测试——读 fixture 跑 project_assessment，断言 == expected。
# ABOUTME: 投影自 a8b1eebb 起收敛为后端独有（前端同名模块与其 vitest 已随之删除）；本 golden 锁投影的行数与键形态。
import json
from pathlib import Path

from sustainability_desk.contract.assessment_projection import project_assessment
from sustainability_desk.contract.models import AssessmentResult
from knowledge_package_fixtures import SSE_PACKAGE

FIXTURE = Path(__file__).parent / "fixtures" / "assessment_projection_golden.json"


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_assessment_projection_golden_backend():
    """每个 golden case：project_assessment 投影 == expected（锁定投影结果的行数与键形态）。"""
    failures = []
    for case in _cases():
        assessment = AssessmentResult.model_validate(case["assessment"])
        got = project_assessment(assessment, package=SSE_PACKAGE)
        if got != case["expected"]:
            failures.append(f"{case['name']}: got {got}, expected {case['expected']}")
    assert not failures, "后端评估投影与 golden 不符：\n" + "\n".join(failures)
