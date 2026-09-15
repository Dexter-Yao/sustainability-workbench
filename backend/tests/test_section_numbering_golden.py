# ABOUTME: 章节编号推导跨端 golden 一致性测试（后端侧）——读共享 fixture 跑 number_sections，断言 == expected。
# ABOUTME: 同一 fixture 前端 vitest 亦消费（section-number.test.ts），两端各自对 golden 成立即防编号双写漂移。
import json
from pathlib import Path

from sustainability_desk.contract.models import Report
from sustainability_desk.contract.section_number import number_sections
from sustainability_desk.contract.visibility import visible

FIXTURE = Path(__file__).parent / "fixtures" / "section_numbering_golden.json"


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_section_numbering_golden_backend():
    """每个 golden case：后端 number_sections 推导 == expected（与前端 vitest 同 fixture，防编号双写漂移）。"""
    failures = []
    for case in _cases():
        report = Report.model_validate(case["report"])
        got = number_sections(
            report.sections,
            lambda node: visible(node, report),
            scheme=case.get("scheme", "chapter_cn"),
        )
        if got != case["expected"]:
            failures.append(f"{case['name']}: got {got}, expected {case['expected']}")
    assert not failures, "后端章节编号与 golden 不符：\n" + "\n".join(failures)
