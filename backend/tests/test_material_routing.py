# ABOUTME: 资料 parser 路由纯函数与工作区服务必须共享同一正式决策合同。
# ABOUTME: 路由结果不含时间戳，便于 corpus manifest 稳定重放。
from io import BytesIO

import pytest
from pypdf import PdfWriter

from sustainability_desk.material.intake.parsers import MaterialParseError
from sustainability_desk.material.intake.routing import route_material_source


def _blank_pdf(page_count: int = 1) -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    return stream.getvalue()


def test_route_decision_uses_official_material_processing_route() -> None:
    decision = route_material_source(
        kind="docx",
        data=b"ignored",
    )

    assert decision.route == "native_docx"
    assert decision.parser == "material-capability-router"


def test_route_decision_keeps_pdf_on_the_deterministic_parser_path() -> None:
    decision = route_material_source(
        kind="pdf",
        data=_blank_pdf(page_count=6),
        pdf_page_count=6,
    )

    assert decision.route == "native_pdf_text"


def test_route_decision_uses_native_pptx_route() -> None:
    decision = route_material_source(
        kind="pptx",
        data=b"ignored",
    )

    assert decision.route == "native_pptx"


def test_route_decision_rejects_images_from_semantic_processing() -> None:
    with pytest.raises(MaterialParseError, match="排版素材"):
        route_material_source(
            kind="png",
            data=b"ignored",
        )
