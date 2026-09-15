# ABOUTME: 规划端点 /api/plan 单测——完整适用评分清单驱动议题章节装配 + 议题诊断。
# ABOUTME: 集成真实 contract + topic_sections；materiality 不再过滤正文议题。
from fastapi.testclient import TestClient
from datetime import datetime, timezone
from uuid import uuid4

from sustainability_desk.api.app import ContractUpgradeRequiredError, app, plan_report
from sustainability_desk.api.auth import AuthenticatedUser, current_user
from sustainability_desk.contract.contract_version import contract_version
from sustainability_desk.contract.models import (
    DisclosureProfile,
    Field,
    Inline,
    MaterialityAssessmentInput,
    MaterialityScoreInput,
    MaterialityThreshold,
    Report,
)
from sustainability_desk.contract.topic_registry import applicable_scoring_topics
from topic_intake_assertions import expected_sme_topic_intake_keys
from knowledge_package_fixtures import SSE_PACKAGE


def _report_with_topics(
    climate_materiality: str = "dual",
    *,
    technology_ethics: str = "否",
) -> Report:
    report = Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t",
        fields={
            "has_technology_ethics_sensitive_activity": Field(
                key="has_technology_ethics_sensitive_activity",
                label="科技伦理适用性",
                type="enum",
                source="user_input",
                value=technology_ethics,
                options=["是", "否"],
            )
        },
        disclosureProfile=DisclosureProfile(),
        sections=[],
    )
    score_by_materiality = {
        "dual": (5.0, 5.0),
        "financial": (5.0, 2.0),
        "impact": (2.0, 5.0),
        "non": (2.0, 2.0),
    }
    scores = []
    for ref in applicable_scoring_topics(report, package=SSE_PACKAGE):
        materiality = climate_materiality if ref.id == "climate_change" else "dual"
        financial_score, impact_score = score_by_materiality[materiality]
        scores.append(MaterialityScoreInput(
            assessmentTopicId=ref.id,
            financialScore=financial_score,
            impactScore=impact_score,
        ))
    report.assessmentInput = MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=scores,
    )
    return report


def _report_with_partial_topic(materiality: str) -> Report:
    score = {"dual": (5.0, 5.0), "financial": (5.0, 2.0), "impact": (2.0, 5.0), "non": (2.0, 2.0)}[materiality]
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="t", fields={}, sections=[],
        assessmentInput=MaterialityAssessmentInput(
            reportingYear=2025,
            threshold=MaterialityThreshold(financial=4.0, impact=4.0),
            scores=[MaterialityScoreInput(
                assessmentTopicId="climate_change",
                financialScore=score[0], impactScore=score[1],
            )],
        ),
    )


def _has_topic_section(sections, topic_id: str) -> bool:
    for s in sections:
        if s.reportSectionId == topic_id:
            return True
        if _has_topic_section(s.children or [], topic_id):
            return True
    return False


def test_plan_assembles_material_topic_section():
    """适用议题 → assembled 挂载其报告章节 + 诊断 report_section_included。"""
    result = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)
    assert _has_topic_section(result["report"].sections, "climate_change"), "适用议题章节未挂载"
    assert any(
        d["reportSectionId"] == "climate_change"
        and d["status"] == "report_section_included"
        for d in result["diagnostics"]
    )


def test_plan_attaches_material_topic_intake_items():
    """适用议题 → report.intakeItems 挂入对应议题内容清单。"""
    result = plan_report(_report_with_topics("financial"), package=SSE_PACKAGE)
    items = [i for i in result["report"].intakeItems if i.contentScopeId == "climate_change"]
    assert {i.key for i in items} == expected_sme_topic_intake_keys("climate")


def test_plan_keeps_non_material_topic():
    """非重要议题仍进入正文。"""
    result = plan_report(_report_with_topics("non"), package=SSE_PACKAGE)
    assert _has_topic_section(result["report"].sections, "climate_change")
    assert any(i.contentScopeId == "climate_change" for i in result["report"].intakeItems)


def test_plan_preserves_prose_on_replan():
    """重新 plan 按 block id 保留已编辑正文，不被模板态覆盖；input assessment 保留。"""
    # 深拷贝后再模拟前端编辑:装配产物与进程内缓存模板共享嵌套块,不得原地改写缓存实例。
    assembled = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"].model_copy(deep=True)
    assert assembled.assessment is not None, "plan 须保留 input assessment（merge 用 current 为基底）"
    para = next(b for b in assembled.iter_blocks() if b.type == "paragraph")
    para.content = [Inline(kind="text", text="用户已编辑正文")]
    para.state = "ready"
    pid = para.id
    result = plan_report(assembled, package=SSE_PACKAGE)
    merged = {b.id: b for b in result["report"].iter_blocks()}
    assert merged[pid].state == "ready"
    assert any((i.text or "") == "用户已编辑正文" for i in (merged[pid].content or []))


def test_plan_preserves_intake_answers_on_replan():
    """重新 plan 按 intake key 保留已填写答案与补充说明。"""
    assembled = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"].model_copy(deep=True)
    item = next(i for i in assembled.intakeItems if i.key == "climate.q_governance_roles")
    item.answer = "由管理层和运营部门共同负责"
    item.supplement = "由总经理办公会定期审议气候相关事项。"

    result = plan_report(assembled, package=SSE_PACKAGE)
    merged = next(i for i in result["report"].intakeItems if i.key == "climate.q_governance_roles")
    assert merged.answer == "由管理层和运营部门共同负责"
    assert merged.supplement == "由总经理办公会定期审议气候相关事项。"


def test_plan_uses_incoming_report_config_for_conditional_topics():
    """科技伦理适用性由传入 Report 控制，而不是固定 contract 默认值；风险管理恒适用。"""
    result = plan_report(_report_with_topics(technology_ethics="是"), package=SSE_PACKAGE)
    report = result["report"]

    assert _has_topic_section(report.sections, "risk_management")
    assert _has_topic_section(report.sections, "technology_ethics")
    assert any(i.contentScopeId == "risk_management" for i in report.intakeItems)
    assert any(i.contentScopeId == "technology_ethics" for i in report.intakeItems)
    assert any(d["reportSectionId"] == "risk_management" and d["status"] == "report_section_included" for d in result["diagnostics"])
    assert any(d["reportSectionId"] == "technology_ethics" and d["status"] == "report_section_included" for d in result["diagnostics"])


def test_plan_tolerates_incomplete_assessment_as_draft():
    """评分草稿（未覆盖全部适用议题）不得让报告在编辑期报错或无法打开——
    plan 按「尚无评分输入」回退 complete_coverage 装配；评分完整性只在
    生成前置门禁与结构化输入提交边界阻断（中途离开不报错，
    阻断仅在报告生成一步）。"""
    result = plan_report(_report_with_partial_topic("dual"), package=SSE_PACKAGE)
    assert _has_topic_section(result["report"].sections, "climate_change")
    assert result["report"].meta is not None
    assert result["report"].meta.materialityStrategy == "complete_coverage"


def test_plan_no_assessment_assembles_complete_coverage():
    """无评分输入 → 与生成侧权威装配（report_revision.build_company_inputs）同判定：
    complete_coverage 全议题挂载。plan 与 build_report_revision 是同一份 state 的两条
    装配路径，必须给出同一棵章节树；否则前端窄投影既看不到也导不出议题正文。"""
    assembled = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"]
    assert _has_topic_section(assembled.sections, "climate_change")
    assembled.assessmentInput = None
    result = plan_report(assembled, package=SSE_PACKAGE)
    assert _has_topic_section(result["report"].sections, "climate_change"), (
        "无评分输入时议题章节被丢弃——plan 与权威装配的重要性策略判定发生分叉"
    )
    # complete_coverage 装配走完整模板（非 conciseDisclosure 单块），正文块必须存在。
    assert any(
        block.blockType in {"generative", "constrained"}
        for block in result["report"].iter_blocks()
    )


def test_plan_writes_back_materiality_strategy_fact():
    """装配用过的重要性策略必须随 Report 返回——下游 /diagnose、/export 与
    生成侧同判定;不回写会把无评分报告误判为"必须完成重要性评分"。"""
    scored = plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)["report"]
    assert scored.meta is not None and scored.meta.materialityStrategy is None

    unscored = _report_with_topics("dual")
    unscored.assessmentInput = None
    planned = plan_report(unscored, package=SSE_PACKAGE)["report"]
    assert planned.meta is not None
    assert planned.meta.materialityStrategy == "complete_coverage"


def test_scope_projection_of_planned_report_stays_in_contract():
    """范围投影后的 Report 必须仍符合合同（前端 Ajv 会忠实拒收越界产物）。

    回归:project_report 曾把非空字段 appendixPackage 经 model_copy 置为 None,
    绕过校验产出违反合同的 plan 响应,新建报告在浏览器端整体不可用。"""
    from sustainability_desk.accounts.report_execution_scope import execution_scope_for_profile

    report = _report_with_topics("dual")
    report.assessmentInput = None
    planned = plan_report(report, package=SSE_PACKAGE)["report"]
    scope = execution_scope_for_profile("local_single_user@1", knowledge_package=SSE_PACKAGE)
    projected = scope.project_report(planned)
    Report.model_validate(projected.model_dump(mode="json"))
    assert projected.appendixPackage is not None


def test_plan_maps_assembly_guard_to_422(monkeypatch):
    """装配 guard（如实质议题无章节模板）→ 422（可读），而非 500。
    guard 本体由 test_planner 直接覆盖；评分输入引用未登记议题现按草稿回退
    complete_coverage（不再触达 guard），故此处只验证 plan 对 guard 异常的映射。"""
    import pytest
    from fastapi import HTTPException
    from sustainability_desk import planner

    def raise_guard(*args: object, **kwargs: object) -> None:
        raise planner.TopicGuardError("实质议题缺少章节模板：unregistered_topic")

    monkeypatch.setattr(planner, "assemble_report", raise_guard)
    with pytest.raises(HTTPException) as exc:
        plan_report(_report_with_topics("dual"), package=SSE_PACKAGE)
    assert exc.value.status_code == 422
    assert "缺少章节模板" in str(exc.value.detail)


def test_plan_requires_explicit_contract_upgrade_for_pinned_report():
    """已钉住旧契约的报告不得静默以当前 YAML 重装配。"""
    import pytest

    with pytest.raises(ContractUpgradeRequiredError):
        plan_report(_report_with_topics(), expected_contract_version="cv-outdated", package=SSE_PACKAGE)

    assert plan_report(_report_with_topics(), expected_contract_version=contract_version(SSE_PACKAGE), package=SSE_PACKAGE)["report"].assessment is not None


def test_plan_endpoint_returns_machine_readable_upgrade_required_response():
    """浏览器恢复链能稳定区分版本冲突，不能把 409 当作普通 plan 失败。"""
    subject, account_id, report_id, grant_id = uuid4(), uuid4(), uuid4(), uuid4()

    class Pool:
        async def fetchrow(self, query, *_args):
            if "from account_identities" in query:
                now = datetime.now(timezone.utc)
                return {
                    "account_id": account_id,
                    "email": "test@example.edu.cn",
                    "phone": None,
                    "organization_name": None,
                    "wechat_id": None,
                    "status": "active",
                    "registered_at": now,
                    "last_active_at": now,
                    "grant_id": grant_id,
                    "profile_id": "local_single_user@1",
                    "starts_at": now,
                    "ends_at": None,
                    "onboarding_seen": [],
                }
            if "from report_states" in query:
                return {
                    "report_id": report_id,
                    "state": {"version": 4},
                    "state_seq": 1,
                    "contract_version": contract_version(SSE_PACKAGE),
                }
            if "from reports" in query:
                now = datetime.now(timezone.utc)
                return {
                    "id": report_id,
                    "title": "test",
                    "report_type": "lightweight",
                    "report_profile_id": "sse_zh_hans@1",
                    "data_classification": "customer",
                    "created_under_profile_id": "local_single_user@1",
                    "contract_version": contract_version(SSE_PACKAGE),
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
            raise AssertionError(query)

    previous = getattr(app.state, "db_pool", None)
    app.state.db_pool = Pool()
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(subject=subject, email=None)
    try:
        response = TestClient(app).post(
            "/api/plan",
            json={
                "report_id": str(report_id),
                "report": _report_with_topics().model_dump(mode="json"),
                "expected_contract_version": "cv-outdated",
            },
        )
    finally:
        app.dependency_overrides.clear()
        app.state.db_pool = previous

    assert response.status_code == 409
    assert response.json() == {
        "code": "contract_upgrade_required",
        "message": "该报告使用的契约版本与当前版本不一致，需显式升级后才能继续编辑。",
    }


def test_with_topic_sections_appends_templates():
    """with_topic_sections 把议题模板并入大纲末尾（generate / prompt-config 共用同一 merge，去 L9 双写）。"""
    from sustainability_desk.contract.models import Section
    from sustainability_desk.planner import with_topic_sections

    base = Report(knowledgePackageId=SSE_PACKAGE.id, title="t", fields={}, sections=[Section(key="s", title="S", headingLevel=1, blocks=[])])
    tmpl = Section(key="climate", title="气候", headingLevel=1, reportSectionId="climate_change", blocks=[])
    merged = with_topic_sections(base, {"climate_change": tmpl})
    assert [s.key for s in merged.sections] == ["s", "climate"]
