# ABOUTME: Word 自动目录的唯一层级合同，并在最终正文排版后固化目录页码。
# ABOUTME: 目录仅展示报告模块与议题；页码只能由真实版式引擎计算，不能由渲染器猜测。
# ABOUTME(en): Sole level contract of the Word automatic table of contents, and freezes its page numbers after layout.
# ABOUTME(en): The TOC lists report modules and topics only; page numbers come from a real layout engine, never guessed.
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader
from xml.etree import ElementTree as ET

from sustainability_desk.observability.registry import Stage, register_stage
from sustainability_desk.observability.stages import current_stage, open_stage
from sustainability_desk.export.format_profile import WordFormatProfile

# LibreOffice 子进程超时。阶段声明从本常量派生，数值只在此维护一份。
TOC_RENDER_TIMEOUT_SECONDS = 120

# TOC 定稿是 render_final_docx 尾部的**无条件**调用，因此 LibreOffice 是导出的运行时硬依赖。
# span 经同任务 ContextVar 嵌套进 delivery.docx.word，不透传句柄污染渲染器签名；
# 单元测试直调本函数时无环境 span，不开 span，失败仍由具名异常 fail-loud。
TOC_FINALIZE_STAGE = register_stage(
    Stage(
        id="delivery.toc.finalize",
        kind="external_process",
        external_dependency="libreoffice",
        timeout_seconds=TOC_RENDER_TIMEOUT_SECONDS,
    )
)

TOC_MAX_HEADING_LEVEL = 2
TOC_OUTLINE_SWITCH = f'TOC \\o "1-{TOC_MAX_HEADING_LEVEL}"'
TOC_FIELD_INSTRUCTION = f" {TOC_OUTLINE_SWITCH} \\h \\z \\u "
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD = f"{{{_WORD_NAMESPACE}}}"


def _body_page_one_pattern(profile: WordFormatProfile) -> re.Pattern[str]:
    """The printed page-number line of body page 1, from the profile's page-number wording."""

    labels = profile.labels
    return re.compile(
        re.escape(labels.page_number_prefix.strip())
        + r"\s*1\s*"
        + re.escape(labels.page_number_suffix.strip())
    )


def toc_includes_heading_level(level: int) -> bool:
    """返回指定 Word Heading 层级是否属于对外目录。"""

    return 1 <= level <= TOC_MAX_HEADING_LEVEL


def page_layout_renderer() -> str | None:
    """可用的版式引擎路径；没装 LibreOffice 时返回 None。

    LibreOffice 只用于**预先算好**目录页码。没有它时交付物仍然有目录：
    每条目录项是指向同文档书签的 ``PAGEREF`` 域并带 ``dirty`` 标记，Word 与
    LibreOffice 打开时会自行解析出页码（实测与预计算结果逐条一致）。差别只在
    「页码是打开前就在那里，还是打开那一刻算出来」——把整套办公套件列为硬依赖
    来买这点确定性，对自用场景不划算。
    """

    return shutil.which("soffice") or shutil.which("libreoffice")


class TocFinalizationError(RuntimeError):
    """最终 DOCX 无法以真实版式更新目录页码。"""


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{_WORD}t")).strip()


def _searchable_text(value: str) -> str:
    """统一 PDF 抽取在中英文混排标题间插入的空白，不改变标题的真实文本。"""

    return re.sub(r"\s+", "", value)


def _toc_entries(document_xml: bytes) -> list[tuple[str, str]]:
    """读取目录条目与正文书签，避免把 Word 域缓存当作报告事实。"""

    root = ET.fromstring(document_xml)
    bookmark_titles: dict[str, str] = {}
    for paragraph in root.iter(f"{_WORD}p"):
        bookmarks = [
            node.get(f"{_WORD}name", "")
            for node in paragraph.findall(f"{_WORD}bookmarkStart")
        ]
        title = _paragraph_text(paragraph)
        for bookmark in bookmarks:
            if bookmark.startswith("GS_TOC_") and title:
                bookmark_titles[bookmark] = title

    entries: list[tuple[str, str]] = []
    for paragraph in root.iter(f"{_WORD}p"):
        instruction = "".join(
            node.text or "" for node in paragraph.iter(f"{_WORD}instrText")
        )
        match = re.search(r"\bPAGEREF\s+(GS_TOC_\d+)", instruction)
        if match is None:
            continue
        bookmark = match.group(1)
        try:
            entries.append((bookmark, bookmark_titles[bookmark]))
        except KeyError as error:
            raise TocFinalizationError(f"目录书签缺少正文标题：{bookmark}") from error
    if not entries:
        raise TocFinalizationError("最终 DOCX 缺少可更新的目录条目。")
    return entries


def _rendered_toc_page_numbers(
    pdf_path: Path, entries: list[tuple[str, str]], *, body_page_one: re.Pattern[str]
) -> dict[str, int]:
    """从真实版式 PDF 的正文页提取每个目录标题所在页，而不是由渲染器猜测页码。"""

    pages = [page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages]
    body_start = next(
        (index for index, page in enumerate(pages) if body_page_one.search(page)),
        None,
    )
    if body_start is None:
        raise TocFinalizationError("真实版式输出中未找到正文第 1 页。")

    page_numbers: dict[str, int] = {}
    search_from = body_start
    for bookmark, title in entries:
        searchable_title = _searchable_text(title)
        match_index = next(
            (
                index
                for index in range(search_from, len(pages))
                if searchable_title in _searchable_text(pages[index])
            ),
            None,
        )
        if match_index is None:
            raise TocFinalizationError(f"真实版式输出中未找到目录标题：{title}")
        page_numbers[bookmark] = match_index - body_start + 1
        search_from = match_index
    return page_numbers


_WORD_PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
_PAGEREF_BOOKMARK = re.compile(
    r"<w:instrText\b[^>]*>[^<]*\bPAGEREF\s+(GS_TOC_\d+)[^<]*</w:instrText>"
)
_PAGEREF_RESULT = re.compile(
    r"(?P<prefix>"
    r"<w:fldChar\b[^>]*\bw:fldCharType=\"separate\"[^>]*/>"
    r"\s*</w:r>\s*<w:r(?:\s[^>]*)?>\s*<w:t(?:\s[^>]*)?>"
    r")"
    r"[^<]*"
    r"(?P<suffix></w:t>)",
    re.DOTALL,
)
_DIRTY_PAGEREF_BEGIN = re.compile(
    r'(<w:fldChar\b(?=[^>]*\bw:fldCharType="begin")'
    r'(?=[^>]*\bw:dirty="true")[^>]*?)\s+w:dirty="true"'
)
_UPDATE_FIELDS = re.compile(r"<w:updateFields\b[^>]*/>")


def _replace_toc_page_caches(document_xml: bytes, page_numbers: dict[str, int]) -> bytes:
    """只替换 PAGEREF 的展示缓存，不重序列化 ``document.xml``。

    ``xml.etree`` 写回完整 WordprocessingML 时会把 ``w``、``w14`` 等前缀
    改为自动生成的名称，却保留 ``mc:Ignorable`` 的旧前缀文本。Word 因而会
    修复文档并丢失目录锚点。这里逐段落做原始 XML 的受限替换，保留模板的
    命名空间声明、兼容性标记、书签与节属性字节结构。
    """

    source = document_xml.decode("utf-8")
    updated: set[str] = set()

    def replace_paragraph(match: re.Match[str]) -> str:
        paragraph = match.group(0)
        reference = _PAGEREF_BOOKMARK.search(paragraph)
        if reference is None:
            return paragraph
        bookmark = reference.group(1)
        if bookmark not in page_numbers:
            return paragraph

        def replace_result(result: re.Match[str]) -> str:
            updated.add(bookmark)
            return f"{result.group('prefix')}{page_numbers[bookmark]}{result.group('suffix')}"

        rewritten, count = _PAGEREF_RESULT.subn(replace_result, paragraph, count=1)
        if count != 1:
            raise TocFinalizationError(f"目录页码缓存无法写回：{bookmark}")
        return rewritten

    rewritten = _WORD_PARAGRAPH.sub(replace_paragraph, source)
    missing = set(page_numbers) - updated
    if missing:
        raise TocFinalizationError(f"目录页码缓存无法写回：{sorted(missing)}")
    return rewritten.encode("utf-8")


def _freeze_toc_page_references(document_xml: bytes) -> bytes:
    """清除目录 ``PAGEREF`` 的脏标记，保留已写入的页码缓存。

    仅对含 ``PAGEREF GS_TOC_*`` 的段落操作，正文页脚的 ``PAGE`` 域继续
    由 Word 正常维护。使用受限文本替换可避免 XML serializer 改写兼容前缀。
    """

    source = document_xml.decode("utf-8")

    def freeze_paragraph(match: re.Match[str]) -> str:
        paragraph = match.group(0)
        if _PAGEREF_BOOKMARK.search(paragraph) is None:
            return paragraph
        return _DIRTY_PAGEREF_BEGIN.sub(r"\1", paragraph)

    return _WORD_PARAGRAPH.sub(freeze_paragraph, source).encode("utf-8")


def _disable_open_field_updates(settings_xml: bytes) -> bytes:
    """移除打开文档时更新全部字段的设置，避免 Word 弹出外部域提示。"""

    return _UPDATE_FIELDS.sub("", settings_xml.decode("utf-8")).encode("utf-8")


def _rewrite_docx_parts(document_path: Path, replacements: dict[str, bytes]) -> None:
    """原子替换指定 DOCX part，不让 LibreOffice 重写节边界。"""

    replacement = document_path.with_suffix(".toc-updated.docx")
    try:
        with ZipFile(document_path) as source, ZipFile(
            replacement,
            "w",
            compression=ZIP_DEFLATED,
        ) as target:
            for entry in source.infolist():
                payload = replacements.get(entry.filename, source.read(entry.filename))
                target.writestr(entry, payload)
        os.replace(replacement, document_path)
    finally:
        replacement.unlink(missing_ok=True)


def finalize_toc_page_numbers(
    document_path: Path,
    *,
    profile: WordFormatProfile,
    renderer: str | None = None,
) -> Path:
    """以 LibreOffice 的 PDF 版式结果固化正文分页后的目录页码。

    ``PAGEREF`` 的页码依赖字体、纸张、分页与表格布局；python-docx 只能写域，
    无法计算这些值。LibreOffice 直接另存 DOCX 会在含前置节的报告中改写正文
    边界，因此这里只让它导出真实 PDF，再回写已有 Word 域的展示缓存，并冻结
    目录字段，禁止 Word 在客户打开文档时重新计算。
    """
    parent = current_stage()
    if parent is None:
        return _finalize_toc_page_numbers(document_path, profile=profile, renderer=renderer)
    with open_stage(
        TOC_FINALIZE_STAGE,
        trace_id=parent.trace_id,
        report_id=parent.report_id,
        scope=parent.scope,
    ):
        return _finalize_toc_page_numbers(document_path, profile=profile, renderer=renderer)


def _finalize_toc_page_numbers(
    document_path: Path,
    *,
    profile: WordFormatProfile,
    renderer: str | None = None,
) -> Path:
    if not document_path.is_file():
        raise TocFinalizationError(f"最终 DOCX 不存在，无法更新目录：{document_path}")
    executable = renderer or page_layout_renderer()
    if executable is None:
        # 调用方（render_final_docx）在没有版式引擎时根本不会走到这里；
        # 显式传了 renderer 却指不到可执行文件仍是硬错误，不静默放行。
        raise TocFinalizationError("未安装 LibreOffice，无法更新最终 Word 目录页码。")

    with tempfile.TemporaryDirectory(
        prefix="sustainability-desk-toc-",
        dir=document_path.parent,
    ) as temporary_directory:
        workdir = Path(temporary_directory)
        output_dir = workdir / "output"
        profile_dir = workdir / "profile"
        output_dir.mkdir()
        try:
            conversion = subprocess.run(
                [
                    executable,
                    "--headless",
                    f"-env:UserInstallation={profile_dir.as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(document_path),
                ],
                capture_output=True,
                text=True,
                timeout=TOC_RENDER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # 超时时子进程已有的 stderr/stdout 是唯一现场证据，不得丢弃。
            detail = " ".join(
                part.strip() for part in (exc.stderr, exc.output) if part
            ).strip()
            raise TocFinalizationError(
                f"LibreOffice 未能在 {TOC_RENDER_TIMEOUT_SECONDS}s 内更新最终 Word "
                f"目录页码。{detail}".rstrip()
            ) from exc
        except OSError as exc:
            raise TocFinalizationError("LibreOffice 未能更新最终 Word 目录页码。") from exc
        rendered_pdf = output_dir / f"{document_path.stem}.pdf"
        if conversion.returncode != 0 or not rendered_pdf.is_file():
            detail = (conversion.stderr or conversion.stdout).strip()
            raise TocFinalizationError(
                f"LibreOffice 未能更新最终 Word 目录页码。{detail}"
            )
        with ZipFile(document_path) as archive:
            document_xml = archive.read("word/document.xml")
            settings_xml = archive.read("word/settings.xml")
        entries = _toc_entries(document_xml)
        page_numbers = _rendered_toc_page_numbers(rendered_pdf, entries, body_page_one=_body_page_one_pattern(profile))
        _rewrite_docx_parts(
            document_path,
            {
                "word/document.xml": _freeze_toc_page_references(
                    _replace_toc_page_caches(document_xml, page_numbers)
                ),
                "word/settings.xml": _disable_open_field_updates(settings_xml),
            },
        )
    return document_path
