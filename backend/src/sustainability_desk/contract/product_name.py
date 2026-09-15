# ABOUTME: 用户可见交付物命名的唯一出口（工作簿文件名、下载响应头、工作簿标题行）。
# ABOUTME(en): Single source for user-facing artefact naming; the technical identifier
# ABOUTME(en): `sustainability_desk` is brand-neutral and independent of any product name.
from __future__ import annotations

from urllib.parse import quote

#: 工作簿命名当前不带产品名前缀——品牌尚未定名，而带前缀的历史命名会在定名时留下
#: 一批需要同步改动的用户可见字面量。定名后若要加前缀，只改本模块三个函数即可。
#: 技术标识（Python 包名、``SUSTAINABILITY_DESK_`` 环境变量前缀、``sustainability_desk.*.vN``
#: 契约串）刻意与品牌无关，任何情况下都不从产品名派生。


def workbook_download_filename(document_label: str) -> str:
    """用户下载的工作簿文件名，例如 ``重要性评分表.xlsx``。"""

    return f"{document_label}.xlsx"


def workbook_content_disposition(document_label: str, ascii_slug: str) -> str:
    """工作簿下载的 Content-Disposition 值。

    RFC 6266 两段式：``filename`` 承载 ASCII 回退（老客户端），``filename*`` 承载 UTF-8 真名。
    两段都从同一出口派生，避免改名时只改中文名、ASCII 回退留着旧值。
    """

    return (
        f"attachment; filename={ascii_slug}.xlsx; "
        f"filename*=UTF-8''{quote(workbook_download_filename(document_label))}"
    )


def workbook_sheet_title(document_label: str) -> str:
    """工作簿首行标题；用户打开表格即看到。"""

    return document_label
