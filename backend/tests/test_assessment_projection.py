# ABOUTME: 评估→values 投影测试——assessment.topics→第四章派生表，计数留在 assessment ref，重要性范畴英→中映射。
# ABOUTME: 与前端 assessment-projection.test.ts 同 golden 防漂移；本文件覆盖纯函数行为与契约 options 对齐。
from sustainability_desk.contract.assessment_projection import project_assessment
from sustainability_desk.contract.loader import assessment_vocabulary
from sustainability_desk.contract.models import (
    AssessmentResult,
    IROItem,
    ScoredAssessmentResult,
)
from knowledge_package_fixtures import SSE_PACKAGE


def _topic(topic_id, materiality, fin=0.0, imp=0.0):
    return ScoredAssessmentResult(determination="scored",
        assessmentTopicId=topic_id,
        materiality=materiality,
        financialScore=fin,
        impactScore=imp,
    )


def test_projects_topics_to_topic_table_rows():
    """每个议题 → sm.topic_table 一行：维度/名称直传、重要性范畴英→中映射、顺序保持。"""
    assessment = AssessmentResult(
        reportingYear=2025,
        topics=[
            _topic("climate_change", "dual"),
            _topic("energy_management", "financial"),
        ],
    )
    rows = project_assessment(assessment, package=SSE_PACKAGE)["tables"]["sm.topic_table"]
    assert rows == [
        {"topic_dimension": "环境", "topic_name": "应对气候变化", "topic_materiality": "双重重要性"},
        {"topic_dimension": "环境", "topic_name": "能源管理", "topic_materiality": "财务重要性"},
    ]


def test_all_materiality_categories_map_to_chinese_full_names():
    """四类重要性范畴各自映射到对应中文全称。"""
    assessment = AssessmentResult(
        reportingYear=2025,
        topics=[
            _topic("anti_bribery_anti_corruption", "dual"),
            _topic("human_capital_development", "impact"),
            _topic("energy_management", "financial"),
            _topic("anti_unfair_competition", "non"),
        ],
    )
    cats = [r["topic_materiality"] for r in project_assessment(assessment, package=SSE_PACKAGE)["tables"]["sm.topic_table"]]
    assert cats == ["双重重要性", "影响重要性", "财务重要性", "非重要性"]


def test_counts_are_not_projected_to_fields():
    """assessment.counts 不再复制到 topics_* 字段；第四章计数通过 assessment.counts.* ref 读取。"""
    assessment = AssessmentResult(reportingYear=2025, topics=[])
    assert "fields" not in project_assessment(assessment, package=SSE_PACKAGE)


def test_projects_iro_rows_from_financial_and_dual_topics():
    """财务/双重重要性议题 → sm.iro_table 行；非重要性与影响重要性不进入 IRO 表。"""
    assessment = AssessmentResult(
        reportingYear=2025,
        topics=[
            _topic("anti_bribery_anti_corruption", "dual").model_copy(update={"iroItems": [
                IROItem(kind="impact", description="影响", classes=["潜在负面影响"], valueChain=["公司运营"], timeHorizon=["中期"]),
                IROItem(kind="opportunity", description="机遇", classes=["机遇"], valueChain=["下游价值链"], timeHorizon=["长期"]),
            ]}),
            _topic("human_capital_development", "impact"),
            _topic("energy_management", "financial").model_copy(update={"iroItems": [
                IROItem(kind="risk", description="风险", valueChain=["上游价值链"], timeHorizon=["短期"]),
            ]}),
        ],
    )
    rows = project_assessment(assessment, package=SSE_PACKAGE)["tables"]["sm.iro_table"]
    # 形态与契约 rowExpansion 一致：共享列在外层、每个披露子行一个嵌套对象。
    assert rows == [
        {
            "iro_topic": "反商业贿赂与反贪污",
            "iro_value_chain": ["公司运营"],
            "iro_time_horizon": ["中期"],
            "impact": {"iro_desc": "影响", "iro_class": ["潜在负面影响"]},
            "risk_opportunity": {"iro_desc": "机遇", "iro_class": ["机遇"]},
        },
        {
            "iro_topic": "能源管理",
            "iro_value_chain": ["上游价值链"],
            "iro_time_horizon": ["短期"],
            "impact": {"iro_desc": "", "iro_class": []},
            "risk_opportunity": {"iro_desc": "风险", "iro_class": ["风险"]},
        },
    ]


def test_empty_assessment_yields_empty_rows_and_zero_counts():
    """无议题、无计数 → 空议题表 + 计数全 0（不报错）。"""
    result = project_assessment(AssessmentResult(reportingYear=2025), package=SSE_PACKAGE)
    assert result["tables"]["sm.topic_table"] == []
    assert result["tables"]["sm.iro_table"] == []
    assert "fields" not in result


def test_materiality_labels_align_with_contract_options(full_contract_yaml):
    """重要性范畴中文映射值须与契约 sm.topic_table 的 topic_materiality 选项完全一致（防漂移）。"""
    from sustainability_desk.contract.loader import load_contract

    report = load_contract(full_contract_yaml)
    col = next(
        c
        for c in report.find_block("sm.topic_table").table.colDefs
        if c.key == "topic_materiality"
    )
    materiality_labels = assessment_vocabulary(SSE_PACKAGE).materiality.model_dump()
    assert set(materiality_labels.values()) == set(col.options)
