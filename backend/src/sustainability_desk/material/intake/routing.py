# ABOUTME: 资料能力路由的确定性决策 owner，供上传服务与 corpus manifest 共用。
# ABOUTME: 决策不含时间、来源 ID 或存储状态；调用方只负责投影运行步骤。
# ABOUTME(en): Deterministic owner of material capability routing, shared by upload service and corpus manifest.
# ABOUTME(en): Decisions carry no timestamps, source IDs or storage state; callers alone project the run steps.
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from sustainability_desk.material.intake.models import MaterialProcessingRoute
from sustainability_desk.material.intake.parsers import MaterialParseError


class MaterialRouteDecision(BaseModel):
    """文件内容能力到正式处理路由的稳定决策。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parser: str = "material-capability-router"
    route: MaterialProcessingRoute
    message: str


def route_material_source(
    *,
    kind: str,
    data: bytes,
    pdf_page_count: int | None = None,
) -> MaterialRouteDecision:
    """只为语义资料选择第三方 parser 路由，绝不把文件页图发送给模型。"""
    if kind == "docx":
        route: MaterialProcessingRoute = "native_docx"
    elif kind == "xlsx":
        route = "native_xlsx"
    elif kind == "pdf":
        route = "native_pdf_text"
    elif kind == "pptx":
        route = "native_pptx"
    else:
        raise MaterialParseError("图片仅能作为排版素材上传，不进入资料语义解析")

    del data, pdf_page_count
    return MaterialRouteDecision(
        route=route,
        message="已选择确定性本地解析",
    )
