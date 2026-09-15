# ABOUTME: 用户资料进入系统前的文件边界校验与 Office ZIP 资源预检。
# ABOUTME: 扩展名、MIME、magic 和容器结构必须一致，解析器不得直接接触未预检的压缩包。
# ABOUTME(en): File boundary validation and Office ZIP resource pre-check before user material enters the system.
# ABOUTME(en): Extension, MIME, magic bytes and container structure must agree; parsers never touch an unvetted archive.
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from sustainability_desk.material.intake.models import (
    MAX_MATERIAL_FILENAME_LENGTH,
    MaterialKind,
    ValidatedMaterialFile,
)

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ZIP_ENTRIES = 5_000
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_RATIO = 100.0
MAX_PDF_PAGES = 40

_EXTENSION_KIND: dict[str, MaterialKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}
_MIME_TYPES: dict[MaterialKind, set[str]] = {
    "pdf": {"application/pdf", "application/octet-stream"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "application/zip",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "application/zip",
    },
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
        "application/zip",
    },
    "png": {"image/png", "application/octet-stream"},
    "jpeg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    "webp": {"image/webp", "application/octet-stream"},
}


class MaterialFileError(ValueError):
    """文件不满足资料边界。"""


class MaterialZipLimitError(MaterialFileError):
    """Office ZIP 容器超过安全资源上限。"""


_OFFICE_ZIP_REQUIRED_PART: dict[Literal["docx", "xlsx", "pptx"], str] = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}


def _validate_office_zip(
    data: bytes,
    kind: Literal["docx", "xlsx", "pptx"],
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_ratio: float,
) -> None:
    required = _OFFICE_ZIP_REQUIRED_PART[kind]
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise MaterialZipLimitError("Office 压缩包文件条目过多")
            total_compressed = sum(max(entry.compress_size, 1) for entry in entries)
            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > max_uncompressed_bytes:
                raise MaterialZipLimitError("Office 压缩包解压后体积过大")
            if total_uncompressed / max(total_compressed, 1) > max_ratio:
                raise MaterialZipLimitError("Office 压缩包压缩比异常")
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or required not in names:
                raise MaterialFileError("文件内容与扩展名不一致")
    except BadZipFile as error:
        raise MaterialFileError("Office 文件容器已损坏") from error


def _magic_matches(kind: MaterialKind, data: bytes) -> bool:
    if kind == "pdf":
        return data.startswith(b"%PDF-")
    if kind == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if kind == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return data.startswith(b"PK\x03\x04")


def validate_material_file(
    *,
    filename: str,
    content_type: str,
    data: bytes,
    max_bytes: int = MAX_FILE_BYTES,
    max_zip_entries: int = MAX_ZIP_ENTRIES,
    max_zip_uncompressed_bytes: int = MAX_ZIP_UNCOMPRESSED_BYTES,
    max_zip_ratio: float = MAX_ZIP_RATIO,
    max_pdf_pages: int = MAX_PDF_PAGES,
) -> ValidatedMaterialFile:
    """在写入 Storage 前验证用户文件并计算稳定去重指纹。"""
    safe_name = Path(filename).name.strip()
    if not safe_name or safe_name != filename.strip() or "\x00" in safe_name:
        raise MaterialFileError("文件名无效")
    if len(safe_name) > MAX_MATERIAL_FILENAME_LENGTH:
        raise MaterialFileError(
            f"文件名不得超过 {MAX_MATERIAL_FILENAME_LENGTH} 个字符"
        )
    suffix = Path(safe_name).suffix.lower()
    if suffix in {".doc", ".xls", ".ppt"}:
        replacement = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}[suffix]
        raise MaterialFileError(f"暂不支持 {suffix}，请先转换为 {replacement}")
    kind = _EXTENSION_KIND.get(suffix)
    if kind is None:
        raise MaterialFileError("仅支持 PDF、DOCX、XLSX、PPTX、PNG、JPEG、WebP")
    if not data:
        raise MaterialFileError("文件为空")
    if len(data) > max_bytes:
        raise MaterialFileError(f"单个文件不得超过 {max_bytes} 字节")
    normalized_mime = content_type.split(";", 1)[0].strip().lower()
    if normalized_mime not in _MIME_TYPES[kind]:
        raise MaterialFileError("文件 MIME 与扩展名不一致")
    if not _magic_matches(kind, data):
        raise MaterialFileError("文件内容与扩展名不一致")
    if kind in ("docx", "xlsx", "pptx"):
        _validate_office_zip(
            data,
            kind,
            max_entries=max_zip_entries,
            max_uncompressed_bytes=max_zip_uncompressed_bytes,
            max_ratio=max_zip_ratio,
        )
    pdf_page_count: int | None = None
    quality_flags: list[str] = []
    if kind == "pdf":
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise MaterialFileError("PDF 已加密，请先取消密码保护后重新上传")
            pdf_page_count = len(reader.pages)
        except MaterialFileError:
            raise
        except (PdfReadError, ValueError, TypeError) as error:
            raise MaterialFileError("PDF 文件结构无法解析") from error
        if pdf_page_count == 0:
            raise MaterialFileError("PDF 不包含可处理页面")
        if pdf_page_count > max_pdf_pages:
            raise MaterialFileError(f"PDF 不得超过 {max_pdf_pages} 页")
    return ValidatedMaterialFile(
        filename=safe_name,
        kind=kind,
        media_type=normalized_mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        pdf_page_count=pdf_page_count,
        quality_flags=quality_flags,
    )
