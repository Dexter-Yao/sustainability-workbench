# ABOUTME: 议题引导问题工作簿真实 xlsx 往返测试：装配范围投影、预填答案、多选行协议与严格批量校验。
# ABOUTME: 解析失败必须返回全部 typed 单元格错误；成功导入为模板范围内整批替换（允许空答案）。
from __future__ import annotations

from io import BytesIO
from uuid import UUID

import openpyxl
import pytest

from sustainability_desk.assets.topic_questions_parser import parse_topic_questions_workbook
from sustainability_desk.assets.topic_questions_template import (
    MULTI_SELECT_YES,
    OPTION_ROW_SUFFIX,
    create_topic_questions_template,
)
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import (
    StoredIntakeAnswer,
    StoredReportStateV4,
)
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    StructuredInputWorkbookError,
    topic_question_items,
)
from knowledge_package_fixtures import SSE_PACKAGE

CONTEXT = StructuredInputContext(
    reportId=UUID("00000000-0000-0000-0000-000000000001"),
    contractVersion="cv-test",
    compiledSemanticsVersion="semantics-test",
)


def _state(**intake: StoredIntakeAnswer) -> StoredReportStateV4:
    return StoredReportStateV4(
        version=4,
        fields={
            "company_registered_name": "测试股份有限公司",
            "industry_major_category": "制造业",
            "reporting_year": 2025,
        },
        intakeItems=dict(intake),
    )


def _report(state: StoredReportStateV4):
    return build_report_revision(state, tolerate_incomplete_assessment=True, package=SSE_PACKAGE)


def _sheet_rows(workbook, sheet_name: str):
    return list(workbook[sheet_name].iter_rows(values_only=True))


def test_template_projects_topic_questions_with_prefilled_answers() -> None:
    state = _state(**{
        "climate.q_governance_policies": StoredIntakeAnswer(
            answer="有相关制度、流程或管理要求",
            supplement="《碳排放管理办法》适用于全部生产基地。",
        ),
        "climate.q_climate_risk_choices": StoredIntakeAnswer(answer=["台风", "暴雨"]),
    })
    report = _report(state)
    items = topic_question_items(report)
    assert items, "装配后的 Report 必须携带议题引导问题"

    content = create_topic_questions_template(report, context=CONTEXT)
    workbook = openpyxl.load_workbook(BytesIO(content))

    assert "应对气候变化" in workbook.sheetnames
    assert workbook["应对气候变化"].column_dimensions["A"].hidden is True

    rows = _sheet_rows(workbook, "应对气候变化")
    by_key = {row[0]: row for row in rows if row[0]}
    policy_row = by_key["climate.q_governance_policies"]
    assert policy_row[4] == "有相关制度、流程或管理要求"
    assert policy_row[5] == "《碳排放管理办法》适用于全部生产基地。"

    # 多选题主行不承载答案；选项行按当前答案预填 是。
    risk_row = by_key["climate.q_climate_risk_choices"]
    assert risk_row[4] is None
    option_rows = [
        row
        for row in rows
        if row[0] == f"climate.q_climate_risk_choices{OPTION_ROW_SUFFIX}"
    ]
    selected = {row[3] for row in option_rows if row[4] == MULTI_SELECT_YES}
    assert selected == {"台风", "暴雨"}

    # 全部议题范围内的题目主行都必须出现在工作簿中。
    all_keys = {
        row[0]
        for sheet in workbook.sheetnames
        if sheet not in {"填写说明", "_模板元数据"}
        for row in _sheet_rows(workbook, sheet)
        if row[0] and "#" not in str(row[0]) and row[0] != "键"
    }
    assert all_keys == {item.key for item in items}


def test_workbook_round_trip_replaces_answers_in_batch() -> None:
    state = _state(**{
        "climate.q_governance_policies": StoredIntakeAnswer(answer="不确定"),
    })
    report = _report(state)
    content = create_topic_questions_template(report, context=CONTEXT)

    workbook = openpyxl.load_workbook(BytesIO(content))
    worksheet = workbook["应对气候变化"]
    for row in worksheet.iter_rows():
        key = row[0].value
        if key == "climate.q_governance_policies":
            row[4].value = "有相关制度、流程或管理要求"
            row[5].value = "已建立双碳管理制度。"
        if key == "climate.q_strategy_content":
            row[4].value = "制定了 2030 碳达峰行动计划，分年度推进节能改造。"
        if key == f"climate.q_climate_risk_choices{OPTION_ROW_SUFFIX}" and row[3].value == "极端高温":
            row[4].value = MULTI_SELECT_YES
    output = BytesIO()
    workbook.save(output)

    answers = parse_topic_questions_workbook(
        output.getvalue(),
        report=report,
        context=CONTEXT,
    )
    assert answers["climate.q_governance_policies"].answer == "有相关制度、流程或管理要求"
    assert answers["climate.q_governance_policies"].supplement == "已建立双碳管理制度。"
    assert answers["climate.q_strategy_content"].answer == "制定了 2030 碳达峰行动计划，分年度推进节能改造。"
    assert answers["climate.q_climate_risk_choices"].answer == ["极端高温"]
    # 空答案的键不出现：整批替换后未回答的问题回到无答案状态。
    assert "climate.q_governance_certifications" not in answers


def test_workbook_rejects_invalid_answers_with_cell_errors() -> None:
    state = _state()
    report = _report(state)
    content = create_topic_questions_template(report, context=CONTEXT)

    workbook = openpyxl.load_workbook(BytesIO(content))
    worksheet = workbook["应对气候变化"]
    for row in worksheet.iter_rows():
        key = row[0].value
        if key == "climate.q_governance_policies":
            row[4].value = "自造选项"
        if key == f"climate.q_climate_risk_choices{OPTION_ROW_SUFFIX}" and row[3].value == "台风":
            row[3].value = "被改写的选项"
        if key == "climate.q_strategy_content":
            row[4].value = "超" * 3001
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as excinfo:
        parse_topic_questions_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )
    codes = {error.code for error in excinfo.value.errors}
    assert "topic_question_answer_invalid" in codes
    assert "topic_question_option_unknown" in codes
    assert "topic_question_answer_too_long" in codes


def test_workbook_rejects_missing_question_rows() -> None:
    state = _state()
    report = _report(state)
    content = create_topic_questions_template(report, context=CONTEXT)

    workbook = openpyxl.load_workbook(BytesIO(content))
    worksheet = workbook["应对气候变化"]
    for row in worksheet.iter_rows():
        if row[0].value == "climate.q_governance_policies":
            row[0].value = "climate.q_not_a_question"
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as excinfo:
        parse_topic_questions_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )
    codes = {error.code for error in excinfo.value.errors}
    assert "topic_question_key_unknown" in codes
    assert "topic_question_key_missing" in codes


def test_trial_scope_only_projects_climate_sheet() -> None:
    state = _state()
    report = _report(state)
    content = create_topic_questions_template(
        report,
        context=CONTEXT,
        allowed_report_section_ids=frozenset({"climate_change"}),
    )
    workbook = openpyxl.load_workbook(BytesIO(content))
    business_sheets = [
        sheet
        for sheet in workbook.sheetnames
        if sheet not in {"填写说明", "_模板元数据"}
    ]
    assert business_sheets == ["应对气候变化"]

    # 全范围工作簿不得用受限范围解析（题目集合不同 → 指纹不一致）。
    with pytest.raises(StructuredInputWorkbookError) as excinfo:
        parse_topic_questions_workbook(
            content,
            report=report,
            context=CONTEXT,
        )
    assert any(error.code == "metadata_mismatch" for error in excinfo.value.errors)
