# ABOUTME: 定义准备中心的服务端投影与最低生成资格；生成门槛只看最低资格，不设 Gap 门禁。
# ABOUTME: 输入状态均从现有权威对象派生；所有报告统一以 active 文件待补充说明/素材标题作为生成门槛。
# ABOUTME(en): Server-side projection of the preparation center plus minimum generation eligibility; no gap gate.
# ABOUTME(en): Input state derives from existing authoritative objects; every report shares one uniform generation gate.
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sustainability_desk.contract.input_obligations import missing_input_obligations
from sustainability_desk.contract.models import QuantitativeMetricsMeta, Report
from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    knowledge_package_of,
    load_knowledge_package,
)
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.report_profiles import ReportProfile
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.contract.topic_registry import (
    all_assessment_topics,
    applicable_scoring_topics,
    load_topic_contract,
)
from sustainability_desk.quantitative_metrics import validate_complete_quantitative_metrics

type PreparationAreaId = Literal[
    "report_identity",
    "materiality",
    "quantitative_metrics",
    "topic_questions",
    "materials",
]
type PreparationAreaStatus = Literal[
    "needs_input",
    "optional_empty",
    "ready",
    "processing",
    "needs_attention",
]


class ReportPreparationModel(BaseModel):
    """准备中心公共合同的严格不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PreparationBlocker(ReportPreparationModel):
    """一项会阻断轻量版首次生成的用户可行动缺失。"""

    target_handle: str
    label: str
    message: str
    href: str


class PreparationArea(ReportPreparationModel):
    """准备中心一个输入域的用户友好状态。"""

    id: PreparationAreaId
    title: str
    href: str
    required_for_generation: bool
    status: PreparationAreaStatus
    summary: str
    action_label: str


class ReportPreparationProjection(ReportPreparationModel):
    """轻量版准备中心唯一公共读模型。"""

    contract: Literal["sustainability_desk.report_preparation.v1"] = (
        "sustainability_desk.report_preparation.v1"
    )
    report_id: UUID
    report_state_seq: int = Field(ge=1)
    generation_eligible: bool
    generation_blockers: tuple[PreparationBlocker, ...]
    areas: tuple[PreparationArea, ...]
    report_update_available: bool = False
    workbench_enabled: bool
    # 报告级主输入路径（materials=上传资料并解析 / questions=直接回答引导问题）。
    # 只驱动分步流编排；None 表示用户尚未选择，前端应引导用户先做二选一。
    primary_input_mode: Literal["materials", "questions"] | None = None
    # 评分草稿已开始但未覆盖全部适用议题。生成时按未评分处理（完整议题覆盖策略），
    # 供前端在用户点击生成时如实告知，而不是让前端自行比对议题清单。
    assessment_partially_scored: bool = False
    assessment_scored_topic_count: int = 0
    assessment_applicable_topic_count: int = 0


# 必填字段的中文名。缺条目时 _field_label 直接抛错，不静默回退成英文标识符——
# `reporting_year` 曾因缺条目让界面显示「请填写reporting_year。」。
_FIELD_LABELS = {
    "company_registered_name": "公司注册名称",
    "industry_major_category": "所属行业门类",
    "reporting_year": "报告年份",
    "report_period_start": "报告期起始日期",
    "report_period_end": "报告期截止日期",
}


def _field_label(field_id: str) -> str:
    """取字段的用户可见中文名；没有登记即是缺陷，fail-loud 而非把标识符给用户看。"""

    try:
        return _FIELD_LABELS[field_id]
    except KeyError as exc:
        raise KeyError(
            f"字段 {field_id} 缺少用户可见中文名，请在 _FIELD_LABELS 登记后再纳入必填"
        ) from exc


def _present(value: object) -> bool:
    return value is not None and bool(str(value).strip())


def _obligation_href(report: Report, owner_id: str) -> str:
    """将已编译输入义务投影为现有用户输入入口，不复制必填名单。"""

    if owner_id == "company_profile":
        return "/intake/info"
    if owner_id.startswith("climate."):
        # 气候题是议题信息填写页的内容；不得把新用户抛进三栏工作台。
        return "/intake/questions"
    # Intake questions are answered on the topic questions page; the report document page
    # only reads and edits generated prose and never collects input.
    return "/intake/questions"


def generation_preparation_blockers(
    *,
    state: StoredReportStateV4,
    profile: ReportProfile,
    report: Report,
    required_quantitative_metric_keys: frozenset[str] | None = None,
    pending_file_description_count: int = 0,
    material_set_requires_confirmation: bool = False,
    unresolved_failed_file_count: int = 0,
    pending_description_href: str = "/materials",
) -> tuple[PreparationBlocker, ...]:
    """解析首次生成门槛；Profile 字段与 compiled 输入义务是唯一来源。

    pending_file_description_count 反映当前 active 文件中，说明文本仍为空、
    待用户补充的数量；语义资料与排版素材两类 role 同计——素材说明是图片识别的
    输入，与语义资料的说明同级守卫生成资格。这不是资料完全缺失
    （后者是 optional，不阻断生成），而是用户已上传但意图未完整表达。
    pending_description_href 是该 blocker 的跳转入口：问答路径下素材在议题信息页
    上传，缺说明的入口随之不同，由调用方按缺说明文件的 role 与填报方式给出。

    material_set_requires_confirmation 仅在语义资料说明已齐但用户尚未点击
    "下一步：资料处理"（或资料集变化后确认已失效）时为真；与说明待补充 blocker
    互斥共存，不重复指责。

    unresolved_failed_file_count 是仍绑定在报告上、文件层无法解析（加密/损坏/超页数）
    的文件数——闸一（design.md §7.3）：这是机械事实而非 AI 判断，用户必须重新上传或
    移出后才能生成。Agent 终态失败（「资料暂不可用」）不计入，保持 §3.5 不阻断语义。

    议题级 generation 义务不阻断生成：轻量版议题引导问题全部选填（design.md §7.3），
    选择 materials 的用户也无法通过资料让 AI 代填这些题（资料走块级证据轨，不写回
    intakeItems）。导出闸读同一侧事实，否则出现"生成得了却导不出"。
    """

    blockers: list[PreparationBlocker] = [
        PreparationBlocker(
            target_handle=f"field.{field_id}",
            label=_field_label(field_id),
            message=f"请填写{_field_label(field_id)}。",
            href="/intake/info",
        )
        for field_id in profile.generation_required_field_ids
        if not _present(state.fields.get(field_id))
    ]
    period_start = state.fields.get("report_period_start")
    period_end = state.fields.get("report_period_end")
    if (
        _present(period_start)
        and _present(period_end)
        and str(period_end) < str(period_start)
    ):
        # ISO 日期字符串按字典序比较即时间序;倒置的报告期是非法领域状态,不得流入生成。
        blockers.append(
            PreparationBlocker(
                target_handle="field.report_period_range",
                label="报告期起止日期",
                message="报告期截止日期不能早于起始日期，请调整。",
                href="/intake/info",
            )
        )
    blockers.extend(
        PreparationBlocker(
            target_handle=obligation.target_handle,
            label=obligation.label,
            # 句子型 label(如公司简介的完整提示)直接作为消息;短名词短语才加"请完成"前缀。
            message=(
                obligation.label
                if obligation.label.startswith("请") or obligation.label.endswith("。")
                # 问句义务以「？」结尾时不再追加句号，避免「…目标？。」式文案。
                else f"请完成{obligation.label}"
                + ("" if obligation.label.endswith("？") else "。")
            ),
            href=_obligation_href(report, obligation.owner_id),
        )
        for obligation in missing_input_obligations(report, "generation")
        if obligation.required_before == "generation"
        if not obligation.owner_id.startswith("climate.")
    )
    if required_quantitative_metric_keys is not None and (
        validate_complete_quantitative_metrics(
            (
                state.meta.quantitativeMetrics
                if state.meta is not None
                else QuantitativeMetricsMeta()
            ),
            package=knowledge_package_of(report),
            allowed_metric_keys=required_quantitative_metric_keys,
        )
    ):
        blockers.append(
            PreparationBlocker(
                target_handle="quantitativeMetrics.climate_change",
                label="ESG 定量信息",
                message="请完成定量信息：每项填写数值或无数值原因。",
                href="/intake/metrics",
            )
        )
    if unresolved_failed_file_count > 0:
        blockers.append(
            PreparationBlocker(
                target_handle="materials.unresolved_failed_file",
                label="资料",
                message=(
                    f"有 {unresolved_failed_file_count} 份文件无法解析，"
                    "请重新上传可读的版本，或将它移出报告。"
                ),
                href="/materials/processing",
            )
        )
    if pending_file_description_count > 0:
        blockers.append(
            PreparationBlocker(
                target_handle="materials.pending_description",
                label="资料说明",
                message=f"还有 {pending_file_description_count} 份文件待补充说明。",
                href=pending_description_href,
            )
        )
    elif material_set_requires_confirmation:
        blockers.append(
            PreparationBlocker(
                target_handle="materials.unconfirmed",
                label="资料处理",
                message="资料确认无误后，请进入下一步提交处理。",
                href="/materials",
            )
        )
    # 同一编译义务不得在公共投影中被重复展示。
    return tuple(
        {blocker.target_handle: blocker for blocker in blockers}.values()
    )


def _quantitative_input_count(state: StoredReportStateV4) -> int:
    # 与定量页完成度和附录 KPI 表同口径：只有数值非空才算已填写；
    # 无值原因（含自动保存写入的"尚未收集"占位）与备注不计入。
    metrics = state.meta.quantitativeMetrics.metrics if state.meta else {}
    return sum(
        bool(str(draft.value or "").strip()) for draft in metrics.values()
    )


def _incomplete_assessment_summary(
    *,
    scored_topic_ids: set[str],
    applicable_topic_ids: set[str],
    package: KnowledgePackage,
) -> str:
    """评分未完成时说清差在哪、下一步做什么，不只报数量。

    「含不适用议题」与「填不全」是两种不同处境：前者需要重新提交一次评分把范围对齐，
    后者只需继续填。数量对比无法区分二者，还会出现 22 / 21 这种自相矛盾的显示。
    """

    names = {topic.id: topic.name for topic in all_assessment_topics(package)}
    inapplicable = sorted(scored_topic_ids - applicable_topic_ids)
    missing = sorted(applicable_topic_ids - scored_topic_ids)
    if inapplicable:
        listed = "、".join(names.get(topic_id, topic_id) for topic_id in inapplicable)
        return (
            f"{listed} 已不在适用范围内，评分需重新提交一次以对齐当前议题；"
            "在此之前本次按未评分处理。"
        )
    return (
        f"已填写 {len(scored_topic_ids)} / {len(applicable_topic_ids)} 个议题；"
        f"还差 {len(missing)} 个，评分需全部填完才会写入报告，否则本次按未评分处理。"
    )


def project_report_preparation(
    *,
    report_id: UUID,
    report_state_seq: int,
    state: StoredReportStateV4,
    profile: ReportProfile,
    active_file_count: int,
    processing_file_count: int = 0,
    processing_mapping_scope_count: int = 0,
    attention_item_count: int = 0,
    report_update_available: bool = False,
    required_quantitative_metric_keys: frozenset[str] | None = None,
    generation_report: Report | None = None,
    pending_file_description_count: int = 0,
    material_set_requires_confirmation: bool = False,
    unresolved_failed_file_count: int = 0,
    primary_input_mode: Literal["materials", "questions"] | None = None,
    pending_description_href: str = "/materials",
) -> ReportPreparationProjection:
    """从 Profile、V4 与资料运行摘要派生准备状态和首次生成资格。

    议题引导问题的归属只由报告级填报方式决定；它们全部选填，不阻断生成。
    """

    # 重要性评分在轻量版是 optional_empty；即使用户只保存了部分草稿，
    # preparation 也必须仍能解析最低输入义务，而不能把评分完整性伪装成生成门槛。
    report = generation_report or build_report_revision(
        state.model_copy(update={"assessmentInput": None}),
        package=load_knowledge_package(profile.knowledge_package),
    )
    blockers = generation_preparation_blockers(
        state=state,
        profile=profile,
        report=report,
        required_quantitative_metric_keys=required_quantitative_metric_keys,
        material_set_requires_confirmation=material_set_requires_confirmation,
        pending_file_description_count=pending_file_description_count,
        unresolved_failed_file_count=unresolved_failed_file_count,
        pending_description_href=pending_description_href,
    )
    identity_blockers = tuple(
        blocker for blocker in blockers if blocker.href == "/intake/info"
    )
    # 议题引导问题的阻断项。
    topic_question_blockers = tuple(
        blocker for blocker in blockers if blocker.href == "/intake/questions"
    )
    quantitative_issues = (
        validate_complete_quantitative_metrics(
            (
                state.meta.quantitativeMetrics
                if state.meta is not None
                else QuantitativeMetricsMeta()
            ),
            package=knowledge_package_of(report),
            allowed_metric_keys=required_quantitative_metric_keys,
        )
        if required_quantitative_metric_keys is not None
        else ()
    )
    assessment_count = (
        len(state.assessmentInput.scores)
        if state.assessmentInput is not None
        else 0
    )
    # 评分只有覆盖全部适用议题才会成为报告结论：assessment_classify 强制完整覆盖，
    # 部分草稿在生成时按"未评分"处理（完整议题覆盖策略）。因此投影必须区分
    # 未填 / 部分填写 / 已完成三态，不能把任何非零计数都当作 ready。
    #
    # 判据必须与 assessment_classify 一致地比较「集合」而非「数量」：数量比较会把
    # 「多出不适用议题、同时缺少适用议题」判成完成，前门放行、生成一步才拒绝。
    # 适用范围与评分集合是同一事实的两面，只允许一个判据。
    applicable_assessment_topic_ids = {
        topic.id for topic in applicable_scoring_topics(report)
    }
    scored_topic_ids = (
        {score.assessmentTopicId for score in state.assessmentInput.scores}
        if state.assessmentInput is not None
        else set()
    )
    applicable_assessment_topic_count = len(applicable_assessment_topic_ids)
    assessment_complete = (
        bool(scored_topic_ids) and scored_topic_ids == applicable_assessment_topic_ids
    )
    metric_count = _quantitative_input_count(state)
    if processing_file_count:
        material_status: PreparationAreaStatus = "processing"
        material_summary = (
            f"已接纳 {active_file_count} 份文件，"
            f"{processing_file_count} 份正在处理。"
        )
    elif processing_mapping_scope_count:
        material_status = "processing"
        material_summary = (
            f"已处理 {active_file_count} 份文件，"
            f"{processing_mapping_scope_count} 个报告范围正在匹配资料。"
        )
    elif attention_item_count:
        material_status = "needs_attention"
        material_summary = (
            f"已接纳 {active_file_count} 份文件，"
            f"有 {attention_item_count} 项可选确认。"
        )
    elif pending_file_description_count:
        material_status = "needs_input"
        material_summary = (
            f"已接纳 {active_file_count} 份文件，"
            f"还有 {pending_file_description_count} 份待补充说明。"
        )
    elif active_file_count:
        material_status = "ready"
        material_summary = f"已接纳 {active_file_count} 份文件。"
    else:
        material_status = "optional_empty"
        material_summary = "尚未上传文件；轻量版仍可继续生成。"

    return ReportPreparationProjection(
        report_id=report_id,
        report_state_seq=report_state_seq,
        generation_eligible=not blockers,
        generation_blockers=blockers,
        report_update_available=report_update_available,
        workbench_enabled=profile.workbench_enabled,
        primary_input_mode=primary_input_mode,
        assessment_partially_scored=(
            assessment_count > 0 and not assessment_complete
        ),
        assessment_scored_topic_count=assessment_count,
        assessment_applicable_topic_count=applicable_assessment_topic_count,
        areas=(
            PreparationArea(
                id="report_identity",
                title="企业及报告基本信息",
                href="/intake/info",
                required_for_generation=True,
                status="needs_input" if identity_blockers else "ready",
                summary=(
                    f"还有 {len(identity_blockers)} 项最低信息需要填写。"
                    if identity_blockers
                    else "最低生成信息已填写。"
                ),
                action_label="填写基本信息" if identity_blockers else "查看或修改",
            ),
            # 评分步骤的存在由知识包的 materiality_regime 决定：不评分的准则（applicability 型，
            # 如 VSME 按「是否适用」逐条取舍）根本没有这一步，投影里就不该出现该区块。
            # 步骤是否展示与步骤能否完成必须由同一侧事实决定，故此处与写入边界读同一个事实。
            *(
                (
                    PreparationArea(
                        id="materiality",
                        # 标题与前端步骤声明（intake-steps）同源口径：该页即重要性评分页。
                        title="议题重要性评分",
                        href="/intake/scoring",
                        required_for_generation=False,
                        status=(
                            "ready"
                            if assessment_complete
                            else "needs_input" if assessment_count else "optional_empty"
                        ),
                        summary=(
                            f"已完成 {assessment_count} 个议题评分。"
                            if assessment_complete
                            else (
                                _incomplete_assessment_summary(
                                    scored_topic_ids=scored_topic_ids,
                                    applicable_topic_ids=applicable_assessment_topic_ids,
                                    package=knowledge_package_of(report),
                                )
                                if assessment_count
                                else "尚未填写；不会阻断轻量版生成。"
                            )
                        ),
                        action_label="填写或导入",
                    ),
                )
                if knowledge_package_of(report).manifest.materiality_regime != "applicability"
                else ()
            ),
            PreparationArea(
                id="quantitative_metrics",
                title="ESG 定量信息",
                href="/intake/metrics",
                required_for_generation=required_quantitative_metric_keys is not None,
                status=(
                    "needs_input" if quantitative_issues
                    else "ready" if metric_count else "optional_empty"
                ),
                summary=(
                    f"已填写 {metric_count} 项定量信息。"
                    if metric_count and not quantitative_issues
                    else "请逐项填写数值或无数值原因。"
                    if required_quantitative_metric_keys is not None
                    else "尚未填写；不会阻断轻量版生成。"
                ),
                action_label="填写或导入",
            ),
            *(
                _topic_questions_area(
                    report, blocking_obligations=topic_question_blockers
                )
                if primary_input_mode == "questions"
                else ()
            ),
            PreparationArea(
                id="materials",
                title="上传资料",
                href="/materials",
                required_for_generation=False,
                status=material_status,
                summary=material_summary,
                action_label="管理文件",
            ),
        ),
    )


def _answer_present(answer: str | list[str] | None) -> bool:
    """多选题答案是列表，空列表与空串一样视作未回答。"""

    if answer is None:
        return False
    if isinstance(answer, list):
        return len(answer) > 0
    return bool(str(answer).strip())


def _topic_questions_area(
    report: Report,
    *,
    blocking_obligations: tuple[PreparationBlocker, ...] = (),
) -> tuple[PreparationArea, ...]:
    """直答路径的议题引导问题区块。

    只在报告级主输入路径为 questions 时投影：materials 路径的用户不走这一步。

    是否必填由「当次实际解析出的议题义务」决定，而不是范围类型——与
    report_identity 区块的 identity_blockers 写法同构。无 generation 级议题义务时
    自然退化为选填。
    """

    topic_section_ids = set(load_topic_contract(knowledge_package_of(report)).reportSectionsById)
    topic_items = [
        item
        for item in report.intakeItems
        if item.contentScopeId in topic_section_ids
    ]
    answered = sum(1 for item in topic_items if _answer_present(item.answer))
    if blocking_obligations:
        return (
            PreparationArea(
                id="topic_questions",
                title="议题信息",
                href="/intake/questions",
                required_for_generation=True,
                status="needs_input",
                summary=f"还有 {len(blocking_obligations)} 项需要确认。",
                action_label="填写议题信息",
            ),
        )
    return (
        PreparationArea(
            id="topic_questions",
            title="议题信息",
            href="/intake/questions",
            required_for_generation=False,
            status="ready" if answered else "optional_empty",
            summary=(
                f"已回答 {answered} / {len(topic_items)} 个问题。"
                if answered
                else "尚未回答；不会阻断轻量版生成，回答越充分报告越具体。"
            ),
            action_label="填写议题信息" if not answered else "查看或修改",
        ),
    )
