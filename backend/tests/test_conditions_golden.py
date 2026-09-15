# ABOUTME: 条件求值跨端 golden 一致性测试（后端侧）——读共享 fixture 跑 visible，断言 == expected。
# ABOUTME: 同一 fixture 前端 vitest 亦消费（conditions.test.ts），两端各自对 golden 成立即防 conditions 双写漂移（H2）。
import json
from pathlib import Path

from sustainability_desk.contract.models import Block, Condition, IntakeItem, Report
from sustainability_desk.contract.visibility import visible
from knowledge_package_fixtures import SSE_PACKAGE

FIXTURE = Path(__file__).parent / "fixtures" / "conditions_golden.json"


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_conditions_golden_backend():
    """每个 golden case：后端 visible 求值 == expected（与前端 vitest 同 fixture，防 conditions 双写漂移）。"""
    failures = []
    for case in _cases():
        report = Report.model_validate(case["report"])
        aw = case["appears_when"]
        node = Block(
            id="__node__", type="paragraph", blockType="fixed", source="template",
            appears_when=Condition.model_validate(aw) if aw else None,
        )
        got = visible(node, report)
        if got != case["expected"]:
            failures.append(f"{case['name']}: got {got}, expected {case['expected']}")
    assert not failures, "后端条件求值与 golden 不符：\n" + "\n".join(failures)


def test_quantitative_metric_condition_paths_are_value_based():
    report = Report.model_validate(
        {
            "title": "t",
            "sections": [],
            "meta": {"quantitativeMetrics": {"metrics": {"economic_environment_r11": {"value": "123"}}}},
        }
    )
    node = Block(
        id="__node__",
        type="paragraph",
        blockType="fixed",
        source="template",
        appears_when=Condition.model_validate(
            {"all": [{"path": "quantitativeMetrics.economic_environment_r11", "op": "exists"}]}
        ),
    )
    missing_node = node.model_copy(
        update={
            "appears_when": Condition.model_validate(
                {"all": [{"path": "quantitativeMetrics.economic_environment_r12", "op": "exists"}]}
            )
        }
    )

    assert visible(node, report)
    assert not visible(missing_node, report)


def test_in_condition_matches_multi_select_answers():
    """multi_select 答案为数组时，in 条件按选项交集求值。"""
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        sections=[],
        intakeItems=[
            IntakeItem(key="k1", contentScopeId="t", prompt="p", kind="multi_select", answer=["A", "C"])
        ],
    )
    node = Block(
        id="__node__",
        type="paragraph",
        blockType="fixed",
        source="template",
        appears_when=Condition.model_validate(
            {"all": [{"path": "intakeItems.k1", "op": "in", "value": ["B", "C"]}]}
        ),
    )

    assert visible(node, report)
