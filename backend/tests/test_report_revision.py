# ABOUTME: 轻量版 StoredReportStateV4 到完整 Report revision 的合同测试。
# ABOUTME: 锁定零评分完整覆盖、无简介压缩以及正文和表格的同源投影。
from sustainability_desk.contract.report_revision import (
    build_report_revision,
    company_inputs_from_stored_state,
)
from sustainability_desk.contract.stored_report_state import (
    StoredGeneratedBlock,
    StoredReportStateV4,
    StoredTableBlock,
    StoredTableCell,
    StoredTableRow,
)
from sustainability_desk.contract.models import Inline
from knowledge_package_fixtures import SSE_PACKAGE


def _state() -> StoredReportStateV4:
    return StoredReportStateV4(
        version=4,
        fields={
            "company_registered_name": "测试公司",
            "industry_major_category": "制造业",
            "report_period_start": "2025-01-01",
            "report_period_end": "2025-12-31",
        },
    )


def test_empty_optional_inputs_build_complete_coverage_without_business_summary() -> None:
    """未派生业务摘要时投影为空串——缺该背景不阻断生成。"""
    inputs = company_inputs_from_stored_state(_state(), package=SSE_PACKAGE)

    assert inputs.materialityStrategy == "complete_coverage"
    assert inputs.assessmentInput is None
    assert inputs.business_summary == ""


def test_stored_business_summary_is_projected_into_company_inputs() -> None:
    """已派生的业务摘要须随投影进入 CompanyInputs。

    若该值被硬编码为空串，主链上每个块的 <report_subject> 都没有
    主营业务概述；投影本身仍不调用模型，派生由生成编排在生成前完成。
    """
    from sustainability_desk.contract.stored_report_state import StoredCompanyBusinessSummary

    state = _state()
    state.companyBusinessSummary = StoredCompanyBusinessSummary(
        text="公司主营精密电子元器件与连接器的研发、制造与销售。",
        sourceFingerprint="a" * 64,
    )

    inputs = company_inputs_from_stored_state(state, package=SSE_PACKAGE)

    assert inputs.business_summary == "公司主营精密电子元器件与连接器的研发、制造与销售。"


def test_revision_tolerates_incomplete_assessment_only_when_asked() -> None:
    """评分草稿（空/不完整 assessmentInput）不得阻断编辑期状态写入——
    tolerate_incomplete_assessment=True 回退 complete_coverage 装配并回写真实策略；
    默认（生成/导出路径）保持严格 fail-loud（阻断仅在生成一步）。"""
    import pytest

    from sustainability_desk.contract.models import MaterialityAssessmentInput, MaterialityThreshold

    state = _state()
    state.assessmentInput = MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=[],
    )

    with pytest.raises(ValueError, match="缺少适用评分议题"):
        build_report_revision(state, package=SSE_PACKAGE)

    report = build_report_revision(state, tolerate_incomplete_assessment=True, package=SSE_PACKAGE)
    assert report.assessment is None
    assert report.meta is not None
    assert report.meta.materialityStrategy == "complete_coverage"


def test_revision_never_tolerates_inapplicable_scored_topic() -> None:
    """范围外评分不是草稿：基本信息判定不适用后，该议题评分在任何路径都 fail-loud。

    回归——科技伦理改「否」后旧评分残留，编辑期容忍放行、
    生成一步才抛裸 ValueError 成 500。
    """
    import pytest

    from sustainability_desk.contract.models import (
        MaterialityAssessmentInput,
        MaterialityScoreInput,
        MaterialityThreshold,
    )
    from sustainability_desk.contract.topic_registry import (
        applicability_facts_from_values,
        applicable_scoring_topics,
    )

    state = _state()
    state.fields["has_technology_ethics_sensitive_activity"] = "否"
    applicable = applicable_scoring_topics(
        applicability_facts_from_values(field_values=state.fields), package=SSE_PACKAGE
    )
    assert all(topic.id != "technology_ethics" for topic in applicable)

    scores = [
        MaterialityScoreInput(
            assessmentTopicId=topic.id,
            financialScore=4.0,
            impactScore=4.0,
        )
        for topic in applicable
    ]
    scores.append(
        MaterialityScoreInput(
            assessmentTopicId="technology_ethics",
            financialScore=4.0,
            impactScore=4.0,
        )
    )
    state.assessmentInput = MaterialityAssessmentInput(
        reportingYear=2025,
        threshold=MaterialityThreshold(financial=4.0, impact=4.0),
        scores=scores,
    )

    # 容忍开关只覆盖「填不全」，不覆盖「多出不适用议题」。
    for tolerate in (False, True):
        with pytest.raises(ValueError, match="科技伦理"):
            build_report_revision(state, tolerate_incomplete_assessment=tolerate, package=SSE_PACKAGE)


def test_report_revision_projects_stored_paragraph() -> None:
    initial = build_report_revision(_state(), package=SSE_PACKAGE)
    paragraph = next(
        block
        for block in initial.iter_blocks()
        if block.type == "paragraph"
        and block.blockType in {"generative", "constrained"}
    )
    state = _state().model_copy(
        update={
            "generatedBlocks": {
                paragraph.id: StoredGeneratedBlock(
                    content=[Inline(kind="text", text="已生成正文。")],
                    state="ready",
                )
            }
        }
    )

    report = build_report_revision(state, package=SSE_PACKAGE)

    assert report.find_block(paragraph.id).content == [
        Inline(kind="text", text="已生成正文。")
    ]


def test_report_revision_drops_stored_header_rows_from_table_state() -> None:
    """状态快照自带的表头行不得进入投影——表头归模板拥有，状态只投影数据行。

    若状态里的 headerRow=true 行被原样拼在模板表头之后，会投影出双表头，
    Word 导出把两行都标记为跨页重复表头（回归：重要性表格表头重复）。
    """
    initial = build_report_revision(_state(), package=SSE_PACKAGE)
    table = next(
        block
        for block in initial.iter_blocks()
        if block.type == "table"
        and block.blockType in {"generative", "constrained"}
        and any(row.headerRow for row in block.table.children)
    )
    template_header_count = sum(
        1 for row in table.table.children if row.headerRow
    )
    first_col_key = table.table.colDefs[0].key
    state = _state().model_copy(
        update={
            "tableBlocks": {
                table.id: StoredTableBlock(
                    children=[
                        StoredTableRow(
                            headerRow=True,
                            children=[StoredTableCell(type="th", value="表头")],
                        ),
                        StoredTableRow(
                            children=[
                                StoredTableCell(
                                    colKey=first_col_key, value="数据行"
                                )
                            ],
                            state="ready",
                        ),
                    ],
                    state="ready",
                )
            }
        }
    )

    report = build_report_revision(state, package=SSE_PACKAGE)

    projected = report.find_block(table.id).table
    assert (
        sum(1 for row in projected.children if row.headerRow)
        == template_header_count
    )
    data_rows = [row for row in projected.children if not row.headerRow]
    assert len(data_rows) == 1
    assert data_rows[0].children[0].value == "数据行"


def test_report_revision_projects_explicit_table_omission() -> None:
    initial = build_report_revision(_state(), package=SSE_PACKAGE)
    table = next(
        block
        for block in initial.iter_blocks()
        if block.type == "table"
        and block.blockType in {"generative", "constrained"}
    )
    state = _state().model_copy(
        update={
            "tableBlocks": {
                table.id: StoredTableBlock(children=[], state="omitted")
            }
        }
    )

    report = build_report_revision(state, package=SSE_PACKAGE)

    assert report.find_block(table.id).state == "omitted"
