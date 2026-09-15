# ABOUTME: 单一「上游输入→Report」装配管线——CompanyInputs（typed parse-first）经现算派生 + 装配产出实例 Report。
# ABOUTME: materiality/industry/summary 一律现算、不接受手设；生产与 eval 共用此入口，杜绝裸 dict 与捏造上游数据。
# ABOUTME(en): The one upstream-input-to-Report pipeline: typed CompanyInputs plus live derivation and assembly.
# ABOUTME(en): materiality/industry/summary are always derived, never set by hand; production and eval share this entry.
from __future__ import annotations

from sustainability_desk.contract.assessment_classify import (
    InapplicableScoredTopicsError,
    inapplicable_scored_topics,
    industry_display,
    resolve_materiality_assessment,
)
from sustainability_desk.contract.company_inputs import CompanyInputs
from sustainability_desk.contract.fill import fill_report
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.models import Report, ReportMeta
from sustainability_desk.planner import assemble_report, load_topic_intake, load_topic_templates


def _config_values(inputs: CompanyInputs) -> dict:
    """由 typed CompanyInputs 现算派生字段并投影成 fill 配置 values（内部实现，喂进去的均已校验、无捏造键）。"""
    fields = dict(inputs.fields)
    major = str(fields.get("industry_major_category", "") or "")
    division = str(fields.get("industry_division", "") or "")
    if major or division:
        fields["industry"] = industry_display(major, division)
    if inputs.business_summary:
        fields["company_business_summary"] = inputs.business_summary
    intake = {
        key: {"answer": spec.answer, "supplement": spec.supplement}
        for key, spec in inputs.intake.items()
    }
    intake["company_profile"] = {
        "answer": inputs.company_profile,
        "supplement": None,
    }
    return {
        "fields": fields,
        "intake": intake,
        "disclosureProfile": inputs.disclosureProfile.model_dump(),
        "appendixPackage": inputs.appendixPackage.model_dump(),
    }


def build_report(inputs: CompanyInputs, *, tolerate_incomplete_assessment: bool = False) -> Report:
    """CompanyInputs → 实例 Report：现算 assessment（materiality）→ 派生字段 → 装配议题章节 → 注入 ESG 定量 meta。

    tolerate_incomplete_assessment：编辑期路径（状态写入校验、准备投影）置 True——评分尚未覆盖
    全部适用议题时按「尚无评分输入」回退 complete_coverage，中途填写/浏览不阻断；生成、导出与
    资料映射路径保持默认 False，评分完整性在生成一步 fail-loud。

    范围外评分不在容忍之列：适用性由基本信息决定，评分只能是其子集，多出的议题是脏数据而非
    草稿，任何路径都直接 fail-loud——写入边界已拒绝其落库。
    """
    package = inputs.knowledge_package
    contract = load_package_contract(package)
    topic_templates = load_topic_templates(package)
    intake_templates = load_topic_intake(package)
    values = _config_values(inputs)

    config_report = fill_report(contract, values)
    complete_coverage = inputs.materialityStrategy == "complete_coverage"
    if complete_coverage:
        assessment = None
    else:
        if inputs.assessmentInput is None:
            raise ValueError("非完整议题覆盖策略必须提供重要性评分输入")
        inapplicable = inapplicable_scored_topics(inputs.assessmentInput, config_report)
        if inapplicable:
            raise InapplicableScoredTopicsError(inapplicable)
        try:
            assessment = resolve_materiality_assessment(inputs.assessmentInput, config_report)
        except ValueError:
            if not tolerate_incomplete_assessment:
                raise
            assessment = None
            complete_coverage = True
    assembled = assemble_report(
        config_report,
        topic_templates,
        assessment=assessment,
        intake_items=intake_templates,
        complete_coverage=complete_coverage,
    ).report
    report = fill_report(assembled, values)

    # 现算的 assessment 回存到实例 Report：驱动 _assessment_whitelist 向生成/评估上下文注入 materiality。
    update: dict = {
        "assessmentInput": inputs.assessmentInput,
        "assessment": assessment,
    }
    # 草稿回退后实际装配策略是 complete_coverage；meta 必须回写真实用过的策略，
    # 否则下游门禁会把回退报告误判为「必须完成重要性评分」。
    effective_strategy = "complete_coverage" if complete_coverage else inputs.materialityStrategy
    if inputs.quantitativeMetrics is not None or effective_strategy is not None:
        update["meta"] = ReportMeta(
            quantitativeMetrics=inputs.quantitativeMetrics or ReportMeta().quantitativeMetrics,
            materialityStrategy=effective_strategy,
        )
    return report.model_copy(update=update)
