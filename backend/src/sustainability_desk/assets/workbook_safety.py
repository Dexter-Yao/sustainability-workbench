# ABOUTME: xlsx 容器与工作表资源上限，在 openpyxl 展开前拒绝 zip bomb 和异常大表。
# ABOUTME: 重要性与定量导入共用同一组限制，避免各解析器维护平行安全语义。
# ABOUTME(en): xlsx container and worksheet resource limits, rejecting zip bombs and oversized sheets before openpyxl.
# ABOUTME(en): Materiality and quantitative imports share these limits; parsers never keep parallel safety semantics.
from __future__ import annotations

import io
import zipfile

from sustainability_desk.contract.structured_inputs import (
    StructuredInputCellError,
    StructuredInputWorkbookError,
)

MAX_XLSX_ENTRIES = 256
MAX_XLSX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 200
# 合法业务最大形态是统一工作簿：填写说明 + 基础资料 + 评分 + 3 张定量 + 22 张议题
# + 隐藏元数据 ≈ 29 张；行列上限仍逐表生效，40 只是防跑飞的容器闸。
MAX_WORKBOOK_SHEETS = 40
MAX_WORKSHEET_ROWS = 5_000
MAX_WORKSHEET_COLUMNS = 64


def _error(code: str, message: str) -> StructuredInputWorkbookError:
    return StructuredInputWorkbookError(
        [
            StructuredInputCellError(
                code=code,
                sheet="工作簿",
                row=1,
                column="A",
                message=message,
            )
        ]
    )


def validate_xlsx_container(content: bytes) -> None:
    """在任何 XML 展开前检查 zip 条目、总展开体积、压缩比与加密标记。"""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        raise _error("workbook_container_invalid", "文件不是有效的 xlsx 容器") from error
    if len(entries) > MAX_XLSX_ENTRIES:
        raise _error(
            "workbook_entry_limit_exceeded",
            f"xlsx 内部条目不得超过 {MAX_XLSX_ENTRIES} 个",
        )
    total = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise _error("workbook_encrypted", "不接受加密 xlsx 文件")
        total += entry.file_size
        if total > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise _error(
                "workbook_expansion_limit_exceeded",
                "xlsx 展开后内容不得超过 100MB",
            )
        if (
            entry.file_size > 1_000_000
            and entry.file_size
            > max(entry.compress_size, 1) * MAX_XLSX_COMPRESSION_RATIO
        ):
            raise _error(
                "workbook_compression_ratio_exceeded",
                "xlsx 内部压缩比异常",
            )


def validate_workbook_dimensions(workbook) -> None:
    """在业务遍历前限制 sheet、行与列规模。"""

    if len(workbook.worksheets) > MAX_WORKBOOK_SHEETS:
        raise _error(
            "workbook_sheet_limit_exceeded",
            f"工作表不得超过 {MAX_WORKBOOK_SHEETS} 张",
        )
    errors: list[StructuredInputCellError] = []
    for worksheet in workbook.worksheets:
        if worksheet.max_row > MAX_WORKSHEET_ROWS:
            errors.append(
                StructuredInputCellError(
                    code="worksheet_row_limit_exceeded",
                    sheet=worksheet.title,
                    row=MAX_WORKSHEET_ROWS + 1,
                    column="A",
                    message=f"工作表行数不得超过 {MAX_WORKSHEET_ROWS}",
                )
            )
        if worksheet.max_column > MAX_WORKSHEET_COLUMNS:
            errors.append(
                StructuredInputCellError(
                    code="worksheet_column_limit_exceeded",
                    sheet=worksheet.title,
                    row=1,
                    column="A",
                    message=f"工作表列数不得超过 {MAX_WORKSHEET_COLUMNS}",
                )
            )
    if errors:
        raise StructuredInputWorkbookError(errors)
