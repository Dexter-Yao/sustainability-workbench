# ABOUTME: 从 Report 创建合同和当前权益派生单份报告的唯一执行范围。
# ABOUTME: 此模块只投影已授权的输入、资料、生成与交付边界，不新增平行权限或报告状态事实。
# ABOUTME(en): Derives one report's single execution scope from its creation contract and current entitlement.
# ABOUTME(en): Only projects authorized input, material, generation and delivery bounds; no parallel permissions.
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from sustainability_desk.accounts.entitlement_profiles import ReportScopeKind, require_profile
from sustainability_desk.contract.models import (
    AppendixPackage,
    QuantitativeMetricDraft,
    Report,
    ReportMeta,
)
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.topic_registry import all_report_sections
from sustainability_desk.quantitative_metrics import all_quantitative_metrics

# 词汇 owner 是 accounts/entitlement_profiles.py 的 ReportScopeKind；此处仅转发以保持既有导入路径。


@dataclass(frozen=True)
class DiagnosticsScope:
    """诊断闸的范围参数。由 EffectiveReportScope 唯一投影，调用方不自行翻译。"""

    include_assessment: bool
    include_module_title_freshness: bool


@dataclass(frozen=True)
class EffectiveReportScope:
    """一份 Report 当前可执行产品范围的不可变投影。

    能力以**声明式字段**承载，不让下游从 `kind` 反推：范围语义在
    `execution_scope_for_profile()` 一处解析完成，消费端只读字段。新增受限范围
    （英文版、定制章节集）时只需在派生处给值，不必再到各调用点补分支。
    """

    profile_id: str
    kind: ReportScopeKind
    # The knowledge package the report is built from; every catalog the scope exposes is drawn from it.
    knowledge_package: KnowledgePackage
    allowed_report_section_ids: frozenset[str]
    allowed_report_artifact_kinds: frozenset[Literal["word", "review"]]
    material_agent_enabled: bool
    can_export_word: bool
    # —— 以下为范围能力：由 kind 在派生处一次性解析，下游不得再按 kind 判断 ——
    # 是否收集议题重要性评分：评分页、Excel 模板下载与导入、矩阵预览。
    # 收集能力与"是否写进报告"是两件事，故下面另有 includes_materiality_assessment。
    collects_materiality_assessment: bool
    # 评分是否进入报告内容：Report 投影、诊断闸与生成上下文。
    includes_materiality_assessment: bool
    # 是否产出附录事实包。
    includes_appendix: bool
    # 是否收集利益相关方沟通事实。
    includes_stakeholder_engagement: bool
    # 是否要求模块 H1 标题新鲜度。
    requires_module_title_freshness: bool
    # 进入模型上下文的范围名称。模型面对的是派生自权威范围的任务视图，
    # 调用点不各自拼装标签；文案改动只在能力表一处发生。
    model_context_scope_label: str

    def diagnostics_scope(self) -> "DiagnosticsScope":
        """投影为诊断闸的范围参数。

        导出闸在 API 与生成 worker 两条路径上必须使用同一范围语义；改由此处唯一投影，
        新增范围参数时不会只改到其中一处。
        """

        return DiagnosticsScope(
            include_assessment=self.includes_materiality_assessment,
            include_module_title_freshness=self.requires_module_title_freshness,
        )

    def allowed_quantitative_metric_keys(self) -> frozenset[str]:
        """本范围可写的指标目录：单档模式下即完整轻量版全量目录。"""

        return frozenset(
            metric.key for metric in all_quantitative_metrics(self.knowledge_package)
        )

    def project_report(self, report: Report) -> Report:
        """删除当前范围外的议题树、问题和定量事实，供所有消费端共用。"""

        def project_sections(sections: Iterable, *, within_allowed_topic: bool = False):
            projected = []
            for section in sections:
                if (
                    section.reportSectionId is not None
                    and section.reportSectionId not in self.allowed_report_section_ids
                ):
                    continue
                section_is_allowed_topic = (
                    section.reportSectionId in self.allowed_report_section_ids
                )
                children = (
                    project_sections(
                        section.children or [],
                        within_allowed_topic=(
                            within_allowed_topic or section_is_allowed_topic
                        ),
                    )
                    if section.children is not None
                    else None
                )
                # 重要性评估不入交付物时，只裁重要性评估小节本身。旧条件按
                # 「无子节点的非议题章节」整体裁剪，会把前四章一并误裁。
                if (
                    not self.includes_materiality_assessment
                    and section.key == "sm.materiality"
                ):
                    continue
                if section.reportModuleId is not None and not children:
                    continue
                projected.append(section.model_copy(update={"children": children}))
            return projected

        meta = self._projected_meta(report.meta)
        return report.model_copy(
            update={
                "sections": project_sections(report.sections),
                "intakeItems": [
                    item
                    for item in report.intakeItems
                    if item.contentScopeId is None
                    or item.contentScopeId.startswith("front_")
                    or item.contentScopeId in self.allowed_report_section_ids
                ],
                "assessment": (
                    report.assessment if self.includes_materiality_assessment else None
                ),
                "assessmentInput": (
                    report.assessmentInput
                    if self.includes_materiality_assessment
                    else None
                ),
                # appendixPackage 在 Report 合同中非空;裁剪投影为契约默认空包,
                # 不得经 model_copy 写入 None 产出违反合同的 Report(前端 Ajv 会忠实拒收)。
                "appendixPackage": (
                    report.appendixPackage if self.includes_appendix else AppendixPackage()
                ),
                "stakeholderEngagement": (
                    report.stakeholderEngagement
                    if self.includes_stakeholder_engagement
                    else None
                ),
                "meta": meta,
            }
        )

    def _projected_meta(self, meta: ReportMeta | None) -> ReportMeta | None:
        """范围投影的定量元数据：目录收窄 + 留空补「尚未收集」。

        留空指标按「尚未收集」确定性补全：定量信息不再
        阻断生成与导出，用户未填即视为尚未收集。补全只发生在范围投影——存储
        状态仍是用户事实；生成上下文与附录 KPI 表消费的是同一份投影。
        """

        if meta is None:
            return None
        metric_keys = self.allowed_quantitative_metric_keys()
        metrics = {
            key: value
            for key, value in meta.quantitativeMetrics.metrics.items()
            if key in metric_keys
        }
        for key in metric_keys:
            if key not in metrics:
                metrics[key] = QuantitativeMetricDraft(noValueReason="not_collected")
        return meta.model_copy(
            update={
                "quantitativeMetrics": meta.quantitativeMetrics.model_copy(
                    update={"metrics": metrics}
                ),
                "materialityStrategy": (
                    meta.materialityStrategy
                    if self.includes_materiality_assessment
                    else None
                ),
            }
        )

    def prepare_deliverable_report(self, report: Report) -> Report:
        """交付物报告投影的唯一出口：与生成侧投影一致，只交付生成范围章节。"""

        return self.project_report(report)


@dataclass(frozen=True)
class _ScopeCapabilities:
    """一个执行范围的能力集合；与 EffectiveReportScope 同名字段一一对应。"""

    collects_materiality_assessment: bool
    includes_materiality_assessment: bool
    includes_appendix: bool
    includes_stakeholder_engagement: bool
    requires_module_title_freshness: bool
    model_context_scope_label: str


# 各执行范围的能力表。新增受限范围时在此增行，不在消费端加分支。
_SCOPE_CAPABILITIES: dict[ReportScopeKind, _ScopeCapabilities] = {
    "full_simplified": _ScopeCapabilities(
        collects_materiality_assessment=True,
        includes_materiality_assessment=True,
        includes_appendix=True,
        includes_stakeholder_engagement=True,
        requires_module_title_freshness=True,
        model_context_scope_label="轻量版 ESG 报告",
    ),
}


def build_execution_scope(
    *,
    profile_id: str,
    kind: ReportScopeKind,
    knowledge_package: KnowledgePackage,
    allowed_report_section_ids: frozenset[str],
    allowed_report_artifact_kinds: frozenset[Literal["word", "review"]],
    material_agent_enabled: bool,
    can_export_word: bool,
) -> EffectiveReportScope:
    """按范围能力表装配执行范围——所有构造点的唯一出口。

    能力字段一律从 `_SCOPE_CAPABILITIES` 取，调用方不得自行拼装：手工构造会与能力表
    双写漂移，且新增能力字段时旧构造点会静默保持旧行为。能力表缺该 kind 即 KeyError，
    新增 ReportScopeKind 却忘记登记时当场失败。

    重要性评分的两个开关是能力表与知识包的**合取**：能力表说这个执行范围允不允许，
    知识包的 `materiality_regime` 说这套准则要不要。二者语义不同、不可互相替代——
    权益放开不会让一套本就不评分的准则长出评分页，准则要求评分也不能越过范围限制。
    """

    capabilities = _SCOPE_CAPABILITIES[kind]
    # "applicability" 型准则（如 VSME）按「是否适用于本企业」逐条取舍，不做重要性评分，
    # 因此既不收集也不写入；其余三型都评分，只是轴数不同（见 MaterialityRegime）。
    package_scores_materiality = knowledge_package.manifest.materiality_regime != "applicability"
    return EffectiveReportScope(
        profile_id=profile_id,
        kind=kind,
        knowledge_package=knowledge_package,
        allowed_report_section_ids=allowed_report_section_ids,
        allowed_report_artifact_kinds=allowed_report_artifact_kinds,
        material_agent_enabled=material_agent_enabled,
        can_export_word=can_export_word,
        collects_materiality_assessment=(
            capabilities.collects_materiality_assessment and package_scores_materiality
        ),
        includes_materiality_assessment=(
            capabilities.includes_materiality_assessment and package_scores_materiality
        ),
        includes_appendix=capabilities.includes_appendix,
        includes_stakeholder_engagement=capabilities.includes_stakeholder_engagement,
        requires_module_title_freshness=capabilities.requires_module_title_freshness,
        model_context_scope_label=capabilities.model_context_scope_label,
    )


def execution_scope_kind_for_profile(profile_id: str) -> ReportScopeKind:
    """The scope kind an entitlement Profile grants; constant in single-tier mode."""

    require_profile(profile_id)
    return "full_simplified"


def execution_scope_for_profile(
    profile_id: str, *, knowledge_package: KnowledgePackage
) -> EffectiveReportScope:
    """由不可变权益 Profile 派生执行范围，不允许客户端指定范围。

    单档模式下报告形态是常量：全部正式报告章节、正式稿与审阅稿两种交付物、
    资料 Agent 与 Word 导出全开；Profile 只贡献活跃报告上限与章节重写额度。
    章节与指标目录取自报告所属知识包。
    """

    return build_execution_scope(
        profile_id=profile_id,
        kind=execution_scope_kind_for_profile(profile_id),
        knowledge_package=knowledge_package,
        allowed_report_section_ids=frozenset(
            section.id for section in all_report_sections(knowledge_package)
        ),
        allowed_report_artifact_kinds=frozenset({"word", "review"}),
        material_agent_enabled=True,
        can_export_word=True,
    )
