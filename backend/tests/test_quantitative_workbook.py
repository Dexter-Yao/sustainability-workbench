# ABOUTME: ESG 定量工作簿真实 xlsx 往返测试，证明 69 项目录、元数据与严格批量校验同源。
# ABOUTME: 解析失败必须返回全部 typed 单元格错误，不允许产生部分 metrics 结果。
from __future__ import annotations

from io import BytesIO
from uuid import UUID

import openpyxl
import pytest

from sustainability_desk.assets.quantitative_parser import parse_quantitative_workbook
from sustainability_desk.assets.quantitative_template import (
    GHG_STANDARD_CELL,
    GHG_STANDARD_OTHER_CELL,
    QUANTITATIVE_COLUMNS,
    QUANTITATIVE_HEADER_ROW,
    create_quantitative_template,
)
from sustainability_desk.contract.models import DisclosureProfile, Field, Report
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    StructuredInputWorkbookError,
)
from sustainability_desk.quantitative_metrics import (
    greenhouse_gas_accounting_standard_options,
    all_quantitative_metrics,
)
from knowledge_package_fixtures import SSE_PACKAGE

CONTEXT = StructuredInputContext(
    reportId=UUID("00000000-0000-0000-0000-000000000001"),
    contractVersion="cv-test",
    compiledSemanticsVersion="semantics-test",
)


def _report(*, consolidation_scope: str = "本公司及子公司") -> Report:
    values: dict[str, tuple[str, str | int]] = {
        "company_registered_name": ("string", "测试股份有限公司"),
        "reporting_year": ("year", 2025),
        "report_period_start": ("date", "2025-01-01"),
        "report_period_end": ("date", "2025-12-31"),
        "consolidation_scope": ("string", consolidation_scope),
    }
    return Report(knowledgePackageId=SSE_PACKAGE.id, 
        title="定量信息",
        sections=[],
        fields={
            key: Field(
                key=key,
                label=key,
                type=field_type,
                source="user_input",
                value=value,
            )
            for key, (field_type, value) in values.items()
        },
        disclosureProfile=DisclosureProfile(),
    )


def _filled_workbook(report: Report) -> bytes:
    workbook = openpyxl.load_workbook(
        BytesIO(create_quantitative_template(report, context=CONTEXT))
    )
    first = True
    for worksheet in workbook.worksheets:
        if worksheet.title not in {"经济+环境", "社会", "治理"}:
            continue
        for row in worksheet.iter_rows(
            min_row=QUANTITATIVE_HEADER_ROW + 1,
        ):
            if not row[0].value:
                continue
            if first:
                row[4].value = "12.5"
                first = False
            else:
                row[5].value = "not_collected"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_quantitative_template_has_exact_catalog_and_round_trips() -> None:
    report = _report()
    content = _filled_workbook(report)
    workbook = openpyxl.load_workbook(BytesIO(content), data_only=True)
    rows = [
        row
        for worksheet in workbook.worksheets
        if worksheet.title in {"经济+环境", "社会", "治理"}
        for row in worksheet.iter_rows(
            min_row=QUANTITATIVE_HEADER_ROW + 1,
            values_only=True,
        )
        if row[0]
    ]

    assert len(rows) == 149
    assert workbook["经济+环境"].column_dimensions["A"].hidden is True
    assert [(row[0], row[3]) for row in rows] == [
        (metric.key, metric.unit) for metric in all_quantitative_metrics(SSE_PACKAGE)
    ]
    parsed = parse_quantitative_workbook(
        content,
        report=report,
        context=CONTEXT,
    )
    assert len(parsed.metrics) == 149
    assert parsed.metrics["economic_environment_r02"].value == "12.5"
    assert parsed.metrics["economic_environment_r03"].noValueReason == "not_collected"
    assert parsed.greenhouseGasAccountingStandard is None


def test_quantitative_parser_accumulates_errors_without_partial_result() -> None:
    report = _report()
    workbook = openpyxl.load_workbook(BytesIO(_filled_workbook(report)))
    worksheet = workbook["经济+环境"]
    first = QUANTITATIVE_HEADER_ROW + 1
    worksheet.cell(first, 4, "错误单位")
    worksheet.cell(first, 3, "错误名称")
    worksheet.cell(first, 6, "not_collected")
    worksheet.cell(first + 1, 6, "unknown_reason")
    worksheet.cell(first + 2, 5, "1,000")
    worksheet.cell(first + 2, 6).value = None
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as captured:
        parse_quantitative_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )

    codes = {error.code for error in captured.value.errors}
    assert "quantitative_unit_mismatch" in codes
    assert "quantitative_metric_name_mismatch" in codes
    assert "quantitative_value_choice_invalid" in codes
    assert "quantitative_no_value_reason_invalid" in codes
    assert "quantitative_draft_invalid" in codes
    assert "quantitative_keys_missing" in codes


def test_quantitative_parser_rejects_stale_report_metadata() -> None:
    original = _report()
    content = _filled_workbook(original)

    with pytest.raises(StructuredInputWorkbookError) as captured:
        parse_quantitative_workbook(
            content,
            report=_report(consolidation_scope="仅母公司"),
            context=CONTEXT,
        )

    assert {
        error.code for error in captured.value.errors
    } == {"metadata_mismatch"}


def test_quantitative_parser_returns_complete_ghg_standard_meta() -> None:
    report = _report()
    workbook = openpyxl.load_workbook(BytesIO(_filled_workbook(report)))
    config = workbook["填写说明"]
    config[GHG_STANDARD_CELL] = greenhouse_gas_accounting_standard_options(SSE_PACKAGE)[0]
    worksheet = workbook["经济+环境"]
    ghg_row = next(
        row
        for row in worksheet.iter_rows(min_row=QUANTITATIVE_HEADER_ROW + 1)
        if row[0].value == "economic_environment_r04"
    )
    ghg_row[4].value = "120"
    ghg_row[5].value = None
    output = BytesIO()
    workbook.save(output)

    parsed = parse_quantitative_workbook(
        output.getvalue(),
        report=report,
        context=CONTEXT,
    )

    assert parsed.greenhouseGasAccountingStandard == greenhouse_gas_accounting_standard_options(SSE_PACKAGE)[0]
    assert parsed.greenhouseGasAccountingStandardOther is None
    assert parsed.metrics["economic_environment_r04"].value == "120"


def test_quantitative_parser_requires_standard_for_ghg_value() -> None:
    report = _report()
    workbook = openpyxl.load_workbook(BytesIO(_filled_workbook(report)))
    worksheet = workbook["经济+环境"]
    ghg_row = next(
        row
        for row in worksheet.iter_rows(min_row=QUANTITATIVE_HEADER_ROW + 1)
        if row[0].value == "economic_environment_r04"
    )
    ghg_row[4].value = "120"
    ghg_row[5].value = None
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as captured:
        parse_quantitative_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )

    assert "ghg_standard_required" in {
        error.code for error in captured.value.errors
    }


def test_quantitative_parser_requires_description_for_other_standard() -> None:
    report = _report()
    workbook = openpyxl.load_workbook(BytesIO(_filled_workbook(report)))
    config = workbook["填写说明"]
    config[GHG_STANDARD_CELL] = "其他"
    config[GHG_STANDARD_OTHER_CELL] = None
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as captured:
        parse_quantitative_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )

    assert "ghg_standard_other_required" in {
        error.code for error in captured.value.errors
    }


def test_template_standard_dropdown_aligned_with_labels() -> None:
    """下拉必须与标签同行（A8→B8、A9→B9），说明文案从无值原因 SSOT 派生。"""
    workbook = openpyxl.load_workbook(
        BytesIO(create_quantitative_template(_report(), context=CONTEXT))
    )
    config = workbook["填写说明"]
    assert config["A8"].value == "温室气体核算标准"
    assert config["A9"].value == "选择「其他」时请说明"
    (standard_validation,) = config.data_validations.dataValidation
    assert str(standard_validation.sqref) == GHG_STANDARD_CELL == "B8"
    assert GHG_STANDARD_OTHER_CELL == "B9"
    assert "其他" in standard_validation.formula1
    assert standard_validation.showInputMessage
    assert config[GHG_STANDARD_CELL].fill.patternType is not None
    assert config[GHG_STANDARD_OTHER_CELL].fill.patternType is not None
    assert "尚未收集" in str(config["A5"].value)


def test_quantitative_parser_standard_error_points_at_label_row() -> None:
    report = _report()
    workbook = openpyxl.load_workbook(BytesIO(_filled_workbook(report)))
    worksheet = workbook["经济+环境"]
    ghg_row = next(
        row
        for row in worksheet.iter_rows(min_row=QUANTITATIVE_HEADER_ROW + 1)
        if row[0].value == "economic_environment_r04"
    )
    ghg_row[4].value = "120"
    ghg_row[5].value = None
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(StructuredInputWorkbookError) as captured:
        parse_quantitative_workbook(
            output.getvalue(),
            report=report,
            context=CONTEXT,
        )

    (standard_error,) = [
        error
        for error in captured.value.errors
        if error.code == "ghg_standard_required"
    ]
    assert (standard_error.sheet, standard_error.row, standard_error.column) == (
        "填写说明",
        8,
        "B",
    )


def test_workbook_guidance_column_is_projected_from_the_same_catalog_text() -> None:
    """网页与 Excel 的指标说明必须逐字同源，杜绝两套手写文案再次漂移。

    历史缺陷：基础资料表在函数内自带私有 hints dict，与 report_contract.yaml 的
    helpText 对同一字段各写一份；评分表的维度释义则只存在于 React 组件里，
    下载的 xlsx 拿不到。此处把「同一事实只有一个文案来源」变成可执行控制。
    """

    workbook = openpyxl.load_workbook(
        BytesIO(create_quantitative_template(_report(), context=CONTEXT))
    )
    guidance_column = QUANTITATIVE_COLUMNS.index("指标说明") + 1
    key_column = QUANTITATIVE_COLUMNS.index("指标 key") + 1

    catalog = {metric.key: metric for metric in all_quantitative_metrics(SSE_PACKAGE)}
    checked = 0
    for sheet_name in workbook.sheetnames:
        worksheet = workbook[sheet_name]
        if worksheet.cell(QUANTITATIVE_HEADER_ROW, key_column).value != "指标 key":
            continue
        for row in range(QUANTITATIVE_HEADER_ROW + 1, worksheet.max_row + 1):
            key = worksheet.cell(row, key_column).value
            metric = catalog.get(str(key))
            if metric is None:
                continue
            cell_text = worksheet.cell(row, guidance_column).value or ""
            # 网页分两段呈现（常驻 + ⓘ），Excel 无折叠形态故拼接；两端同源于目录字段。
            assert metric.metricDefinition in cell_text, f"{key} 的常驻说明未投影进 Excel"
            if metric.termExplanation:
                assert metric.termExplanation in cell_text, f"{key} 的术语说明未投影进 Excel"
            checked += 1

    assert checked == len(catalog), f"仅核对到 {checked} 项，应覆盖全部 {len(catalog)} 项"
