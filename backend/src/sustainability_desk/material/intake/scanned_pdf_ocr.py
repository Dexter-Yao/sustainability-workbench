# ABOUTME: 对无文本层 PDF 页执行本地 RapidOCR 文字识别，只服务图片型（扫描件）页面。
# ABOUTME: 内存边界事实：900MB cgroup 下 QEMU x86 实测零 OOM（2.4-6.1s/页）；因此单进程内必须串行、
# 每次调用只处理一页并在独立子进程中运行，避免与 asyncio worker 的其他并发任务叠加内存峰值。
# ABOUTME(en): Runs local RapidOCR on PDF pages lacking a text layer, serving scanned image-only pages.
# ABOUTME(en): Memory fact: zero OOM under a 900MB cgroup, so calls stay serial, one page each, in a subprocess.
from __future__ import annotations

import multiprocessing
import threading
import time
from dataclasses import dataclass
from io import BytesIO

OCR_RENDER_LONG_EDGE_PIXELS = 1600
OCR_PAGE_TIMEOUT_SECONDS = 60
OCR_FILE_TIMEOUT_SECONDS = 15 * 60

# 全局串行锁：部署机内存边界下同一时刻只允许一个 OCR 子进程运行。
# asyncio worker 的 extraction 并发（默认 4）与本锁无关——OCR 调用方仍会阻塞事件循环线程，
# 这与现有同步 parser（parse_docx/parse_xlsx/parse_pptx/parse_pdf_text）的阻塞行为一致。
_OCR_SERIAL_LOCK = threading.Lock()


class ScannedPdfOcrError(ValueError):
    """OCR 子进程失败、超时或渲染异常；调用方必须弃用当页结果，不得重试。"""


#: OCR 引擎未安装时给出的可执行提示。扫描件解析必须**明确报错**而不是静默返回空文本：
#: 静默会让一份根本没读进去的扫描件看起来像「读过但没内容」，用户无从判断是资料本身
#: 没信息还是系统少装了组件，而这两者的处置完全不同。
OCR_EXTRA_HINT = "扫描件识别需要 OCR 组件，请执行 `uv sync --extra ocr` 后重试"


def ocr_engine_available() -> bool:
    """OCR 引擎是否已安装（`--extra ocr`）。只做导入探测，不初始化模型。"""

    from importlib.util import find_spec

    return find_spec("rapidocr") is not None


@dataclass(frozen=True)
class OcrPageText:
    """单页 OCR 结果；confidence 仅供内部质量判断，不得进入模型上下文。"""

    page_number: int
    text: str
    mean_confidence: float | None


def _render_page_png(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        width, height = page.get_size()
        long_edge = max(width, height)
        scale = (
            OCR_RENDER_LONG_EDGE_PIXELS / long_edge
            if long_edge > OCR_RENDER_LONG_EDGE_PIXELS
            else 1.0
        )
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
    finally:
        document.close()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _ocr_worker_entrypoint(
    pdf_bytes: bytes, page_index: int, result_queue: "multiprocessing.Queue"
) -> None:
    """在独立子进程中渲染单页并执行 RapidOCR；结果经队列回传，永不与主进程共享内存。"""
    try:
        from rapidocr import RapidOCR

        png_bytes = _render_page_png(pdf_bytes, page_index)
        engine = RapidOCR()
        result = engine(png_bytes)
        texts = list(result.txts) if result.txts else []
        scores = list(result.scores) if result.scores else []
        mean_confidence = (sum(scores) / len(scores)) if scores else None
        result_queue.put(("ok", "\n".join(texts), mean_confidence))
    except Exception as error:  # noqa: BLE001 - 子进程异常必须转为确定性失败信号
        result_queue.put(("error", str(error), None))


def _ocr_single_page(pdf_bytes: bytes, page_index: int) -> OcrPageText:
    """在超时保护的子进程中渲染并识别单页；失败或超时即弃，不重试。"""
    context = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue = context.Queue()
    process = context.Process(
        target=_ocr_worker_entrypoint,
        args=(pdf_bytes, page_index, result_queue),
        daemon=True,
    )
    process.start()
    process.join(timeout=OCR_PAGE_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        raise ScannedPdfOcrError(f"第 {page_index + 1} 页 OCR 超时")
    if process.exitcode != 0:
        raise ScannedPdfOcrError(
            f"第 {page_index + 1} 页 OCR 子进程异常退出（exitcode={process.exitcode}）"
        )
    try:
        # multiprocessing.Queue.put 是异步落盘；子进程退出不保证管道已可读，须带超时 get 而非 get_nowait。
        status, payload, mean_confidence = result_queue.get(timeout=5)
    except Exception as error:
        raise ScannedPdfOcrError(f"第 {page_index + 1} 页 OCR 未返回结果") from error
    if status != "ok":
        raise ScannedPdfOcrError(f"第 {page_index + 1} 页 OCR 失败：{payload}")
    return OcrPageText(
        page_number=page_index + 1,
        text=payload,
        mean_confidence=mean_confidence,
    )


def ocr_pdf_pages(
    pdf_bytes: bytes, page_indexes: list[int]
) -> dict[int, OcrPageText | ScannedPdfOcrError]:
    """对指定页（0-based）串行执行 OCR；每页结果独立成功或失败，不相互拖累。

    调用方必须持有 `_OCR_SERIAL_LOCK`（本函数内部获取），保证同一时刻全进程只有一个
    OCR 子进程在运行。整份文件超过 `OCR_FILE_TIMEOUT_SECONDS` 直接放弃剩余页。
    """
    if not ocr_engine_available():
        # 每页都给同一条可执行提示：调用方按页汇报失败原因，不必各自判断整体可用性。
        return {index: ScannedPdfOcrError(OCR_EXTRA_HINT) for index in page_indexes}
    results: dict[int, OcrPageText | ScannedPdfOcrError] = {}
    started = time.monotonic()
    with _OCR_SERIAL_LOCK:
        for page_index in page_indexes:
            if time.monotonic() - started > OCR_FILE_TIMEOUT_SECONDS:
                results[page_index] = ScannedPdfOcrError(
                    f"第 {page_index + 1} 页 OCR 因整份文件超时被放弃"
                )
                continue
            try:
                results[page_index] = _ocr_single_page(pdf_bytes, page_index)
            except ScannedPdfOcrError as error:
                results[page_index] = error
    return results
