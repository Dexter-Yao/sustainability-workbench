# ABOUTME: 导出闸范围语义回归——诊断按执行范围声明语义，能力表与诊断投影单源。
# ABOUTME: 覆盖:完整范围默认沟通框架放行;能力表逐项钉住;范围外资料说明措辞;唯一构造点。
from sustainability_desk.accounts.report_execution_scope import execution_scope_for_profile
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.diagnostics import diagnose
from local_e2e_fixture import (
    load_local_e2e_fixture_recipe,
    synthesize_stored_report_state,
)
from knowledge_package_fixtures import SSE_PACKAGE


def test_full_scope_projects_default_stakeholder_framework_instead_of_blocking() -> None:
    """无沟通档案时按目录默认映射成表并放行，不再以未分配沟通对象阻断交付。

    若无档案即整表为空、导出被 stakeholder_topic_unassigned 阻断，用户没有任何
    可操作出口。目录只承载通用沟通渠道（不含事件、金额、时间），默认成表即企业
    客观存在的沟通框架，用户可在工作台按实际调整。
    """
    state = synthesize_stored_report_state(load_local_e2e_fixture_recipe())
    stripped = state.model_copy(update={"stakeholderEngagement": None})
    report = build_report_revision(stripped, package=SSE_PACKAGE)
    diag = diagnose(report, stored_state=stripped)
    assert not any(
        issue.code == "stakeholder_topic_unassigned" and issue.level == "block"
        for issue in diag.issues
    )


def test_scope_capability_table_covers_every_scope_kind() -> None:
    """新增 ReportScopeKind 却忘记登记能力时，派生必须当场失败而非静默退化。"""
    import typing

    from sustainability_desk.accounts.entitlement_profiles import ReportScopeKind
    from sustainability_desk.accounts.report_execution_scope import _SCOPE_CAPABILITIES

    assert set(typing.get_args(ReportScopeKind)) == set(_SCOPE_CAPABILITIES)


def test_scope_capabilities_match_full_simplified_semantics() -> None:
    """能力取值是范围语义的可执行声明；搭反一处即改变生产行为，此处逐项钉住。"""
    full = execution_scope_for_profile("local_single_user@1", knowledge_package=SSE_PACKAGE)

    assert full.kind == "full_simplified"
    assert full.collects_materiality_assessment
    assert full.includes_materiality_assessment
    assert full.includes_appendix
    assert full.includes_stakeholder_engagement
    assert full.requires_module_title_freshness
    assert full.material_agent_enabled
    assert full.can_export_word
    assert full.allowed_report_artifact_kinds == frozenset({"word", "review"})
    assert full.model_context_scope_label == "轻量版 ESG 报告"


def test_outside_scope_notice_never_promises_material_carryover() -> None:
    """范围外资料说明不得承诺这份资料日后可用——资料是报告级的，不跨报告结转。

    工作区按 report_id 唯一（``material_workspaces_one_active_report_idx``），资料挂在
    工作区下并随报告级联删除；另建的是另一份 Report，用户必须重新上传资料。因此任何
    "之后可使用（这份资料）"式的措辞都是空头承诺。范围提示要落在"议题范畴"上，
    主语是这类议题能否被覆盖，不是这份资料的去向。

    该文案同时会印进客户审阅包的资料使用说明（``report_review_packages`` 的
    ``_material_usage_note``），对外交付物中出现产品促销式承诺尤其不可接受。
    """
    from sustainability_desk.material.workspace import OUTSIDE_SCOPE_MATERIAL_NOTICE

    carryover_promises = (
        "后可使用",
        "后可采用",
        "后即可使用",
        "后仍可使用",
        "后继续使用",
        "可继续使用",
        "会保留",
        "自动带入",
        "无需重新上传",
    )
    assert "未纳入" in OUTSIDE_SCOPE_MATERIAL_NOTICE
    for promise in carryover_promises:
        assert promise not in OUTSIDE_SCOPE_MATERIAL_NOTICE, (
            f"范围外资料说明暗示资料会结转到另一份报告：{OUTSIDE_SCOPE_MATERIAL_NOTICE!r}"
        )


def test_diagnostics_scope_is_single_source_for_both_export_gates() -> None:
    """API 与生成 worker 的导出闸口径必须同源——两侧都读同一投影，不各自翻译。"""
    scope = execution_scope_for_profile("local_single_user@1", knowledge_package=SSE_PACKAGE)
    projected = scope.diagnostics_scope()
    assert projected.include_assessment == scope.includes_materiality_assessment
    assert (
        projected.include_module_title_freshness
        == scope.requires_module_title_freshness
    )


def test_execution_scope_has_single_construction_site() -> None:
    """EffectiveReportScope 只能经 build_execution_scope 装配。

    直接构造会绕过范围能力表：新增能力字段时旧构造点要么报错要么静默给出错误默认，
    而后者不会被任何测试发现。此处以源码扫描钉住唯一构造点。
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "sustainability_desk"
    # 目录必须存在：rglob 对不存在的路径静默返回空，扫描型断言会变成永远通过。
    assert root.is_dir(), f"源码根不存在，扫描断言会静默失效：{root}"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "report_execution_scope.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "EffectiveReportScope(" in line and "build_execution_scope" not in line:
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, f"请改用 build_execution_scope：{offenders}"


def test_projection_defaults_missing_metrics_to_not_collected() -> None:
    """留空定量指标在范围投影中确定性补「尚未收集」。

    补全只发生在投影：存储状态仍是用户事实；生成上下文与附录 KPI 表消费同一投影，
    完整性校验对补全后的投影恒过，定量信息不再阻断生成与导出。
    """
    from sustainability_desk.contract.models import QuantitativeMetricsMeta

    scope = execution_scope_for_profile("local_single_user@1", knowledge_package=SSE_PACKAGE)
    state = synthesize_stored_report_state(load_local_e2e_fixture_recipe())
    # 清空用户已填指标，模拟从未打开定量页的用户。
    state = state.model_copy(
        update={
            "meta": state.meta.model_copy(
                update={"quantitativeMetrics": QuantitativeMetricsMeta()}
            )
        }
    )
    projected = scope.project_report(build_report_revision(state, package=SSE_PACKAGE))

    assert projected.meta is not None
    metrics = projected.meta.quantitativeMetrics.metrics
    allowed = scope.allowed_quantitative_metric_keys()
    assert set(metrics) == set(allowed)
    assert all(draft.noValueReason == "not_collected" for draft in metrics.values())
    assert all(draft.value is None for draft in metrics.values())


def test_materiality_switches_are_the_conjunction_of_scope_and_package() -> None:
    """重要性两个开关 = 执行范围能力 ∧ 知识包判定型。

    二者语义不同：能力表说这个执行范围允不允许收集，知识包的 materiality_regime 说
    这套准则要不要评分。把准则事实塞进能力表会让「换准则」变成「换权益档」；反过来
    只看准则则会让范围限制失效。此处钉住合取，并证明 applicability 型确实关掉开关——
    当前四个包都不是该型，若不构造就没有任何用例覆盖这条分支。
    """
    from sustainability_desk.accounts.report_execution_scope import build_execution_scope

    def scope_for(regime: str):
        manifest = SSE_PACKAGE.manifest.model_copy(update={"materiality_regime": regime})
        return build_execution_scope(
            profile_id="sse_zh_hans@1",
            kind="full_simplified",
            knowledge_package=SSE_PACKAGE.model_copy(update={"manifest": manifest}),
            allowed_report_section_ids=frozenset(),
            allowed_report_artifact_kinds=frozenset({"word"}),
            material_agent_enabled=True,
            can_export_word=True,
        )

    for regime in ("double", "financial_primary", "impact_primary"):
        scope = scope_for(regime)
        assert scope.collects_materiality_assessment, regime
        assert scope.includes_materiality_assessment, regime

    unscored = scope_for("applicability")
    assert not unscored.collects_materiality_assessment
    assert not unscored.includes_materiality_assessment


def test_frontend_default_threshold_mirrors_the_backend_constant() -> None:
    """前端评分页的默认阈值必须与后端 resolver 的同一个值。

    两端各存一份是跨语言的无奈，但漂移的后果不对称：前端只是输入框初值，后端是
    实际分类依据，用户看着 4.0 的界面拿到按别的阈值分好的结论，且哪一端都不会报错。
    `frontend/lib/assessment.ts` 的注释写了「两端不得单独修改」——此处把它变成控制。
    """
    import pathlib
    import re

    from sustainability_desk.contract.assessment_classify import DEFAULT_THRESHOLD

    source = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "lib" / "assessment.ts"
    assert source.is_file(), f"前端常量文件不存在，扫描断言会静默失效：{source}"
    match = re.search(
        r"DEFAULT_THRESHOLD:\s*MaterialityThreshold\s*=\s*\{\s*financial:\s*([\d.]+)\s*,\s*impact:\s*([\d.]+)\s*\}",
        source.read_text(encoding="utf-8"),
    )
    assert match, "未能在 frontend/lib/assessment.ts 找到 DEFAULT_THRESHOLD 声明"
    assert (float(match.group(1)), float(match.group(2))) == (
        DEFAULT_THRESHOLD.financial,
        DEFAULT_THRESHOLD.impact,
    )
