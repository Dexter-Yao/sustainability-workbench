# ABOUTME: 利益相关方沟通确定性合同测试，覆盖目录、默认多对多、范围协调、投影与完整性诊断。
# ABOUTME: 所有测试使用本地 typed 数据，不调用模型或恢复旧静态单元格。
from pathlib import Path

import pytest

from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.knowledge_packages import bind_knowledge_package
from sustainability_desk.contract.models import CustomEngagementMethod, Report
from sustainability_desk.contract.stakeholder_engagement import (
    apply_stakeholder_engagement_projection,
    load_stakeholder_engagement_catalog,
    missing_stakeholder_topic_ids,
    public_stakeholder_engagement_catalog,
    reconcile_stakeholder_engagement_profile,
)
from sustainability_desk.diagnostics import diagnose
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract

BACKEND = Path(__file__).resolve().parents[1]


def _report(*, technology_ethics: bool):
    report = load_package_contract(SSE_PACKAGE)
    report.fields["has_technology_ethics_sensitive_activity"].value = (
        "是" if technology_ethics else "否"
    )
    # 目录默认值只可作为显式编辑起点；正式投影不再在缺少企业 Profile 时
    # 自行制造“已沟通”的企业事实。
    return apply_stakeholder_engagement_projection(
        report.model_copy(
            update={
                "stakeholderEngagement": reconcile_stakeholder_engagement_profile(
                    report
                )
            }
        )
    )


def test_catalog_has_stable_eight_stakeholders_and_partner_candidates() -> None:
    catalog = load_stakeholder_engagement_catalog(SSE_PACKAGE)

    assert [item.label for item in catalog.stakeholders] == [
        "政府及监管机构",
        "股东及投资者",
        "客户",
        "管理层",
        "员工",
        "供应商",
        "合作伙伴",
        "社区与公众",
    ]
    partner_labels = {
        method.label
        for method in catalog.methods
        if "partners" in method.allowedStakeholderTypes
    }
    assert {"行业交流", "产学研交流与合作", "联合研发", "项目合作"} <= partner_labels
    partner_defaults = next(
        item.defaultMethodIds for item in catalog.stakeholders if item.id == "partners"
    )
    assert "industry_academia_research_cooperation" not in partner_defaults
    assert "joint_research_development" not in partner_defaults


def test_fixed_intro_speaks_to_report_readers_only() -> None:
    """引言只对报告读者说话，不得混入面向编制者或模型的操作指引。

    原文案含「如已有企业实际沟通资料，应以相应事实为准」——那是内部作业提示，
    出现在对外披露正文里既错位又自曝内容不实。
    """
    report = load_package_contract(SSE_PACKAGE)
    intro = report.find_block("sm.stakeholder_intro")
    text = "".join(item.text or "" for item in intro.content)
    assert text == "利益相关方沟通有助于识别可持续发展议题的关注重点，并为持续完善相关管理提供参考。"
    for leaked in ("应以相应事实为准", "如已有", "可采用方式"):
        assert leaked not in text
    table = report.find_block("sm.stakeholder_table").table
    assert table is not None
    assert table.caption == "利益相关方沟通与参与情况"
    assert table.disclaimer is None
    assert table.rowSource == "stakeholder_engagement"
    assert len(table.children) == 1 and table.children[0].headerRow


def test_missing_profile_projects_default_communication_framework() -> None:
    """用户未确认时按目录默认映射成表，而不是留一张空表。

    目录只承载股东会、信息披露、客服热线、员工代表沟通这类任何在营企业都必然具备的
    通用渠道，不含事件、金额、时间、项目名或成效，因此默认成表不构成编造企业事实。
    留空表反而既不满足准则披露，又会被导出闸以「议题未分配沟通对象」阻断交付。
    """
    report = load_package_contract(SSE_PACKAGE)
    assert report.stakeholderEngagement is None

    projected = apply_stakeholder_engagement_projection(report)
    table = projected.find_block("sm.stakeholder_table").table

    assert projected.stakeholderEngagement is not None
    assert table is not None
    rows = [row for row in table.children if not row.headerRow]
    assert len(rows) == 8
    assert missing_stakeholder_topic_ids(projected) == []
    methods = " ".join(row.children[2].value or "" for row in rows)
    assert "股东会" in methods and "信息披露" in methods


@pytest.mark.parametrize(
    ("technology_ethics", "expected_count"),
    [(False, 20), (True, 21)],
)
def test_default_profile_covers_all_applicable_topics(
    technology_ethics: bool, expected_count: int
) -> None:
    report = _report(technology_ethics=technology_ethics)
    profile = report.stakeholderEngagement

    assert profile is not None
    assert len(profile.entries) == 8
    assert len(profile.scopeAssessmentTopicIds) == expected_count
    assert missing_stakeholder_topic_ids(report) == []
    assert "due_diligence" not in profile.scopeAssessmentTopicIds
    assert "stakeholder_communication" not in profile.scopeAssessmentTopicIds
    assert "risk_management" not in profile.scopeAssessmentTopicIds
    assert ("technology_ethics" in profile.scopeAssessmentTopicIds) is technology_ethics


def test_same_topic_can_map_to_multiple_stakeholders() -> None:
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None
    owners = [
        entry.stakeholderType
        for entry in report.stakeholderEngagement.entries
        if "climate_change" in entry.assessmentTopicIds
    ]
    assert owners == [
        "government_regulators",
        "shareholders_investors",
        "management",
        "community_public",
    ]


def test_reconcile_adds_and_removes_conditional_topic_without_restoring_user_removal() -> None:
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None
    management = next(
        entry
        for entry in report.stakeholderEngagement.entries
        if entry.stakeholderType == "management"
    )
    management.assessmentTopicIds.remove("climate_change")
    management.customMethods.append(
        CustomEngagementMethod(kind="collaboration_activity", label="年度共创工作坊")
    )

    unchanged = apply_stakeholder_engagement_projection(report)
    unchanged_management = next(
        entry
        for entry in unchanged.stakeholderEngagement.entries
        if entry.stakeholderType == "management"
    )
    assert "climate_change" not in unchanged_management.assessmentTopicIds
    assert unchanged_management.customMethods[0].label == "年度共创工作坊"

    unchanged.fields["has_technology_ethics_sensitive_activity"].value = "是"
    added = apply_stakeholder_engagement_projection(unchanged)
    assert "technology_ethics" in added.stakeholderEngagement.scopeAssessmentTopicIds
    assert any(
        "technology_ethics" in entry.assessmentTopicIds
        for entry in added.stakeholderEngagement.entries
    )

    added.fields["has_technology_ethics_sensitive_activity"].value = "否"
    removed = apply_stakeholder_engagement_projection(added)
    assert "technology_ethics" not in removed.stakeholderEngagement.scopeAssessmentTopicIds
    assert all(
        "technology_ethics" not in entry.assessmentTopicIds
        for entry in removed.stakeholderEngagement.entries
    )


def test_projection_uses_registry_labels_and_combines_custom_methods() -> None:
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None
    partner = next(
        entry
        for entry in report.stakeholderEngagement.entries
        if entry.stakeholderType == "partners"
    )
    partner.customMethods.append(
        CustomEngagementMethod(kind="collaboration_activity", label="区域协作计划")
    )
    report = apply_stakeholder_engagement_projection(report)

    block = report.find_block("sm.stakeholder_table")
    rows = [row for row in block.table.children if not row.headerRow]
    assert len(rows) == 8
    partner_row = rows[6]
    assert partner_row.children[0].value == "合作伙伴"
    assert "可持续供应链管理" in partner_row.children[1].value
    assert "行业交流" in partner_row.children[2].value
    assert partner_row.children[2].value.endswith("区域协作计划")
    assert rows[7].children[0].value == "社区与公众"


def test_public_catalog_joins_topic_labels_from_registry() -> None:
    public = public_stakeholder_engagement_catalog(SSE_PACKAGE)
    topics = {topic["id"]: topic["label"] for topic in public["topics"]}
    assert topics["data_security_customer_privacy_protection"] == "数据安全与客户隐私保护"
    assert topics["anti_bribery_anti_corruption"] == "反商业贿赂与反贪污"


def test_stored_state_v4_roundtrips_profile() -> None:
    report = _report(technology_ethics=True)
    state = StoredReportStateV4(
        version=4,
        stakeholderEngagement=report.stakeholderEngagement,
    )

    restored = StoredReportStateV4.model_validate(state.model_dump())
    assert restored.version == 4
    assert restored.stakeholderEngagement == report.stakeholderEngagement


def test_missing_topic_blocks_export_without_preventing_profile_parse() -> None:
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None
    for entry in report.stakeholderEngagement.entries:
        entry.assessmentTopicIds = [
            topic_id for topic_id in entry.assessmentTopicIds if topic_id != "climate_change"
        ]

    diagnostics = diagnose(report)
    issue = next(
        item for item in diagnostics.issues if item.code == "stakeholder_topic_unassigned"
    )
    assert issue.level == "block"
    assert issue.blockId == "sm.stakeholder_table"
    assert "尚有 1 个适用议题" in issue.message
    assert "应对气候变化" in issue.message


def test_unbound_report_parses_so_the_client_projection_can_reach_the_server() -> None:
    """未绑定知识包的报告必须能通过校验——客户端投影按设计不带包身份。

    回归 2026-09-16：客户端投影（`frontend/public/contract.json`）是单包静态快照，
    不带 `knowledgePackageId`；而生成完成后状态里带 stakeholderEngagement。二者一合，
    `/api/plan`、`/api/reports/{id}/diagnose`、`generation-freshness` 全部在入口 422
    （`body.report`），表现为报告正文页「无法载入或解析当前报告」——即报告一旦生成完成
    就再也打不开。包身份是服务端事实，不能在校验期强求客户端先知道它。
    """
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None

    unbound = Report.model_validate(
        {**report.model_dump(mode="json"), "knowledgePackageId": None}
    )

    assert unbound.knowledgePackageId is None
    assert unbound.stakeholderEngagement is not None


def test_binding_a_package_still_rejects_unknown_engagement_references() -> None:
    """绑定包之后必须重新校验引用——`model_copy` 不重跑验证器。

    与上一条是一对：验证器在未绑定时跳过，若绑定侧只做 `model_copy`，未知沟通方式
    将完全失去拦截并一路进入正文。`bind_knowledge_package` 因此把绑定与校验合为一步。
    """
    report = _report(technology_ethics=False)
    assert report.stakeholderEngagement is not None
    broken = report.stakeholderEngagement.model_copy(
        update={
            "entries": [
                report.stakeholderEngagement.entries[0].model_copy(
                    update={"methodIds": ["不存在的沟通方式"]}
                ),
                *report.stakeholderEngagement.entries[1:],
            ]
        }
    )
    unbound = Report.model_validate(
        {
            **report.model_dump(mode="json"),
            "knowledgePackageId": None,
            "stakeholderEngagement": broken.model_dump(mode="json"),
        }
    )

    with pytest.raises(ValueError, match="未知沟通方式"):
        bind_knowledge_package(unbound, SSE_PACKAGE)
