# ABOUTME: 将轻量版 StoredReportStateV4 解析为完整 Report revision，供生成、工作台和 Word 共用。
# ABOUTME: 可选评分为空时采用完整议题覆盖；既有正文只作为同一 Report 的实例投影，不另立真相源。
# ABOUTME(en): Resolves a lightweight StoredReportStateV4 into a full Report revision for generation, workbench, Word.
# ABOUTME(en): Absent optional scoring means full topic coverage; existing prose is a projection, not a second truth.
from __future__ import annotations

from sustainability_desk.contract.build_report import build_report
from sustainability_desk.contract.company_inputs import CompanyInputs, IntakeAnswerSpec
from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.models import (
    AppendixPackage,
    Block,
    DisclosureProfile,
    GsTableRow,
    Report,
    Section,
)
from sustainability_desk.contract.stored_report_state import StoredReportStateV4

_DERIVED_FIELDS = frozenset({"industry", "company_business_summary"})


def company_inputs_from_stored_state(
    state: StoredReportStateV4,
    *,
    package: KnowledgePackage,
) -> CompanyInputs:
    """把用户输入状态投影为唯一 CompanyInputs，不运行简介压缩或猜测缺失值。

    业务摘要取状态中已保存的派生结果；本函数仍不调用模型——派生由生成编排在
    生成前完成并落入状态，此处只做投影。未派生时为空串，其余块缺该背景但不阻断。
    """

    fields = {
        key: value
        for key, value in state.fields.items()
        if value is not None and key not in _DERIVED_FIELDS
    }
    profile = state.intakeItems.get("company_profile")
    company_profile = (
        profile.answer
        if profile is not None and isinstance(profile.answer, str)
        else ""
    )
    intake = {
        key: IntakeAnswerSpec(
            answer=value.answer,
            supplement=value.supplement,
        )
        for key, value in state.intakeItems.items()
        if key != "company_profile"
    }
    assessment = state.assessmentInput
    return CompanyInputs(
        knowledgePackageId=package.id,
        fields=fields,
        company_profile=company_profile,
        business_summary=(
            state.companyBusinessSummary.text
            if state.companyBusinessSummary is not None
            else ""
        ),
        intake=intake,
        assessmentInput=assessment,
        disclosureProfile=state.disclosureProfile or DisclosureProfile(),
        appendixPackage=state.appendixPackage or AppendixPackage(),
        quantitativeMetrics=(
            state.meta.quantitativeMetrics if state.meta is not None else None
        ),
        materialityStrategy=(
            None if assessment is not None else "complete_coverage"
        ),
    )


def _project_block(block: Block, state: StoredReportStateV4) -> Block:
    generated = state.generatedBlocks.get(block.id)
    table_state = state.tableBlocks.get(block.id)
    image_state = state.imageBlocks.get(block.id)
    if image_state is not None and block.image is not None and block.image.layoutAssetSlot:
        return block.model_copy(
            update={
                "state": image_state.state,
                "image": block.image.model_copy(
                    update={"layoutAssetIds": list(image_state.layoutAssetIds)}
                ),
            }
        )
    if generated is not None:
        return block.model_copy(
            update={
                "content": generated.content,
                "state": generated.state,
            }
        )
    if table_state is not None and block.table is not None:
        # 职责边界：表头与列合同归运行时模板拥有，状态快照只承载数据行。
        # 状态中可能自带 headerRow=true 的表头行，必须在投影时过滤——
        # 否则模板表头 + 状态表头拼成双表头，docx 渲染会把两行都标记为
        # 跨页重复表头，Word 中表首与跨页处出现两行相同表头。
        headers = [row for row in block.table.children if row.headerRow]
        data_rows = [
            GsTableRow.model_validate(row.model_dump(mode="json", by_alias=True))
            for row in table_state.children
            if not row.headerRow
        ]
        return block.model_copy(
            update={
                "state": table_state.state,
                "table": block.table.model_copy(
                    update={"children": [*headers, *data_rows]}
                ),
            }
        )
    return block


def _project_section(section: Section, state: StoredReportStateV4) -> Section:
    return section.model_copy(
        update={
            "displayTitle": state.sectionTitles.get(section.key),
            "blocks": [_project_block(block, state) for block in section.blocks],
            "conciseDisclosure": (
                _project_block(section.conciseDisclosure, state)
                if section.conciseDisclosure is not None
                else None
            ),
            "children": (
                [_project_section(child, state) for child in section.children]
                if section.children is not None
                else None
            ),
        }
    )


def build_report_revision(
    state: StoredReportStateV4,
    *,
    package: KnowledgePackage,
    tolerate_incomplete_assessment: bool = False,
) -> Report:
    """建立包含用户输入、生成正文、表格与动态标题的完整 Report revision。

    tolerate_incomplete_assessment 语义见 build_report：编辑期路径（状态写入校验、准备投影）
    对尚未填全的评分回退 complete_coverage；生成/导出/资料映射路径保持严格。
    范围外评分在任何路径都 fail-loud，不受本参数影响。
    """

    report = build_report(
        company_inputs_from_stored_state(state, package=package),
        tolerate_incomplete_assessment=tolerate_incomplete_assessment,
    )
    return report.model_copy(
        update={
            "sections": [
                _project_section(section, state) for section in report.sections
            ],
            "stakeholderEngagement": state.stakeholderEngagement,
        }
    )
