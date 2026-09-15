# ABOUTME: 排版素材图片理解的确定性预处理与单轮 VLM 适配器，经统一模型出口执行识别。
# ABOUTME: 送模前把任意来源图片收敛为 DashScope 兼容的 BinaryContent；Harness 只校验 scope_alias 合法性。
# ABOUTME(en): Deterministic preprocessing plus a single-turn VLM adapter for layout-asset image understanding.
# ABOUTME(en): Any source image becomes DashScope-compatible BinaryContent; the Harness only validates scope_alias.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from typing import Any
from uuid import UUID

from PIL import Image
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext

from sustainability_desk.llm.ai_observability import ObservationRun
from sustainability_desk.llm.client import build_agent
from sustainability_desk.llm.concurrency import run_agent
from sustainability_desk.llm.model_registry import DEFAULT_MODEL_ID
from sustainability_desk.llm.prompt_profiles import ImageAgentTexts
from sustainability_desk.material.intake.file_agent_contract import AttentionItem
from sustainability_desk.material.intake.image_agent_contract import (
    ImageAgentContext,
    ImageAgentRunReceipt,
    ImageDossier,
    ImageDossierDraft,
    image_dossier_fingerprint,
)

DEFAULT_IMAGE_AGENT_MODEL_ID = DEFAULT_MODEL_ID

# 与 material_intake/scanned_pdf_ocr.py 的 OCR 渲染基准一致选取量级；VLM 识别对分辨率的要求
# 明显低于 OCR，长边超过该值再等比降采样，控制上行体积与推理时延。
MODEL_IMAGE_LONG_EDGE_PIXELS = 2048



def prepare_model_image(data: bytes, *, media_type: str) -> BinaryContent:
    """把任意已校验来源图片收敛为可直接送模的 BinaryContent。

    media_type 为 application/pdf 时只渲染首页；长边超过
    MODEL_IMAGE_LONG_EDGE_PIXELS 时等比降采样；webp 转 JPEG（quality=90）
    以保 DashScope 兼容；png/jpeg 且不超限时原字节直传，不重新编码。
    """

    if media_type == "application/pdf":
        image = _render_pdf_first_page(data)
        return _encode_for_model(image, prefer_format="PNG")
    image = Image.open(BytesIO(data))
    image.load()
    long_edge = max(image.width, image.height)
    if media_type == "image/webp":
        resized = _downscale_if_needed(image, long_edge)
        return _encode_for_model(resized, prefer_format="JPEG")
    if long_edge > MODEL_IMAGE_LONG_EDGE_PIXELS:
        resized = _downscale_if_needed(image, long_edge)
        prefer_format = "PNG" if media_type == "image/png" else "JPEG"
        return _encode_for_model(resized, prefer_format=prefer_format)
    return BinaryContent(data=data, media_type=media_type)


def model_image_pixel_size(data: bytes, *, media_type: str) -> tuple[int, int]:
    """返回原图（或 PDF 首页）的像素尺寸，供落库记录，不参与降采样判断以外的用途。"""

    if media_type == "application/pdf":
        image = _render_pdf_first_page(data)
        return image.width, image.height
    with Image.open(BytesIO(data)) as image:
        return image.width, image.height


def _render_pdf_first_page(data: bytes) -> Image.Image:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page = document[0]
        bitmap = page.render()
        return bitmap.to_pil().convert("RGB")
    finally:
        document.close()


def _downscale_if_needed(image: Image.Image, long_edge: int) -> Image.Image:
    if long_edge <= MODEL_IMAGE_LONG_EDGE_PIXELS:
        return image
    scale = MODEL_IMAGE_LONG_EDGE_PIXELS / long_edge
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def _encode_for_model(image: Image.Image, *, prefer_format: str) -> BinaryContent:
    buffer = BytesIO()
    if prefer_format == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
        return BinaryContent(data=buffer.getvalue(), media_type="image/jpeg")
    image.save(buffer, format="PNG")
    return BinaryContent(data=buffer.getvalue(), media_type="image/png")


@dataclass
class ImageAgentDeps:
    """图片理解运行的只读上下文；allowed_scope_aliases 用于 output_validator 闸门。"""

    allowed_scope_aliases: frozenset[str]


def build_image_understanding_agent(
    model_id: str = DEFAULT_IMAGE_AGENT_MODEL_ID,
    *,
    texts: ImageAgentTexts,
) -> Agent[ImageAgentDeps, ImageDossierDraft]:
    """构造单轮图片理解 Agent；只校验 scope_alias 合法性，不做内容审查。指令措辞由知识包 prompt profile 拥有。"""

    agent = build_agent(
        model_id,
        output_type=ImageDossierDraft,
        instructions=texts.instructions,
        deps_type=ImageAgentDeps,
        retries=1,
    )

    @agent.output_validator
    async def validate_scope_alias(
        ctx: RunContext[ImageAgentDeps],
        draft: ImageDossierDraft,
    ) -> ImageDossierDraft:
        if draft.scope_alias not in ctx.deps.allowed_scope_aliases:
            raise ModelRetry(
                f"scope_alias 必须是 allowedScopeAliases 中的一个：{draft.scope_alias!r}"
            )
        return draft

    return agent


def build_report_need_catalog(material_scopes) -> dict[str, Any]:
    """从承载位 scope 目录派生 Image Agent 所需的最小报告需要边界，形态与 file_agent 同构。"""

    return {
        "allowedMaterialScopes": [
            {
                "scopeAlias": scope.alias,
                "title": scope.title,
                "kind": scope.kind,
            }
            for scope in material_scopes
        ],
    }


def _initial_prompt(context: ImageAgentContext, texts: ImageAgentTexts) -> str:
    """投影单图任务、用户意图与由承载位目录派生的报告需要；不含 UUID、存储路径或 observability 字段。"""

    payload = {
        "productTask": {
            "objective": context.product_task.objective,
            "reportSubjectName": context.product_task.report_subject_name,
            "reportPeriodLabel": context.product_task.report_period_label,
        },
        "reportNeedCatalog": build_report_need_catalog(
            context.product_task.material_scopes,
        ),
        "allowedScopeAliases": [
            scope.alias for scope in context.product_task.material_scopes
        ],
        "file": {
            "filename": context.filename,
            "materialKind": context.material_kind,
            "sizeBytes": context.size_bytes,
        },
        "userDeclaration": {
            "authority": "user_intent_not_file_evidence",
            "assetTitle": context.declaration.asset_title,
            "description": context.declaration.description,
            "topicTags": context.declaration.topic_tags,
            "revision": context.source_revision.declaration_revision,
        },
    }
    return texts.task_preamble + "\n" + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def freeze_image_dossier(
    draft: ImageDossierDraft,
    *,
    context: ImageAgentContext,
    scope_alias_to_id: dict[str, str],
) -> ImageDossier:
    """把模型草稿的 scope alias 收敛为报告 scope_id，并计算内容指纹冻结为 ImageDossier。"""

    scope_id = scope_alias_to_id.get(draft.scope_alias)
    if scope_id is None:
        raise ValueError(f"scope_alias 无法映射到报告范围：{draft.scope_alias!r}")
    attention_items = tuple(
        AttentionItem(
            code=item.code,
            message=item.message,
            next_action=item.next_action,
        )
        for item in draft.attention_items
    )
    fingerprint = image_dossier_fingerprint(
        source_revision=context.source_revision,
        summary=draft.summary,
        category=draft.category,
        caption=draft.caption,
        alt_text=draft.alt_text,
        scope_id=scope_id,
        placement_reason=draft.placement_reason,
        certificate_fact=draft.certificate_fact,
        attention_items=attention_items,
    )
    return ImageDossier(
        source_revision=context.source_revision,
        summary=draft.summary,
        category=draft.category,
        caption=draft.caption,
        alt_text=draft.alt_text,
        scope_id=scope_id,
        placement_reason=draft.placement_reason,
        certificate_fact=draft.certificate_fact,
        attention_items=attention_items,
        dossier_fingerprint=fingerprint,
    )


class ImageUnderstandingAgentAdapter:
    """经统一并发与 trace 执行单轮真实 VLM 调用。"""

    def __init__(
        self,
        *,
        texts: ImageAgentTexts,
        model_id: str = DEFAULT_IMAGE_AGENT_MODEL_ID,
        agent: Agent[ImageAgentDeps, ImageDossierDraft] | None = None,
    ) -> None:
        self._model_id = model_id
        self._texts = texts
        self._agent = agent or build_image_understanding_agent(model_id, texts=texts)

    async def run(
        self,
        context: ImageAgentContext,
        image: BinaryContent,
        *,
        observation: ObservationRun,
    ) -> ImageDossierDraft:
        """送模一张已预处理的图片并冻结为已校验合法 scope 的 ImageDossierDraft。"""

        prompt_text = _initial_prompt(context, self._texts)
        context_fingerprint = sha256(prompt_text.encode("utf-8")).hexdigest()
        allowed_scope_aliases = frozenset(
            scope.alias for scope in context.product_task.material_scopes
        )
        deps = ImageAgentDeps(allowed_scope_aliases=allowed_scope_aliases)
        result = await run_agent(
            self._agent,
            [prompt_text, image],
            observation.invocation(
                model_id=self._model_id,
                evidence_selector_kind="image_agent_context",
                block_id=f"file:{context.source_revision.source_id}",
                context_fingerprint=context_fingerprint,
                task_context={
                    "materialKind": context.material_kind,
                    "declarationRevision": context.source_revision.declaration_revision,
                    "imageWidthPx": context.image_width_px,
                    "imageHeightPx": context.image_height_px,
                },
            ),
            deps=deps,
        )
        return result.output


def build_run_receipt(
    *,
    run_id: UUID,
    observation_run_id: str | None,
    attempt: int,
    context: ImageAgentContext,
    started_at: datetime,
    dossier_fingerprint: str | None = None,
    failure_code: str | None = None,
) -> ImageAgentRunReceipt:
    """构造单次图片识别运行的收据；成功须携带 dossier 指纹，失败须携带 failure_code。"""

    return ImageAgentRunReceipt(
        run_id=run_id,
        observation_run_id=observation_run_id,
        attempt=attempt,
        status="failed" if failure_code else "completed",
        source_revision=context.source_revision,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        dossier_fingerprint=dossier_fingerprint,
        failure_code=failure_code,
    )
