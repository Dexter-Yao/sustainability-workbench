# ABOUTME: 议题引导问题工作簿生成器，按装配后 Report 的议题范围每议题一张工作表投影全部引导问题。
# ABOUTME: 模板预填当前答案（下载即状态快照，导入为整批替换）；隐藏键列承载题目/选项行对齐协议。
# ABOUTME(en): Topic guidance question workbook generator, one sheet per topic in the assembled Report's topic scope.
# ABOUTME(en): Prefilled with current answers (download is a state snapshot); the hidden key column aligns rows.
from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from sustainability_desk.contract.product_name import workbook_sheet_title
from sustainability_desk.contract.models import IntakeItem, Report
from sustainability_desk.contract.structured_inputs import (
    StructuredInputContext,
    append_metadata_sheet,
    context_metadata_values,
    topic_question_items,
    topic_questions_context_fingerprint,
)
from sustainability_desk.contract.knowledge_packages import knowledge_package_of
from sustainability_desk.contract.topic_registry import load_topic_contract

_BACKEND = Path(__file__).resolve().parents[3]
_ROOT = _BACKEND.parent

TOPIC_QUESTIONS_HEADER_ROW = 7
TOPIC_QUESTIONS_COLUMNS: tuple[str, ...] = (
    "键",
    "填写问题",
    "填写要求",
    "填写格式 / 可选值",
    "填写内容",
    "补充说明",
    "填写提示",
)
# 隐藏键列的行协议：题目主行=key；多选选项行=key#option；分组标签行=key#group。
OPTION_ROW_SUFFIX = "#option"
GROUP_ROW_SUFFIX = "#group"
MULTI_SELECT_YES = "是"
MULTI_SELECT_NO = "否"

_PINE = "2C6E49"
_PINE_SUBTLE = "E7F0E9"
_SURFACE = "F6F7F5"
_BORDER = "E2E6E1"
_MUTED = "677069"
_FOREGROUND = "19211D"



def _format_label(item: IntakeItem) -> str:
    if item.kind == "single_select":
        return "单选：在「填写内容」下拉选择"
    if item.kind == "multi_select":
        return "多选：逐个选项行选择 是 / 否"
    limits: list[str] = []
    if item.minChars:
        limits.append(f"至少 {item.minChars} 字")
    if item.maxChars:
        limits.append(f"最多 {item.maxChars} 字")
    return f"长文本（{'，'.join(limits)}）" if limits else "长文本"


def _requirement_label(item: IntakeItem, *, climate_core_required: bool) -> str:
    if climate_core_required and item.requiredBefore == "generation":
        return "生成前必答"
    return "选填"


def _selected_options(item: IntakeItem) -> set[str]:
    if isinstance(item.answer, list):
        return set(item.answer)
    return set()


def create_topic_questions_template(
    report: Report,
    *,
    context: StructuredInputContext,
    allowed_report_section_ids: frozenset[str] | None = None,
    climate_core_required: bool = False,
) -> bytes:
    """按装配后 Report 的议题范围生成引导问题工作簿；不得维护静态题目副本。"""

    fingerprint = topic_questions_context_fingerprint(
        report,
        context,
        allowed_report_section_ids=allowed_report_section_ids,
    )
    workbook = Workbook()
    workbook.remove(workbook.active)
    _add_instructions(workbook)
    append_topic_questions_sheets(
        workbook,
        report,
        allowed_report_section_ids=allowed_report_section_ids,
        climate_core_required=climate_core_required,
    )
    append_metadata_sheet(
        workbook,
        context_metadata_values(
            input_kind="topic_questions",
            context=context,
            context_fingerprint=fingerprint,
        ),
    )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def append_topic_questions_sheets(
    workbook: Workbook,
    report: Report,
    *,
    allowed_report_section_ids: frozenset[str] | None = None,
    climate_core_required: bool = False,
) -> None:
    """向工作簿追加各议题引导问题工作表；说明页与元数据页由调用方写入。"""

    items = topic_question_items(
        report,
        allowed_report_section_ids=allowed_report_section_ids,
    )
    sections_by_id = load_topic_contract(knowledge_package_of(report)).reportSectionsById
    items_by_section: dict[str, list[IntakeItem]] = {}
    for item in items:
        items_by_section.setdefault(item.contentScopeId, []).append(item)

    thin_border = Border(
        top=Side(style="thin", color=_BORDER),
        bottom=Side(style="thin", color=_BORDER),
    )
    for section_id in sections_by_id:
        section_items = items_by_section.get(section_id)
        if not section_items:
            continue
        title = sections_by_id[section_id].title
        worksheet = workbook.create_sheet(title[:31])
        worksheet.sheet_view.showGridLines = False
        worksheet.sheet_properties.tabColor = _PINE
        worksheet.freeze_panes = f"A{TOPIC_QUESTIONS_HEADER_ROW + 1}"
        worksheet.column_dimensions["A"].width = 40
        worksheet.column_dimensions["A"].hidden = True
        worksheet.column_dimensions["B"].width = 44
        worksheet.column_dimensions["C"].width = 12
        worksheet.column_dimensions["D"].width = 34
        worksheet.column_dimensions["E"].width = 40
        worksheet.column_dimensions["F"].width = 40
        worksheet.column_dimensions["G"].width = 46

        worksheet.row_dimensions[1].height = 48

        # A 列是隐藏键协议列，除表头与键值外不得写入任何文本，否则解析器会误读为题目键。
        worksheet.merge_cells("B3:G3")
        title_cell = worksheet.cell(3, 2, f"{title} — 议题信息填写")
        title_cell.font = Font(name="Microsoft YaHei", size=12, bold=True, color=_FOREGROUND)
        worksheet.row_dimensions[3].height = 26
        worksheet.merge_cells("B4:G4")
        hint_cell = worksheet.cell(
            4,
            2,
            "请填写与本议题相关的管理与实践信息；全部问题选填，回答越充分报告越具体。",
        )
        hint_cell.font = Font(name="Microsoft YaHei", size=10, color=_MUTED)

        for column, label in enumerate(TOPIC_QUESTIONS_COLUMNS, start=1):
            cell = worksheet.cell(TOPIC_QUESTIONS_HEADER_ROW, column, label)
            cell.font = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=_PINE)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = Border(
                top=Side(style="medium", color=_PINE),
                bottom=Side(style="medium", color=_PINE),
            )

        yes_no_validation = DataValidation(
            type="list",
            formula1=f'"{MULTI_SELECT_YES},{MULTI_SELECT_NO}"',
            allow_blank=True,
        )
        yes_no_validation.error = "多选选项行只能选择 是 或 否"
        yes_no_validation.errorTitle = "选项值不合法"
        yes_no_validation.showErrorMessage = True
        worksheet.add_data_validation(yes_no_validation)

        row_number = TOPIC_QUESTIONS_HEADER_ROW
        for item in section_items:
            row_number += 1
            answer_text = item.answer if isinstance(item.answer, str) else None
            main_row = (
                item.key,
                item.prompt,
                _requirement_label(item, climate_core_required=climate_core_required),
                _format_label(item),
                answer_text if item.kind != "multi_select" else None,
                item.supplement,
                item.hint,
            )
            for column, value in enumerate(main_row, start=1):
                cell = worksheet.cell(row_number, column, value)
                cell.font = Font(
                    name="Microsoft YaHei",
                    size=10,
                    bold=column == 2,
                )
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=column in {2, 4, 5, 6, 7},
                )
                cell.border = thin_border
                if column in {5, 6}:
                    cell.fill = PatternFill(
                        "solid",
                        fgColor=(
                            _SURFACE
                            if item.kind == "multi_select" and column == 5
                            else _PINE_SUBTLE
                        ),
                    )
            if item.kind == "single_select" and item.options:
                joined = ",".join(item.options)
                # Excel list 校验公式上限 255 字符；超限时退化为提示文本，交由导入侧校验。
                if len(joined) + 2 <= 255:
                    select_validation = DataValidation(
                        type="list",
                        formula1=f'"{joined}"',
                        allow_blank=True,
                    )
                    select_validation.error = "请选择模板提供的选项"
                    select_validation.errorTitle = "选项不合法"
                    select_validation.showErrorMessage = True
                    worksheet.add_data_validation(select_validation)
                    select_validation.add(f"E{row_number}")
                worksheet.cell(row_number, 4, f"单选：{' / '.join(item.options)}")
            if item.kind == "multi_select" and item.options:
                selected = _selected_options(item)
                groups = item.optionGroups or []
                grouped_options = {
                    option for group in groups for option in group.options
                }
                plan: list[tuple[str, str | None, str]] = []
                for group in groups:
                    constraint = (
                        f"（至少选择 {group.minSelections} 项）"
                        if group.minSelections
                        else ""
                    )
                    plan.append(("group", None, f"—— {group.label}{constraint}"))
                    plan.extend(("option", option, option) for option in group.options)
                plan.extend(
                    ("option", option, option)
                    for option in item.options
                    if option not in grouped_options
                )
                for row_kind, option, display in plan:
                    row_number += 1
                    if row_kind == "group":
                        key_cell = worksheet.cell(
                            row_number, 1, f"{item.key}{GROUP_ROW_SUFFIX}"
                        )
                        label_cell = worksheet.cell(row_number, 4, display)
                        label_cell.font = Font(
                            name="Microsoft YaHei", size=10, bold=True, color=_MUTED
                        )
                    else:
                        key_cell = worksheet.cell(
                            row_number, 1, f"{item.key}{OPTION_ROW_SUFFIX}"
                        )
                        option_cell = worksheet.cell(row_number, 4, display)
                        option_cell.font = Font(name="Microsoft YaHei", size=10)
                        option_cell.alignment = Alignment(vertical="top", wrap_text=True)
                        value_cell = worksheet.cell(
                            row_number,
                            5,
                            MULTI_SELECT_YES if option in selected else None,
                        )
                        value_cell.font = Font(name="Microsoft YaHei", size=10)
                        value_cell.fill = PatternFill("solid", fgColor=_PINE_SUBTLE)
                        value_cell.alignment = Alignment(vertical="top")
                        yes_no_validation.add(f"E{row_number}")
                    key_cell.font = Font(name="Microsoft YaHei", size=9, color=_MUTED)
                    for column in range(1, 8):
                        worksheet.cell(row_number, column).border = thin_border


def _add_instructions(workbook: Workbook) -> None:
    worksheet = workbook.create_sheet("填写说明")
    worksheet.sheet_view.showGridLines = False
    worksheet.column_dimensions["A"].width = 110

    worksheet.row_dimensions[1].height = 54

    worksheet["A3"] = workbook_sheet_title("议题信息填写表")
    worksheet["A3"].font = Font(name="Microsoft YaHei", size=16, bold=True, color=_PINE)
    worksheet.row_dimensions[3].height = 30

    instructions = (
        "每个议题一张工作表；只需填写「填写内容」与「补充说明」两列，其余列为只读说明，请勿修改。",
        "单选题在「填写内容」下拉选择；多选题在其下方的每个选项行选择 是 / 否。",
        "全部问题均为选填：留空的议题按无资料方式生成；回答越充分，报告内容越具体。",
        "导入时整簿替换当前答案：请先下载最新模板（已预填现有回答），修改后再导入。",
    )
    for row_offset, line in enumerate(instructions):
        row_number = 4 + row_offset
        cell = worksheet.cell(row_number, 1, line)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(name="Microsoft YaHei", size=10, color=_MUTED)
        worksheet.row_dimensions[row_number].height = 26
