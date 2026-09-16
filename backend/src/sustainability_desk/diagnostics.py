# ABOUTME: 报告诊断单一真相层——diagnose(report)→Diagnostics，导出闸与前端预检/进度同源消费。
# ABOUTME: 规则确定性、无 LLM；模板级生成约束以服务端当前模板为准；接上 table_export_issues。
# ABOUTME(en): Single source of truth for report diagnostics — diagnose(report) to Diagnostics, consumed alike by the
# ABOUTME(en): export gate and the frontend precheck. Deterministic rules, no LLM; folds in table_export_issues.
from __future__ import annotations

from functools import lru_cache
from typing import Literal, get_args

from pydantic import BaseModel, computed_field

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.knowledge_packages import knowledge_package_of, load_knowledge_package
from sustainability_desk.contract.disclosure_coverage import (
    DisclosureCoverageReport,
    evaluate_disclosure_coverage,
)
from sustainability_desk.contract.input_obligations import (
    input_obligations_due,
    missing_input_obligations,
)
from sustainability_desk.contract.user_visible_disclosure_clause_annotations import find_user_visible_disclosure_clause_annotation_entry
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.models import Block, Report
from sustainability_desk.contract.stakeholder_engagement import (
    apply_stakeholder_engagement_projection,
    missing_stakeholder_topic_ids,
)
from sustainability_desk.contract.topic_registry import all_assessment_topics
from sustainability_desk.contract.report_values import resolve_report_ref
from sustainability_desk.llm.guardrail_lexicon import lexicon_for
from sustainability_desk.contract.section_titles import display_title_is_stale
from sustainability_desk.contract.visibility import assessment_value, visible
from sustainability_desk.llm.standard_disclosure_requirements import resolve_standard_disclosure_requirements
from sustainability_desk.llm.topic_validate import validate_topic_templates_or_raise
from sustainability_desk.llm.table_validate import (
    TableExportIssue,
    TableIssueKind,
    table_export_issues,
)
from sustainability_desk.planner import load_topic_intake, load_topic_templates, with_topic_sections
from sustainability_desk.quantitative_metrics import apply_quantitative_metrics_table_projection
from sustainability_desk.lightweight_report_readiness import (
    LightweightReportReadiness,
    parse_stored_lightweight_report_readiness,
)
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.structured_inputs import StructuredInputContext

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型引用，避免 accounts→diagnostics 的运行期反向依赖
    from sustainability_desk.accounts.report_execution_scope import EffectiveReportScope


# Internal-text markers are language lexicon data (llm/guardrail_lexicon.py); the report's package picks the set.


class Issue(BaseModel):
    """单条诊断：level 决定是否阻断导出；code 供前端归类；定位字段按问题类型择填。

    **用户可见文案由前端按 `code` + `params` 渲染，不用 `message`。** `message` 恒简体
    （本模块内联构造），直接呈现会在英文报告的导出前检查里混排中文——界面语言跟随
    报告所属知识包，而诊断不知道那是哪一种语言。同一问题在生成阻断侧已有既成范式：
    `frontend/components/intake/generation-section.tsx` 的 `blockerMessage()` 按稳定
    handle + 字典渲染，不透传后端串。

    `message` 保留且继续填写：它是服务端日志与既有消费者的事实，去掉即破坏契约。
    `params` 只承载**渲染所需的业务值**（标签、计数、名称列表），不含 id、路径或内部结构。
    """

    level: Literal["block", "warn"]
    code: str
    message: str
    #: 前端按 code 取文案模板后代入的值；键名与各 code 的模板占位符一一对应。
    params: dict[str, str | int | list[str]] = {}
    blockId: str | None = None
    rowId: str | None = None
    fieldKey: str | None = None
    path: str | None = None
    col: str | None = None
    readinessStageId: str | None = None
    actionHref: str | None = None
    assessmentTopicId: str | None = None
    reportSectionId: str | None = None
    metricKey: str | None = None


class Diagnostics(BaseModel):
    """一份报告的全部诊断；blocking 为是否存在阻断级问题（导出闸据此 fail-loud）。"""

    issues: list[Issue] = []
    readiness: LightweightReportReadiness | None = None
    # 准则披露覆盖判定：轻量版不阻断（不进 issues），只经审阅稿「准则对照说明」页告知用户。
    coverage: DisclosureCoverageReport | None = None

    @computed_field
    @property
    def blocking(self) -> bool:
        return any(i.level == "block" for i in self.issues)


# 表行 gate（table_export_issues）各 kind 的级别与文案——与 checks 的表格 severity 对齐。
_TABLE_LEVEL: dict[str, Literal["block", "warn"]] = {
    "required_empty": "block",
    "ai_text_empty": "warn",
    "row_failed": "block",
}
_TABLE_MSG: dict[str, str] = {
    "required_empty": "必填列为空",
    "ai_text_empty": "AI 列未生成",
    "row_failed": "该行生成失败",
    "fixed_row_missing": "缺少固定行",
    "fixed_row_duplicate": "固定行重复",
}
# 每种表行问题都必须有显式级别，不留默认值：漏登记一种就等于让一类本该阻断导出的问题
# 静默降级放行，而 Word 导出保真是一级风险。加载期即失败，不等到某份报告导出时才发现。
_TABLE_KIND_WITHOUT_LEVEL = set(get_args(TableIssueKind)) - set(_TABLE_LEVEL) - {
    "fixed_row_missing", "fixed_row_duplicate",  # 仅 risk_response_matrix 版式阻断，见 _table_issue_level
}
if _TABLE_KIND_WITHOUT_LEVEL:
    raise RuntimeError(f"表行问题缺少级别登记：{sorted(_TABLE_KIND_WITHOUT_LEVEL)}")
_INPUT_PHASE_LABEL = {
    "workbench": "工作台",
    "generation": "正式生成",
    "export": "Word 导出",
}


def _empty(value) -> bool:
    return value is None or str(value).strip() == ""


def _plain_text(content) -> str:
    return "".join(i.text or "" for i in (content or []) if i.kind == "text")


def _internal_report_text_marker(text: str, report: Report) -> str | None:
    markers = lexicon_for(knowledge_package_of(report).language).internal_report_text_markers
    return next((marker for marker in markers if marker in text), None)


def _iter_visible_blocks(report: Report):
    """深度优先遍历可见章节下的可见块。"""

    def walk(sections):
        for sec in sections:
            if not visible(sec, report):
                continue
            for block in sec.blocks:
                if visible(block, report):
                    yield block
            if sec.children:
                yield from walk(sec.children)

    yield from walk(report.sections)


def _iter_visible_sections_with_report_section(report: Report):
    """遍历可见章节，并保留最近的 reportSectionId。"""

    def walk(sections, report_section_id: str | None = None):
        for sec in sections:
            if not visible(sec, report):
                continue
            current_report_section_id = sec.reportSectionId or report_section_id
            yield sec, current_report_section_id
            if sec.children:
                yield from walk(sec.children, current_report_section_id)

    yield from walk(report.sections)


def _iter_visible_blocks_with_report_section(report: Report):
    for sec, report_section_id in _iter_visible_sections_with_report_section(report):
        for block in sec.blocks:
            if visible(block, report):
                yield block, report_section_id


def _table_issue_level(block: Block, kind: str) -> Literal["block", "warn"]:
    if block.table and block.table.layoutProfile == "risk_response_matrix" and kind in {
        "ai_text_empty",
        "fixed_row_missing",
        "fixed_row_duplicate",
    }:
        return "block"
    return _TABLE_LEVEL.get(kind, "warn")


def _table_issue_message(block: Block, detail: TableExportIssue) -> str:
    kind = detail.kind
    caption = block.table.caption if block.table and block.table.caption else "表格"
    row_label = detail.rowLabel
    row_part = f"「{row_label}」行" if row_label else (f"第 {detail.rowId} 行" if detail.rowId else "")
    col_label = detail.colHeader or detail.col
    if kind == "fixed_row_missing":
        return f"{caption}缺少「{row_label}」行"
    if kind == "fixed_row_duplicate":
        return f"{caption}{row_part}重复"
    if kind == "ai_text_empty":
        return f"{caption}{row_part}{col_label}为空"
    if kind == "required_empty":
        return f"{caption}{row_part}{col_label}为空"
    if kind == "row_failed":
        return f"{caption}{row_part}生成失败"
    return _TABLE_MSG.get(kind, kind) + (f"（{col_label}）" if col_label else "")


@lru_cache(maxsize=None)
def _obligation_labels_by_path(package_id: str) -> dict[str, str]:
    """输入义务编译层持有的 path→中文标签，供残留检查以用户语言指认缺失内容。"""
    definition = load_compiled_report_definition(load_knowledge_package(package_id))
    return {
        obligation.path: obligation.label
        for obligation in definition.input_obligations_by_target_handle.values()
    }


def _ref_display_label(ref: str, report: Report) -> str | None:
    """把正文引用目标翻译成用户可见标签；翻译不出的引用不得进入消息文案。"""
    field = report.fields.get(ref)
    if field is not None and field.label:
        return field.label
    labels = _obligation_labels_by_path(knowledge_package_of(report).id)
    return labels.get(ref) or labels.get(f"fields.{ref}.value")


@lru_cache(maxsize=None)
def _template_blocks_by_id(package_id: str):
    package = load_knowledge_package(package_id)
    report = load_package_contract(package)
    templates = load_topic_templates(package)
    intake = load_topic_intake(package)
    validate_topic_templates_or_raise(templates, intake, package=package)
    merged = with_topic_sections(report, templates)
    return {block.id: block for block in merged.iter_blocks()}


def diagnose(
    report: Report,
    *,
    stored_state: StoredReportStateV4 | None = None,
    structured_input_context: StructuredInputContext | None = None,
    include_assessment: bool = True,
    allowed_quantitative_metric_keys: frozenset[str] | None = None,
    include_module_title_freshness: bool = True,
) -> Diagnostics:
    """报告可导出性诊断（确定性、无 LLM）：聚合必填/要点/未审/表行 gate/残留为统一 issue 列表。

    范围语义由调用方声明，诊断自身不推断权益。**持有执行范围的调用一律走
    `diagnose_in_scope()`**，它从 `EffectiveReportScope` 唯一投影这些参数，保证 API 与
    生成 worker 两条路径的导出闸口径同源；本函数的散开参数只服务于不涉及权益的单元测试。
    """
    report = apply_stakeholder_engagement_projection(report)
    report = apply_quantitative_metrics_table_projection(report)
    issues: list[Issue] = []
    readiness = parse_stored_lightweight_report_readiness(
        report,
        state=stored_state,
        context=structured_input_context,
        include_assessment=include_assessment,
        allowed_metric_keys=allowed_quantitative_metric_keys,
    )
    topic_names = {topic.id: topic.name for topic in all_assessment_topics(knowledge_package_of(report))}
    # 沟通对象分配只对实际携带利益相关方表承载块的报告树生效;
    # 裁剪掉该块的报告树不得再以全量语义阻断。
    stakeholder_table_present = any(
        block.id == "sm.stakeholder_table" for block in report.iter_blocks()
    )
    missing_stakeholder_topics = (
        missing_stakeholder_topic_ids(report) if stakeholder_table_present else []
    )
    if missing_stakeholder_topics:
        issues.append(
            Issue(
                level="block",
                code="stakeholder_topic_unassigned",
                message=(
                    f"尚有 {len(missing_stakeholder_topics)} 个适用议题未分配沟通对象："
                    + "、".join(topic_names[topic_id] for topic_id in missing_stakeholder_topics)
                ),
                params={
                    "count": len(missing_stakeholder_topics),
                    # 议题名来自知识包，天然是包语言，前端按界面语言的分隔符连接。
                    "topics": [topic_names[topic_id] for topic_id in missing_stakeholder_topics],
                },
                blockId="sm.stakeholder_table",
            )
        )
    # readiness 面向"引导用户补齐"，与"能否交付 Word"不是同一判断：
    # 配置类缺失只有在其义务确实设定了 export 门禁时才阻断导出，否则降为 warn。
    # 其余 readiness issue（准则、评分、定量）保持阻断——正文对它们有无条件引用。
    export_gated_paths = {
        obligation.path
        for obligation in input_obligations_due("export", package=knowledge_package_of(report))
        if obligation.required_before == "export"
    }
    for issue in readiness.issues:
        configuration_only = (
            issue.code == "required_report_configuration"
            and issue.path not in export_gated_paths
        )
        issues.append(
            Issue(
                level="warn" if configuration_only else "block",
                code=issue.code,
                message=issue.message,
                fieldKey=issue.fieldKey,
                path=issue.path,
                readinessStageId=issue.stageId,
                actionHref=issue.actionHref,
                assessmentTopicId=issue.assessmentTopicId,
                metricKey=issue.metricKey,
            )
        )
    for obligation in missing_input_obligations(report, "export"):
        if obligation.required_before == "workbench":
            continue
        # 议题必答作答不是导出义务，与生成门槛同一裁定（report_preparation 的
        # generation_preparation_blockers）：轻量版议题引导问题全部选填，
        # 不得因它阻断导出，否则会出现"生成得了却导不出"。
        if obligation.owner_id.startswith("climate."):
            continue
        issues.append(
            Issue(
                level="block",
                code="required_input_obligation",
                message=(
                    f"{obligation.label}未填写，"
                    f"无法进入{_INPUT_PHASE_LABEL[obligation.required_before]}阶段"
                ),
                params={
                    # label 由知识包下发，天然是包语言；phase 传**稳定 id**而非中文标签，
                    # 由前端按界面语言取词（传中文标签等于把翻译责任推给客户端字符串匹配）。
                    "label": obligation.label,
                    "phase": obligation.required_before,
                },
                fieldKey=(
                    obligation.owner_id
                    if obligation.owner_kind == "field"
                    else None
                ),
                path=obligation.path,
                actionHref="/intake/info",
            )
        )

    for section, _report_section_id in _iter_visible_sections_with_report_section(report):
        if (
            section.reportModuleId is not None
            and not include_module_title_freshness
        ):
            # 模块 H1 不进入本范围交付物(如气候试用的独立气候章 Word)时,
            # 其标题新鲜度不构成导出阻断;H4 配对标题仍照常检查。
            continue
        if (
            section.reportModuleId is not None or section.titleGeneration is not None
        ) and display_title_is_stale(section, report):
            issues.append(
                Issue(
                    level="block",
                    code="stale_display_title",
                    message=f"章节「{section.title or section.key}」的用户可见标题尚未生成或已因正文变化而过期",
                    params={"section": section.title or section.key},
                    reportSectionId=section.reportSectionId,
                    path=f"sections.{section.key}.displayTitle",
                )
            )

    mainland_standard_selectable = knowledge_package_of(
        report
    ).manifest.disclosure_basis.mainland_standard_selectable
    if not mainland_standard_selectable:
        # A fixed disclosure basis names its standards in the package; there is nothing to choose
        # and no per-standard clause annotation source to check.
        pass
    elif report.disclosureProfile is None:
        # readiness 已以「大陆披露准则未选择」指认同一事实时不再重复报告。
        if not any(issue.path == "disclosureProfile.mainlandStandard" for issue in issues):
            issues.append(
                Issue(
                    level="block",
                    code="required_disclosure_profile",
                    message="报告披露准则未配置",
                    path="disclosureProfile.mainlandStandard",
                )
            )
    else:
        checked_annotation_sections: set[tuple[str, str | None]] = set()
        for section, report_section_id in _iter_visible_sections_with_report_section(report):
            if section.key != "sustainability_mgmt" and not section.reportSectionId:
                continue
            key = (section.key, section.reportSectionId or report_section_id)
            if key in checked_annotation_sections:
                continue
            checked_annotation_sections.add(key)
            if not find_user_visible_disclosure_clause_annotation_entry(
                knowledge_package_of(report),
                mainland_standard=report.disclosureProfile.mainlandStandard,
                report_section_key=section.key,
            ):
                issues.append(
                    Issue(
                        level="warn",
                        code="missing_user_visible_clause_annotation_source",
                        message=f"当前大陆准则下缺少「{section.title or section.key}」章节的用户可见准则批注条款原文",
                        params={"section": section.title or section.key},
                        path="disclosureProfile.mainlandStandard",
                    )
                )

    # 官网发布为选填依赖：选择后未填官网地址时，「报告获取及意见反馈」落入不含地址的默认句；
    # 诊断以 warn 引导补齐，不阻断导出。
    channel = report.fields.get("report_publication_channel")
    website_url = report.fields.get("report_publication_website_url")
    if (
        channel is not None
        and channel.value == "公司官网发布"
        and _empty(website_url.value if website_url is not None else None)
    ):
        issues.append(
            Issue(
                level="warn",
                code="required_report_configuration",
                message="已选择公司官网发布，但未填写公司官网地址；未补齐前报告获取方式不写出官网地址",
                fieldKey="report_publication_website_url",
            )
        )

    # 外部鉴证为纯选填：开启开关但未补齐时，对应段落与附录按合同 appears_when 自动省略；
    # 诊断以 warn 引导补齐（放行不等于沉默），不再阻断导出。
    assurance = report.appendixPackage.externalAssuranceReport
    if assurance.isIncluded:
        def _assurance_field(key: str) -> object | None:
            field = report.fields.get(key)
            return field.value if field is not None else None

        missing_assurance = [
            label
            for label, value in (
                ("鉴证机构", _assurance_field("assurance_provider_name")),
                ("鉴证标准", _assurance_field("assurance_standard")),
                ("附件说明", assurance.fileLabel),
            )
            if _empty(value)
        ]
        if missing_assurance:
            issues.append(
                Issue(
                    level="warn",
                    code="required_assurance_report",
                    message=(
                        "已选择外部鉴证，但未填写"
                        + "、".join(missing_assurance)
                        + "；未补齐前对应段落与附录自动省略"
                    ),
                    params={"missing": list(missing_assurance)},
                    path=(
                        "appendixPackage.externalAssuranceReport.fileLabel"
                        if _empty(assurance.fileLabel)
                        else None
                    ),
                )
            )

    # 残留检查的去重基线：同一缺失事实已被必填/就绪/鉴证等**阻断**指认时，不再以第二套话术重复报告。
    # 只收集 level=="block"：降为 warn 的缺失不构成交付阻断，若在此计入 covered，
    # key_residue 就不会补位，正文空洞会一路漏到渲染层才 fail-loud。
    covered_paths = {
        issue.path for issue in issues if issue.path and issue.level == "block"
    }
    covered_field_keys = {
        issue.fieldKey for issue in issues if issue.fieldKey and issue.level == "block"
    }
    scoring_incomplete = any(issue.readinessStageId == "assessment_scoring" for issue in issues)

    def _residue_already_reported(ref: str) -> bool:
        if ref in covered_field_keys or ref in covered_paths:
            return True
        if f"fields.{ref}.value" in covered_paths:
            return True
        return ref.startswith("assessment.") and scoring_incomplete

    template_blocks = _template_blocks_by_id(knowledge_package_of(report).id)
    for block, report_section_id in _iter_visible_blocks_with_report_section(report):
        generation_source = template_blocks.get(block.id) or block
        standard_requirement_keys = (
            generation_source.generation.standardDisclosureRequirementKeys
            if generation_source.generation and generation_source.generation.standardDisclosureRequirementKeys
            else []
        )
        if standard_requirement_keys and report_section_id:
            for key in standard_requirement_keys:
                if not resolve_standard_disclosure_requirements(
                    knowledge_package_of(report), report_section_id, [key]
                ):
                    issues.append(
                        Issue(
                            level="block",
                            code="unresolved_standard_disclosure_requirement",
                            message="该处内容的准则披露要求配置无法解析，请联系管理员处理",
                            blockId=block.id,
                        )
                    )
        if block.type == "table" and block.table is not None:
            # 表行 gate：接上 table_export_issues（消解 H1），映射为统一 issue
            for d in table_export_issues(block, report):
                issues.append(
                    Issue(level=_table_issue_level(block, d.kind), code=d.kind,
                          message=_table_issue_message(block, d),
                          # 表题、行标签与列表头都来自知识包或用户填写，天然是报告语言；
                          # 只有连接它们的措辞需要按界面语言取词。rowId 是内部标识，不入 params。
                          params={
                              key: value
                              for key, value in (
                                  ("caption", block.table.caption if block.table and block.table.caption else ""),
                                  ("row", d.rowLabel or ""),
                                  ("column", d.colHeader or d.col or ""),
                              )
                              if value
                          },
                          blockId=d.blockId, rowId=d.rowId, col=d.col)
                )
        else:
            text = _plain_text(block.content)
            marker = _internal_report_text_marker(text, report)
            if marker:
                issues.append(
                    Issue(
                        level="block",
                        code="internal_report_text",
                        message="正文包含内部说明或代理提示内容，已阻断导出",
                        blockId=block.id,
                    )
                )
        # 残留检查：正文 ref 指向空字段且无回退文案 → 导出时该处内容缺失（消解 ESG#3）。
        # 带 fallback 的引用由渲染器用回退文案渲染，不是缺失；消息只用用户可见标签，
        # 内部引用路径仅进 path/fieldKey 供跳转定位。
        for inl in block.content or []:
            if inl.kind == "ref" and inl.ref and not inl.fallback:
                value = assessment_value(inl.ref, report) if inl.ref.startswith("assessment.") else None
                if value is None:
                    value = resolve_report_ref(inl.ref, report)
                if _empty(value) and not _residue_already_reported(inl.ref):
                    label = _ref_display_label(inl.ref, report)
                    issues.append(
                        Issue(level="block", code="key_residue",
                              message=(
                                  f"「{label}」未填写，导出时正文引用它的位置会缺失内容"
                                  if label
                                  else "正文引用的报告内容未生成或未填写，导出时该处会缺失"
                              ),
                              # label 缺省时前端取无标签的通用措辞；不回落到把 ref 路径给用户看。
                              params={"label": label} if label else {},
                              blockId=block.id,
                              fieldKey=inl.ref if inl.ref in report.fields else None,
                              path=inl.ref if inl.ref.startswith(("disclosureProfile.", "appendixPackage.")) else None)
                    )

    if getattr(report.meta, "materialityStrategy", None) == "complete_coverage":
        issues.append(
            Issue(
                level="warn",
                code="materiality_complete_coverage",
                message="企业重要性评分未获授权资料支持；报告按当前合同的完整议题覆盖策略组织章节，未呈现为企业评分结论。",
            )
        )
    return Diagnostics(
        issues=issues,
        readiness=readiness,
        coverage=evaluate_disclosure_coverage(report),
    )


def diagnose_in_scope(
    report: Report,
    *,
    scope: "EffectiveReportScope",
    stored_state: StoredReportStateV4 | None = None,
    structured_input_context: StructuredInputContext | None = None,
) -> Diagnostics:
    """按执行范围诊断——持有 EffectiveReportScope 的调用点的唯一入口。

    范围到诊断参数的翻译只存在于 `EffectiveReportScope.diagnostics_scope()` 一处。
    若 API 与生成 worker 各写一遍同样的翻译、靠注释保持同步，任何一侧新增范围
    参数都可能漏改另一侧；两侧共享同一投影后，漏改在类型层面不可表达。
    """

    projected = scope.diagnostics_scope()
    return diagnose(
        report,
        stored_state=stored_state,
        structured_input_context=structured_input_context,
        include_assessment=projected.include_assessment,
        include_module_title_freshness=projected.include_module_title_freshness,
    )
