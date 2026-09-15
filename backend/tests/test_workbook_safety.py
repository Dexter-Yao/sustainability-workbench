# ABOUTME: 结构化输入 xlsx 资源边界测试，在解析业务单元格前拒绝异常压缩与超限工作表。
# ABOUTME: 重要性和定量解析器共用同一安全模块，避免上传入口只按压缩后文件大小判断。
from __future__ import annotations

from io import BytesIO
import zipfile

from openpyxl import Workbook
import pytest

from sustainability_desk.assets.workbook_safety import (
    MAX_WORKSHEET_ROWS,
    validate_workbook_dimensions,
    validate_xlsx_container,
)
from fastapi import HTTPException
from sustainability_desk.api.structured_input_router import (
    MAX_STRUCTURED_INPUT_BYTES,
    _read_limited_xlsx,
)
from sustainability_desk.contract.structured_inputs import StructuredInputWorkbookError


def test_xlsx_container_rejects_abnormal_expansion_ratio() -> None:
    output = BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"a" * 2_000_000)

    with pytest.raises(
        StructuredInputWorkbookError,
        match="压缩比异常",
    ):
        validate_xlsx_container(output.getvalue())


def test_workbook_dimensions_reject_oversized_sheet() -> None:
    workbook = Workbook()
    workbook.active.cell(MAX_WORKSHEET_ROWS + 1, 1, "越界")

    with pytest.raises(
        StructuredInputWorkbookError,
        match="行数不得超过",
    ):
        validate_workbook_dimensions(workbook)


class _Upload:
    filename = "input.xlsx"

    def __init__(self, size: int) -> None:
        self.remaining = size
        self.requested_sizes: list[int] = []

    async def read(self, size: int) -> bytes:
        self.requested_sizes.append(size)
        amount = min(size, self.remaining)
        self.remaining -= amount
        return b"x" * amount


async def test_upload_is_read_in_bounded_chunks_and_stops_over_20mb() -> None:
    upload = _Upload(MAX_STRUCTURED_INPUT_BYTES + 1)

    with pytest.raises(HTTPException) as captured:
        await _read_limited_xlsx(upload)  # type: ignore[arg-type]

    assert captured.value.status_code == 413
    assert set(upload.requested_sizes) == {1024 * 1024}
